"""
用户模块单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 用户服务与接口测试：创建（查重 / 加密）、查询（缓存 / 空值占位防穿透）、
              分页、状态更新；接口层统一响应结构验证。
"""
import pytest

from web_infra import BizException, CommonErrorCode, PasswordEncoder
from web_infra.cache import MemoryCacheBackend

from user_service.constants.user_constant import UserConstant
from user_service.repository.user_repository import UserRepository
from user_service.schema.user_schema import UserCreateRequest
from user_service.service.user_service import UserService


def _build_service(db) -> UserService:
    """构造用户服务（注入 SQLite 内存库 + 内存缓存）"""
    return UserService(UserRepository(db), MemoryCacheBackend())


@pytest.mark.asyncio
async def test_create_user_success(db):
    """创建用户成功：密码 bcrypt 加密存储、状态默认启用"""
    service = _build_service(db)
    vo = await service.create_user(UserCreateRequest(username="alice", password="secret123", nickname="爱丽丝"))

    assert vo.id is not None
    assert vo.status == 1
    saved = await UserRepository(db).find_by_id(vo.id)
    assert saved is not None
    assert saved.password_hash != "secret123"
    assert PasswordEncoder.verify("secret123", saved.password_hash)


@pytest.mark.asyncio
async def test_create_user_conflict(db):
    """创建用户重名：抛 COMMON_CONFLICT"""
    service = _build_service(db)
    await service.create_user(UserCreateRequest(username="alice", password="secret123"))

    with pytest.raises(BizException) as exc_info:
        await service.create_user(UserCreateRequest(username="alice", password="secret456"))
    assert exc_info.value.code == CommonErrorCode.COMMON_CONFLICT.code


@pytest.mark.asyncio
async def test_get_user_cached(db):
    """查询用户：首次落库并写缓存，二次命中缓存"""
    service = _build_service(db)
    created = await service.create_user(UserCreateRequest(username="bob", password="secret123"))

    vo = await service.get_user(created.id)
    assert vo.username == "bob"
    cache_key = UserConstant.USER_CACHE_KEY_TEMPLATE.format(user_id=created.id)
    assert await service._cache.get(cache_key) is not None


@pytest.mark.asyncio
async def test_get_user_not_found_empty_placeholder(db):
    """查询不存在的用户：抛 COMMON_NOT_FOUND 并写空值占位（防穿透，规范 §8.2）"""
    service = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.get_user(999)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code
    # 空值占位已写入：二次查询直接命中占位，不再直打 DB
    cache_key = UserConstant.USER_CACHE_KEY_TEMPLATE.format(user_id=999)
    assert await service._cache.is_empty(cache_key) is True
    with pytest.raises(BizException) as exc_info_2:
        await service.get_user(999)
    assert exc_info_2.value.code == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_list_users_page(db):
    """分页查询用户：总数与倒序"""
    service = _build_service(db)
    for i in range(5):
        await service.create_user(UserCreateRequest(username=f"user{i}", password="secret123"))

    users, total = await service.list_users(1, 10)
    assert total == 5
    assert len(users) == 5
    assert users[0].username == "user4"  # 按主键倒序


@pytest.mark.asyncio
async def test_update_status_success(db):
    """更新用户状态成功"""
    service = _build_service(db)
    vo = await service.create_user(UserCreateRequest(username="carol", password="secret123"))

    await service.update_status(vo.id, 0)
    updated = await UserRepository(db).find_by_id(vo.id)
    assert updated is not None
    assert updated.status == 0


@pytest.mark.asyncio
async def test_update_status_not_found(db):
    """更新不存在的用户：抛 COMMON_NOT_FOUND"""
    service = _build_service(db)
    with pytest.raises(BizException) as exc_info:
        await service.update_status(999, 0)
    assert exc_info.value.code == CommonErrorCode.COMMON_NOT_FOUND.code


@pytest.mark.asyncio
async def test_create_user_api(client):
    """接口：创建用户返回统一响应结构（code=S0000）"""
    resp = await client.post("/v1/users", json={"username": "dave", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "S0000"
    assert body["data"]["username"] == "dave"


@pytest.mark.asyncio
async def test_get_user_api_not_found(client):
    """接口：查询不存在用户返回统一错误响应结构（HTTP 404 + 业务错误码）"""
    resp = await client.get("/v1/users/999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == CommonErrorCode.COMMON_NOT_FOUND.code
