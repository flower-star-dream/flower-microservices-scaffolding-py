"""
网关服务业务包（gateway）

@Author: 花海
@Date: 2026/08/16
@Description: flower 微服务脚手架网关服务：按路由表将 /api/{service_key}/{path} 请求经注册中心
              发现并转发到下游服务（user-service / order-service）。无状态，仅依赖注册中心。
"""
