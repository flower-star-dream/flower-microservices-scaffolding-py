"""
订单 ORM 模型（Model）

@Author: 花海
@Date: 2026/08/16
@Description: 订单实体模型（继承 web_infra.Base，数据库访问强制走 ORM 会话规范 §10），
              对应库 flower_order 中的表 t_order。模型属性命名使用 snake_case。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from web_infra import Base


class OrderModel(Base):
    """订单实体模型"""

    __tablename__ = "t_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="订单号（业务唯一）")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="下单用户 ID")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="订单金额")
    status: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="状态：1 已创建 / 2 已确认 / 3 已取消"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, onupdate=func.now(), comment="更新时间"
    )
