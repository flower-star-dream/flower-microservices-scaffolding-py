"""
网关路由转发（ProxyRouter）

@Author: 花海
@Date: 2026/08/16
@Description: 网关路由控制器：/api/{service_key}/{path:path} 按路由表经 FeignClient（注册中心
              发现 + 负载均衡 + 重试 + 熔断）转发到下游服务，透传上游状态码与响应体。
              路由表来源：app.state.gateway_routes（main.py 由 yml app.gateway.routes 加载，缺省回落 DEFAULT_ROUTES）。
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response

from web_infra import CommonErrorCode

# 内置默认路由表（yml app.gateway.routes 可覆盖/追加；{service_key} 为 /api/ 后第一段路径）
DEFAULT_ROUTES: dict[str, dict[str, str]] = {
    "users": {"service": "user-service", "prefix": "/v1/users"},
    "orders": {"service": "order-service", "prefix": "/v1/orders"},
}

# 允许透传的 HTTP 方法（GET/POST/PUT/PATCH/DELETE）
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

router = APIRouter(prefix="/api", tags=["网关路由"])


@router.api_route("/{service_key}", methods=_PROXY_METHODS, include_in_schema=False, summary="服务路由转发（无尾斜杠）")
@router.api_route("/{service_key}/{path:path}", methods=_PROXY_METHODS, summary="服务路由转发")
async def proxy(service_key: str, request: Request, path: str = "") -> Response:
    """按路由表将请求转发到下游服务（经注册中心发现实例）

    :param service_key: 路由键（如 users -> user-service）
    :param path: 剩余路径（追加到路由前缀之后；缺省表示仅服务根路径，如 /api/orders）
    :param request: 原始请求（透传 method / query / json body）
    :return: 上游响应（透传状态码与响应体）
    :raises BizException: 路由不存在（COMMON_NOT_FOUND）/ 服务熔断降级（SYS_UNAVAILABLE）
    """
    route = _find_route(request, service_key)
    if route is None:
        raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message=f"未找到服务路由：{service_key}")

    feign = request.app.state.feign
    target_path = f"{route['prefix']}/{path}" if path else route["prefix"]
    resp = await feign.request(
        route["service"],
        request.method,
        target_path,
        json_data=await _read_json_body(request),
        params=dict(request.query_params),
    )
    if resp is None:
        raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message=f"服务 {route['service']} 暂不可用（熔断降级）")
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


def _find_route(request: Request, service_key: str) -> dict[str, str] | None:
    """从路由表查找服务路由（优先 app.state.gateway_routes，缺省回落内置默认路由）"""
    routes = getattr(request.app.state, "gateway_routes", None) or DEFAULT_ROUTES
    return routes.get(service_key)


async def _read_json_body(request: Request) -> dict | None:
    """读取请求 JSON 体（空体/非 JSON 返回 None，GET 等无体请求不报错）"""
    try:
        return await request.json()
    except Exception:  # noqa: BLE001 - 空体 / 非法 JSON 统一视为无体
        return None
