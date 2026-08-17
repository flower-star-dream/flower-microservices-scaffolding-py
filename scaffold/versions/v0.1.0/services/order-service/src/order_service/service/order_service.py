"""
订单服务层（Service）

@Author: 花海
@Date: 2026/08/16
@Description: 订单业务逻辑：创建（远程校验用户 + 落库 + 发布事件）、详情查询（带缓存防穿透）、
              按用户分页、状态更新。演示微服务能力：FeignClient 服务间远程调用、消息队列事件发布、
              统一错误码、缓存空值防穿透。
"""
from datetime import datetime
from typing import Any

from web_infra import CommonErrorCode, get_logger
from web_infra.cache import CacheBackendInterface
from web_infra.utils import snowflake_id

from order_service.client.user_client import UserClient
from order_service.constants.order_constant import OrderConstant
from order_service.model.order_model import OrderModel
from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.repository.order_repository import OrderRepository
from order_service.schema.order_schema import OrderCreateRequest, OrderVO

logger = get_logger("order.service")


class OrderService:
    """订单服务：业务规则与用例编排"""

    def __init__(
        self,
        repository: OrderRepository,
        user_client: UserClient,
        publisher: OrderEventPublisher,
        cache: CacheBackendInterface,
    ) -> None:
        """初始化服务

        :param repository: 订单仓储
        :param user_client: 用户服务远程客户端（FeignClient）
        :param publisher: 订单事件发布器
        :param cache: 缓存后端（app.state.cache）
        """
        self._repository = repository
        self._user_client = user_client
        self._publisher = publisher
        self._cache = cache

    async def create_order(self, request: OrderCreateRequest) -> OrderVO:
        """创建订单（远程校验用户存在 → 落库 → 发布订单创建事件）

        :param request: 创建请求
        :return: 订单出参
        :raises BizException: 用户不存在时抛 COMMON_NOT_FOUND；用户服务不可用时抛 SYS_UNAVAILABLE
        """
        # 1) 远程校验用户存在（FeignClient：注册中心发现 user-service + 负载均衡 + 熔断）
        user = await self._user_client.get_user(request.user_id)
        if user is None:
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="用户不存在")

        # 2) 生成订单号并落库（订单号 = 时间戳 + 雪花 ID，保证唯一且可排序）
        order = OrderModel(
            order_no=self._generate_order_no(),
            user_id=request.user_id,
            amount=request.amount,
            status=OrderConstant.ORDER_STATUS_CREATED,
        )
        created = await self._repository.create(order)

        # 3) 发布订单创建事件（MQ，异步消费幂等）
        await self._publisher.publish_created(created)
        logger.info(
            "order_created order_id=%s order_no=%s user_id=%s",
            created.id, created.order_no, created.user_id,
        )
        return self._to_vo(created)

    async def get_order(self, order_id: int) -> OrderVO:
        """查询订单详情（带缓存，空值占位防穿透规范 §8.2）

        :param order_id: 订单 ID
        :return: 订单出参
        :raises BizException: 订单不存在时抛 COMMON_NOT_FOUND
        """
        cache_key = OrderConstant.ORDER_CACHE_KEY_TEMPLATE.format(order_id=order_id)
        if await self._cache.is_empty(cache_key):
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="订单不存在")
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return OrderVO.model_validate(cached)

        order = await self._repository.find_by_id(order_id)
        if order is None:
            await self._cache.set_empty(cache_key, ttl=OrderConstant.ORDER_CACHE_EMPTY_TTL_SECONDS)
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="订单不存在")
        vo = self._to_vo(order)
        await self._cache.set(cache_key, vo.model_dump(mode="json"), ttl=OrderConstant.ORDER_CACHE_TTL_SECONDS)
        return vo

    async def list_orders_by_user(self, user_id: int, page_no: int, page_size: int) -> tuple[list[OrderVO], int]:
        """按用户分页查询订单

        :param user_id: 用户 ID
        :param page_no: 页码（从 1 开始）
        :param page_size: 每页大小
        :return: (订单出参列表, 总数)
        """
        orders, total = await self._repository.find_page_by_user(user_id, page_no, page_size)
        return [self._to_vo(order) for order in orders], total

    async def update_status(self, order_id: int, status: int) -> None:
        """更新订单状态（更新后失效缓存）

        :param order_id: 订单 ID
        :param status: 目标状态
        :raises BizException: 订单不存在时抛 COMMON_NOT_FOUND
        """
        updated = await self._repository.update_status(order_id, status)
        if not updated:
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="订单不存在")
        await self._cache.delete(OrderConstant.ORDER_CACHE_KEY_TEMPLATE.format(order_id=order_id))
        logger.info("order_status_updated order_id=%s status=%s", order_id, status)

    @staticmethod
    def _generate_order_no() -> str:
        """生成订单号（时间戳 + 雪花 ID，保证唯一且可排序）"""
        return f"{datetime.now():%Y%m%d%H%M%S}{snowflake_id()}"

    @staticmethod
    def _to_vo(order: OrderModel) -> OrderVO:
        """ORM 模型转出参 VO（金额转字符串，避免精度丢失）

        :param order: 订单模型
        :return: 订单出参
        """
        return OrderVO(
            id=order.id,
            order_no=order.order_no,
            user_id=order.user_id,
            amount=f"{order.amount:.2f}",
            status=order.status,
            created_at=order.created_at,
        )
