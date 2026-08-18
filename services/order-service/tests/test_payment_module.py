"""
订单支付示例模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 订单支付（payment SPI 示例）测试：下单（预支付）、查单、支付回调驱动订单状态机
              （支付成功 → 订单 PAID）、回调幂等（重复/非法流转忽略）。内存渠道不触网。
"""
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from web_infra import BizException, CommonErrorCode, create_app
from web_infra.capabilities.cache import MemoryCacheBackend
from web_infra.capabilities.mq import InMemoryMessageQueue, MysqlOutboxStore
from web_infra.capabilities.payment import (
    InMemoryLimitCounterStore,
    InMemoryPaymentFlowStore,
    InMemoryPaymentGateway,
    InMemoryPaymentOrderStore,
    PaymentCallback,
    PaymentCallbackDispatcher,
    PaymentErrorCode,
    PaymentGatewayRegistry,
    PaymentRiskGuard,
)
from web_infra.capabilities.payment.risk.payment_limit_config import LimitRule

from order_service.api.v1.order_controller import router as order_router
from order_service.api.v1.order_payment_controller import router as payment_router
from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.payment.order_payment_callback_handler import OrderPaymentCallbackHandler
from order_service.payment.order_payment_service import OrderPaymentService
from order_service.repository.order_repository import OrderRepository
from order_service.schema.order_schema import OrderCreateRequest
from order_service.service.order_service import OrderService
from order_service.state.order_state_machine import OrderStatus


class _FakeUserClient:
    """用户服务远程客户端替身（ID=1 用户存在）"""

    async def get_user(self, user_id: int) -> dict | None:
        """按 ID 返回假用户（仅 ID=1 存在）"""
        return {"id": 1, "username": "alice"} if user_id == 1 else None


def _build_order_service(db) -> OrderService:
    """构造订单服务（注入 SQLite 内存库 + Outbox 存储 + 内存缓存）"""
    outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    return OrderService(
        repository=OrderRepository(db),
        user_client=_FakeUserClient(),
        publisher=OrderEventPublisher(outbox_store),
        cache=MemoryCacheBackend(),
        db=db,
    )


@pytest.mark.asyncio
async def test_prepay_and_query(db):
    """下单：按订单金额向渠道创建支付单；查单可查到支付单"""
    order_service = _build_order_service(db)
    vo = await order_service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("99.50")))
    gateway = InMemoryPaymentGateway()
    service = OrderPaymentService(OrderRepository(db), gateway)

    resp = await service.prepay(vo.id)
    assert resp.prepay_id == f"prepay-{vo.order_no}"  # 内存渠道：prepay-{out_trade_no}

    order = await service.query_order(vo.order_no)
    assert order is not None
    assert order.out_trade_no == vo.order_no


@pytest.mark.asyncio
async def test_prepay_order_not_found(db):
    """下单订单不存在：抛 COMMON_NOT_FOUND"""
    service = OrderPaymentService(OrderRepository(db), InMemoryPaymentGateway())
    with pytest.raises(BizException) as exc_info:
        await service.prepay(999)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_prepay_per_transaction_limit_rejected(db):
    """风控限额（§9.1）：单笔超限抛 E4-PAY-005，不透传渠道"""
    order_service = _build_order_service(db)
    vo = await order_service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("999999.00")))
    gateway = InMemoryPaymentGateway()
    service = OrderPaymentService(
        OrderRepository(db), gateway,
        risk_guard=PaymentRiskGuard(InMemoryLimitCounterStore()),
        limit_rule=LimitRule(per_transaction=Decimal("5000")),
    )
    with pytest.raises(BizException) as exc_info:
        await service.prepay(vo.id)
    assert exc_info.value.code == PaymentErrorCode.PAY_LIMIT_EXCEEDED.code


@pytest.mark.asyncio
async def test_notify_pays_order(db):
    """支付回调：支付成功 → 订单状态机 PAY → 订单 PAID"""
    order_service = _build_order_service(db)
    vo = await order_service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("66.60")))

    handler = OrderPaymentCallbackHandler(order_service)
    await handler.handle(
        PaymentCallback(
            event_type="TRANSACTION.SUCCESS",
            out_trade_no=vo.order_no,
            transaction_id="txn-001",
            amount=Decimal("66.60"),
            attach=str(vo.id),
        )
    )
    updated = await OrderRepository(db).find_by_id(vo.id)
    assert updated is not None
    assert updated.status == OrderStatus.PAID


@pytest.mark.asyncio
async def test_notify_duplicate_idempotent(db):
    """回调幂等：订单已支付后重复收到支付成功回调，忽略且不抛错"""
    order_service = _build_order_service(db)
    vo = await order_service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("20.00")))
    handler = OrderPaymentCallbackHandler(order_service)

    await handler.handle(
        PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no=vo.order_no, amount=Decimal("20.00"), attach=str(vo.id))
    )
    # 重复回调（模拟 MQ 重投）：非法流转被状态机拦截，处理器忽略
    await handler.handle(
        PaymentCallback(event_type="TRANSACTION.SUCCESS", out_trade_no=vo.order_no, amount=Decimal("20.00"), attach=str(vo.id))
    )
    updated = await OrderRepository(db).find_by_id(vo.id)
    assert updated.status == OrderStatus.PAID


@pytest.mark.asyncio
async def test_notify_other_event_ignored(db):
    """非支付成功回调（如退款通知）：忽略，订单状态不变"""
    order_service = _build_order_service(db)
    vo = await order_service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("10.00")))
    handler = OrderPaymentCallbackHandler(order_service)

    await handler.handle(
        PaymentCallback(event_type="REFUND.SUCCESS", out_trade_no=vo.order_no, amount=Decimal("10.00"), attach=str(vo.id))
    )
    updated = await OrderRepository(db).find_by_id(vo.id)
    assert updated.status == OrderStatus.CREATED


@pytest_asyncio.fixture
async def payment_client(db):
    """支付接口测试客户端（挂 order_router + payment_router，装配内存渠道与回调分发器）"""
    application = create_app({"app.name": "order-service-payment-test"})
    application.state.db = db
    application.state.user_client = _FakeUserClient()
    application.state.outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    order_service = _build_order_service(db)
    application.state.order_service = order_service

    gateway = InMemoryPaymentGateway(
        flow_store=InMemoryPaymentFlowStore(),
        order_store=InMemoryPaymentOrderStore(),
    )
    PaymentGatewayRegistry.register("memory", gateway)
    dispatcher = PaymentCallbackDispatcher()
    dispatcher.register(OrderPaymentCallbackHandler(order_service))
    application.state.payment_dispatcher = dispatcher

    application.include_router(order_router)
    application.include_router(payment_router)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_pay_api(payment_client):
    """接口：订单发起支付返回统一响应结构（prepay_id）"""
    resp = await payment_client.post("/v1/orders", json={"user_id": 1, "amount": "88.00"})
    order_id = resp.json()["data"]["id"]

    resp = await payment_client.post(f"/v1/payments/orders/{order_id}/pay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["prepay_id"]


@pytest.mark.asyncio
async def test_notify_api(payment_client, db):
    """接口：下单 → 支付回调入口（骨架校验）→ 订单状态机 PAY → 订单 PAID（闭环演示）"""
    resp = await payment_client.post("/v1/orders", json={"user_id": 1, "amount": "77.00"})
    order = resp.json()["data"]
    # 先下单（骨架 prepay 写本地支付订单，§4.2：回调校验/关单确认依赖本地记录）
    resp = await payment_client.post(f"/v1/payments/orders/{order['id']}/pay")
    assert resp.status_code == 200

    resp = await payment_client.post(
        "/v1/payments/notify",
        json={
            "event_type": "TRANSACTION.SUCCESS",
            "out_trade_no": order["order_no"],
            "transaction_id": "txn-api-1",
            "amount": "77.00",
            "attach": str(order["id"]),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == "S0000"

    updated = await OrderRepository(db).find_by_id(order["id"])
    assert updated.status == OrderStatus.PAID


@pytest.mark.asyncio
async def test_notify_api_amount_mismatch_rejected(payment_client, db):
    """接口：回调金额与本地支付订单不符 → 骨架校验拒绝（E4-PAY-002，§4.3），订单不入账"""
    resp = await payment_client.post("/v1/orders", json={"user_id": 1, "amount": "55.00"})
    order = resp.json()["data"]
    resp = await payment_client.post(f"/v1/payments/orders/{order['id']}/pay")
    assert resp.status_code == 200

    resp = await payment_client.post(
        "/v1/payments/notify",
        json={
            "event_type": "TRANSACTION.SUCCESS",
            "out_trade_no": order["order_no"],
            "amount": "99.00",  # 与订单金额 55.00 不符
            "attach": str(order["id"]),
        },
    )
    assert resp.status_code == 422  # E4-PAY-002 业务异常统一映射 4xx（框架全局异常处理器）
    updated = await OrderRepository(db).find_by_id(order["id"])
    assert updated.status == OrderStatus.CREATED  # 未入账
