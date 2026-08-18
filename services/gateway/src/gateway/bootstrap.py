"""
服务注册中心引导（bootstrap）

@Author: 花海
@Date: 2026/08/16
@Description: 微服务脚手架统一的注册中心引导：应用启动时将当前服务实例注册到配置的注册中心
              （app.registry.type: memory/nacos，由 create_app 装配），停机时注销。
              对外注册 IP 复用框架 NacosRegistration 分级探测（register_ip 配置 >
              NACOS_REGISTER_IP > POD_IP > HOST_IP > 默认网关 > UDP 探测 > 回环地址），
              生产容器环境建议显式注入对外可达 IP。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.infra.config import Settings
from web_infra.capabilities.config.nacos_properties import NacosProperties
from web_infra.capabilities.registry import NacosRegistration, ServiceInstance

logger = logging.getLogger("bootstrap")


def resolve_register_ip() -> str:
    """解析对外注册 IP（复用框架 NacosRegistration 分级探测，避免重复实现框架逻辑）

    探测优先级：register_ip > 环境变量 NACOS_REGISTER_IP > POD_IP > HOST_IP > 默认网关
    > UDP 本机探测 > 回环地址。其中 register_ip 本身经框架 Settings 读取（环境变量
    APP_REGISTRY_NACOS_REGISTER_IP 优先于 application.yml 配置，遵循"环境变量 > 配置文件"）。
    生产容器环境（K8s/Docker）建议显式注入 POD_IP / HOST_IP / register_ip，
    避免注册到容器内部不可达 IP。
    """
    settings = Settings.instance()
    props = NacosProperties(register_ip=str(settings.get("app.registry.nacos.register_ip") or ""))
    return NacosRegistration(props)._get_local_ip()


async def register_service(app: Any, service_name: str, port: int) -> None:
    """应用启动时注册当前服务实例到注册中心

    :param app: FastAPI 应用（app.state.registry 为 create_app 装配的注册中心组件）
    :param service_name: 注册中心中的服务名（如 gateway）
    :param port: 服务对外端口
    """
    registry = getattr(app.state, "registry", None)
    if registry is None:
        return
    instance = ServiceInstance(ip=resolve_register_ip(), port=port)
    ok = await registry.register(service_name, instance)
    logger.info(
        "service_register service_name=%s ip=%s port=%s result=%s", service_name, instance.ip, port, ok
    )
    app.state.service_name = service_name
    app.state.service_instance = instance


async def deregister_service(app: Any) -> None:
    """应用停机时注销服务实例（幂等：未注册过则跳过）"""
    registry = getattr(app.state, "registry", None)
    service_name = getattr(app.state, "service_name", None)
    instance = getattr(app.state, "service_instance", None)
    if registry is None or service_name is None or instance is None:
        return
    await registry.deregister(service_name, instance)
    logger.info("service_deregister service_name=%s", service_name)
