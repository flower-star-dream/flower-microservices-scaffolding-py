"""
用户业务 API 模块（v1 路由汇总）

@Author: 花海
@Date: 2026/08/16
@Description: user-service v1 版本路由汇总入口，供 main.py 统一注册。
"""
from fastapi import APIRouter

from user_service.api.v1.user_controller import router as user_router

api_router = APIRouter()
api_router.include_router(user_router)

__all__ = ["api_router"]
