"""增量迁移：创建 Outbox 本地事务表 message_outbox

Revision ID: 0002
Revises: 0001
Create Date: 2026/08/16 20:00

@Author: 花海
@Date: 2026/08/16 20:00
@Description: order-service 订单事件可靠投递（Outbox 模式，规范 §21.3）：订单落库与
              事件记录同事务写入 message_outbox，由框架 OutboxPublisher 轮询投递 MQ，
              投递失败指数退避重试、超限进死信（S9-4/P0-3）。
              字段与框架 db/init/ddl/001-mq-init-ddl.sql（含 next_retry_at 增量）对齐。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级迁移：创建 message_outbox 表（Outbox 本地事务表）"""
    op.create_table(
        "message_outbox",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False, primary_key=True, comment="主键"),
        sa.Column("msg_id", sa.String(64), nullable=False, comment="消息幂等键组成之一（规范 §9.2）"),
        sa.Column("biz_id", sa.String(64), nullable=False, comment="业务键（幂等键组成之一，如 orderId）"),
        sa.Column("topic", sa.String(128), nullable=False, comment="目标 Topic"),
        sa.Column("tag", sa.String(64), nullable=True, comment="Tag（对齐 §5.8 消息常量规范）"),
        sa.Column("payload", sa.Text(), nullable=False, comment="消息体（JSON）"),
        sa.Column("status", sa.SmallInteger().with_variant(mysql.TINYINT(), "mysql"), nullable=False, server_default=sa.text("0"), comment="0 待发送 / 1 已发送 / 2 失败超限 / 3 死信队列"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="投递重试次数（§9.6）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间（清理判断依据）"),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="最近一次投递/重试时间"),
        sa.Column("cleaned_at", sa.DateTime(), nullable=True, comment="清理时间（§21.3 清理策略）"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True, comment="下次可重试时间（指数退避，NULL 立即重试，S9-4）"),
        sa.UniqueConstraint("msg_id", "biz_id", name="uk_msg_biz"),
        sa.Index("idx_status_next_retry", "status", "next_retry_at"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_comment="Outbox 本地事务表",
    )


def downgrade() -> None:
    """回滚迁移：删除 message_outbox 表"""
    op.drop_table("message_outbox")
