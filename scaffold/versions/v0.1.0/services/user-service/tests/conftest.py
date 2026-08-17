"""
测试公共夹具（conftest）

@Author: 花海
@Date: 2026/08/16
@Description: user-service 测试夹具：SQLite 内存库（StaticPool 共享连接）替换 MySQL 组件，
              使业务模块测试不依赖外部 MySQL/Redis/Nacos 服务即可运行（本地 / CI 通用；
              注册中心/缓存/MQ 用 create_app 默认配置的内存实现，不触网）。
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# 业务模型注册到 Base.metadata（建表依据），需在 create_all 前导入
import user_service.model  # noqa: F401
from user_service.api.v1.user_controller import router as user_router
from web_infra import create_app
from web_infra.db import Base, MySQLDatabase

_JWT_SECRET = "scaffolding-test-secret-0123456789"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥（避免框架安全能力校验失败）"""
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)


@pytest_asyncio.fixture
async def db():
    """SQLite 内存库数据库工厂（StaticPool 共享单连接，跨会话可见）"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _FakeConfig:
        """最小数据库配置替身（仅提供 new_session，复用 sqlite+aiosqlite 会话工厂）"""

        async def new_session(self):
            return factory()

    database = MySQLDatabase(_FakeConfig())  # type: ignore[arg-type]
    yield database
    await engine.dispose()


@pytest_asyncio.fixture
async def app(db):
    """装配应用并将 db 组件替换为 SQLite 内存库（MySQL 懒连接不依赖外部服务）"""
    application = create_app({"app.name": "user-service-test"})
    application.state.db = db
    application.include_router(user_router)
    return application


@pytest_asyncio.fixture
async def client(app):
    """HTTP 测试客户端（ASGI 直连，无需启动真实服务）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
