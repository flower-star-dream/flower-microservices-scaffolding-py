"""
订单服务业务包（order-service）

@Author: 花海
@Date: 2026/08/16
@Description: flower 微服务脚手架示例服务：订单管理。独立数据库 flower_order，
              创建订单时经注册中心发现并调用 user-service（FeignClient）校验用户，
              并发布订单创建事件（MQ，内存/生产 RocketMQ）。
              包名 order_service 与注册中心服务名 order-service 对应。
"""
