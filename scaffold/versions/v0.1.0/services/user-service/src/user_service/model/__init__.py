"""
用户实体模型模块

@Author: 花海
@Date: 2026/08/16
@Description: user-service 业务 ORM 模型汇总入口。后续新增实体模型在此导出；
              同时被 alembic/env.py 导入以注册 Base.metadata（autogenerate 依据）。
"""
from user_service.model.user_model import UserModel

__all__ = ["UserModel"]
