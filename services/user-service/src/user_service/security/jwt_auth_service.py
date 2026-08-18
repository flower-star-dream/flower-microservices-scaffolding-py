"""
认证服务（JWT SPI 示例）

@Author: 花海
@Date: 2026/08/16
@Description: 认证服务，演示框架 JWT SPI 能力（规范 §6.1 认证域）：
              - JwtKeyProvider（签名密钥与算法 SPI，默认 EnvJwtKeyProvider：JWT_SECRET_KEY 环境变量 + HS256）
              - JwtTokenStore（Token 状态存储 SPI：InMemoryJwtTokenStore 单机 / RedisJwtTokenStore 分布式，
                登出撤销与同设备凭证复用）
              登录签发 access/refresh token、Token 校验、登出失效、静默刷新；
              生产多实例部署时 Token 状态存储切换为 RedisJwtTokenStore（见 main.py 装配注释）。
"""
from __future__ import annotations

from web_infra import CommonErrorCode, PasswordEncoder, TokenVerifyStatus
from web_infra.capabilities.security import EnvJwtKeyProvider, InMemoryJwtTokenStore, JWTUtil, JwtKeyProvider, JwtTokenStore

from user_service.constants.user_constant import UserConstant
from user_service.repository.user_repository import UserRepository
from user_service.schema.auth_schema import TokenVO


class JwtAuthService:
    """认证服务：签发 / 校验 / 登出 / 刷新（JWT SPI 装配演示）"""

    def __init__(
        self,
        repository: UserRepository,
        token_store: JwtTokenStore | None = None,
        key_provider: JwtKeyProvider | None = None,
    ) -> None:
        """初始化认证服务。

        演示 JWT SPI 装配：显式注入 Token 状态存储与签名密钥/算法提供器
        （缺省回落 InMemoryJwtTokenStore / EnvJwtKeyProvider，与框架默认一致）。
        业务可替换为 RedisJwtTokenStore（多实例）或自研实现，不修改调用方代码。

        :param repository: 用户仓储
        :param token_store: Token 状态存储 SPI（None 回落内存实现）
        :param key_provider: 签名密钥/算法 SPI（None 回落环境变量实现）
        """
        JWTUtil.configure(
            token_store=token_store or InMemoryJwtTokenStore(),
            key_provider=key_provider or EnvJwtKeyProvider(),
        )
        self._repository = repository

    async def login(
        self,
        username: str,
        password: str,
        client_id: str | None = None,
        device_id: str | None = None,
    ) -> TokenVO:
        """登录：校验用户名密码 → 签发 access/refresh token（同设备凭证复用，规范 §6.2）

        :param username: 用户名
        :param password: 明文密码
        :param client_id: 客户端标识（同设备凭证复用，不传按 user_id 聚合）
        :param device_id: 设备标识（同设备凭证复用）
        :return: Token 出参（access + refresh）
        :raises BizException: 用户名或密码错误抛 AUTH_INVALID；账号禁用抛 AUTH_UNAUTHENTICATED
        """
        user = await self._repository.find_by_username(username)
        if user is None or not PasswordEncoder.verify(password, user.password_hash):
            raise CommonErrorCode.AUTH_INVALID.to_exception(message="用户名或密码错误")
        if user.status != UserConstant.USER_STATUS_ENABLED:
            raise CommonErrorCode.AUTH_UNAUTHENTICATED.to_exception(message="账号已被禁用")

        access_token = await JWTUtil.generate_token(
            user_id=str(user.id), username=user.username, client_id=client_id, device_id=device_id
        )
        refresh_token = await JWTUtil.create_refresh_token(user_id=str(user.id), username=user.username)
        return TokenVO(access_token=access_token, refresh_token=refresh_token)

    async def validate(self, token: str) -> dict:
        """校验 access token：有效返回 payload（sub/jti/exp 等），无效/过期/已撤销抛对应错误码

        :param token: access token
        :return: token payload（含 user_id=sub、jti、exp）
        :raises BizException: Token 无效/已撤销抛 AUTH_INVALID；已过期抛 AUTH_EXPIRED
        """
        payload, status = await JWTUtil.verify_token(token)
        if payload is None:
            code = CommonErrorCode.AUTH_EXPIRED if status == TokenVerifyStatus.EXPIRED else CommonErrorCode.AUTH_INVALID
            raise code.to_exception(message=f"Token 不可用：{status.name}")
        return payload

    async def logout(self, token: str) -> bool:
        """登出：撤销当前 access token（jti 置为失效，规范 §6.7 凭证撤销）

        :param token: access token
        :return: 是否撤销成功
        :raises BizException: Token 无效无法撤销抛 AUTH_INVALID
        """
        if not await JWTUtil.invalidate_token(token):
            raise CommonErrorCode.AUTH_INVALID.to_exception(message="Token 无效，无法登出")
        return True

    async def refresh(self, refresh_token: str) -> TokenVO:
        """静默刷新：用 refresh token 换取新 access/refresh token（规范 §6.1）

        :param refresh_token: refresh token（单独密钥段签发）
        :return: 新的 Token 出参（refresh token 同步轮换）
        :raises BizException: refresh token 无效/过期抛 AUTH_INVALID / AUTH_EXPIRED
        """
        payload, status = await JWTUtil.verify_refresh_token(refresh_token)
        if payload is None:
            code = CommonErrorCode.AUTH_EXPIRED if status == TokenVerifyStatus.EXPIRED else CommonErrorCode.AUTH_INVALID
            raise code.to_exception(message=f"refresh token 不可用：{status.name}")
        user_id = payload.get("sub")
        username = payload.get("username") or ""
        if not user_id:
            raise CommonErrorCode.AUTH_INVALID.to_exception(message="refresh token 缺少用户标识")
        access_token = await JWTUtil.generate_token(user_id=user_id, username=username)
        new_refresh_token = await JWTUtil.create_refresh_token(user_id=user_id, username=username)
        return TokenVO(access_token=access_token, refresh_token=new_refresh_token)
