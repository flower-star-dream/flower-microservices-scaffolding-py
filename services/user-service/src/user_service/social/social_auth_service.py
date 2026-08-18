"""
三方登录服务（SocialAuthService）

@Author: 花海
@Date: 2026/08/16
@Description: 三方登录业务编排，演示框架 social SPI（规范 §6.8 认证域）：
              复用框架 SocialLoginService（平台注册表 + 绑定存储 + 换 token/拉 userinfo 编排），
              补充本地用户域：未绑定自动注册本地账号并绑定（示例策略，生产按业务决定
              自动注册或引导手动绑定）、登录成功签发框架自有 JWT、绑定/解绑管理。
              平台适配实现（SocialPlatform SPI）由 main.py 装配时注册进 SocialPlatformRegistry。
"""
from __future__ import annotations

import secrets

from web_infra import CommonErrorCode, JWTUtil, PasswordEncoder
from web_infra.capabilities.security import SocialBindingStore, SocialLoginService, SocialUserInfo

from user_service.constants.user_constant import UserConstant
from user_service.model.user_model import UserModel
from user_service.repository.user_repository import UserRepository
from user_service.schema.auth_schema import TokenVO
from user_service.schema.social_schema import SocialUserVO

# 三方用户自动注册的用户名前缀与生成规则（避免与手工注册用户名冲突）
_AUTO_USERNAME_PREFIX = "soc"


class SocialAuthService:
    """三方登录服务：授权跳转 / 登录（未绑定自动注册） / 绑定 / 解绑 / 绑定列表"""

    def __init__(
        self,
        repository: UserRepository,
        social: SocialLoginService,
        binding_store: SocialBindingStore,
    ) -> None:
        """初始化三方登录服务

        :param repository: 用户仓储
        :param social: 框架三方登录编排服务（SocialLoginService，装配于 main.py）
        :param binding_store: 三方绑定存储 SPI（与 SocialLoginService 共用同一实例）
        """
        self._repository = repository
        self._social = social
        self._binding_store = binding_store

    async def authorize_url(self, provider: str, redirect_uri: str, state: str) -> str:
        """生成三方平台授权跳转 URL（state 防 CSRF，业务生成）

        :param provider: 平台标识（SocialPlatformRegistry 中已注册）
        :param redirect_uri: 授权后回跳地址
        :param state: 防 CSRF 随机态
        :return: 授权跳转 URL
        :raises BizException: 平台未注册抛 AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED
        """
        return await self._social.generate_authorize_url(provider, redirect_uri, state)

    async def login(self, provider: str, code: str, redirect_uri: str) -> TokenVO:
        """三方登录：已绑定直接签发 JWT；未绑定自动注册本地账号并绑定（示例策略）后签发 JWT

        :param provider: 平台标识
        :param code: 平台授权码
        :param redirect_uri: 授权时使用的回跳地址
        :return: Token 出参（access + refresh）
        :raises BizException: 平台未注册 / 授权码无效抛对应错误码
        """
        result = await self._social.login(provider, code, redirect_uri)
        if result.bound:
            if result.user_id is None:
                raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="三方登录结果缺少用户标识")
            # 已绑定：查询本地用户后统一签发（覆盖框架签发的 access token，附带 refresh token）
            user = await self._repository.find_by_id(int(result.user_id))
            if user is None:
                raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="绑定的本地用户不存在")
        else:
            # 未绑定：自动注册本地账号并绑定（示例策略；真实业务可按需引导手动绑定）
            user = await self._auto_register(result.user_info)
            await self._social.bind(provider, code, redirect_uri, str(user.id))
        return await self._issue_tokens(user, provider)

    async def bind(self, provider: str, code: str, redirect_uri: str, user_id: int) -> SocialUserVO:
        """已登录用户绑定三方账号（重复绑定同用户幂等）

        :param provider: 平台标识
        :param code: 平台授权码
        :param redirect_uri: 授权时使用的回跳地址
        :param user_id: 本地用户 ID
        :return: 绑定出参
        :raises BizException: 已被其他用户绑定抛 AUTH_SOCIAL_ALREADY_BOUND
        """
        binding = await self._social.bind(provider, code, redirect_uri, str(user_id))
        return SocialUserVO(provider=binding.provider, openid=binding.openid)

    async def unbind(self, provider: str, openid: str, user_id: int) -> bool:
        """解绑三方账号（校验绑定属主，非属主抛 PERM_DENIED）

        :param provider: 平台标识
        :param openid: 平台内用户唯一标识
        :param user_id: 本地用户 ID
        :return: 是否实际解绑
        """
        return await self._social.unbind(provider, openid, str(user_id))

    async def list_bindings(self, user_id: int) -> list[SocialUserVO]:
        """查询用户全部三方绑定

        :param user_id: 本地用户 ID
        :return: 绑定出参列表
        """
        bindings = await self._binding_store.find_all_by_user_id(str(user_id))
        return [SocialUserVO(provider=b.provider, openid=b.openid, nickname=None) for b in bindings]

    async def _auto_register(self, user_info: SocialUserInfo | None) -> UserModel:
        """未绑定三方登录自动注册本地账号（示例策略）

        用户名 = soc_<provider>_<openid>（截断 64 字符），密码随机不可登录；
        已存在（同一三方账号并发/重复登录）则直接返回既有账号。

        :param user_info: 三方用户信息
        :return: 本地用户模型
        """
        provider = (user_info.provider if user_info else "unknown")
        openid = (user_info.openid if user_info else "unknown")
        username = f"{_AUTO_USERNAME_PREFIX}_{provider}_{openid}"[:64]
        existed = await self._repository.find_by_username(username)
        if existed is not None:
            return existed
        user = UserModel(
            username=username,
            password_hash=PasswordEncoder.encode(secrets.token_urlsafe(16)),
            nickname=(user_info.nickname if user_info else None),
            status=UserConstant.USER_STATUS_ENABLED,
        )
        return await self._repository.create(user)

    async def _issue_tokens(self, user: UserModel, provider: str) -> TokenVO:
        """签发框架自有 JWT（access + refresh，携带三方登录标识）

        :param user: 本地用户模型
        :param provider: 平台标识（写入 extra_claims 便于审计）
        :return: Token 出参
        """
        access_token = await JWTUtil.generate_token(
            user_id=str(user.id),
            username=user.username,
            extra_claims={"login_type": "social", "provider": provider},
        )
        refresh_token = await JWTUtil.create_refresh_token(user_id=str(user.id), username=user.username)
        return TokenVO(access_token=access_token, refresh_token=refresh_token)
