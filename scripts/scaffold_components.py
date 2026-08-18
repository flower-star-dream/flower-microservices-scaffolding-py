#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脚手架组件与实现选择模块（scaffold_components）

@Author: 花海
@Date: 2026/08/17
@Description: 单体 / 微服务脚手架共用的组件选择能力：
    1. COMPONENTS 组件目录：覆盖框架（flower-web-infrastructure）全部能力组件，
       每个组件定义可选实现（SPI 默认策略 / 生产实现 / 自行实现）；
    2. 交互式向导 prompt_components / 参数解析 parse_components / 统一解析 resolve_components
       （--components 显式取值 > 交互式询问 TTY > 非交互默认值）；
    3. 标记块裁剪 apply_components_to_text：模板文件用
       # <<<COMPONENT:<name>>> ... # <<</COMPONENT:<name>>> 包裹组件配置段，
       未选择 / 关闭的组件整块移除；已选择组件的 @@IMPL:<name>@@ 占位符替换为所选实现；
    4. 自研 SPI 骨架生成 generate_spi_skeletons：选择 custom 的组件生成
       src/<package>/spi/<name>_custom.py（实现类 + TODO 提示）；
    5. 框架 extras 渲染 render_extras：按所选实现汇总框架安装 extras。
    约束：注册中心（registry）不提供内存实现选项，禁止启用内存实现（内存只可用于单体/测试的单进程场景，
          脚手架按用户要求一律不允许选择）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 组件目录（覆盖框架全部能力）
# 每个组件：
#   label        中文名
#   group        分组（基础设施 / 业务能力 / 平台质量）
#   off          是否允许不使用（True 提供 0=不使用；False 为必选组件）
#   default      默认实现 id（"off" 表示默认不使用）
#   options      实现选项列表（id / label）
#   forbidden    禁止选择的实现 id（如注册中心禁止 memory）
#   extras       各实现所需框架 extras（id -> extras 元组）
#   spi          涉及的主 SPI 接口（custom 选项的骨架生成依据）
#   type_default application.yml 模板块内 type 的默认值（块内真实默认，生成时按选择块内替换）
#   flag         是否有 enabled 开关（模板块内 enabled: false，选择后块内替换为 true）
#   hint         选择提示（展示给用户）
# 说明：模板 application.yml / .env.example 中组件配置段始终为合法默认值（脚手架自身可直接运行），
#       生成时按选择做块内替换（type / enabled）与整块移除（未选择/关闭的组件）。
# ---------------------------------------------------------------------------
COMPONENTS: Dict[str, dict] = {
    "db": {
        "label": "数据库",
        "group": "基础设施",
        "off": False,
        "default": "mysql",
        "options": [
            {"id": "mysql", "label": "MySQL（生产推荐）"},
            {"id": "sqlite", "label": "SQLite（轻量 / 测试）"},
            {"id": "orm_custom", "label": "基于框架 ORM 自定义（复用 SQLAlchemy 会话/工厂，自定义数据源/路由）", "strategy": True},
            {"id": "custom", "label": "完全自定义（自行实现 DatabaseSessionInterface / DatabaseFactoryInterface，如接 PostgreSQL / 其他 ORM）", "strategy": True},
        ],
        "extras": {
            "mysql": ("mysql",),
            "sqlite": ("mysql",),  # aiosqlite 属框架 mysql extra
            "orm_custom": ("mysql",),
            "custom": (),
        },
        "type_default": "mysql",
        "spi": "DatabaseSessionInterface / DatabaseFactoryInterface / DatabaseRouterInterface",
        "config": True,
    },
    "cache": {
        "label": "缓存",
        "group": "基础设施",
        "off": True,
        "default": "memory",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 MemoryCacheBackend）"},
            {"id": "redis", "label": "Redis（生产推荐，多实例共享）"},
            {"id": "custom", "label": "自行实现 CacheBackendInterface", "strategy": True},
        ],
        "extras": {"redis": ("redis",)},
        "spi": "CacheBackendInterface",
        "type_default": "memory",
        "config": True,
    },
    "storage": {
        "label": "对象存储",
        "group": "基础设施",
        "off": True,
        "default": "local",
        "options": [
            {"id": "local", "label": "本地存储（SPI 默认策略 LocalObjectStorage）"},
            {"id": "minio", "label": "MinIO（生产推荐，S3 兼容）"},
            {"id": "custom", "label": "自行实现 ObjectStorageInterface", "strategy": True},
        ],
        "extras": {"minio": ("storage",)},
        "spi": "ObjectStorageInterface",
        "type_default": "local",
        "config": True,
    },
    "mq": {
        "label": "消息队列",
        "group": "基础设施",
        "off": True,
        "default": "memory",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 InMemoryMessageQueue）"},
            {"id": "rocketmq", "label": "RocketMQ（生产推荐，分布式）"},
            {"id": "custom", "label": "自行实现 MessagePublisherInterface 等", "strategy": True},
        ],
        "extras": {"rocketmq": ("rocketmq",)},
        "spi": "MessagePublisherInterface / MessageConsumerInterface / MessageIdempotencyStoreInterface / OutboxStoreInterface",
        "type_default": "memory",
        "config": True,
    },
    "registry": {
        "label": "注册中心",
        "group": "基础设施",
        "off": True,
        "default": "off",
        "options": [
            {"id": "nacos", "label": "Nacos（生产推荐）"},
            {"id": "custom", "label": "自行实现 ServiceRegistryInterface", "strategy": True},
        ],
        "forbidden": ("memory",),
        "extras": {"nacos": ("nacos",)},
        "spi": "ServiceRegistryInterface",
        "type_default": "nacos",
        "config": True,
        "hint": "注册中心不允许启用内存实现",
    },
    "config": {
        "label": "配置中心",
        "group": "基础设施",
        "off": True,
        "default": "off",
        "options": [
            {"id": "nacos", "label": "Nacos 配置中心（生产推荐）"},
            {"id": "custom", "label": "自行实现 ConfigClientInterface", "strategy": True},
        ],
        "extras": {"nacos": ("nacos",)},
        "spi": "ConfigClientInterface / ConfigSourceInterface",
        "config": True,
    },
    "mongo": {
        "label": "MongoDB",
        "group": "基础设施",
        "off": True,
        "default": "off",
        "options": [
            {"id": "default", "label": "启用 MongoDB（框架默认装配）"},
        ],
        "extras": {"default": ("mongo",)},
        "flag": True,
        "config": True,
    },
    "payment": {
        "label": "支付",
        "group": "业务能力",
        "off": True,
        "default": "memory",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 InMemoryPaymentGateway）"},
            {"id": "wechat", "label": "微信支付（官方 APIv3，生产）"},
            {"id": "custom", "label": "自行实现 PaymentGateway / PaymentCallbackVerifier", "strategy": True},
        ],
        "extras": {},
        "spi": "PaymentGateway / PaymentCallbackVerifier / PaymentCallbackHandler",
        "type_default": "memory",
        "config": True,
    },
    "ai": {
        "label": "AI 能力",
        "group": "业务能力",
        "off": True,
        "default": "off",
        "options": [
            {"id": "default", "label": "默认装配（OpenAI 兼容供应商 + 内存存储组件）"},
            {"id": "custom", "label": "自行实现 ModelProviderInterface（模型供应商）", "strategy": True},
        ],
        "extras": {},
        "spi": "ModelProviderInterface / ModelConfigStoreInterface / ContentGuardInterface 等 11 个 AI SPI",
        "flag": True,
        "config": True,
    },
    "security": {
        "label": "安全组件（验证码 / 登录防爆破）",
        "group": "业务能力",
        "off": True,
        "default": "memory",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 InMemoryCaptchaStore）"},
            {"id": "redis", "label": "Redis（生产推荐，验证码多实例共享）"},
            {"id": "custom", "label": "自行实现 CaptchaStoreInterface", "strategy": True},
        ],
        "extras": {"redis": ("redis",)},
        "spi": "CaptchaStoreInterface",
        "config": False,
    },
    "jwt": {
        "label": "JWT 鉴权",
        "group": "业务能力",
        "off": True,
        "default": "default",
        "options": [
            {"id": "default", "label": "默认策略（EnvJwtKeyProvider + 内存 Token 存储）"},
            {"id": "redis", "label": "Redis Token 存储（生产推荐，多实例凭证共享）"},
            {"id": "custom", "label": "自行实现 JwtTokenStore / JwtKeyProvider", "strategy": True},
        ],
        "extras": {"redis": ("redis",)},
        "spi": "JwtTokenStore / JwtKeyProvider",
        "config": False,
    },
    "social": {
        "label": "三方登录",
        "group": "业务能力",
        "off": True,
        "default": "demo",
        "options": [
            {"id": "demo", "label": "Demo 平台（SPI 默认策略，不触网）"},
            {"id": "custom", "label": "自行实现 SocialPlatform / SocialBindingStore", "strategy": True},
        ],
        "extras": {},
        "spi": "SocialPlatform / SocialBindingStore",
        "config": False,
    },
    "task": {
        "label": "异步任务",
        "group": "业务能力",
        "off": True,
        "default": "memory",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 InMemoryTaskRecordStore）"},
            {"id": "custom", "label": "自行实现 TaskRecordStoreInterface", "strategy": True},
        ],
        "extras": {},
        "spi": "TaskRecordStoreInterface",
        "config": False,
    },
    "schedule": {
        "label": "任务调度",
        "group": "平台质量",
        "off": True,
        "default": "off",
        "options": [
            {"id": "default", "label": "启用 TaskScheduler（框架默认装配）"},
        ],
        "extras": {},
        "config": False,
    },
    "state_machine": {
        "label": "状态机",
        "group": "平台质量",
        "off": True,
        "default": "off",
        "options": [
            {"id": "default", "label": "启用状态机引擎（框架默认装配）"},
        ],
        "extras": {},
        "config": False,
    },
    "monitoring": {
        "label": "监控",
        "group": "平台质量",
        "off": True,
        "default": "default",
        "options": [
            {"id": "default", "label": "启用监控（/metrics 指标采集与可视化）"},
        ],
        "extras": {},
        "config": False,
    },
    "tenant": {
        "label": "多租户",
        "group": "平台质量",
        "off": True,
        "default": "off",
        "options": [
            {"id": "default", "label": "启用多租户（strict 强隔离）"},
        ],
        "extras": {},
        "config": False,
    },
    "idempotency": {
        "label": "幂等中间件",
        "group": "平台质量",
        "off": True,
        "default": "off",
        "options": [
            {"id": "memory", "label": "内存默认（SPI 默认策略 InMemoryIdempotencyStore）"},
            {"id": "redis", "label": "Redis（生产推荐，多实例共享）"},
            {"id": "custom", "label": "自行实现 IdempotencyStoreInterface", "strategy": True},
        ],
        "extras": {"redis": ("redis",)},
        "spi": "IdempotencyStoreInterface",
        "flag": True,
        "config": True,
    },
}

# 标记块行格式：# <<<COMPONENT:<name>>> / # <<</COMPONENT:<name>>>
_COMPONENT_START = "# <<<COMPONENT:{}>>>"
_COMPONENT_END = "# <<</COMPONENT:{}>>>"

# 组件 -> 能力名映射（框架能力依赖装配系统 app.capabilities.enabled，2026-08-17 新增）：
# 业务能力链 user -> authn（认证）-> authz（鉴权）-> pay（支付），按包含关系自动补足前置；
# 基础设施能力（db/cache/storage/mq/registry/config/ai）按框架模块登记。mongo/task/schedule 等
# 组件无对应框架能力（builtin_capabilities 未登记），不参与 enabled 渲染。
COMPONENT_CAPABILITY: Dict[str, str] = {
    "db": "db",
    "cache": "cache",
    "storage": "storage",
    "mq": "mq",
    "registry": "registry",
    "config": "config",
    "payment": "pay",
    "ai": "ai",
    "security": "authn",  # 验证码/登录防爆破属认证域
    "jwt": "authn",       # JWT 签发/校验属认证域
    "social": "authn",    # 三方登录属认证域
}

# application.yml 能力装配段占位（模板固定写 enabled: []，脚手架自测/未选组件时为安全空列表）
_CAPABILITIES_ANCHOR = "enabled: []"

# ---------------------------------------------------------------------------
# 自研 SPI 骨架模板（选择策略型实现（custom / orm_custom 等）时生成；{date} 替换为生成日期）
# 键：组件名（单一 custom）或 <组件>:<实现>（一个组件多个自研选项，如 db:custom / db:orm_custom）
# ---------------------------------------------------------------------------
SPI_SKELETONS: Dict[str, str] = {
    "db:custom": """\"\"\"
自定义数据库会话 / 工厂（DatabaseSessionInterface / DatabaseFactoryInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（db=custom）生成：完全自定义实现通用数据库会话与工厂
              （如接入 PostgreSQL / 其他 ORM / 其他数据源）。SQL 使用命名参数（:name），
              各实现自行适配驱动占位符（接口契约见框架文档 SPI-Extensions.md §4.1 / §4.2）。
\"\"\"
from __future__ import annotations

from typing import Any, AsyncContextManager

from web_infra.capabilities.db.database_factory_interface import DatabaseFactoryInterface
from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface


class CustomDatabaseSession(DatabaseSessionInterface):
    \"\"\"自定义数据库会话：实现 execute / query_one / query_all / commit / rollback / close。\"\"\"

    async def execute(self, sql: str, params: Any = None) -> int:
        # TODO(花海): 执行写操作，返回影响行数（命名参数 :name 需适配驱动占位符）
        return 0

    async def query_one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        # TODO(花海): 查询单行，返回字典或 None
        return None

    async def query_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        # TODO(花海): 查询多行，返回字典列表
        return []

    async def commit(self) -> None:
        # TODO(花海): 提交事务
        ...

    async def rollback(self) -> None:
        # TODO(花海): 回滚事务
        ...

    async def close(self) -> None:
        # TODO(花海): 关闭会话（归还连接）
        ...


class CustomDatabaseFactory(DatabaseFactoryInterface):
    \"\"\"自定义数据库工厂：创建会话 / 异步上下文管理器 / 关闭 / 健康检查。\"\"\"

    async def create_session(self) -> DatabaseSessionInterface:
        # TODO(花海): 创建通用数据库会话
        return CustomDatabaseSession()

    def session(self) -> AsyncContextManager[DatabaseSessionInterface]:
        # TODO(花海): 实现异步上下文管理器（进入创建会话，退出自动提交 / 异常回滚并关闭）
        raise NotImplementedError

    async def close(self) -> None:
        # TODO(花海): 关闭连接池 / 底层资源
        ...

    async def health_check(self) -> bool:
        # TODO(花海): 健康检查
        return True
""",
    "db:orm_custom": """\"\"\"
基于框架 ORM 的自定义数据库实现骨架（复用 SQLAlchemy 会话 / 工厂）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（db=orm_custom）生成：复用框架已有 SQLAlchemy 生态
              （SqlAlchemyDatabaseSession / MySQLDatabase / DatabaseManager），按需自定义
              数据源、会话行为或动态路由（DatabaseRouterInterface / TenantDatabaseRouter），
              无需从零实现 DatabaseSessionInterface（接口契约见框架文档 SPI-Extensions.md §4）。
\"\"\"
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.capabilities.db.database_session_interface import DatabaseSessionInterface


class OrmCustomDatabaseSession(DatabaseSessionInterface):
    \"\"\"基于 SQLAlchemy AsyncSession 的自定义会话（组合方式包装，可扩展审计 / 超时 / 多数据源路由）。\"\"\"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, sql: str, params: Any = None) -> int:
        # 示例：SQLAlchemy text() 执行原生 SQL；可改为复用模型 / 仓库层能力
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        return result.rowcount

    async def query_one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        row = result.mappings().first()
        return dict(row) if row else None

    async def query_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        from sqlalchemy import text

        result = await self._session.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def close(self) -> None:
        await self._session.close()


# TODO(花海): 在装配处接入（参考框架实现 web_infra.capabilities.db.sqlalchemy_database_session /
#   mysql_database / database_manager）：
#   - 自定义会话工厂：async_sessionmaker(engine, ...) 包装为 OrmCustomDatabaseSession；
#   - 多数据源 / 动态路由：实现 DatabaseRouterInterface 或复用框架 TenantDatabaseRouter，
#     由 DatabaseManager 统一管理；健康检查复用框架组件。
""",
    "cache": """\"\"\"
自定义缓存后端（CacheBackendInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（cache=custom）生成：实现 CacheBackendInterface
              后在应用装配处注入替换默认 MemoryCacheBackend
              （接口契约见框架文档 SPI-Extensions.md §8.1）。
\"\"\"
from typing import Any

from web_infra.capabilities.cache.cache_backend_interface import CacheBackendInterface


class CustomCacheBackend(CacheBackendInterface):
    \"\"\"自定义缓存后端：实现后注入替换默认内存实现。\"\"\"

    async def get(self, key: str) -> Any | None:
        # TODO(花海): 实现缓存读取（未命中返回 None）
        return None

    async def set(self, key: str, value: Any, ttl: int | None = None, ttl_jitter_seconds: float | None = None) -> None:
        # TODO(花海): 实现缓存写入（ttl 为空用后端默认；ttl_jitter_seconds 为防雪崩抖动上限）
        ...

    async def delete(self, key: str) -> None:
        # TODO(花海): 实现缓存删除
        ...

    async def exists(self, key: str) -> bool:
        # TODO(花海): 实现缓存存在判断
        return False

    async def set_empty(self, key: str, ttl: int = 60) -> None:
        # TODO(花海): 实现空值占位（防穿透，TTL 默认 60，上限 120 自动钳制）
        ...

    async def is_empty(self, key: str) -> bool:
        # TODO(花海): 实现空值占位判断（过期自动失效返回 False）
        return False
""",
    "storage": """\"\"\"
自定义对象存储（ObjectStorageInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（storage=custom）生成：实现 ObjectStorageInterface
              后在应用装配处注入替换默认 LocalObjectStorage
              （接口契约见框架文档 SPI-Extensions.md §12.1）。
\"\"\"
from web_infra.capabilities.storage.object_storage_interface import ObjectStorageInterface


class CustomObjectStorage(ObjectStorageInterface):
    \"\"\"自定义对象存储：实现后注入替换默认本地存储。\"\"\"

    async def put(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        # TODO(花海): 实现对象上传
        ...

    async def get(self, bucket: str, key: str) -> bytes | None:
        # TODO(花海): 实现对象下载（不存在返回 None）
        return None

    async def delete(self, bucket: str, key: str) -> None:
        # TODO(花海): 实现对象删除
        ...

    async def exists(self, bucket: str, key: str) -> bool:
        # TODO(花海): 实现对象存在判断
        return False

    async def presign_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        # TODO(花海): 实现带过期时间的签名访问 URL
        return ""
""",
    "mq": """\"\"\"
自定义消息队列（MessagePublisherInterface 等自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（mq=custom）生成：实现 MessagePublisherInterface 后
              在装配处注入替换默认 InMemoryMessageQueue；消费/幂等/Outbox 接口同理
              （MessageConsumerInterface / MessageIdempotencyStoreInterface / OutboxStoreInterface，
              契约见框架文档 SPI-Extensions.md §9）。
\"\"\"
from web_infra.capabilities.mq.message import Message
from web_infra.capabilities.mq.message_publisher_interface import MessagePublisherInterface


class CustomMessagePublisher(MessagePublisherInterface):
    \"\"\"自定义消息发布者：实现后注入替换默认内存队列。\"\"\"

    async def publish(self, message: Message) -> str:
        # TODO(花海): 实现消息发送，返回消息 ID
        return message.msg_id

    async def send_delay(self, message: Message, delay_seconds: int) -> str:
        # TODO(花海): 实现延迟消息发送（RocketMQ 实现映射官方固定 delay level，禁止 sleep）
        return message.msg_id
""",
    "registry": """\"\"\"
自定义服务注册发现（ServiceRegistryInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（registry=custom）生成：实现 ServiceRegistryInterface
              后在装配处注入替换框架默认（注意：注册中心不允许使用内存实现）
              （接口契约见框架文档 SPI-Extensions.md §5.1）。
\"\"\"
from web_infra.capabilities.registry.service_instance import ServiceInstance
from web_infra.capabilities.registry.service_registry_interface import ServiceRegistryInterface


class CustomServiceRegistry(ServiceRegistryInterface):
    \"\"\"自定义服务注册发现实现（如对接 Eureka / Consul / 自研注册中心）。\"\"\"

    async def register(self, service_name: str, instance: ServiceInstance) -> bool:
        # TODO(花海): 实现服务实例注册
        return True

    async def deregister(self, service_name: str, instance: ServiceInstance) -> bool:
        # TODO(花海): 实现服务实例注销
        return True

    async def get_instances(self, service_name: str) -> list[ServiceInstance]:
        # TODO(花海): 实现服务实例发现（仅健康实例）
        return []

    async def close(self) -> None:
        # TODO(花海): 释放底层资源
        ...
""",
    "config": """\"\"\"
自定义配置中心（ConfigClientInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（config=custom）生成：实现 ConfigClientInterface 后
              接入自有配置中心（如 Apollo），替换默认本地复合配置源
              （接口契约见框架文档 SPI-Extensions.md §3.1）。
\"\"\"
from web_infra.capabilities.config.config_client_interface import ConfigClientInterface


class CustomConfigClient(ConfigClientInterface):
    \"\"\"自定义配置中心客户端：实现后接入自有配置中心。\"\"\"

    async def get_config(self, data_id: str, group: str | None = None) -> str:
        # TODO(花海): 拉取指定配置内容（不存在返回空字符串）
        return ""

    def get_config_sync(self, data_id: str, group: str | None = None) -> str:
        # TODO(花海): 同步拉取配置（应用启动阶段使用；事件循环内请用异步方法）
        return ""

    async def close(self) -> None:
        # TODO(花海): 释放底层资源
        ...
""",
    "payment": """\"\"\"
自定义支付渠道（PaymentGateway / PaymentCallbackVerifier 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（payment=custom）生成：实现 PaymentGateway 与
              PaymentCallbackVerifier 后在 PaymentGatewayRegistry 注册
              （接口契约见框架文档 SPI-Extensions.md §15；金额统一 Decimal 元）。
\"\"\"
from decimal import Decimal

from web_infra.capabilities.payment.payment_callback import PaymentCallback
from web_infra.capabilities.payment.payment_gateway_interface import PaymentGateway
from web_infra.capabilities.payment.prepay_request import PaymentPrepayRequest
from web_infra.capabilities.payment.prepay_response import PaymentPrepayResponse
from web_infra.capabilities.payment.refund_request import PaymentRefundRequest
from web_infra.capabilities.payment.refund_response import PaymentRefundResponse
from web_infra.capabilities.payment.payment_order import PaymentOrder


class CustomPaymentGateway(PaymentGateway):
    \"\"\"自定义支付渠道：实现后注册进 PaymentGatewayRegistry。\"\"\"

    async def prepay(self, request: PaymentPrepayRequest) -> PaymentPrepayResponse:
        # TODO(花海): 实现下单，按场景返回 prepay_id / 调起参数 / code_url / h5_url
        raise NotImplementedError

    async def query_order(self, out_trade_no: str) -> PaymentOrder | None:
        # TODO(花海): 实现查单（不存在返回 None）
        return None

    async def close_order(self, out_trade_no: str) -> None:
        # TODO(花海): 实现关闭订单
        ...

    async def refund(self, request: PaymentRefundRequest) -> PaymentRefundResponse:
        # TODO(花海): 实现申请退款（out_refund_no 幂等）
        raise NotImplementedError

    async def query_refund(self, out_refund_no: str) -> PaymentRefundResponse | None:
        # TODO(花海): 实现查退款（不存在返回 None）
        return None
""",
    "ai": """\"\"\"
自定义模型供应商（ModelProviderInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（ai=custom）生成：实现 ModelProviderInterface 后
              经 ModelProviderRegistry.register 注册（接口契约见框架文档
              SPI-Extensions.md §7.1；更多 AI SPI：ModelConfigStoreInterface /
              ContentGuardInterface / QuotaStoreInterface 等）。
\"\"\"
from web_infra.capabilities.ai.chat_request import ChatRequest
from web_infra.capabilities.ai.chat_response import ChatResponse
from web_infra.capabilities.ai.model_provider_interface import ModelProviderInterface


class CustomModelProvider(ModelProviderInterface):
    \"\"\"自定义模型供应商：实现后注册进 ModelProviderRegistry。\"\"\"

    name = "custom-llm"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        # TODO(花海): 对接自有模型服务，返回统一 ChatResponse
        raise NotImplementedError
""",
    "security": """\"\"\"
自定义验证码存储（CaptchaStoreInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（security=custom）生成：实现 CaptchaStoreInterface 后
              注入验证码服务替换默认 InMemoryCaptchaStore
              （接口契约见框架文档 SPI-Extensions.md §11.1）。
\"\"\"
from web_infra.capabilities.security.captcha_store_interface import CaptchaStoreInterface


class CustomCaptchaStore(CaptchaStoreInterface):
    \"\"\"自定义验证码存储：实现后注入验证码服务（一次性消费语义由 take 保证）。\"\"\"

    async def save(self, captcha_id: str, code: str, ttl_seconds: int) -> None:
        # TODO(花海): 实现验证码保存（含有效期）
        ...

    async def take(self, captcha_id: str) -> str | None:
        # TODO(花海): 实现取走验证码（一次性消费：取走后即删除，未命中/过期返回 None）
        return None
""",
    "jwt": """\"\"\"
自定义 JWT 状态存储 / 密钥提供（JwtTokenStore / JwtKeyProvider 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（jwt=custom）生成：实现 JwtTokenStore（或 JwtKeyProvider）后
              经 JWTUtil.configure(token_store=..., key_provider=...) 注入，优先级最高
              （接口契约见框架文档 SPI-Extensions.md §11.4 / §11.5）。
\"\"\"
from web_infra.capabilities.security.jwt_token_store_interface import JwtTokenStore


class CustomJwtTokenStore(JwtTokenStore):
    \"\"\"自定义 JWT Token 状态存储：实现后注入 JWTUtil（覆盖框架默认）。\"\"\"

    async def save(self, user_id: str, jti: str, ttl_seconds: int, client_id: str, device_id: str) -> str | None:
        # TODO(花海): 保存有效凭证；返回被同设备复用替换的旧 jti（无则 None）
        return None

    async def exists(self, user_id: str, jti: str) -> bool:
        # TODO(花海): 查询凭证是否有效（撤销/过期/复用替换后 False）
        return False

    async def revoke(self, user_id: str, jti: str) -> bool:
        # TODO(花海): 撤销凭证（登出）
        return True

    async def current_jti(self, user_id: str, client_id: str, device_id: str) -> str | None:
        # TODO(花海): 查询同设备当前有效 jti
        return None
""",
    "social": """\"\"\"
自定义三方登录平台 / 绑定存储（SocialPlatform / SocialBindingStore 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（social=custom）生成：实现 SocialPlatform 后注册进
              SocialPlatformRegistry（参考框架 DemoSocialPlatform）；绑定存储多实例
              可另行实现 SocialBindingStore 的 Redis/DB 版（契约见框架文档
              SPI-Extensions.md §11.2 / §11.3）。
\"\"\"
from web_infra.capabilities.security.social.social_platform_interface import SocialPlatform
from web_infra.capabilities.security.social.social_user_info import SocialUserInfo


class CustomSocialPlatform(SocialPlatform):
    \"\"\"自定义三方登录平台（如微信 / GitHub / 钉钉）：实现后注册进 SocialPlatformRegistry。\"\"\"

    provider = "custom"

    async def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        # TODO(花海): 生成授权跳转 URL（state 防 CSRF）
        return ""

    async def exchange_token(self, code: str, redirect_uri: str):
        # TODO(花海): 授权码换取平台 token，返回 SocialAccessToken
        raise NotImplementedError

    async def fetch_userinfo(self, token) -> SocialUserInfo:
        # TODO(花海): 拉取三方用户信息（返回 SocialUserInfo）
        raise NotImplementedError
""",
    "task": """\"\"\"
自定义异步任务记录存储（TaskRecordStoreInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（task=custom）生成：实现 TaskRecordStoreInterface 后
              注入任务执行器替换默认 InMemoryTaskRecordStore（更新采用乐观锁）
              （接口契约见框架文档 SPI-Extensions.md §13.1）。
\"\"\"
from web_infra.capabilities.task.task_record import TaskRecord
from web_infra.capabilities.task.task_record_store import TaskRecordStoreInterface


class CustomTaskRecordStore(TaskRecordStoreInterface):
    \"\"\"自定义任务记录存储：实现后注入任务执行器（多实例需共享存储）。\"\"\"

    async def save(self, record: TaskRecord) -> None:
        # TODO(花海): 保存任务记录（新增或全量覆盖）
        ...

    async def load(self, task_id: str) -> TaskRecord | None:
        # TODO(花海): 按任务 ID 加载记录（未找到返回 None）
        return None

    async def update(self, record: TaskRecord) -> bool:
        # TODO(花海): 乐观锁更新：仅版本一致时写入并自增，否则返回 False
        return False

    async def list_all(self) -> list[TaskRecord]:
        # TODO(花海): 列出全部任务记录
        return []
""",
    "idempotency": """\"\"\"
自定义 API 幂等存储（IdempotencyStoreInterface 自研实现骨架）

@Author: 花海
@Date: {date}
@Description: 由脚手架组件选择（idempotency=custom）生成：实现 IdempotencyStoreInterface 后
              注入幂等中间件替换默认 InMemoryIdempotencyStore
              （接口契约见框架文档 SPI-Extensions.md §14.1）。
\"\"\"
from web_infra.infra.web.idempotency_store_interface import IdempotencyResult, IdempotencyStoreInterface


class CustomIdempotencyStore(IdempotencyStoreInterface):
    \"\"\"自定义幂等存储：实现后注入幂等中间件（多实例需共享存储保证原子性）。\"\"\"

    async def try_occupy(self, key: str, ttl_seconds: int) -> bool:
        # TODO(花海): 原子占用幂等键（SETNX 语义）：首次 True，重复占用 False
        return True

    async def set_result(self, key: str, result: IdempotencyResult, ttl_seconds: int) -> None:
        # TODO(花海): 保存首次处理结果
        ...

    async def get_result(self, key: str) -> IdempotencyResult | None:
        # TODO(花海): 读取已缓存的处理结果（未完成或无结果返回 None）
        return None

    async def release(self, key: str) -> None:
        # TODO(花海): 释放占用（业务处理异常时调用，允许后续请求重试）
        ...
""",
}


# ---------------------------------------------------------------------------
# 组件选择解析
# ---------------------------------------------------------------------------


def _default_impl(name: str, spec: dict, defaults: Optional[Dict[str, str]] = None) -> str:
    """返回组件默认实现 id（defaults 中指定的组件按脚手架形态覆盖目录默认）。

    Args:
        name: 组件名。
        spec: 组件定义。
        defaults: 脚手架形态默认覆盖（如微服务 {"registry": "nacos", "cache": "redis"}）。
    """
    if defaults and name in defaults:
        return defaults[name]
    return spec.get("default", "off")


def _minimal_impl(name: str, spec: dict, defaults: Optional[Dict[str, str]] = None) -> str:
    """返回最小化默认实现 id：必选组件（off=False）与脚手架形态覆盖组件（defaults）取默认，其余可选组件一律 off。

    用途：--components 显式列表未提及的组件 / 非交互默认 / 交互询问默认。保证生成项目只保留
    显式选择 + 必选 + 形态覆盖的组件配置，未选组件整块裁剪（避免默认启用过多组件导致配置全量给出）。

    Args:
        name: 组件名。
        spec: 组件定义。
        defaults: 脚手架形态默认覆盖（如微服务 {"registry": "nacos", "cache": "redis"}）。
    """
    if not spec.get("off"):
        return _default_impl(name, spec, defaults)
    if defaults and name in defaults:
        return defaults[name]
    return "off"


def _option_ids(spec: dict) -> List[str]:
    """返回组件可选实现 id 列表（含 off）。"""
    ids = [opt["id"] for opt in spec["options"]]
    if spec.get("off"):
        ids.insert(0, "off")
    return ids


def parse_components(value: str, *, defaults: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """解析 --components 取值：name:impl 逗号分隔；all=全部默认 / none=仅必选组件。

    Args:
        value: --components 原始值。
        defaults: 脚手架形态默认覆盖（如微服务注册中心强制 Nacos、缓存默认 Redis）。

    Returns:
        组件 -> 实现 id 的映射（未显式指定的组件取默认）。

    Raises:
        SystemExit: 格式错误 / 未知组件 / 未知实现 / 违反必选或禁止约束时退出。
    """
    normalized = value.strip().lower()
    if normalized in ("all", "*"):
        return {name: _default_impl(name, spec, defaults) for name, spec in COMPONENTS.items()}
    if normalized == "none":
        return {
            name: _default_impl(name, spec, defaults) if not spec.get("off") else "off"
            for name, spec in COMPONENTS.items()
        }
    result: Dict[str, str] = {}
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            sys.exit(f"--components 格式错误：{token!r}（应为 name:impl，如 cache:redis）")
        name, impl = token.split(":", 1)
        name, impl = name.strip().lower(), impl.strip().lower()
        if name not in COMPONENTS:
            sys.exit(f"未知组件：{name!r}（可用：{'、'.join(COMPONENTS)}）")
        spec = COMPONENTS[name]
        if impl not in _option_ids(spec):
            sys.exit(f"组件 {name} 不支持实现 {impl!r}（可选：{'、'.join(_option_ids(spec))}）")
        result[name] = impl
    # 未显式指定的组件取最小化默认：必选 + 形态覆盖组件保留，其余可选组件 off（按需显式启用）
    for name, spec in COMPONENTS.items():
        if name not in result:
            result[name] = _minimal_impl(name, spec, defaults)
    _validate_components(result)
    return result


def _validate_components(components: Dict[str, str]) -> None:
    """校验组件选择：必选组件不得 off、禁止实现不得选择、注册中心形态约束。"""
    for name, spec in COMPONENTS.items():
        impl = components.get(name, "off")
        if not spec.get("off") and impl == "off":
            sys.exit(f"必选组件 {name} 不能关闭（请用 --components={name}:<实现> 指定）")
        if impl in spec.get("forbidden", ()):
            sys.exit(f"组件 {name} 禁止使用实现 {impl!r}（{spec.get('hint', '')}）")
        if impl != "off" and impl not in _option_ids(spec):
            sys.exit(f"组件 {name} 不支持实现 {impl!r}（可选：{'、'.join(_option_ids(spec))}）")


def prompt_components(*, defaults: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """交互式逐个询问组件与实现选择（TTY 使用；输入序号 / 实现名 / 回车取默认）。"""
    print("=" * 60)
    print("组件与实现选择（回车使用默认值；输入序号或实现名；注册中心禁止内存实现）")
    print("=" * 60)
    selected: Dict[str, str] = {}
    for name, spec in COMPONENTS.items():
        options = list(spec["options"])
        if spec.get("off"):
            options.insert(0, {"id": "off", "label": "不使用"})
        default = _minimal_impl(name, spec, defaults)
        hint = f"（{spec['hint']}）" if spec.get("hint") else ""
        print(f"\n[{spec['label']}]{hint}（{spec['group']}）")
        for idx, opt in enumerate(options):
            mark = "（默认）" if opt["id"] == default else ""
            print(f"  {idx}) {opt['id']:<10} {opt['label']} {mark}")
        selected[name] = _ask_component(name, options, default)
    _print_selection(selected)
    return selected


def _ask_component(name: str, options: List[dict], default: str) -> str:
    """询问单个组件实现（带输入校验，非法输入循环重试）。"""
    while True:
        line = input(f"  {name}（默认 {default}）> ").strip().lower()
        if not line:
            return default
        if line.isdigit():
            idx = int(line)
            if 0 <= idx < len(options):
                return options[idx]["id"]
        elif line in (opt["id"] for opt in options):
            return line
        print("  无效输入：请输入序号、实现名，或直接回车使用默认值")


def resolve_components(value: Optional[str], *, defaults: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """解析组件选择：--components 显式取值 > 交互式询问（TTY）> 非交互默认。

    Args:
        value: --components 参数值（None 表示未指定）。
        defaults: 脚手架形态默认覆盖（如微服务注册中心强制 Nacos、缓存默认 Redis）。
    """
    if value is not None:
        return parse_components(value, defaults=defaults)
    if sys.stdin.isatty():
        return prompt_components(defaults=defaults)
    # 非交互默认（CI / 脚本）：最小化——仅必选 + 形态覆盖组件，其余可选组件 off（按需显式指定）
    return {name: _minimal_impl(name, spec, defaults) for name, spec in COMPONENTS.items()}


def _print_selection(selected: Dict[str, str]) -> None:
    """输出组件选择结果汇总。"""
    print("\n" + "=" * 60)
    print("组件选择结果：")
    for name, spec in COMPONENTS.items():
        impl = selected.get(name, "off")
        if impl == "off":
            print(f"  - {spec['label']}：不使用")
        else:
            label = next((o["label"] for o in spec["options"] if o["id"] == impl), impl)
            print(f"  - {spec['label']}：{label}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 标记块裁剪与占位符替换
# ---------------------------------------------------------------------------


def remove_component_block(text: str, name: str) -> str:
    """移除单个组件的标记块（含标记行）。

    Args:
        text: 文件原文。
        name: 组件名。

    Returns:
        移除标记块后的文本。
    """
    start_marker = _COMPONENT_START.format(name)
    end_marker = _COMPONENT_END.format(name)
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == start_marker:
            inside = True
            continue
        if stripped == end_marker:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _replace_in_block(text: str, name: str, old: str, new: str) -> str:
    """在单个组件的标记块内替换文本（模板块内为合法默认值，按选择替换为所选实现）。"""
    start_marker = _COMPONENT_START.format(name)
    end_marker = _COMPONENT_END.format(name)
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    inside = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped == start_marker:
            inside = True
            out.append(line)
            continue
        if stripped == end_marker:
            inside = False
            out.append(line)
            continue
        if inside and not replaced and old in line:
            out.append(line.replace(old, new, 1))
            replaced = True
            continue
        out.append(line)
    return "".join(out)


def _replace_type_in_block(text: str, name: str, impl: str) -> str:
    """在单个组件的标记块内替换 type 值（正则匹配首个 type 行，兼容块内任意当前值）。

    说明：模板 application.yml 各组件块内首个 `type: <value>` 即组件实现类型；
    按选择替换为所选实现 id（custom 保留原值，另生成自研骨架）。
    """
    import re

    start_marker = _COMPONENT_START.format(name)
    end_marker = _COMPONENT_END.format(name)
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    inside = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped == start_marker:
            inside = True
            out.append(line)
            continue
        if stripped == end_marker:
            inside = False
            out.append(line)
            continue
        if inside and not replaced:
            match = re.match(r"^(\s*type:\s*)(\S+)(.*)$", line)
            if match:
                out.append(f"{match.group(1)}{impl}{match.group(3)}\n")
                replaced = True
                continue
        out.append(line)
    return "".join(out)


def apply_components_to_text(text: str, components: Dict[str, str]) -> str:
    """按组件选择处理文本：移除未选组件标记块 + 已选组件块内替换实现（type / enabled）。

    Args:
        text: 文件原文。
        components: 组件 -> 实现 id 映射。

    Returns:
        处理后的文本。
    """
    for name, spec in COMPONENTS.items():
        impl = components.get(name)
        if impl is None or impl == "off":
            text = remove_component_block(text, name)
            continue
        # 已选择：块内 type 替换（模板为合法默认值；策略型实现如 orm_custom/custom 不写 type，
        # 保留框架默认 type，另生成自研骨架）
        if spec.get("type_default"):
            opt = next((o for o in spec["options"] if o["id"] == impl), None)
            if opt is not None and not opt.get("strategy"):
                text = _replace_type_in_block(text, name, impl)
        # 已选择：enabled 开关翻转（模板默认关闭，选择后启用）
        if spec.get("flag"):
            text = _replace_in_block(text, name, "enabled: false", "enabled: true")
    return text


def render_capabilities(components: Dict[str, str]) -> list[str]:
    """按组件选择渲染框架能力装配清单（app.capabilities.enabled，去重保持组件目录顺序）。

    未选择/关闭的组件不映射能力；无对应能力的组件（mongo/task 等）不参与。

    Args:
        components: 组件 -> 实现 id 映射。

    Returns:
        能力名列表（如 ["db", "pay", "authn"]；空表示不启用任何可选能力）。
    """
    caps: list[str] = []
    for name in COMPONENTS:
        if components.get(name) in (None, "off"):
            continue
        capability = COMPONENT_CAPABILITY.get(name)
        if capability and capability not in caps:
            caps.append(capability)
    return caps


def apply_capabilities_to_text(text: str, components: Dict[str, str]) -> str:
    """将模板 application.yml 的能力装配段（app.capabilities.enabled: []）渲染为组件选择对应的能力清单。

    能力依赖链（如 pay 自动带上 authz/authn/user）由框架装配时按包含关系补足，此处仅声明直接能力；
    未选择任何可映射组件时保持空列表（`enabled: []`）。

    Args:
        text: 文件原文。
        components: 组件 -> 实现 id 映射。

    Returns:
        渲染能力装配段后的文本。
    """
    caps = render_capabilities(components)
    if not caps:
        return text
    rendered = "[" + ", ".join(f'"{c}"' for c in caps) + "]"
    return text.replace(_CAPABILITIES_ANCHOR, f"enabled: {rendered}", 1)


def render_extras(components: Dict[str, str]) -> str:
    """按组件选择渲染框架安装 extras（唯一去重、保持组件目录顺序；迁移工具恒含）。

    Args:
        components: 组件 -> 实现 id 映射。

    Returns:
        逗号分隔的 extras 串，如 "mysql,redis,migrate"。
    """
    extras: List[str] = []
    for name, spec in COMPONENTS.items():
        impl = components.get(name)
        if not impl or impl == "off":
            continue
        for extra in spec.get("extras", {}).get(impl, ()):
            if extra not in extras:
                extras.append(extra)
    if "migrate" not in extras:
        extras.append("migrate")
    return ",".join(extras)


def generate_spi_skeletons(root: Path, package: str, components: Dict[str, str]) -> List[str]:
    """为选择策略型实现（custom / orm_custom 等）的组件生成骨架文件到 src/<package>/spi/。

    Args:
        root: 生成目标根目录。
        package: 项目 Python 包名。
        components: 组件 -> 实现 id 映射。

    Returns:
        已生成骨架的组件名列表。
    """
    from datetime import date

    spi_dir = root / "src" / package / "spi"
    generated: List[str] = []
    for name, spec in COMPONENTS.items():
        impl = components.get(name)
        if not impl or impl == "off":
            continue
        opt = next((o for o in spec["options"] if o["id"] == impl), None)
        if opt is None or not opt.get("strategy"):
            continue
        # 骨架模板键：<组件>:<实现> 优先（一个组件多个自研选项），回落 <组件>（单一 custom）
        skeleton = SPI_SKELETONS.get(f"{name}:{impl}") or SPI_SKELETONS.get(name)
        if not skeleton:
            continue
        spi_dir.mkdir(parents=True, exist_ok=True)
        suffix = impl if impl != "custom" else "custom"
        (spi_dir / f"{name}_{suffix}.py").write_text(
            skeleton.replace("{date}", date.today().strftime("%Y/%m/%d")), encoding="utf-8"
        )
        generated.append(name)
    if generated and not (spi_dir / "__init__.py").exists():
        (spi_dir / "__init__.py").write_text(
            '"""自研 SPI 实现骨架（脚手架组件选择生成，按需补全 TODO 后接入装配）。"""\n',
            encoding="utf-8",
        )
    return generated
