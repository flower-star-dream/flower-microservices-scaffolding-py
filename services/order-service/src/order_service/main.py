"""
订单服务启动入口（main）

@Author: 花海
@Date: 2026/08/16
@Description: order-service 应用入口：基于 web_infra.create_app 配置驱动装配（读取服务目录 application.yml），
              装配服务间远程调用客户端（FeignClient）、Outbox 轮询投递任务（订单事件可靠投递，规范 §21.3）、
              注册业务路由（订单 / 支付，支付回调驱动订单状态机），启动时注册本服务到注册中心
              并启动内存消息队列消费（mq.type=memory 时）。
              生产 MQ 切换 rocketmq 后由外部消费组消费。
              启动命令（在服务目录执行）：
              cd services/order-service && uvicorn order_service.main:app --host 0.0.0.0 --port 8002
"""
from typing import Any
from decimal import Decimal

import uvicorn

from web_infra import build_feign_client, create_app
from web_infra.http.feign_client import FeignClient
from web_infra.mq import MqConfig, MysqlOutboxStore, register_outbox_tasks
from web_infra.mq.in_memory_message_queue import InMemoryMessageQueue
from web_infra.schedule import TaskScheduler

from order_service.api.v1.order_controller import router as order_router
from order_service.bootstrap import deregister_service, register_service
from order_service.client.user_client import UserClient
from order_service.mq.order_event_consumer import OrderEventConsumer
# <<<MODULE:payment>>>
from web_infra.payment import (
    InMemoryLimitCounterStore,
    InMemoryPaymentFlowStore,
    InMemoryPaymentGateway,
    InMemoryPaymentOrderStore,
    PaymentCallbackDispatcher,
    PaymentGatewayRegistry,
    PaymentRiskGuard,
)
from web_infra.payment.risk.payment_limit_config import LimitRule
from order_service.api.v1.order_payment_controller import router as order_payment_router
from order_service.mq.order_event_publisher import OrderEventPublisher
from order_service.payment.order_payment_callback_handler import OrderPaymentCallbackHandler
from order_service.repository.order_repository import OrderRepository
from order_service.service.order_service import OrderService
# <<</MODULE:payment>>>

# 注册中心中的服务名与对外端口（与 Dockerfile EXPOSE / 文档端口规划对齐）
SERVICE_NAME = "order-service"
SERVICE_PORT = 8002


def create_application():
    """创建并装配 FastAPI 应用（配置驱动，读取服务目录 application.yml）

    :return: 已装配的 FastAPI 实例
    """
    application = create_app()
    # 服务间远程调用客户端（注册中心发现 + 负载均衡 + 重试 + 熔断降级）
    application.state.user_client = UserClient(_build_feign(application))
    # Outbox 轮询投递 + 清理定时任务（订单事件可靠投递兜底，规范 §21.3）
    application.state.outbox_scheduler = _build_outbox_scheduler(application)
    application.include_router(order_router)
    # <<<MODULE:payment>>>
    application.include_router(order_payment_router)
    # 支付装配演示（app.payment.type=memory）：注册内存渠道 + 回调分发器（支付成功 → 订单状态机 PAY）。
    # 内存渠道注入骨架存储（流水/本地订单，规范 §5.2/§4.2），下单幂等/关单查单确认/回调校验/流水落库全量生效。
    # 生产接入真实渠道（如微信 WeChatPayProvider）时仅替换注册的网关实现，回调需配验签解密器。
    payment_gateway = InMemoryPaymentGateway(
        flow_store=InMemoryPaymentFlowStore(),
        order_store=InMemoryPaymentOrderStore(),
    )
    PaymentGatewayRegistry.register("memory", payment_gateway)
    # 风控限额（规范 §9）：内存计数存储 + 配置化规则（生产换 Redis 跨实例计数 + 配置中心推送）。
    # 演示规则：单笔 5000 元、日累计 10000 元、下单频次窗口 1h 内 10 次。
    risk_guard = PaymentRiskGuard(InMemoryLimitCounterStore())
    application.state.payment_risk_guard = risk_guard
    application.state.payment_limit_rule = LimitRule(
        per_transaction=Decimal("5000"), daily_limit=Decimal("10000"),
        frequency_window_seconds=3600, max_attempts=10,
    )
    dispatcher = PaymentCallbackDispatcher()
    dispatcher.register(
        OrderPaymentCallbackHandler(
            OrderService(
                repository=OrderRepository(application.state.db),
                user_client=application.state.user_client,
                publisher=OrderEventPublisher(MysqlOutboxStore(_session_factory(application.state.db))),
                cache=application.state.cache,
                db=application.state.db,
            )
        )
    )
    application.state.payment_dispatcher = dispatcher
    # <<</MODULE:payment>>>
    application.router.add_event_handler("startup", _build_startup_handler(application))
    application.router.add_event_handler("shutdown", _build_shutdown_handler(application))
    return application


def _build_feign(application) -> FeignClient:
    """构造 FeignClient（配置驱动，规范 §7：超时/重试/退避/熔断收敛于 application.yml app.feign 段）

    未显式传 fallback，采用框架默认兜底（default_service_fallback：统一 503 服务不可用）；
    业务需自定义降级（如返回缓存数据）时在此传 fallback 参数覆盖。

    :param application: FastAPI 应用（app.state.registry 为注册中心组件）
    :return: FeignClient 实例
    """
    return build_feign_client(registry=application.state.registry)


def _build_outbox_scheduler(application) -> TaskScheduler:
    """装配 Outbox 轮询投递与清理定时任务（S21-2，订单事件可靠投递兜底）。

    Outbox 本地事务表（message_outbox）由订单创建事务写入；本调度器周期调用
    OutboxPublisher.publish_pending 投递 MQ（失败指数退避重试、超限进死信 P0-3/S9-7），
    并周期清理已发送记录（保留期 7 天）。参数收敛于 application.yml app.mq.outbox 段。

    :param application: FastAPI 应用（app.state.db / app.state.mq 已装配）
    :return: 已注册 Outbox 任务的调度器（startup 启动 / shutdown 停止）
    """
    db = application.state.db
    settings = application.state.settings
    outbox_cfg = settings.get("app.mq.outbox") or {}
    store = MysqlOutboxStore(_session_factory(db))
    config = MqConfig(
        max_retry=int(outbox_cfg.get("max_retry") or 3),
        retry_backoff_seconds=int(outbox_cfg.get("retry_backoff_seconds") or 30),
        dead_letter_topic=outbox_cfg.get("dead_letter_topic") or "web-dlq-topic",
    )
    scheduler = TaskScheduler()
    register_outbox_tasks(
        scheduler,
        store,
        application.state.mq,
        config=config,
        publish_interval_seconds=float(outbox_cfg.get("publish_interval_seconds") or 5.0),
        cleanup_interval_seconds=float(outbox_cfg.get("cleanup_interval_seconds") or 3600.0),
        retain_days=int(outbox_cfg.get("retain_days") or 7),
    )
    application.state.outbox_store = store
    return scheduler


def _session_factory(db):
    """Outbox 存储会话工厂：动态读取数据库配置的 async_sessionmaker（引擎懒加载，首次连接后就绪）

    :param db: 数据库工厂（MySQLDatabase）
    :return: () -> AsyncSession 的同步工厂
    """
    def _make() -> Any:
        factory = getattr(db, "session_factory", None)
        if factory is None:
            raise RuntimeError("MySQL 会话工厂未初始化（Outbox 需在数据库首次连接后运行，请检查连接配置）")
        return factory()

    return _make


def _build_startup_handler(application):
    """构造启动处理器：注册本服务 + 启动 Outbox 轮询 + 启动内存消息队列消费（mq.type=memory 时）"""

    async def _startup() -> None:
        await register_service(application, SERVICE_NAME, SERVICE_PORT)
        scheduler: TaskScheduler = application.state.outbox_scheduler
        scheduler.start()
        await _start_consumers(application)

    return _startup


async def _start_consumers(application) -> None:
    """启动内存消息队列消费（仅 mq.type=memory 时；生产 rocketmq 由外部消费组消费）"""
    mq = application.state.mq
    if isinstance(mq, InMemoryMessageQueue):
        # 幂等 + 异常分类重试（规范 §9.1/§9.6）：死信发布者复用内存队列（P0-3/S9-7）
        consumer = OrderEventConsumer(mq, dlq_publisher=mq)
        consumer.register()
        await mq.start()
        application.state.order_consumer = consumer
        application.state.mq_started = True


def _build_shutdown_handler(application):
    """构造停机处理器：注销服务 + 停止 Outbox 轮询 + 停止内存消息队列消费"""

    async def _shutdown() -> None:
        await deregister_service(application)
        scheduler: TaskScheduler = application.state.outbox_scheduler
        await scheduler.stop()
        mq = application.state.mq
        if getattr(application.state, "mq_started", False) and hasattr(mq, "stop"):
            await mq.stop()

    return _shutdown


app = create_application()


if __name__ == "__main__":
    uvicorn.run("order_service.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=True)
