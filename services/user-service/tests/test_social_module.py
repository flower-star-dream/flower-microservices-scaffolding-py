"""
三方登录示例模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 三方登录（social SPI 示例）测试：授权跳转 URL、登录（未绑定自动注册 + 签发 JWT）、
              绑定 / 解绑幂等与属主校验，以及接口层统一响应结构验证。
              Demo 平台不触网：授权码以 demo- 开头有效。
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from web_infra import BizException, CommonErrorCode
from web_infra import create_app
from web_infra.security import (
    DemoSocialPlatform,
    InMemorySocialBindingStore,
    SocialLoginService,
    SocialPlatformRegistry,
)

from user_service.api.v1.social_controller import router as social_router
from user_service.repository.user_repository import UserRepository
from user_service.social.social_auth_service import SocialAuthService


def _build_service(db) -> tuple[SocialAuthService, SocialPlatformRegistry, InMemorySocialBindingStore]:
    """构造三方登录服务（Demo 平台 + 内存绑定存储，与 main.py 装配一致）"""
    registry = SocialPlatformRegistry()
    registry.register(DemoSocialPlatform())
    binding_store = InMemorySocialBindingStore()
    social = SocialLoginService(registry, binding_store)
    service = SocialAuthService(UserRepository(db), social, binding_store)
    return service, registry, binding_store


@pytest.mark.asyncio
async def test_authorize_url(db):
    """生成授权跳转 URL：Demo 平台返回 redirect_uri?code=demo-{state}"""
    service, _, _ = _build_service(db)
    url = await service.authorize_url("demo", "http://localhost:8001/cb", "abc123")
    assert url == "http://localhost:8001/cb?code=demo-abc123"


@pytest.mark.asyncio
async def test_login_auto_register(db):
    """三方登录未绑定：自动注册本地账号并绑定，签发 JWT"""
    service, _, binding_store = _build_service(db)
    token = await service.login("demo", "demo-open-1", "http://localhost:8001/cb")

    assert token.access_token
    assert token.refresh_token
    # 自动注册用户已落库（用户名 = soc_demo_demo-openid-...）
    user = await UserRepository(db).find_by_username("soc_demo_demo-openid-demo-open-1")
    assert user is not None
    # 绑定已写入
    binding = await binding_store.find_by_platform("demo", "demo-openid-demo-open-1")
    assert binding is not None
    assert binding.user_id == str(user.id)


@pytest.mark.asyncio
async def test_login_twice_same_user(db):
    """同三方账号重复登录：不重复创建本地用户（幂等）"""
    service, _, _ = _build_service(db)
    await service.login("demo", "demo-open-1", "http://localhost:8001/cb")
    token2 = await service.login("demo", "demo-open-1", "http://localhost:8001/cb")

    assert token2.access_token
    user = await UserRepository(db).find_by_username("soc_demo_demo-openid-demo-open-1")
    assert user is not None


@pytest.mark.asyncio
async def test_login_platform_not_configured(db):
    """未注册平台登录：抛 AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED"""
    service, _, _ = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.login("wechat", "code", "http://localhost:8001/cb")
    assert exc_info.value.code == CommonErrorCode.AUTH_SOCIAL_PLATFORM_NOT_CONFIGURED.code


@pytest.mark.asyncio
async def test_bind_and_unbind(db):
    """绑定 / 解绑：绑定后查得到，解绑后查不到"""
    service, _, binding_store = _build_service(db)
    # 先登录触发自动注册，得到本地用户
    token = await service.login("demo", "demo-bind-1", "http://localhost:8001/cb")
    user = await UserRepository(db).find_by_username("soc_demo_demo-openid-demo-bind-1")

    vo = await service.bind("demo", "demo-bind-2", "http://localhost:8001/cb", user.id)
    assert vo.openid == "demo-openid-demo-bind-2"
    assert await binding_store.find_by_platform("demo", "demo-openid-demo-bind-2") is not None

    # 解绑
    assert await service.unbind("demo", "demo-openid-demo-bind-2", user.id) is True
    assert await binding_store.find_by_platform("demo", "demo-openid-demo-bind-2") is None


@pytest.mark.asyncio
async def test_unbind_not_owner_forbidden(db):
    """解绑他人绑定：抛 PERM_DENIED（属主校验）"""
    service, _, binding_store = _build_service(db)
    await service.login("demo", "demo-own-1", "http://localhost:8001/cb")

    binding = await binding_store.find_by_platform("demo", "demo-openid-demo-own-1")
    assert binding is not None
    # 用非属主 user_id 解绑
    with pytest.raises(BizException) as exc_info:
        await service.unbind("demo", "demo-openid-demo-own-1", 99999)
    assert exc_info.value.code == CommonErrorCode.PERM_DENIED.code


@pytest_asyncio.fixture
async def social_client(db):
    """三方登录接口测试客户端（挂 social_router + 装配 Demo 平台/绑定存储）"""
    application = create_app({"app.name": "user-service-social-test"})
    application.state.db = db
    registry = SocialPlatformRegistry()
    registry.register(DemoSocialPlatform())
    binding_store = InMemorySocialBindingStore()
    application.state.social_login_service = SocialLoginService(registry, binding_store)
    application.state.social_auth_service = SocialAuthService(UserRepository(db), application.state.social_login_service, binding_store)
    application.include_router(social_router)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_login_api(social_client):
    """接口：三方登录返回统一响应结构（code=S0000 + Token 出参）"""
    resp = await social_client.get("/v1/social/demo/login", params={"code": "demo-api-1", "redirect_uri": "http://localhost:8001/cb"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["access_token"]


@pytest.mark.asyncio
async def test_authorize_url_api(social_client):
    """接口：生成授权跳转 URL"""
    resp = await social_client.get(
        "/v1/social/demo/authorize-url",
        params={"redirect_uri": "http://localhost:8001/cb", "state": "st"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["authorize_url"] == "http://localhost:8001/cb?code=demo-st"
