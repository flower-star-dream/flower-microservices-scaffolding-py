"""
三方登录 DTO（Schema，请求/响应模型）

@Author: 花海
@Date: 2026/08/16
@Description: 三方登录模块的请求与响应模型（Pydantic v2）：授权跳转 / 登录 / 绑定 / 解绑。
              演示框架 social SPI（规范 §6.8 认证域）：平台适配 + 绑定存储 + 编排服务。
"""
from pydantic import BaseModel, Field


class SocialAuthorizeUrlRequest(BaseModel):
    """生成授权跳转 URL 请求"""

    redirect_uri: str = Field(description="平台授权后回跳地址")
    state: str = Field(min_length=1, max_length=128, description="防 CSRF 随机态（业务生成，回调原样带回）")


class SocialLoginRequest(BaseModel):
    """三方登录请求"""

    code: str = Field(description="平台授权码（Demo 平台以 demo- 开头有效）")
    redirect_uri: str = Field(description="授权时使用的回跳地址（与换取 token 一致）")


class SocialBindRequest(BaseModel):
    """绑定三方账号请求"""

    code: str = Field(description="平台授权码（Demo 平台以 demo- 开头有效）")
    redirect_uri: str = Field(description="授权时使用的回跳地址")
    user_id: int = Field(ge=1, description="待绑定的本地用户 ID")


class SocialUnbindRequest(BaseModel):
    """解绑三方账号请求"""

    openid: str = Field(description="平台内用户唯一标识（openid）")
    user_id: int = Field(ge=1, description="本地用户 ID（校验绑定属主）")


class SocialUserVO(BaseModel):
    """三方绑定出参视图"""

    provider: str = Field(description="平台标识（如 demo / wechat_open / github）")
    openid: str = Field(description="平台内用户唯一标识")
    nickname: str | None = Field(default=None, description="平台昵称")
