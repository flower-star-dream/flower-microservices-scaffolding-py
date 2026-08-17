"""基线迁移：创建订单表 t_order

Revision ID: 0001
Revises:
Create Date: 2026/08/16 10:30

@Author: 花海
@Date: 2026/08/16 10:30
@Description: order-service 示例业务表 t_order 基线迁移（等价 db/init/ddl/002-order-init-ddl.sql）。
              Alembic 为权威迁移工具（规范 §13.1），基线 SQL 保留供 DBA 参考。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级迁移：创建 t_order 表（订单表）"""
    op.create_table(
        "t_order",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
            primary_key=True,
            comment="主键",
        ),
        sa.Column("order_no", sa.String(64), nullable=False, comment="订单号（业务唯一）"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="下单用户 ID"),
        sa.Column(
            "amount",
            sa.Numeric(12, 2).with_variant(mysql.DECIMAL(12, 2), "mysql"),
            nullable=False,
            comment="订单金额",
        ),
        sa.Column(
            "status",
            sa.SmallInteger().with_variant(mysql.TINYINT(), "mysql"),
            nullable=False,
            server_default=sa.text("1"),
            comment="状态：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="更新时间"),
        sa.UniqueConstraint("order_no", name="uk_order_no"),
        sa.Index("idx_user_id", "user_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_comment="订单表",
    )


def downgrade() -> None:
    """回滚迁移：删除 t_order 表"""
    op.drop_table("t_order")
