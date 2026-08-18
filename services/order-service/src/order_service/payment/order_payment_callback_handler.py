"""
订单支付回调处理器（OrderPaymentCallbackHandler）

@Author: 花海
@Date: 2026/08/16
@Description: 支付回调业务处理器（PaymentCallbackHandler SPI 实现）：支付成功回调
              （TRANSACTION.SUCCESS）→ 订单状态机 PAY 事件推进订单为已支付。
              幂等：重复回调/非法流转（订单已支付再次 PAY）由状态机引擎拦截并忽略，
              回调入口不抛错（框架 PaymentCallbackDispatcher 语义）；业务侧以订单状态为准。
"""
from __future__ import annotations

from web_infra import BizException, get_logger
from web_infra.capabilities.payment import PaymentCallback, PaymentCallbackHandler
from web_infra.capabilities.state_machine import StateMachineErrorCode

from order_service.service.order_service import OrderService
from order_service.state.order_state_machine import OrderEvent

logger = get_logger("order.payment")


class OrderPaymentCallbackHandler(PaymentCallbackHandler):
    """订单支付回调处理器：支付成功 → 订单状态机 PAY"""

    def __init__(self, order_service: OrderService) -> None:
        """初始化回调处理器

        :param order_service: 订单服务（transition 状态机驱动，main.py 装配共享实例）
        """
        self._order_service = order_service

    async def handle(self, callback: PaymentCallback) -> None:
        """处理支付/退款回调（仅支付成功驱动订单状态机，退款回调按需扩展）

        :param callback: 统一回调结构（验签解密后由分发器分发）
        """
        if callback.event_type != "TRANSACTION.SUCCESS":
            logger.info("非支付成功回调忽略 event_type=%s out_trade_no=%s", callback.event_type, callback.out_trade_no)
            return
        if callback.attach is None:
            logger.warning("支付回调缺少 attach（下单时未携带订单 ID）out_trade_no=%s", callback.out_trade_no)
            return
        order_id = int(callback.attach)
        try:
            await self._order_service.transition(order_id, OrderEvent.PAY)
        except BizException as exc:
            # 幂等：订单已支付/已取消等非法流转（重复回调、并发回调）直接忽略，回调入口不抛错
            if exc.code == StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.code:
                logger.warning("支付回调流转非法已忽略 order_id=%s（可能重复回调）", order_id)
                return
            raise
        logger.info("payment_success order_id=%s out_trade_no=%s amount=%s", order_id, callback.out_trade_no, callback.amount)
