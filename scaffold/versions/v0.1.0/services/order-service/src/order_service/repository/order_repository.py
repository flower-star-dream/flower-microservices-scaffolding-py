"""
订单仓储层（Repository）

@Author: 花海
@Date: 2026/08/16
@Description: 订单数据访问封装：统一走框架 orm_session()（退出自动提交/回滚/关闭，规范 §10.6），
              业务禁止裸获取连接。依赖注入数据库工厂（app.state.db，实现 DatabaseFactoryInterface）。
"""
from typing import Any

from sqlalchemy import func, select, update

from order_service.model.order_model import OrderModel


class OrderRepository:
    """订单仓储：封装订单表的 ORM 读写"""

    def __init__(self, db: Any) -> None:
        """初始化仓储

        :param db: 数据库工厂（app.state.db，实现 DatabaseFactoryInterface）
        """
        self._db = db

    async def find_by_id(self, order_id: int) -> OrderModel | None:
        """按主键查询订单

        :param order_id: 订单 ID
        :return: 订单模型或 None
        """
        async with self._db.orm_session() as session:
            return await session.get(OrderModel, order_id)

    async def find_page_by_user(self, user_id: int, page_no: int, page_size: int) -> tuple[list[OrderModel], int]:
        """按用户分页查询订单（按主键倒序）

        :param user_id: 用户 ID
        :param page_no: 页码（从 1 开始）
        :param page_size: 每页大小
        :return: (订单列表, 总数)
        """
        async with self._db.orm_session() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(OrderModel).where(OrderModel.user_id == user_id)
                )
            ).scalar_one()
            result = await session.execute(
                select(OrderModel)
                .where(OrderModel.user_id == user_id)
                .order_by(OrderModel.id.desc())
                .offset((page_no - 1) * page_size)
                .limit(page_size)
            )
            return list(result.scalars().all()), int(total)

    async def create(self, order: OrderModel) -> OrderModel:
        """新增订单

        :param order: 待新增的订单模型
        :return: 已落库的订单模型（含主键）
        """
        async with self._db.orm_session() as session:
            session.add(order)
            await session.flush()
            return order

    async def update_status(self, order_id: int, status: int) -> bool:
        """更新订单状态

        :param order_id: 订单 ID
        :param status: 目标状态
        :return: 是否更新成功
        """
        async with self._db.orm_session() as session:
            result = await session.execute(
                update(OrderModel).where(OrderModel.id == order_id).values(status=status)
            )
            return result.rowcount > 0
