"""
订单支付服务（OrderPaymentService）

@Author: 花海
@Date: 2026/08/16
@Description: 订单支付编排，演示框架支付 SPI：
              - PaymentGateway（渠道统一抽象：下单/查单/关单/退款，金额 Decimal 元）
              - PaymentGatewayRegistry（类级注册表，main.py 装配注册渠道）
              - PaymentRiskGuard（风控限额，规范 §9：单笔/日/月限额、频次、可疑拆分，
                注入后下单前校验，超限抛 E4-PAY-005/006/007）
              下单（prepay）按订单号作为商户订单号（out_trade_no，渠道侧唯一/幂等键），
              attach 携带订单 ID 供回调关联；生产接入真实渠道（如微信 WeChatPayProvider）时
              仅替换注册的渠道实现，本服务代码不变。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from web_infra import CommonErrorCode
from web_infra.payment import (
    PaymentGateway,
    PaymentOrder,
    PaymentPrepayRequest,
    PaymentPrepayResponse,
    PaymentRiskGuard,
    PaymentScene,
)
from web_infra.payment.risk.payment_limit_config import LimitRule

from order_service.repository.order_repository import OrderRepository


class OrderPaymentService:
    """订单支付服务：下单 / 查单（支付网关渠道抽象 + 风控限额，§9）"""

    def __init__(self, repository: OrderRepository, gateway: PaymentGateway,
                 risk_guard: PaymentRiskGuard | None = None, limit_rule: LimitRule | None = None) -> None:
        """初始化支付服务

        :param repository: 订单仓储
        :param gateway: 支付网关渠道（PaymentGatewayRegistry.get("memory")，生产换真实渠道）
        :param risk_guard: 风控守卫（§9，None 时不启用限额/频次校验）
        :param limit_rule: 渠道限额规则（§9.1 配置化，None 时不限制）
        """
        self._repository = repository
        self._gateway = gateway
        self._risk_guard = risk_guard
        self._limit_rule = limit_rule

    async def prepay(self, order_id: int) -> PaymentPrepayResponse:
        """订单发起支付（下单）：风控校验（§9）→ 按订单金额向渠道创建支付单

        :param order_id: 订单 ID
        :return: 渠道下单结果（prepay_id / code_url / h5_url 按场景）
        :raises BizException: 订单不存在抛 COMMON_NOT_FOUND；限额/频次/风控超限抛 E4-PAY-005/006/007
        """
        order = await self._repository.find_by_id(order_id)
        if order is None:
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="订单不存在")
        # 风控限额前置校验（§9.1/§9.2/§9.3）：未注入 guard/rule 时跳过（配置化）
        if self._risk_guard is not None and self._limit_rule is not None:
            await self._risk_guard.check_prepay(
                user_id=order.user_id, channel="memory",
                amount=Decimal(order.amount), rule=self._limit_rule,
            )
        request = PaymentPrepayRequest(
            scene=PaymentScene.APP,
            out_trade_no=order.order_no,
            description=f"订单{order.order_no}",
            total_amount=Decimal(order.amount),
            attach=str(order.id),  # 回调原样返回，用于关联订单状态机
        )
        return await self._gateway.prepay(request)

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        """按商户订单号查单（支付结果以渠道查询/回调为准）

        :param out_trade_no: 商户订单号（订单表 order_no）
        :return: 支付订单或 None（渠道无记录）
        """
        return await self._gateway.query_order(out_trade_no)
