"""
订单接口层（Controller）

@Author: 花海
@Date: 2026/08/16
@Description: 订单管理 HTTP 接口：创建（远程校验用户 + 发布事件）/ 详情 / 按用户分页 / 状态更新，
              统一返回 Result / PageResult。演示微服务能力：注册中心 + FeignClient 服务间调用、
              消息队列事件发布、统一响应与分页。
"""
from fastapi import APIRouter, Depends, Query, Request

from web_infra import PageResult, Result
from web_infra.capabilities.db.page_query import PageQuery

from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.repository.order_repository import OrderRepository
from order_service.schema.order_schema import OrderCreateRequest, OrderStatusUpdateRequest
from order_service.service.order_service import OrderService


def get_order_service(request: Request) -> OrderService:
    """构造订单服务（依赖注入：从应用已装配组件获取 db / cache / mq / user_client）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 订单服务实例
    """
    return OrderService(
        repository=OrderRepository(request.app.state.db),
        user_client=request.app.state.user_client,
        publisher=OrderEventPublisher(request.app.state.outbox_store),
        cache=request.app.state.cache,
        db=request.app.state.db,
    )


router = APIRouter(prefix="/v1/orders", tags=["订单管理"])


@router.post("", summary="创建订单")
async def create_order(
    request: OrderCreateRequest, service: OrderService = Depends(get_order_service)
) -> Result:
    """创建订单（经注册中心发现 user-service 校验用户，成功后发布订单创建事件）"""
    return Result.success(data=await service.create_order(request))


@router.get("/{order_id}", summary="查询订单详情")
async def get_order(order_id: int, service: OrderService = Depends(get_order_service)) -> Result:
    """查询订单详情（按主键）"""
    return Result.success(data=await service.get_order(order_id))


@router.get("", summary="按用户分页查询订单")
async def list_orders(
    user_id: int = Query(ge=1, description="用户 ID（按用户维度分页查询）"),
    page_no: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页大小"),
    service: OrderService = Depends(get_order_service),
) -> PageResult:
    """按用户分页查询订单（演示框架 PageQuery 分页参数与 PageResult 分页响应）"""
    query = PageQuery(page_no=page_no, page_size=page_size)
    orders, total = await service.list_orders_by_user(user_id, query.page_no, query.page_size)
    return PageResult.success(records=orders, total=total)


@router.patch("/{order_id}/status", summary="更新订单状态")
async def update_status(
    order_id: int,
    request: OrderStatusUpdateRequest,
    service: OrderService = Depends(get_order_service),
) -> Result:
    """更新订单状态（状态机驱动：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消）"""
    await service.update_status(order_id, request.status)
    return Result.success()
