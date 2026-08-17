"""
网关服务启动入口（main）

@Author: 花海
@Date: 2026/08/16
@Description: gateway 应用入口：基于 web_infra.create_app 配置驱动装配（读取服务目录 application.yml），
              装配路由转发客户端（FeignClient，注册中心发现 + 负载均衡 + 重试 + 熔断降级），
              注册业务路由，启动时注册本服务到注册中心。
              启动命令（在服务目录执行）：
              cd services/gateway && uvicorn gateway.main:app --host 0.0.0.0 --port 8000
"""
import uvicorn

from web_infra import build_feign_client, create_app
from web_infra.config import Settings
from web_infra.http.feign_client import FeignClient

from gateway.bootstrap import deregister_service, register_service
from gateway.proxy_router import DEFAULT_ROUTES, router as gateway_router

# 注册中心中的服务名与对外端口（与 Dockerfile EXPOSE / 文档端口规划对齐）
SERVICE_NAME = "gateway"
SERVICE_PORT = 8000


def create_application():
    """创建并装配 FastAPI 应用（配置驱动，读取服务目录 application.yml）

    :return: 已装配的 FastAPI 实例
    """
    application = create_app()
    # 路由转发客户端（服务发现 + 负载均衡 + 重试 + 熔断降级）
    application.state.feign = _build_feign(application)
    # 路由表：yml app.gateway.routes 覆盖/追加代码内置默认路由
    application.state.gateway_routes = _load_routes()
    application.include_router(gateway_router)
    application.router.add_event_handler("startup", _build_startup_handler(application))
    application.router.add_event_handler("shutdown", _build_shutdown_handler(application))
    return application


def _build_feign(application) -> FeignClient:
    """构造 FeignClient（配置驱动，规范 §7：超时/重试/退避/熔断收敛于 application.yml app.feign 段）

    未显式传 fallback，采用框架默认兜底（default_service_fallback：统一 503 服务不可用）；
    业务需自定义降级时在此传 fallback 参数覆盖。

    :param application: FastAPI 应用（app.state.registry 为注册中心组件）
    :return: FeignClient 实例
    """
    return build_feign_client(registry=application.state.registry)


def _load_routes() -> dict[str, dict[str, str]]:
    """加载网关路由表：yml app.gateway.routes 覆盖/追加代码内置默认路由（DEFAULT_ROUTES）

    :return: {service_key: {"service": 服务名, "prefix": 转发前缀}} 路由表
    """
    routes: dict[str, dict[str, str]] = dict(DEFAULT_ROUTES)
    configured = Settings.instance().get("app.gateway.routes") or {}
    for key, value in configured.items():
        if isinstance(value, dict) and value.get("service"):
            routes[key] = {
                "service": str(value["service"]),
                "prefix": str(value.get("prefix") or f"/v1/{key}"),
            }
    return routes


def _build_startup_handler(application):
    """构造启动处理器：注册本服务到注册中心"""

    async def _startup() -> None:
        await register_service(application, SERVICE_NAME, SERVICE_PORT)

    return _startup


def _build_shutdown_handler(application):
    """构造停机处理器：注销本服务"""

    async def _shutdown() -> None:
        await deregister_service(application)

    return _shutdown


app = create_application()


if __name__ == "__main__":
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=True)
