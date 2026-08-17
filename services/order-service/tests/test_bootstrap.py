"""
服务注册引导单元测试（bootstrap）

@Author: 花海
@Date: 2026/08/16
@Description: 验证 order-service bootstrap.resolve_register_ip 复用框架 NacosRegistration
              分级探测的接线：register_ip 配置（application.yml）与 NACOS_REGISTER_IP 环境变量
              的优先级。三个服务的 bootstrap.py 代码一致，此处以 order-service 为代表验证；
              框架 tests/test_registry.py 已覆盖 _get_local_ip 的完整探测链路（网关/UDP/回环）。
"""
import order_service.bootstrap as bootstrap
from order_service.bootstrap import resolve_register_ip


def test_resolve_register_ip_from_env(monkeypatch):
    """环境变量 NACOS_REGISTER_IP 生效（复用 NacosRegistration 探测链路）"""
    monkeypatch.setenv("NACOS_REGISTER_IP", "10.0.0.10")
    assert resolve_register_ip() == "10.0.0.10"


class _FakeSettings:
    """替身 Settings：模拟 application.yml 配置了 app.registry.nacos.register_ip"""

    @classmethod
    def instance(cls):
        """返回替身实例（替代框架全局 Settings 单例）"""
        return _FakeSettings()

    def get(self, key: str, default=None):
        """仅模拟 register_ip 配置项，其余返回默认"""
        if key == "app.registry.nacos.register_ip":
            return "10.0.0.5"
        return default


def test_resolve_register_ip_config_wins_over_env(monkeypatch):
    """register_ip 配置优先于环境变量（经 Settings 透传给 NacosRegistration）"""
    monkeypatch.setenv("NACOS_REGISTER_IP", "10.0.0.10")
    monkeypatch.setattr(bootstrap, "Settings", _FakeSettings)
    assert resolve_register_ip() == "10.0.0.5"
