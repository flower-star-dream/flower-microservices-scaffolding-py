"""
用户仓储层（Repository）

@Author: 花海
@Date: 2026/08/16
@Description: 用户数据访问封装：统一走框架 orm_session()（退出自动提交/回滚/关闭，规范 §10.6），
              业务禁止裸获取连接。依赖注入数据库工厂（app.state.db，实现 DatabaseFactoryInterface）。
"""
from typing import Any

from sqlalchemy import func, select, update

from user_service.model.user_model import UserModel


class UserRepository:
    """用户仓储：封装用户表的 ORM 读写"""

    def __init__(self, db: Any) -> None:
        """初始化仓储

        :param db: 数据库工厂（app.state.db，实现 DatabaseFactoryInterface）
        """
        self._db = db

    async def find_by_id(self, user_id: int) -> UserModel | None:
        """按主键查询用户

        :param user_id: 用户 ID
        :return: 用户模型或 None
        """
        async with self._db.orm_session() as session:
            return await session.get(UserModel, user_id)

    async def find_by_username(self, username: str) -> UserModel | None:
        """按用户名查询用户

        :param username: 用户名
        :return: 用户模型或 None
        """
        async with self._db.orm_session() as session:
            result = await session.execute(select(UserModel).where(UserModel.username == username))
            return result.scalar_one_or_none()

    async def find_page(self, page_no: int, page_size: int) -> tuple[list[UserModel], int]:
        """分页查询用户（普通分页，按主键倒序）

        :param page_no: 页码（从 1 开始）
        :param page_size: 每页大小
        :return: (用户列表, 总数)
        """
        async with self._db.orm_session() as session:
            total = (await session.execute(select(func.count()).select_from(UserModel))).scalar_one()
            result = await session.execute(
                select(UserModel)
                .order_by(UserModel.id.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
            return list(result.scalars().all()), int(total)

    async def create(self, user: UserModel) -> UserModel:
        """新增用户

        :param user: 待新增的用户模型
        :return: 已落库的用户模型（含主键）
        """
        async with self._db.orm_session() as session:
            session.add(user)
            await session.flush()
            return user

    async def update_status(self, user_id: int, status: int) -> bool:
        """更新用户状态

        :param user_id: 用户 ID
        :param status: 目标状态
        :return: 是否更新成功
        """
        async with self._db.orm_session() as session:
            result = await session.execute(
                update(UserModel).where(UserModel.id == user_id).values(status=status)
            )
            return result.rowcount > 0
