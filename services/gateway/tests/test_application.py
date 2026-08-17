"""
应用装配单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证 gateway 应用装配：create_app 组件注入、网关路由注册、健康检查端点。
"""
import httpx
import pytest

from web_infra import create_app

from gateway.proxy_router import router as gateway_router


def test_create_app_components():
    """应用装配：默认组件注入 app.state（无外部依赖，db 为 SQLite 内存库）"""
    app = create_app({"app.name": "gateway-test"})
    components = app.state.components
    assert components["cache"] is app.state.cache
    assert components["db"] is app.state.db
    assert components["registry"] is app.state.registry
    assert "mongo" not in components


def test_router_registered():
    """网关路由注册到应用（/api/{service_key} 与 /api/{service_key}/{path:path} 兜底路由）"""
    app = create_app({"app.name": "gateway-test"})
    app.include_router(gateway_router)
    # 新版 FastAPI include_router 延迟解析（app.routes 为 _IncludedRouter 包装），经 url_path_for 断言
    assert app.url_path_for("proxy", service_key="users", path="1") == "/api/users/1"
    assert app.url_path_for("proxy", service_key="users", path="") == "/api/users/"


def test_health_endpoints():
    """健康检查端点（存活 / 就绪 / 兼容 / 指标）"""
    app = create_app({"app.name": "gateway-test"})
    paths = {route.path for route in app.routes}
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/health" in paths
    assert "/metrics" in paths


@pytest.mark.asyncio
async def test_health_live_ok():
    """存活探针返回 200"""
    app = create_app({"app.name": "gateway-test"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/live")
        assert resp.status_code == 200
