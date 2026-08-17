"""
用户域常量（USER_ 前缀）

@Author: 花海
@Date: 2026/08/16
@Description: 用户域常量：权限点（规范 §6.6 权限点常量，禁止裸字符串）、状态枚举、缓存 Key 模板。
"""
from __future__ import annotations


class UserConstant:
    """用户域常量类"""

    # 资源权限点（规范 §6.6：声明式控制，常量前缀 AUTH_PERM_）
    AUTH_PERM_USER_READ = "USER_READ"
    AUTH_PERM_USER_WRITE = "USER_WRITE"

    # 用户状态（1 启用 / 0 禁用）
    USER_STATUS_ENABLED = 1
    USER_STATUS_DISABLED = 0

    # 用户缓存 Key 模板（规范 §5.7：web:{module}:v1:{biz}，动态段运行时注入，禁止手写拼接）
    USER_CACHE_KEY_TEMPLATE = "web:user:v1:info:{user_id}"

    # 用户缓存 TTL（秒）：正常缓存 300s / 空值占位 60s（防穿透，规范 §8.2）
    USER_CACHE_TTL_SECONDS = 300
    USER_CACHE_EMPTY_TTL_SECONDS = 60

    # 分页排序字段白名单（规范 §12.2：排序字段只允许白名单内取值）
    USER_SORT_FIELDS = frozenset({"id", "username", "created_at"})
