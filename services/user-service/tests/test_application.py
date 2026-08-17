"""
应用装配单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证 user-service 应用装配：create_app 组件注入、业务路由注册、健康检查端点。
"""
import httpx
import pytest

from web_infra import create_app

from user_service.api.v1.user_controller import router as user_router


def test_create_app_components():
    """应用装配：默认组件注入 app.state（MySQL 懒连接不触发建连）"""
    app = create_app({"app.name": "user-service-test"})
    components = app.state.components
    assert components["cache"] is app.state.cache
    assert components["db"] is app.state.db
    assert "mongo" not in components


def test_router_registered():
    """业务路由注册到应用（新版 FastAPI include_router 延迟解析，经 url_path_for 断言）"""
    app = create_app({"app.name": "user-service-test"})
    app.include_router(user_router)
    assert app.url_path_for("get_user", user_id=1) == "/v1/users/1"
    assert app.url_path_for("list_users") == "/v1/users"
    assert app.url_path_for("create_user") == "/v1/users"
    assert app.url_path_for("update_status", user_id=1) == "/v1/users/1/status"


def test_health_endpoints():
    """健康检查端点（存活 / 就绪 / 兼容 / 指标）"""
    app = create_app({"app.name": "user-service-test"})
    paths = {route.path for route in app.routes}
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/health" in paths
    assert "/metrics" in paths


@pytest.mark.asyncio
async def test_health_live_ok():
    """存活探针返回 200"""
    app = create_app({"app.name": "user-service-test"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/live")
        assert resp.status_code == 200
