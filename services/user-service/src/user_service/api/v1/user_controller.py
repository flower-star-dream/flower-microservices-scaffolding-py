"""
用户接口层（Controller）

@Author: 花海
@Date: 2026/08/16
@Description: 用户管理 HTTP 接口：详情 / 分页 / 创建 / 状态更新，统一返回 Result / PageResult。
              演示框架：统一响应结构、分页参数（PageQuery）、依赖注入（Request + app.state 组件）。
              本服务注册中心服务名为 user-service，供 order-service（Feign 调用）与 gateway（路由转发）发现。
"""
from fastapi import APIRouter, Depends, Query, Request

from web_infra import PageResult, Result
from web_infra.db.page_query import PageQuery

from user_service.repository.user_repository import UserRepository
from user_service.schema.user_schema import UserCreateRequest, UserStatusUpdateRequest
from user_service.service.user_service import UserService


def get_user_service(request: Request) -> UserService:
    """构造用户服务（依赖注入：从应用已装配组件获取 db / cache）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 用户服务实例
    """
    return UserService(
        repository=UserRepository(request.app.state.db),
        cache=request.app.state.cache,
    )


router = APIRouter(prefix="/v1/users", tags=["用户管理"])


@router.get("/{user_id}", summary="查询用户详情")
async def get_user(user_id: int, service: UserService = Depends(get_user_service)) -> Result:
    """查询用户详情（按主键）"""
    return Result.success(data=await service.get_user(user_id))


@router.get("", summary="分页查询用户")
async def list_users(
    page_no: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页大小"),
    service: UserService = Depends(get_user_service),
) -> PageResult:
    """分页查询用户（演示框架 PageQuery 分页参数与 PageResult 分页响应）"""
    query = PageQuery(page_no=page_no, page_size=page_size)
    users, total = await service.list_users(query.page_no, query.page_size)
    return PageResult.success(records=users, total=total)


@router.post("", summary="创建用户")
async def create_user(
    request: UserCreateRequest, service: UserService = Depends(get_user_service)
) -> Result:
    """创建用户（用户名查重 + 密码加密）"""
    return Result.success(data=await service.create_user(request))


@router.patch("/{user_id}/status", summary="更新用户状态")
async def update_status(
    user_id: int,
    request: UserStatusUpdateRequest,
    service: UserService = Depends(get_user_service),
) -> Result:
    """更新用户状态（启用 / 禁用）"""
    await service.update_status(user_id, request.status)
    return Result.success()
