"""
认证 DTO（Schema，请求/响应模型）

@Author: 花海
@Date: 2026/08/16
@Description: 认证模块的请求与响应模型（Pydantic v2）：登录请求 / 刷新请求 / Token 出参。
              演示框架 JWT SPI（规范 §6.1）：access token 与 refresh token 分离，同设备凭证复用。
"""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求（用户名 + 密码）"""

    username: str = Field(min_length=2, max_length=64, description="用户名")
    password: str = Field(min_length=6, max_length=72, description="密码（明文，服务层校验）")
    client_id: str | None = Field(default=None, max_length=64, description="客户端标识（规范 §6.2 同设备凭证复用）")
    device_id: str | None = Field(default=None, max_length=64, description="设备标识（规范 §6.2 同设备凭证复用）")


class RefreshTokenRequest(BaseModel):
    """刷新请求"""

    refresh_token: str = Field(description="refresh token（登录/刷新时签发，单独密钥段）")


class TokenVO(BaseModel):
    """Token 出参视图"""

    access_token: str = Field(description="access token（后续请求经 Authorization: Bearer 携带）")
    refresh_token: str = Field(description="refresh token（access 即将过期时换取新 access，规范 §6.1 静默刷新）")
    token_type: str = Field(default="Bearer", description="Token 类型")
