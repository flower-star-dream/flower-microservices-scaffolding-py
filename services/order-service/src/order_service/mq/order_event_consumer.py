"""
订单事件消费者（OrderEventConsumer）

@Author: 花海
@Date: 2026/08/16
@Description: 订单事件消费（幂等 + 异常分类重试，规范 §9.1/§9.2）：
              - IdempotentConsumer：bizId + msgId 幂等键，重复消费跳过（§9.2）
              - RetryableConsumer：业务失败按异常分类指数退避重试，超限或不可重试进死信（§9.6/P0-3）
              仅 mq.type=memory 时由 main.py 装配到进程内 InMemoryMessageQueue；
              生产 RocketMQ 场景由外部消费组消费（框架提供封装，接入点不变）。
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

from web_infra.mq import (
    IdempotentConsumer,
    InMemoryMessageIdempotencyStore,
    Message,
    MessageConsumerInterface,
    RetryableConsumer,
)

from order_service.constants.order_constant import OrderConstant

logger = logging.getLogger("order_service.mq")

# 消费观测记录容量上限（仅内存 MQ 演示形态使用；有界防止进程内长期运行内存无限增长）
HANDLED_RECORD_LIMIT = 1024


class OrderEventConsumer:
    """订单事件消费者：幂等 + 可重试消费 order.created 事件"""

    def __init__(
        self,
        mq: MessageConsumerInterface,
        idempotency_store: Any | None = None,
        dlq_publisher: Any | None = None,
    ) -> None:
        """初始化消费者

        :param mq: 消息消费者（实现 MessageConsumerInterface，如 InMemoryMessageQueue）
        :param idempotency_store: 幂等键存储（缺省内存实现；生产跨实例用 RedisMessageIdempotencyStore）
        :param dlq_publisher: 死信发布者（MessagePublisherInterface；重试超限/不可重试时投递死信，
                              缺省 None 时不启用 RetryableConsumer 重试，仅幂等）
        """
        self._mq = mq
        self._idempotent = IdempotentConsumer(idempotency_store or InMemoryMessageIdempotencyStore())
        self._retry = RetryableConsumer(dlq_publisher) if dlq_publisher is not None else None
        # 消费观测记录（供测试断言；deque 有界容量 HANDLED_RECORD_LIMIT，防内存无限增长；
        # 生产仅用日志/指标，不依赖此列表）
        self._handled: deque[dict[str, Any]] = deque(maxlen=HANDLED_RECORD_LIMIT)

    def register(self) -> None:
        """订阅订单创建事件"""
        self._mq.subscribe(OrderConstant.ORDER_EVENT_TOPIC, self._handle)

    async def _handle(self, message: Message) -> None:
        """消息处理入口：幂等封装 + 异常分类重试（业务失败回滚幂等键允许重试，规范 §9.6）"""
        if self._retry is not None:
            await self._retry.consume(message, self._consume_idempotent)
        else:
            await self._consume_idempotent(message)

    async def _consume_idempotent(self, message: Message) -> None:
        """幂等消费封装（RetryableConsumer 回调：失败抛异常由外层分类重试）"""
        await self._idempotent.consume(message, self._process)

    async def _process(self, message: Message) -> None:
        """业务处理：订单创建事件（此处演示幂等消费与结构化日志，业务可扩展如通知/积分）"""
        order_id = message.body.get("order_id")
        order_no = message.body.get("order_no")
        logger.info("order_event_consumed order_id=%s order_no=%s", order_id, order_no)
        self._handled.append(message.body)
