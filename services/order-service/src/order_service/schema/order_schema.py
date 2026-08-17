"""
订单 DTO（Schema，请求/响应模型）

@Author: 花海
@Date: 2026/08/16
@Description: 订单模块的请求与响应模型（Pydantic v2），用于接口入参校验与出参序列化。
              金额出参使用字符串，避免浮点/前端精度问题（Decimal 转 str）。
"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OrderCreateRequest(BaseModel):
    """创建订单请求"""

    user_id: int = Field(ge=1, description="下单用户 ID（user-service 的用户）")
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="订单金额")


class OrderStatusUpdateRequest(BaseModel):
    """更新订单状态请求"""

    status: int = Field(ge=1, le=5, description="状态：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消")


class OrderVO(BaseModel):
    """订单出参视图"""

    id: int = Field(description="订单 ID")
    order_no: str = Field(description="订单号")
    user_id: int = Field(description="下单用户 ID")
    amount: str = Field(description="订单金额（字符串，避免精度丢失）")
    status: int = Field(description="状态：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消")
    created_at: datetime | None = Field(default=None, description="创建时间")
