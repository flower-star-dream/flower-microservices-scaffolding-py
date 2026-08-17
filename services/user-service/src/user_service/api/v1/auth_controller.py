"""
认证接口层（Controller）

@Author: 花海
@Date: 2026/08/16
@Description: 认证 HTTP 接口：登录签发 Token、Token 校验、登出、静默刷新。
              演示框架 JWT SPI：签发（access + refresh）走 JWTUtil，登出经 Token 状态存储撤销。
              Authorization 头格式：Bearer <access_token>。
"""
from fastapi import APIRouter, Depends, Header, Request

from web_infra import CommonErrorCode, Result

from user_service.repository.user_repository import UserRepository
from user_service.schema.auth_schema import LoginRequest, RefreshTokenRequest
from user_service.security.jwt_auth_service import JwtAuthService


def get_auth_service(request: Request) -> JwtAuthService:
    """构造认证服务（依赖注入：从应用已装配组件获取 db）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 认证服务实例
    """
    return JwtAuthService(repository=UserRepository(request.app.state.db))


def _extract_token(authorization: str | None) -> str:
    """从 Authorization 头提取 Bearer token（缺失/格式错误抛 AUTH_UNAUTHENTICATED）

    :param authorization: Authorization 请求头原始值
    :return: token 字符串
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise CommonErrorCode.AUTH_UNAUTHENTICATED.to_exception(
            message="缺少 Authorization: Bearer <token> 请求头"
        )
    return authorization.removeprefix("Bearer ").strip()


router = APIRouter(prefix="/v1/auth", tags=["认证管理"])


@router.post("/token", summary="登录签发 Token")
async def login(request: LoginRequest, service: JwtAuthService = Depends(get_auth_service)) -> Result:
    """登录：校验用户名密码 → 签发 access/refresh token（同设备凭证复用，规范 §6.2）"""
    return Result.success(data=await service.login(request.username, request.password, request.client_id, request.device_id))


@router.get("/validate", summary="校验 Token")
async def validate(
    authorization: str | None = Header(default=None),
    service: JwtAuthService = Depends(get_auth_service),
) -> Result:
    """校验 access token：有效返回 payload（sub/jti/exp），无效/过期返回对应错误码"""
    return Result.success(data=await service.validate(_extract_token(authorization)))


@router.post("/logout", summary="登出")
async def logout(
    authorization: str | None = Header(default=None),
    service: JwtAuthService = Depends(get_auth_service),
) -> Result:
    """登出：撤销当前 access token（jti 置为失效，同设备复用语义）"""
    await service.logout(_extract_token(authorization))
    return Result.success()


@router.post("/refresh", summary="刷新 Token")
async def refresh(request: RefreshTokenRequest, service: JwtAuthService = Depends(get_auth_service)) -> Result:
    """静默刷新：用 refresh token 换取新 access/refresh token（access 即将过期时调用，规范 §6.1）"""
    return Result.success(data=await service.refresh(request.refresh_token))
