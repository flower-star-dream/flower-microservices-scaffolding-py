"""
用户服务层（Service）

@Author: 花海
@Date: 2026/08/16
@Description: 用户业务逻辑：创建（密码加密/用户名查重）、详情查询（带缓存防穿透）、分页、状态更新。
              演示框架能力：统一错误码（BizException + CommonErrorCode）、密码加密（PasswordEncoder）、
              日志（get_logger）、缓存（CacheBackendInterface 空值防穿透）。
"""
from typing import Any

from web_infra import CommonErrorCode, PasswordEncoder, get_logger
from web_infra.capabilities.cache import CacheBackendInterface

from user_service.constants.user_constant import UserConstant
from user_service.model.user_model import UserModel
from user_service.repository.user_repository import UserRepository
from user_service.schema.user_schema import UserCreateRequest, UserVO

logger = get_logger("user.service")


class UserService:
    """用户服务：业务规则与用例编排"""

    def __init__(self, repository: UserRepository, cache: CacheBackendInterface) -> None:
        """初始化服务

        :param repository: 用户仓储
        :param cache: 缓存后端（app.state.cache，实现 CacheBackendInterface）
        """
        self._repository = repository
        self._cache = cache

    async def get_user(self, user_id: int) -> UserVO:
        """查询用户详情（带缓存，空值占位防穿透规范 §8.2）

        :param user_id: 用户 ID
        :return: 用户出参
        :raises BizException: 用户不存在时抛 COMMON_NOT_FOUND
        """
        cache_key = UserConstant.USER_CACHE_KEY_TEMPLATE.format(user_id=user_id)
        # 空值占位命中：数据确实不存在，直接返回（不再直打 DB）
        if await self._cache.is_empty(cache_key):
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="用户不存在")
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return UserVO.model_validate(cached)

        user = await self._repository.find_by_id(user_id)
        if user is None:
            # 数据不存在写空值占位（TTL 取 USER_CACHE_EMPTY_TTL_SECONDS），防恶意高频请求直打 DB
            await self._cache.set_empty(cache_key, ttl=UserConstant.USER_CACHE_EMPTY_TTL_SECONDS)
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="用户不存在")
        vo = self._to_vo(user)
        await self._cache.set(cache_key, vo.model_dump(mode="json"), ttl=UserConstant.USER_CACHE_TTL_SECONDS)
        return vo

    async def list_users(self, page_no: int, page_size: int) -> tuple[list[UserVO], int]:
        """分页查询用户

        :param page_no: 页码（从 1 开始）
        :param page_size: 每页大小
        :return: (用户出参列表, 总数)
        """
        users, total = await self._repository.find_page(page_no, page_size)
        return [self._to_vo(user) for user in users], total

    async def create_user(self, request: UserCreateRequest) -> UserVO:
        """创建用户（用户名查重 + 密码 bcrypt 加密）

        :param request: 创建请求
        :return: 用户出参
        :raises BizException: 用户名已存在时抛 COMMON_CONFLICT
        """
        existed = await self._repository.find_by_username(request.username)
        if existed is not None:
            raise CommonErrorCode.COMMON_CONFLICT.to_exception(message="用户名已存在")

        user = UserModel(
            username=request.username,
            password_hash=PasswordEncoder.encode(request.password),
            nickname=request.nickname,
            status=UserConstant.USER_STATUS_ENABLED,
        )
        created = await self._repository.create(user)
        logger.info("user_created user_id=%s username=%s", created.id, created.username)
        return self._to_vo(created)

    async def update_status(self, user_id: int, status: int) -> None:
        """更新用户状态（更新后失效缓存）

        :param user_id: 用户 ID
        :param status: 目标状态
        :raises BizException: 用户不存在时抛 COMMON_NOT_FOUND
        """
        updated = await self._repository.update_status(user_id, status)
        if not updated:
            raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="用户不存在")
        await self._cache.delete(UserConstant.USER_CACHE_KEY_TEMPLATE.format(user_id=user_id))
        logger.info("user_status_updated user_id=%s status=%s", user_id, status)

    @staticmethod
    def _to_vo(user: UserModel) -> UserVO:
        """ORM 模型转出参 VO（隐藏密码哈希等敏感字段）

        :param user: 用户模型
        :return: 用户出参
        """
        return UserVO(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            status=user.status,
            created_at=user.created_at,
        )
