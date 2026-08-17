"""
订单事件消费者（OrderEventConsumer）

@Author: 花海
@Date: 2026/08/16
@Description: 订单事件消费（幂等，规范 §9.2：bizId + msgId 幂等键，重复消费跳过）。
              仅 mq.type=memory 时由 main.py 装配到进程内 InMemoryMessageQueue；
              生产 RocketMQ 场景由外部消费组消费（框架提供 IdempotentConsumer 封装，接入点不变）。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.mq import (
    IdempotentConsumer,
    InMemoryMessageIdempotencyStore,
    Message,
    MessageConsumerInterface,
)

from order_service.constants.order_constant import OrderConstant

logger = logging.getLogger("order_service.mq")


class OrderEventConsumer:
    """订单事件消费者：幂等消费 order.created 事件"""

    def __init__(
        self,
        mq: MessageConsumerInterface,
        idempotency_store: Any | None = None,
    ) -> None:
        """初始化消费者

        :param mq: 消息消费者（实现 MessageConsumerInterface，如 InMemoryMessageQueue）
        :param idempotency_store: 幂等键存储（缺省内存实现；生产跨实例用 RedisMessageIdempotencyStore）
        """
        self._mq = mq
        self._idempotent = IdempotentConsumer(idempotency_store or InMemoryMessageIdempotencyStore())
        # 消费观测记录（供测试断言；生产仅用日志/指标，不依赖此列表）
        self._handled: list[dict[str, Any]] = []

    def register(self) -> None:
        """订阅订单创建事件"""
        self._mq.subscribe(OrderConstant.ORDER_EVENT_TOPIC, self._handle)

    async def _handle(self, message: Message) -> None:
        """消息处理入口（幂等封装，业务失败自动回滚幂等键允许重试，规范 §9.6）"""
        await self._idempotent.consume(message, self._process)

    async def _process(self, message: Message) -> None:
        """业务处理：订单创建事件（此处演示幂等消费与结构化日志，业务可扩展如通知/积分）"""
        order_id = message.body.get("order_id")
        order_no = message.body.get("order_no")
        logger.info("order_event_consumed order_id=%s order_no=%s", order_id, order_no)
        self._handled.append(message.body)
