"""
订单消息队列模块

@Author: 花海
@Date: 2026/08/16
@Description: order-service 消息队列：订单事件发布（MessagePublisherInterface，内存/RocketMQ 通用）
              与消费（幂等消费演示，仅 mq.type=memory 时由 main.py 装配）。
"""
