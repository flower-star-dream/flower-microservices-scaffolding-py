"""
用户 DTO（Schema，请求/响应模型）

@Author: 花海
@Date: 2026/08/16
@Description: 用户模块的请求与响应模型（Pydantic v2），用于接口入参校验与出参序列化。
              出参使用 VO 视图，避免直接暴露 ORM 模型（含密码哈希）。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """创建用户请求"""

    username: str = Field(min_length=2, max_length=64, description="用户名")
    password: str = Field(min_length=6, max_length=72, description="密码（明文，服务层加密存储）")
    nickname: str | None = Field(default=None, max_length=64, description="昵称")


class UserStatusUpdateRequest(BaseModel):
    """更新用户状态请求"""

    status: int = Field(ge=0, le=1, description="状态：1 启用 / 0 禁用")


class UserVO(BaseModel):
    """用户出参视图"""

    id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    nickname: str | None = Field(default=None, description="昵称")
    status: int = Field(description="状态：1 启用 / 0 禁用")
    created_at: datetime | None = Field(default=None, description="创建时间")
