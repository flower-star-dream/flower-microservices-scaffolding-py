"""
用户 ORM 模型（Model）

@Author: 花海
@Date: 2026/08/16
@Description: 用户实体模型（继承 web_infra.Base，数据库访问强制走 ORM 会话规范 §10），
              对应库 flower_user 中的表 t_user。模型属性命名使用 snake_case。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from web_infra import Base


class UserModel(Base):
    """用户实体模型"""

    __tablename__ = "t_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="密码哈希（bcrypt）")
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="昵称")
    status: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="状态：1 启用 / 0 禁用"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, onupdate=func.now(), comment="更新时间"
    )
