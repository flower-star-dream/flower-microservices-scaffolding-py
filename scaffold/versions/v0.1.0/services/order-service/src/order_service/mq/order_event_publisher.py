"""
订单事件发布器（OrderEventPublisher）

@Author: 花海
@Date: 2026/08/16
@Description: 订单事件发布（规范 §9）：统一 Message 结构（topic/tag 常量收敛于 OrderConstant），
              按业务主键（order_id）作为分区键保证同一订单消息分区内串行。
              依赖 MessagePublisherInterface SPI：本地用内存队列、生产切 RocketMQ（RocketMqPublisher）。
"""
from __future__ import annotations

from web_infra.mq import Message, MessagePublisherInterface

from order_service.constants.order_constant import OrderConstant
from order_service.model.order_model import OrderModel


class OrderEventPublisher:
    """订单事件发布器"""

    def __init__(self, mq: MessagePublisherInterface) -> None:
        """初始化发布器

        :param mq: 消息发布者（app.state.mq，实现 MessagePublisherInterface）
        """
        self._mq = mq

    async def publish_created(self, order: OrderModel) -> str:
        """发布订单创建事件

        :param order: 已落库的订单模型
        :return: 消息 ID
        """
        message = Message(
            topic=OrderConstant.ORDER_EVENT_TOPIC,
            tag=OrderConstant.ORDER_EVENT_TAG_CREATED,
            body={
                "biz_id": str(order.id),
                "order_id": str(order.id),
                "order_no": order.order_no,
                "user_id": str(order.user_id),
                "amount": f"{order.amount:.2f}",
            },
            partition_key=str(order.id),
        )
        return await self._mq.publish(message)
