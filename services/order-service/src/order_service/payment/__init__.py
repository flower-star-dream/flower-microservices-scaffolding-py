"""
订单支付模块（payment）

@Author: 花海
@Date: 2026/08/16
@Description: order-service 支付示例包：支付网关 SPI 装配（PaymentGatewayRegistry + 内存渠道）
              与订单支付编排（web_infra.payment.order_payment_service / order_payment_callback_handler）。
              依赖订单状态机（回调成功触发 PAY 事件）；生成项目时可经 --modules 裁剪移除
              （裁剪 payment 会同时移除本包与支付控制器，state_machine 保留）。
"""
