"""
订单事件发布器（OrderEventPublisher）

@Author: 花海
@Date: 2026/08/16
@Description: 订单事件发布（Outbox 本地事务表，规范 §21.3）：与订单落库同事务写入
              message_outbox（同库同事务提交，杜绝"订单已落库但事件丢失"），
              由框架 OutboxPublisher 轮询投递 MQ（投递失败指数退避重试、超限进死信 S9-4/P0-3）。
              topic/tag 常量收敛于 OrderConstant；biz_id 用订单 ID（幂等键组成之一，规范 §9.2）。
              依赖 OutboxStoreInterface SPI：MySQL 生产实现 MysqlOutboxStore。
"""
from __future__ import annotations

from typing import Any

from web_infra.mq import MysqlOutboxStore, OutboxRecord

from order_service.constants.order_constant import OrderConstant
from order_service.model.order_model import OrderModel


class OrderEventPublisher:
    """订单事件发布器（Outbox 模式：业务事务内追加待发送记录，异步轮询投递 MQ）"""

    def __init__(self, outbox_store: MysqlOutboxStore) -> None:
        """初始化发布器

        :param outbox_store: Outbox 存储（MysqlOutboxStore，append 支持 session 同事务写入）
        """
        self._outbox_store = outbox_store

    async def append_created(self, order: OrderModel, session: Any | None = None) -> OutboxRecord:
        """追加订单创建事件到 Outbox（与订单落库同事务提交时传业务 session）

        :param order: 已落库（或待落库）的订单模型
        :param session: 业务事务会话（同事务写入保证不丢消息，规范 §21.3 S21-1）；None 时自建会话
        :return: Outbox 记录（含生成的 msg_id）
        """
        record = OutboxRecord(
            topic=OrderConstant.ORDER_EVENT_TOPIC,
            tag=OrderConstant.ORDER_EVENT_TAG_CREATED,
            biz_id=str(order.id),
            payload={
                "biz_id": str(order.id),
                "order_id": str(order.id),
                "order_no": order.order_no,
                "user_id": str(order.user_id),
                "amount": f"{order.amount:.2f}",
            },
        )
        return await self._outbox_store.append(record, session=session)
