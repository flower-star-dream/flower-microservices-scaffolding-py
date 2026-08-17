"""基线迁移：创建用户表 t_user

Revision ID: 0001
Revises:
Create Date: 2026/08/16 10:00

@Author: 花海
@Date: 2026/08/16 10:00
@Description: user-service 示例业务表 t_user 基线迁移（等价 db/init/ddl/001-user-init-ddl.sql）。
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
    """升级迁移：创建 t_user 表（用户表）"""
    op.create_table(
        "t_user",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
            primary_key=True,
            comment="主键",
        ),
        sa.Column("username", sa.String(64), nullable=False, comment="用户名"),
        sa.Column("password_hash", sa.String(128), nullable=False, comment="密码哈希（bcrypt）"),
        sa.Column("nickname", sa.String(64), nullable=True, comment="昵称"),
        sa.Column(
            "status",
            sa.SmallInteger().with_variant(mysql.TINYINT(), "mysql"),
            nullable=False,
            server_default=sa.text("1"),
            comment="状态：1 启用 / 0 禁用",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="更新时间"),
        sa.UniqueConstraint("username", name="uk_username"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_comment="用户表",
    )


def downgrade() -> None:
    """回滚迁移：删除 t_user 表"""
    op.drop_table("t_user")
