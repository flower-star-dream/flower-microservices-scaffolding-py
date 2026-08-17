"""
订单域常量（ORDER_ 前缀）

@Author: 花海
@Date: 2026/08/16
@Description: 订单域常量：权限点（规范 §6.6）、状态枚举、事件 Topic/Tag（规范 §9）、缓存 Key 模板。
"""
from __future__ import annotations


class OrderConstant:
    """订单域常量类"""

    # 资源权限点（规范 §6.6：声明式控制，常量前缀 AUTH_PERM_）
    AUTH_PERM_ORDER_READ = "ORDER_READ"
    AUTH_PERM_ORDER_WRITE = "ORDER_WRITE"

    # 订单状态（状态机驱动：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消，
    # 合法流转见 order_service.state.order_state_machine）
    ORDER_STATUS_CREATED = 1
    ORDER_STATUS_PAID = 2
    ORDER_STATUS_SHIPPED = 3
    ORDER_STATUS_COMPLETED = 4
    ORDER_STATUS_CANCELLED = 5

    # 订单创建事件（规范 §9：Topic 与业务域对齐，禁止散落字符串）
    ORDER_EVENT_TOPIC = "order.created"
    ORDER_EVENT_TAG_CREATED = "ORDER_CREATED"

    # 订单缓存 Key 模板（规范 §5.7：web:{module}:v1:{biz}，动态段运行时注入，禁止手写拼接）
    ORDER_CACHE_KEY_TEMPLATE = "web:order:v1:info:{order_id}"

    # 订单缓存 TTL（秒）：正常缓存 300s / 空值占位 60s（防穿透，规范 §8.2）
    ORDER_CACHE_TTL_SECONDS = 300
    ORDER_CACHE_EMPTY_TTL_SECONDS = 60

    # 分页排序字段白名单（规范 §12.2：排序字段只允许白名单内取值）
    ORDER_SORT_FIELDS = frozenset({"id", "order_no", "created_at"})
