"""
网关路由转发单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证网关路径路由转发：按路由表将 /api/{service_key}/{path} 请求经注册中心发现
              并转发到下游服务（透传方法 / 路径 / 查询参数 / JSON 体 / 状态码），未知路由统一错误。
"""
import json

import pytest

from web_infra import CommonErrorCode


@pytest.mark.asyncio
async def test_proxy_user_get(client, app):
    """GET /api/users/1 -> user-service /v1/users/1（返回上游 JSON）"""
    resp = await client.get("/api/users/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["username"] == "alice"

    forwarded = app.state.forwarded[-1]
    assert forwarded.method == "GET"
    assert forwarded.url.path == "/v1/users/1"
    assert forwarded.url.port == 8001  # user-service 实例端口（注册中心发现）


@pytest.mark.asyncio
async def test_proxy_order_post(client, app):
    """POST /api/orders -> order-service /v1/orders（透传 JSON 体与上游状态码 201）"""
    resp = await client.post("/api/orders", json={"user_id": 1, "amount": "10.00"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["order_no"] == "NO10001"

    forwarded = app.state.forwarded[-1]
    assert forwarded.method == "POST"
    assert forwarded.url.path == "/v1/orders"
    assert forwarded.url.port == 8002  # order-service 实例端口（注册中心发现）
    assert json.loads(forwarded.content) == {"user_id": 1, "amount": "10.00"}


@pytest.mark.asyncio
async def test_proxy_query_params(client, app):
    """查询参数透传：/api/users?page_no=2&page_size=5"""
    resp = await client.get("/api/users", params={"page_no": 2, "page_size": 5})
    assert resp.status_code == 200

    forwarded = app.state.forwarded[-1]
    assert forwarded.url.path == "/v1/users"
    assert forwarded.url.params["page_no"] == "2"
    assert forwarded.url.params["page_size"] == "5"


@pytest.mark.asyncio
async def test_proxy_nested_path(client, app):
    """嵌套路径透传：PATCH /api/users/1/status -> /v1/users/1/status"""
    resp = await client.patch("/api/users/1/status", json={"status": 0})
    assert resp.status_code == 200

    forwarded = app.state.forwarded[-1]
    assert forwarded.method == "PATCH"
    assert forwarded.url.path == "/v1/users/1/status"
    assert json.loads(forwarded.content) == {"status": 0}


@pytest.mark.asyncio
async def test_proxy_unknown_route(client):
    """未知路由键：HTTP 404 + 统一错误码"""
    resp = await client.get("/api/unknown/1")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == CommonErrorCode.COMMON_NOT_FOUND.code
