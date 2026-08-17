"""
订单服务启动入口（main）

@Author: 花海
@Date: 2026/08/16
@Description: order-service 应用入口：基于 web_infra.create_app 配置驱动装配（读取服务目录 application.yml），
              装配服务间远程调用客户端（FeignClient），注册业务路由，启动时注册本服务到注册中心
              并启动内存消息队列消费（mq.type=memory 时）。生产 MQ 切换 rocketmq 后由外部消费组消费。
              启动命令（在服务目录执行）：
              cd services/order-service && uvicorn order_service.main:app --host 0.0.0.0 --port 8002
"""
import uvicorn

from web_infra import build_feign_client, create_app
from web_infra.http.feign_client import FeignClient
from web_infra.mq.in_memory_message_queue import InMemoryMessageQueue

from order_service.api.v1.order_controller import router as order_router
from order_service.bootstrap import deregister_service, register_service
from order_service.client.user_client import UserClient
from order_service.mq.order_event_consumer import OrderEventConsumer

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
    application.include_router(order_router)
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


def _build_startup_handler(application):
    """构造启动处理器：注册本服务 + 启动内存消息队列消费（mq.type=memory 时）"""

    async def _startup() -> None:
        await register_service(application, SERVICE_NAME, SERVICE_PORT)
        await _start_consumers(application)

    return _startup


async def _start_consumers(application) -> None:
    """启动内存消息队列消费（仅 mq.type=memory 时；生产 rocketmq 由外部消费组消费）"""
    mq = application.state.mq
    if isinstance(mq, InMemoryMessageQueue):
        consumer = OrderEventConsumer(mq)
        consumer.register()
        await mq.start()
        application.state.order_consumer = consumer
        application.state.mq_started = True


def _build_shutdown_handler(application):
    """构造停机处理器：注销服务 + 停止内存消息队列消费"""

    async def _shutdown() -> None:
        await deregister_service(application)
        mq = application.state.mq
        if getattr(application.state, "mq_started", False) and hasattr(mq, "stop"):
            await mq.stop()

    return _shutdown


app = create_application()


if __name__ == "__main__":
    uvicorn.run("order_service.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=True)
