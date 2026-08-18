"""
JWT SPI 示例模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 认证服务（JWT SPI 示例）测试：登录签发（同设备凭证复用）、Token 校验、
              登出撤销、静默刷新，以及接口层统一响应结构验证。
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from web_infra import BizException, CommonErrorCode
from web_infra import create_app
from web_infra.capabilities.cache import MemoryCacheBackend
from web_infra.capabilities.security import InMemoryJwtTokenStore

from user_service.api.v1.auth_controller import router as auth_router
from user_service.api.v1.user_controller import router as user_router
from user_service.repository.user_repository import UserRepository
from user_service.schema.user_schema import UserCreateRequest
from user_service.security.jwt_auth_service import JwtAuthService
from user_service.service.user_service import UserService


def _build_service(db, store: InMemoryJwtTokenStore | None = None) -> tuple[JwtAuthService, InMemoryJwtTokenStore]:
    """构造认证服务（注入 SQLite 内存库 + 显式内存 Token 状态存储，便于断言撤销状态）"""
    store = store or InMemoryJwtTokenStore()
    service = JwtAuthService(UserRepository(db), token_store=store)
    return service, store


@pytest.mark.asyncio
async def test_login_issue_tokens(db):
    """登录成功：签发 access/refresh token，并写入 Token 状态存储（jti 有效）"""
    user = await UserService(UserRepository(db), MemoryCacheBackend()).create_user(
        UserCreateRequest(username="alice", password="secret123")
    )
    service, store = _build_service(db)

    token = await service.login("alice", "secret123")
    assert token.access_token
    assert token.refresh_token
    # access token 状态已写入存储（登出/校验依赖）
    payload = await service.validate(token.access_token)
    assert payload["sub"] == str(user.id)
    assert await store.exists(str(user.id), payload["jti"])


@pytest.mark.asyncio
async def test_login_wrong_password(db):
    """登录密码错误：抛 AUTH_INVALID"""
    await UserService(UserRepository(db), MemoryCacheBackend()).create_user(
        UserCreateRequest(username="alice", password="secret123")
    )
    service, _ = _build_service(db)

    with pytest.raises(BizException) as exc_info:
        await service.login("alice", "wrong-password")
    assert exc_info.value.code == CommonErrorCode.AUTH_INVALID.code


@pytest.mark.asyncio
async def test_validate_invalid_token(db):
    """校验非法 Token：抛 AUTH_INVALID"""
    service, _ = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.validate("not-a-jwt")
    assert exc_info.value.code == CommonErrorCode.AUTH_INVALID.code


@pytest.mark.asyncio
async def test_logout_revokes_token(db):
    """登出：jti 撤销后再次校验抛 AUTH_INVALID（规范 §6.7 凭证撤销）"""
    await UserService(UserRepository(db), MemoryCacheBackend()).create_user(
        UserCreateRequest(username="bob", password="secret123")
    )
    service, store = _build_service(db)

    token = await service.login("bob", "secret123")
    payload = await service.validate(token.access_token)
    assert await store.exists(str(payload["sub"]), payload["jti"]) is True

    assert await service.logout(token.access_token) is True
    assert await store.exists(str(payload["sub"]), payload["jti"]) is False
    with pytest.raises(BizException) as exc_info:
        await service.validate(token.access_token)
    assert exc_info.value.code == CommonErrorCode.AUTH_INVALID.code


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(db):
    """静默刷新：refresh token 换取新 access/refresh token，新 token 可校验"""
    await UserService(UserRepository(db), MemoryCacheBackend()).create_user(
        UserCreateRequest(username="carol", password="secret123")
    )
    service, _ = _build_service(db)

    token = await service.login("carol", "secret123")
    refreshed = await service.refresh(token.refresh_token)
    assert refreshed.access_token
    assert refreshed.refresh_token != token.refresh_token
    payload = await service.validate(refreshed.access_token)
    assert payload["username"] == "carol"


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(db):
    """防混用（规范 §6.1）：用 access token 冒充 refresh token 抛 AUTH_INVALID"""
    await UserService(UserRepository(db), MemoryCacheBackend()).create_user(
        UserCreateRequest(username="dave", password="secret123")
    )
    service, _ = _build_service(db)

    token = await service.login("dave", "secret123")
    with pytest.raises(BizException) as exc_info:
        await service.refresh(token.access_token)
    assert exc_info.value.code == CommonErrorCode.AUTH_INVALID.code


@pytest_asyncio.fixture
async def auth_client(db):
    """认证接口测试客户端（挂 auth_router + user_router，db 替换为 SQLite 内存库）"""
    application = create_app({"app.name": "user-service-auth-test"})
    application.state.db = db
    application.include_router(user_router)
    application.include_router(auth_router)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_login_api(auth_client):
    """接口：登录签发返回统一响应结构（code=S0000 + Token 出参）"""
    await auth_client.post("/v1/users", json={"username": "erin", "password": "secret123"})

    resp = await auth_client.post(
        "/v1/auth/token", json={"username": "erin", "password": "secret123", "client_id": "web", "device_id": "pc-1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["access_token"]
    assert body["data"]["token_type"] == "Bearer"


@pytest.mark.asyncio
async def test_login_api_bad_password(auth_client):
    """接口：密码错误返回统一错误响应（AUTH_INVALID）"""
    await auth_client.post("/v1/users", json={"username": "frank", "password": "secret123"})

    resp = await auth_client.post("/v1/auth/token", json={"username": "frank", "password": "bad-pass"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == CommonErrorCode.AUTH_INVALID.code
