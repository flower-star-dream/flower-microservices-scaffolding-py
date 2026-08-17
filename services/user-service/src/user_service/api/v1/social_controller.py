"""
三方登录接口层（Controller）

@Author: 花海
@Date: 2026/08/16
@Description: 三方登录 HTTP 接口：授权跳转 URL、登录（未绑定自动注册）、绑定 / 解绑 / 绑定列表。
              演示框架 social SPI（规范 §6.8 认证域）：平台适配注册表 + 绑定存储 + 编排服务。
              Demo 平台授权码以 demo- 开头（如 code=demo-xxx），可本地直测。
"""
from fastapi import APIRouter, Depends, Query, Request

from web_infra import Result

from user_service.schema.social_schema import (
    SocialBindRequest,
    SocialUnbindRequest,
)
from user_service.social.social_auth_service import SocialAuthService


def get_social_auth_service(request: Request) -> SocialAuthService:
    """构造三方登录服务（依赖注入：从应用已装配组件获取 main.py 装配的 SocialAuthService）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 三方登录服务实例
    """
    service = getattr(request.app.state, "social_auth_service", None)
    if service is None:
        raise RuntimeError("三方登录服务未装配：请在 main.py 中设置 app.state.social_auth_service")
    return service


router = APIRouter(prefix="/v1/social", tags=["三方登录"])


@router.get("/{provider}/authorize-url", summary="生成授权跳转 URL")
async def authorize_url(
    provider: str,
    redirect_uri: str = Query(description="授权后回跳地址"),
    state: str = Query(min_length=1, description="防 CSRF 随机态（业务生成）"),
    service: SocialAuthService = Depends(get_social_auth_service),
) -> Result:
    """生成三方平台授权跳转 URL（用户跳转后由平台回跳 redirect_uri?code=xxx）"""
    url = await service.authorize_url(provider, redirect_uri, state)
    return Result.success(data={"authorize_url": url})


@router.get("/{provider}/login", summary="三方登录")
async def login(
    provider: str,
    code: str = Query(description="平台授权码（Demo 平台以 demo- 开头）"),
    redirect_uri: str = Query(description="授权时使用的回跳地址"),
    service: SocialAuthService = Depends(get_social_auth_service),
) -> Result:
    """三方登录：已绑定直接签发 JWT；未绑定自动注册本地账号并绑定后签发 JWT"""
    return Result.success(data=await service.login(provider, code, redirect_uri))


@router.post("/{provider}/bind", summary="绑定三方账号")
async def bind(
    provider: str,
    request: SocialBindRequest,
    service: SocialAuthService = Depends(get_social_auth_service),
) -> Result:
    """已登录用户绑定三方账号（重复绑定同用户幂等）"""
    return Result.success(data=await service.bind(provider, request.code, request.redirect_uri, request.user_id))


@router.post("/{provider}/unbind", summary="解绑三方账号")
async def unbind(
    provider: str,
    request: SocialUnbindRequest,
    service: SocialAuthService = Depends(get_social_auth_service),
) -> Result:
    """解绑三方账号（校验绑定属主）"""
    unbound = await service.unbind(provider, request.openid, request.user_id)
    return Result.success(data={"unbound": unbound})


@router.get("/users/{user_id}/bindings", summary="查询绑定列表")
async def list_bindings(
    user_id: int,
    service: SocialAuthService = Depends(get_social_auth_service),
) -> Result:
    """查询用户全部三方绑定"""
    return Result.success(data=await service.list_bindings(user_id))
