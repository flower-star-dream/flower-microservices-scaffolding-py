"""
用户服务启动入口（main）

@Author: 花海
@Date: 2026/08/16
@Description: user-service 应用入口：基于 web_infra.create_app 配置驱动装配（读取服务目录 application.yml），
              注册业务路由（用户 / 认证 JWT SPI / 三方登录），并在启动时经注册中心
              （app.registry.type: nacos/memory）注册本服务实例。
              启动命令（在服务目录执行，配置读取依赖 cwd）：
              cd services/user-service && uvicorn user_service.main:app --host 0.0.0.0 --port 8001
"""
import uvicorn

from web_infra import create_app
from web_infra.capabilities.security import InMemoryJwtTokenStore, JWTUtil, SocialLoginService, SocialPlatformRegistry, DemoSocialPlatform, InMemorySocialBindingStore

from user_service.api.v1.user_controller import router as user_router
# <<<MODULE:jwt_spi>>>
from user_service.api.v1.auth_controller import router as auth_router
# <<</MODULE:jwt_spi>>>
# <<<MODULE:social_login>>>
from user_service.api.v1.social_controller import router as social_router
# <<</MODULE:social_login>>>
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
    # <<<MODULE:jwt_spi>>>
    application.include_router(auth_router)
    # JWT SPI 装配演示（规范 §6.1/§6.2）：显式注入 Token 状态存储与签名密钥/算法提供器。
    # 默认内存实现（单机演示）；生产多实例部署切换为 RedisJwtTokenStore(redis=...) 或经
    # JWTUtil.set_redis 注入，密钥/算法回落 EnvJwtKeyProvider（读取 JWT_SECRET_KEY 环境变量）。
    JWTUtil.configure(token_store=InMemoryJwtTokenStore())
    # <<</MODULE:jwt_spi>>>
    # <<<MODULE:social_login>>>
    application.include_router(social_router)
    # 三方登录装配演示（规范 §6.8）：注册 Demo 平台（不触网，code=demo-xxx 有效）+ 内存绑定存储；
    # 生产实现真实平台 SPI（如微信/GitHub）后注册进 SocialPlatformRegistry，绑定存储可换 Redis/DB 实现。
    social_registry = SocialPlatformRegistry()
    social_registry.register(DemoSocialPlatform())
    binding_store = InMemorySocialBindingStore()
    application.state.social_login_service = SocialLoginService(social_registry, binding_store)
    from user_service.social.social_auth_service import SocialAuthService
    from user_service.repository.user_repository import UserRepository
    application.state.social_auth_service = SocialAuthService(
        repository=UserRepository(application.state.db),
        social=application.state.social_login_service,
        binding_store=binding_store,
    )
    # <<</MODULE:social_login>>>
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
