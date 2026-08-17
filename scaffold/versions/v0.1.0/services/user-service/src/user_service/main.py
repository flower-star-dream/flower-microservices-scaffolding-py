"""
用户服务启动入口（main）

@Author: 花海
@Date: 2026/08/16
@Description: user-service 应用入口：基于 web_infra.create_app 配置驱动装配（读取服务目录 application.yml），
              注册业务路由，并在启动时经注册中心（app.registry.type: nacos/memory）注册本服务实例。
              启动命令（在服务目录执行，配置读取依赖 cwd）：
              cd services/user-service && uvicorn user_service.main:app --host 0.0.0.0 --port 8001
"""
import uvicorn

from web_infra import create_app

from user_service.api.v1.user_controller import router as user_router
from user_service.bootstrap import deregister_service, register_service

# 注册中心中的服务名与对外端口（与 Dockerfile EXPOSE / 文档端口规划对齐）
SERVICE_NAME = "user-service"
SERVICE_PORT = 8001


def create_application():
    """创建并装配 FastAPI 应用（配置驱动，读取服务目录 application.yml）

    :return: 已装配的 FastAPI 实例
    """
    application = create_app()
    application.include_router(user_router)
    # 启动注册 / 停机注销：框架 create_app 自带 lifespan，router.add_event_handler 与其并存（uvicorn 启动时触发）
    application.router.add_event_handler("startup", _build_register_handler(application))
    application.router.add_event_handler("shutdown", _build_deregister_handler(application))
    return application


def _build_register_handler(application):
    """构造启动注册处理器（闭包绑定应用实例）"""

    async def _register() -> None:
        await register_service(application, SERVICE_NAME, SERVICE_PORT)

    return _register


def _build_deregister_handler(application):
    """构造停机注销处理器（闭包绑定应用实例）"""

    async def _deregister() -> None:
        await deregister_service(application)

    return _deregister


app = create_application()


if __name__ == "__main__":
    uvicorn.run("user_service.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=True)
