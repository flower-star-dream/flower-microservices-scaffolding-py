"""
订单状态机示例模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 订单状态机（state_machine 示例）测试：合法流转（创建→支付→发货→完成）、
              取消分支、非法流转拦截、事件处理器落库持久化，以及全局注册表演示。
"""
from decimal import Decimal

import pytest

from web_infra import BizException, CommonErrorCode
from web_infra.capabilities.cache import MemoryCacheBackend
from web_infra.capabilities.mq import InMemoryMessageQueue, MysqlOutboxStore
from web_infra.capabilities.state_machine import StateMachineErrorCode, StateMachineRegistry

from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.repository.order_repository import OrderRepository
from order_service.schema.order_schema import OrderCreateRequest
from order_service.service.order_service import OrderService
from order_service.state.order_state_machine import (
    OrderEvent,
    OrderStateRouter,
    OrderStatus,
    register_order_state_machine,
)


class _FakeUserClient:
    """用户服务远程客户端替身（ID=1 用户存在）"""

    async def get_user(self, user_id: int) -> dict | None:
        """按 ID 返回假用户（仅 ID=1 存在）"""
        return {"id": 1, "username": "alice"} if user_id == 1 else None


def _build_service(db) -> OrderService:
    """构造订单服务（注入 SQLite 内存库 + Outbox 存储 + 内存缓存）"""
    mq = InMemoryMessageQueue()
    outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    return OrderService(
        repository=OrderRepository(db),
        user_client=_FakeUserClient(),
        publisher=OrderEventPublisher(outbox_store),
        cache=MemoryCacheBackend(),
        db=db,
    )


@pytest.mark.asyncio
async def test_transition_full_flow(db):
    """完整合法流转：创建 → 支付 → 发货 → 完成（每步事件处理器落库持久化）"""
    service = _build_service(db)
    vo = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("99.50")))
    assert vo.status == OrderStatus.CREATED

    assert await service.transition(vo.id, OrderEvent.PAY) == OrderStatus.PAID
    assert (await OrderRepository(db).find_by_id(vo.id)).status == OrderStatus.PAID

    assert await service.transition(vo.id, OrderEvent.SHIP) == OrderStatus.SHIPPED
    assert (await OrderRepository(db).find_by_id(vo.id)).status == OrderStatus.SHIPPED

    assert await service.transition(vo.id, OrderEvent.COMPLETE) == OrderStatus.COMPLETED
    assert (await OrderRepository(db).find_by_id(vo.id)).status == OrderStatus.COMPLETED


@pytest.mark.asyncio
async def test_transition_cancel_branches(db):
    """取消分支：已创建/已支付均可取消到已取消"""
    service = _build_service(db)
    created = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("10.00")))
    assert await service.transition(created.id, OrderEvent.CANCEL) == OrderStatus.CANCELLED
    assert (await OrderRepository(db).find_by_id(created.id)).status == OrderStatus.CANCELLED

    paid = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("20.00")))
    await service.transition(paid.id, OrderEvent.PAY)
    assert await service.transition(paid.id, OrderEvent.CANCEL) == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_transition_illegal_intercepted(db):
    """非法流转被引擎拦截：已创建直接发货抛 ILLEGAL_STATE_TRANSITION，且状态未变"""
    service = _build_service(db)
    vo = await service.create_order(OrderCreateRequest(user_id=1, amount=Decimal("30.00")))

    with pytest.raises(BizException) as exc_info:
        await service.transition(vo.id, OrderEvent.SHIP)
    assert exc_info.value.code == StateMachineErrorCode.ILLEGAL_STATE_TRANSITION.code
    # 非法流转不落库
    assert (await OrderRepository(db).find_by_id(vo.id)).status == OrderStatus.CREATED


@pytest.mark.asyncio
async def test_transition_order_not_found(db):
    """订单不存在：抛 COMMON_NOT_FOUND"""
    service = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.transition(999, OrderEvent.PAY)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_registry_demo(db):
    """全局注册表演示：register_order_state_machine 注册并复用引擎（重复注册同 key 抛 ValueError）"""
    machine = register_order_state_machine(OrderRepository(db))
    assert machine is not None

    # 再次注册同 key 抛 ValueError（进程内单例）
    with pytest.raises(ValueError):
        StateMachineRegistry.register_instance(OrderStateRouter(OrderRepository(db)))
