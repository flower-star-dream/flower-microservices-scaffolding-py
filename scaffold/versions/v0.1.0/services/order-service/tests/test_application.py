"""
应用装配单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证 order-service 应用装配：create_app 组件注入、业务路由注册、健康检查端点。
"""
import httpx
import pytest

from web_infra import create_app

from order_service.api.v1.order_controller import router as order_router


def test_create_app_components():
    """应用装配：默认组件注入 app.state（MySQL 懒连接不触发建连）"""
    app = create_app({"app.name": "order-service-test"})
    components = app.state.components
    assert components["cache"] is app.state.cache
    assert components["db"] is app.state.db
    assert "mongo" not in components


def test_router_registered():
    """业务路由注册到应用（新版 FastAPI include_router 延迟解析，经 url_path_for 断言）"""
    app = create_app({"app.name": "order-service-test"})
    app.include_router(order_router)
    assert app.url_path_for("create_order") == "/v1/orders"
    assert app.url_path_for("get_order", order_id=1) == "/v1/orders/1"
    assert app.url_path_for("list_orders") == "/v1/orders"
    assert app.url_path_for("update_status", order_id=1) == "/v1/orders/1/status"


def test_health_endpoints():
    """健康检查端点（存活 / 就绪 / 兼容 / 指标）"""
    app = create_app({"app.name": "order-service-test"})
    paths = {route.path for route in app.routes}
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/health" in paths
    assert "/metrics" in paths


@pytest.mark.asyncio
async def test_health_live_ok():
    """存活探针返回 200"""
    app = create_app({"app.name": "order-service-test"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/live")
        assert resp.status_code == 200
