"""
订单状态机（状态/事件/路由定义）

@Author: 花海
@Date: 2026/08/16
@Description: 订单生命周期状态机示例，演示框架 state_machine 能力：
              - OrderStatus / OrderEvent：状态与事件枚举
              - OrderStateRouter(StateRouter[OrderStatus, OrderEvent, OrderModel])：
                声明合法流转表（状态×事件→目标状态）与事件处理器（处理器内持久化落库）
              - StateMachine：流转合法性校验 + 事件分发（fire_async 支持异步处理器）
              使用方式一（引擎实例，OrderService 采用）：build_order_state_machine(repository)
              使用方式二（全局注册表，多业务共享）：StateMachineRegistry.register_instance(router) 后
              StateMachineRegistry.get(OrderStatus, OrderEvent, OrderModel) 复用引擎实例。
              状态语义（与 OrderConstant / t_order.status 一致）：
              1 已创建 → 2 已支付 → 3 已发货 → 4 已完成；已创建/已支付可取消（5 已取消）。
"""
from __future__ import annotations

from enum import Enum, IntEnum
from typing import Callable, cast

from web_infra import CommonErrorCode
from web_infra.capabilities.state_machine import (
    StateMachine,
    StateMachineErrorCode,
    StateMachineRegistry,
    StateRouteParams,
    StateRouter,
)

from order_service.model.order_model import OrderModel
from order_service.repository.order_repository import OrderRepository


class OrderStatus(IntEnum):
    """订单状态（与 t_order.status 存储值一致）"""

    CREATED = 1  # 已创建
    PAID = 2  # 已支付
    SHIPPED = 3  # 已发货
    COMPLETED = 4  # 已完成
    CANCELLED = 5  # 已取消


class OrderEvent(Enum):
    """订单状态流转事件"""

    PAY = "pay"  # 支付成功（支付回调触发）
    SHIP = "ship"  # 发货
    COMPLETE = "complete"  # 完成
    CANCEL = "cancel"  # 取消


class OrderStateRouter(StateRouter[OrderStatus, OrderEvent, OrderModel]):
    """订单状态路由：合法流转表 + 事件处理器（处理器内持久化订单状态）"""

    def __init__(self, repository: OrderRepository) -> None:
        """初始化路由

        :param repository: 订单仓储（事件处理器持久化用）
        """
        self._repository = repository

    def get_state_event_target_config(self) -> dict[OrderStatus, dict[OrderEvent, OrderStatus]]:
        """状态×事件 → 目标状态 合法组合表（引擎据此校验流转合法性）"""
        return {
            OrderStatus.CREATED: {
                OrderEvent.PAY: OrderStatus.PAID,
                OrderEvent.CANCEL: OrderStatus.CANCELLED,
            },
            OrderStatus.PAID: {
                OrderEvent.SHIP: OrderStatus.SHIPPED,
                OrderEvent.CANCEL: OrderStatus.CANCELLED,
            },
            OrderStatus.SHIPPED: {
                OrderEvent.COMPLETE: OrderStatus.COMPLETED,
            },
        }

    def get_event_dispatcher(self) -> dict[OrderEvent, Callable]:
        """事件 → 业务处理器（签名 handler(current_state, params)，持久化由处理器完成）"""
        return {
            OrderEvent.PAY: self._persist(OrderStatus.PAID),
            OrderEvent.SHIP: self._persist(OrderStatus.SHIPPED),
            OrderEvent.COMPLETE: self._persist(OrderStatus.COMPLETED),
            OrderEvent.CANCEL: self._persist(OrderStatus.CANCELLED),
        }

    def _persist(self, target: OrderStatus) -> Callable:
        """构造持久化处理器：按 params.order_id 落库目标状态（重复流转由引擎校验拦截）

        :param target: 目标状态
        :return: 事件处理器（async）
        """

        async def _handler(current_state: OrderStatus, params: StateRouteParams) -> OrderStatus:
            """持久化订单状态并返回目标状态

            :param current_state: 当前状态（引擎已校验合法）
            :param params: 路由参数（须含 order_id）
            :return: 目标状态
            :raises BizException: 缺少 order_id 抛 EMPTY_PARAMETER；订单不存在抛 COMMON_NOT_FOUND
            """
            order_id = params.get_param("order_id")
            if order_id is None:
                raise StateMachineErrorCode.EMPTY_PARAMETER.to_exception(message="状态流转缺少 order_id 参数")
            updated = await self._repository.update_status(int(order_id), int(target))
            if not updated:
                raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="订单不存在")
            return target

        return _handler


def build_order_state_machine(repository: OrderRepository) -> StateMachine[OrderStatus, OrderEvent, OrderModel]:
    """构造订单状态机引擎（路由注入仓储，事件处理器落库持久化）

    演示引擎实例用法（无全局状态，适合服务实例持有）；多业务共享同型状态机时
    可用全局注册表：StateMachineRegistry.register_instance(OrderStateRouter(repository))，
    随后 StateMachineRegistry.get(OrderStatus, OrderEvent, OrderModel) 获取复用引擎。

    :param repository: 订单仓储
    :return: 订单状态机引擎
    """
    return StateMachine(OrderStateRouter(repository))


def register_order_state_machine(repository: OrderRepository) -> StateMachine[OrderStatus, OrderEvent, OrderModel]:
    """演示全局注册表用法：注册订单状态机路由并返回复用引擎（重复注册同 key 抛 ValueError）

    :param repository: 订单仓储
    :return: 注册表获取的状态机引擎
    :raises ValueError: 同 key 已注册（进程内单例，测试/重启场景需自行管理）
    """
    StateMachineRegistry.register_instance(OrderStateRouter(repository))
    # 注册表按 key 返回引擎实例（类型为 StateMachineEngine），业务侧已知为 StateMachine 实现
    return cast(
        StateMachine[OrderStatus, OrderEvent, OrderModel],
        StateMachineRegistry.get(OrderStatus, OrderEvent, OrderModel),
    )
