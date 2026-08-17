"""
订单模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 订单服务与接口测试：创建（远程用户校验 / 事件发布）、查询（缓存 / 空值占位防穿透）、
              分页、状态更新、MQ 幂等消费、UserClient+FeignClient 服务发现调用链路（MockTransport 不触网）。
"""
import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest

from web_infra import BizException, CommonErrorCode
from web_infra.cache import MemoryCacheBackend
from web_infra.http.feign_client import FeignClient
from web_infra.mq import InMemoryMessageIdempotencyStore, Message
from web_infra.mq.in_memory_message_queue import InMemoryMessageQueue
from web_infra.registry import InMemoryServiceRegistry, ServiceInstance
from web_infra.resilience import CircuitBreakerConfig

from order_service.api.v1.order_controller import router as order_router
from order_service.client.user_client import UserClient
from order_service.constants.order_constant import OrderConstant
from order_service.model.order_model import OrderModel
from order_service.mq.order_event_consumer import OrderEventConsumer
from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.repository.order_repository import OrderRepository
from order_service.schema.order_schema import OrderCreateRequest
from order_service.service.order_service import OrderService


class _FakeUserClient:
    """用户服务远程客户端替身（内存返回，避免测试触网）"""

    def __init__(self, users: dict[int, dict] | None = None) -> None:
        self._users = users or {1: {"id": 1, "username": "alice"}}

    async def get_user(self, user_id: int) -> dict | None:
        """按 ID 返回假用户（不存在返回 None）"""
        return self._users.get(user_id)


def _build_service(db, users: dict[int, dict] | None = None) -> tuple[OrderService, InMemoryMessageQueue, Any]:
    """构造订单服务（注入 SQLite 内存库 + 假用户客户端 + 内存消息队列 + Outbox 存储 + 内存缓存）"""
    mq = InMemoryMessageQueue()
    from web_infra.mq import MysqlOutboxStore

    outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    service = OrderService(
        repository=OrderRepository(db),
        user_client=_FakeUserClient(users),
        publisher=OrderEventPublisher(outbox_store),
        cache=MemoryCacheBackend(),
        db=db,
    )
    return service, mq, outbox_store


async def _wait_until(condition, timeout: float = 2.0) -> bool:
    """轮询等待条件成立（消费循环异步处理场景）"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_create_order_success(db):
    """创建订单成功：远程校验用户通过、订单落库、事件写入 Outbox（同事务，不直接发 MQ）"""
    service, mq, outbox_store = _build_service(db)
    vo = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("99.50")))

    assert vo.id is not None
    assert vo.order_no.startswith("20")  # 时间戳前缀
    assert vo.user_id == 1
    assert vo.amount == "99.50"
    assert vo.status == OrderConstant.ORDER_STATUS_CREATED
    saved = await OrderRepository(db).find_by_id(vo.id)
    assert saved is not None
    assert saved.order_no == vo.order_no
    # 事件已写入 Outbox（待发送），未直接发布到 MQ
    assert mq._queue.qsize() == 0
    pending = await outbox_store.next_pending()
    assert len(pending) == 1
    assert pending[0].biz_id == str(vo.id)
    assert pending[0].topic == OrderConstant.ORDER_EVENT_TOPIC
    # 轮询投递后消息进入 MQ（OutboxPublisher 兜底，规范 §21.3）
    from web_infra.mq import OutboxPublisher

    outbox = OutboxPublisher(outbox_store, mq)
    assert await outbox.publish_pending() == 1
    assert mq._queue.qsize() == 1


@pytest.mark.asyncio
async def test_create_order_user_not_found(db):
    """创建订单用户不存在（user-service 返回 404）：抛 COMMON_NOT_FOUND，且不落库、无 Outbox 记录"""
    service, mq, outbox_store = _build_service(db, users={})
    with pytest.raises(BizException) as exc_info:
        await service.create_order(OrderCreateRequest(user_id=999, amount=Decimal("10.00")))
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code
    assert await OrderRepository(db).find_by_id(999) is None  # 未落库
    assert await outbox_store.next_pending() == []  # 未写入 Outbox


@pytest.mark.asyncio
async def test_get_order_cached(db):
    """查询订单：首次落库并写缓存，二次命中缓存"""
    service, _, _ = _build_service(db)
    created = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("20.00")))

    vo = await service.get_order(created.id)
    assert vo.order_no == created.order_no
    cache_key = OrderConstant.ORDER_CACHE_KEY_TEMPLATE.format(order_id=created.id)
    assert await service._cache.get(cache_key) is not None


@pytest.mark.asyncio
async def test_get_order_not_found_empty_placeholder(db):
    """查询不存在的订单：抛 COMMON_NOT_FOUND 并写空值占位（防穿透，规范 §8.2）"""
    service, _, _ = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.get_order(999)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code
    cache_key = OrderConstant.ORDER_CACHE_KEY_TEMPLATE.format(order_id=999)
    assert await service._cache.is_empty(cache_key) is True


@pytest.mark.asyncio
async def test_list_orders_by_user_page(db):
    """按用户分页查询订单：总数与倒序"""
    service, _, _ = _build_service(db)
    for i in range(5):
        await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal(f"{i + 1}.00")))

    orders, total = await service.list_orders_by_user(1, 1, 10)
    assert total == 5
    assert len(orders) == 5
    assert orders[0].id > orders[1].id  # 按主键倒序


@pytest.mark.asyncio
async def test_update_status_success(db):
    """更新订单状态成功"""
    service, _, _ = _build_service(db)
    vo = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("30.00")))

    await service.update_status(vo.id, OrderConstant.ORDER_STATUS_PAID)
    updated = await OrderRepository(db).find_by_id(vo.id)
    assert updated is not None
    assert updated.status == OrderConstant.ORDER_STATUS_PAID


@pytest.mark.asyncio
async def test_update_status_not_found(db):
    """更新不存在的订单：抛 COMMON_NOT_FOUND"""
    service, _, _ = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.update_status(999, OrderConstant.ORDER_STATUS_CANCELLED)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_order_event_consumer_idempotent(db):
    """订单事件幂等消费：同 biz_id 消息重复消费跳过（规范 §9.2）"""
    mq = InMemoryMessageQueue()
    consumer = OrderEventConsumer(mq, InMemoryMessageIdempotencyStore())
    consumer.register()
    await mq.start()
    try:
        await mq.publish(
            Message(
                topic=OrderConstant.ORDER_EVENT_TOPIC,
                tag=OrderConstant.ORDER_EVENT_TAG_CREATED,
                body={"biz_id": "biz-10001", "order_id": "10001", "order_no": "N10001"},
                partition_key="10001",
            )
        )
        assert await _wait_until(lambda: len(consumer._handled) >= 1)
        assert len(consumer._handled) == 1

        # 同 biz_id 再次投递（模拟 MQ 重投）：幂等键命中，跳过
        await mq.publish(
            Message(
                topic=OrderConstant.ORDER_EVENT_TOPIC,
                tag=OrderConstant.ORDER_EVENT_TAG_CREATED,
                body={"biz_id": "biz-10001", "order_id": "10001", "order_no": "N10001"},
                partition_key="10001",
            )
        )
        await asyncio.sleep(0.1)
        assert len(consumer._handled) == 1
    finally:
        await mq.stop()


@pytest.mark.asyncio
async def test_outbox_publish_consumed_idempotently(db):
    """全链路兜底：创建订单 → Outbox 同事务落库 → 轮询投递 MQ → 幂等消费（不重复处理）"""
    from web_infra.mq import OutboxPublisher

    service, mq, outbox_store = _build_service(db)
    consumer = OrderEventConsumer(mq, InMemoryMessageIdempotencyStore())
    consumer.register()
    await mq.start()
    try:
        vo = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("88.00")))
        assert mq._queue.qsize() == 0  # 事件尚未直接进入 MQ（在 Outbox 中）

        outbox = OutboxPublisher(outbox_store, mq)
        assert await outbox.publish_pending() == 1
        # 投递成功：消息被幂等消费一次
        assert await _wait_until(lambda: len(consumer._handled) >= 1)
        assert len(consumer._handled) == 1
        assert consumer._handled[0]["order_id"] == str(vo.id)
        # 再次轮询：已发送记录不再投递（不重复消费）
        assert await outbox.publish_pending() == 0
        await asyncio.sleep(0.1)
        assert len(consumer._handled) == 1
    finally:
        await mq.stop()


# ---------------------------------------------------------------------------
# UserClient + FeignClient 链路（注册中心发现 + 负载均衡 + HTTP 调用，MockTransport 不触网）
# ---------------------------------------------------------------------------


def _fake_user_http_handler(request: httpx.Request) -> httpx.Response:
    """模拟 user-service 的 HTTP 响应（按路径返回，统一 Result 结构）"""
    if request.url.path == "/v1/users/1":
        return httpx.Response(200, json={"code": "S0000", "data": {"id": 1, "username": "alice"}})
    if request.url.path == "/v1/users/999":
        return httpx.Response(404, json={"code": CommonErrorCode.COMMON_NOT_FOUND.code, "message": "用户不存在"})
    return httpx.Response(500, json={"code": "S0000", "message": "internal error"})


@pytest.mark.asyncio
async def test_user_client_feign_wiring():
    """UserClient + FeignClient 完整链路：注册中心发现实例 → 负载均衡 → HTTP 调用 → 解析 Result"""
    registry = InMemoryServiceRegistry()
    await registry.register("user-service", ServiceInstance(ip="127.0.0.1", port=8001))

    feign = FeignClient(registry=registry, retries=1, retry_delay_base=0.01, retry_delay_max=0.05)
    # 用 MockTransport 拦截出网请求（本地测试不触网）
    feign._client = httpx.AsyncClient(transport=httpx.MockTransport(_fake_user_http_handler))
    client = UserClient(feign)
    try:
        data = await client.get_user(1)
        assert data is not None
        assert data["username"] == "alice"
        # 用户不存在（上游 404）：返回 None
        assert await client.get_user(999) is None
    finally:
        await feign.close()


@pytest.mark.asyncio
async def test_user_client_default_fallback():
    """框架默认兜底：启用熔断未传 fallback 时，服务不可用返回统一 503，UserClient 归一为 SYS_UNAVAILABLE（规范 §7.4）"""
    registry = InMemoryServiceRegistry()  # 未注册任何实例
    feign = FeignClient(
        registry=registry,
        retries=1,
        retry_delay_base=0.01,
        circuit_breaker_config=CircuitBreakerConfig(minimum_number_of_calls=1),
    )
    client = UserClient(feign)
    try:
        with pytest.raises(BizException) as exc_info:
            await client.get_user(1)
        assert exc_info.value.code == CommonErrorCode.SYS_UNAVAILABLE.code
    finally:
        await feign.close()


@pytest.mark.asyncio
async def test_user_client_custom_fallback_none():
    """业务自定义降级（fallback 返回 None）：UserClient 兜底为 SYS_UNAVAILABLE"""
    registry = InMemoryServiceRegistry()  # 未注册任何实例
    feign = FeignClient(
        registry=registry,
        retries=1,
        retry_delay_base=0.01,
        circuit_breaker_config=CircuitBreakerConfig(minimum_number_of_calls=1),
        fallback=lambda service_name: None,  # 业务自定义降级：无兜底数据
    )
    client = UserClient(feign)
    try:
        with pytest.raises(BizException) as exc_info:
            await client.get_user(1)
        assert exc_info.value.code == CommonErrorCode.SYS_UNAVAILABLE.code
    finally:
        await feign.close()


@pytest.mark.asyncio
async def test_create_order_api_success(client):
    """接口：创建订单成功返回统一响应结构（code=S0000）"""
    resp = await client.post("/v1/orders", json={"user_id": 1, "amount": "66.60"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["user_id"] == 1
    assert body["data"]["amount"] == "66.60"
    assert body["data"]["order_no"]


@pytest.mark.asyncio
async def test_create_order_api_user_not_found(client):
    """接口：创建订单用户不存在返回统一错误响应（HTTP 404 + 业务错误码）"""
    resp = await client.post("/v1/orders", json={"user_id": 999, "amount": "10.00"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_create_order_api_idempotent(db):
    """接口兜底：幂等键中间件防重复下单（规范 §12.6：同键重放首次结果，订单仅一条）"""
    from httpx import ASGITransport, AsyncClient

    from web_infra import create_app
    from web_infra.mq import MysqlOutboxStore
    from web_infra.web.idempotency_middleware import IdempotencyMiddleware
    from web_infra.web.in_memory_idempotency_store import InMemoryIdempotencyStore

    application = create_app({"app.name": "order-service-test"})
    application.state.db = db
    application.state.user_client = _FakeUserClient()
    application.state.outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    application.add_middleware(IdempotencyMiddleware, store=InMemoryIdempotencyStore())
    application.include_router(order_router)

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        payload = {"user_id": 1, "amount": "55.00"}
        headers = {"Idempotency-Key": "idem-create-001"}
        first = await c.post("/v1/orders", json=payload, headers=headers)
        second = await c.post("/v1/orders", json=payload, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        # 重复请求重放首次结果（同一订单），不重复创建
        assert first.json()["data"]["id"] == second.json()["data"]["id"]
        _, total = await OrderRepository(db).find_page_by_user(1, 1, 10)
        assert total == 1
