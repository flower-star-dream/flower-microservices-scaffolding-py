"""
测试公共夹具（conftest）

@Author: 花海
@Date: 2026/08/16
@Description: order-service 测试夹具：SQLite 内存库（StaticPool 共享连接）替换 MySQL 组件，
              使业务模块测试不依赖外部 MySQL/Redis/Nacos 服务即可运行（本地 / CI 通用；
              注册中心/缓存/MQ 用 create_app 默认配置的内存实现，不触网）。
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# 业务模型注册到 Base.metadata（建表依据），需在 create_all 前导入
import order_service.model  # noqa: F401
from order_service.api.v1.order_controller import router as order_router
from web_infra import create_app
from web_infra.capabilities.db import Base, MySQLDatabase

_JWT_SECRET = "scaffolding-test-secret-0123456789"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """注入 JWT 测试密钥（避免框架安全能力校验失败）"""
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)


@pytest_asyncio.fixture
async def db():
    """SQLite 内存库数据库工厂（StaticPool 共享单连接，跨会话可见）"""
    from sqlalchemy import text

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # message_outbox 为 Outbox 原生 SQL 存储（非 ORM 模型），手动建表（SQLite 兼容，字段对齐框架 DDL）
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS message_outbox ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  msg_id VARCHAR(64) NOT NULL,"
                "  biz_id VARCHAR(64) NOT NULL,"
                "  topic VARCHAR(128) NOT NULL,"
                "  tag VARCHAR(64),"
                "  payload TEXT NOT NULL,"
                "  status INTEGER NOT NULL DEFAULT 0,"
                "  retry_count INTEGER NOT NULL DEFAULT 0,"
                "  created_at DATETIME NOT NULL,"
                "  updated_at DATETIME,"
                "  cleaned_at DATETIME,"
                "  next_retry_at DATETIME,"
                "  UNIQUE (msg_id, biz_id)"
                ")"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _FakeConfig:
        """最小数据库配置替身（session_factory 供 Outbox 存储装配，new_session 供 orm_session）"""

        session_factory = factory

        async def new_session(self):
            return factory()

    database = MySQLDatabase(_FakeConfig())  # type: ignore[arg-type]
    yield database
    await engine.dispose()


class _FakeUserClient:
    """用户服务远程客户端替身（内存返回，避免接口测试触网）"""

    async def get_user(self, user_id: int) -> dict | None:
        """按 ID 返回假用户（仅 ID=1 存在）"""
        if user_id == 1:
            return {"id": 1, "username": "alice"}
        return None


@pytest_asyncio.fixture
async def app(db):
    """装配应用并将 db 组件替换为 SQLite 内存库（MySQL 懒连接不依赖外部服务）"""
    application = create_app({"app.name": "order-service-test"})
    application.state.db = db
    application.state.user_client = _FakeUserClient()
    # 装配 Outbox 存储（订单事件可靠投递，规范 §21.3；会话工厂复用 SQLite 内存库）
    from web_infra.capabilities.mq import MysqlOutboxStore

    application.state.outbox_store = MysqlOutboxStore(lambda: db.session_factory())
    application.include_router(order_router)
    return application


@pytest_asyncio.fixture
async def client(app):
    """HTTP 测试客户端（ASGI 直连，无需启动真实服务）"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
