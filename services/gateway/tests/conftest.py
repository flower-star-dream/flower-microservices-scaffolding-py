"""
测试公共夹具（conftest）

@Author: 花海
@Date: 2026/08/16
@Description: gateway 测试夹具：create_app 默认配置（内存注册中心/缓存）装配应用，
              注册假下游服务实例（user-service / order-service），并将 FeignClient 的
              httpx 客户端替换为 MockTransport（本地测试不触网）。
"""
import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gateway.proxy_router import DEFAULT_ROUTES, router as gateway_router
from web_infra import create_app
from web_infra.capabilities.http.feign_client import FeignClient
from web_infra.capabilities.registry import ServiceInstance


def _upstream_handler(request: httpx.Request) -> httpx.Response:
    """模拟下游服务的 HTTP 响应（按路径前缀返回，统一 Result 结构）"""
    if request.url.path.startswith("/v1/users"):
        return httpx.Response(200, json={"code": "S0000", "data": {"id": 1, "username": "alice"}})
    if request.url.path.startswith("/v1/orders"):
        return httpx.Response(201, json={"code": "S0000", "data": {"id": 100, "order_no": "NO10001"}})
    return httpx.Response(404, json={"code": "S40400", "message": "not found"})


@pytest_asyncio.fixture
async def app():
    """装配应用：内存注册中心注册假下游实例 + FeignClient 用 MockTransport 拦截出网请求"""
    application = create_app({"app.name": "gateway-test"})
    # 捕获被转发的上游请求（供测试断言路径/方法/参数/体）
    captured: list[httpx.Request] = []
    application.state.forwarded = captured

    def _capture_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _upstream_handler(request)

    feign = FeignClient(
        registry=application.state.registry,
        timeout=10.0,
        retries=1,
        retry_delay_base=0.01,
        retry_delay_max=0.05,
    )
    feign._client = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler))
    application.state.feign = feign
    application.state.gateway_routes = DEFAULT_ROUTES
    # 注册假下游服务实例（注册中心发现链路）
    await application.state.registry.register("user-service", ServiceInstance(ip="127.0.0.1", port=8001))
    await application.state.registry.register("order-service", ServiceInstance(ip="127.0.0.1", port=8002))
    application.include_router(gateway_router)
    yield application
    await feign.close()


@pytest_asyncio.fixture
async def client(app):
    """HTTP 测试客户端（ASGI 直连，无需启动真实服务）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
