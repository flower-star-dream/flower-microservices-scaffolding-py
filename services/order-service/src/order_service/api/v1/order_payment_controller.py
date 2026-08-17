"""
订单支付接口层（Controller）

@Author: 花海
@Date: 2026/08/16
@Description: 订单支付 HTTP 接口：订单发起支付（下单）、支付回调入口（分发到业务处理器）、
              查单。演示框架支付 SPI：PaymentGateway 渠道抽象 + PaymentCallbackDispatcher 回调分发。
              内存渠道（app.payment.type=memory）本地可直测；生产切换真实渠道后回调需验签解密
              （PaymentCallbackVerifier），本接口演示统一回调分发语义。
"""
from fastapi import APIRouter, Depends, Request

from web_infra import CommonErrorCode, Result
from web_infra.payment import (
    InMemoryPaymentGateway,
    PaymentCallback,
    PaymentCallbackDispatcher,
    PaymentGatewayRegistry,
)

from order_service.payment.order_payment_service import OrderPaymentService
from order_service.repository.order_repository import OrderRepository


def get_order_payment_service(request: Request) -> OrderPaymentService:
    """构造订单支付服务（依赖注入：从应用已装配组件获取 db / 渠道注册表 / 风控限额）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 订单支付服务实例
    """
    risk_guard = getattr(request.app.state, "payment_risk_guard", None)
    limit_rule = getattr(request.app.state, "payment_limit_rule", None)
    return OrderPaymentService(
        repository=OrderRepository(request.app.state.db),
        gateway=PaymentGatewayRegistry.get("memory"),
        risk_guard=risk_guard,
        limit_rule=limit_rule,
    )


def get_payment_gateway(request: Request) -> InMemoryPaymentGateway:
    """获取支付渠道（骨架校验入口：回调通用校验/下单幂等/关单确认，规范 §4.3/§5.5）

    :param request: FastAPI 请求（携带 app.state 已装配组件）
    :return: 已注册的内存支付渠道（骨架实现）
    :raises RuntimeError: 未注册内存渠道（生产切换真实渠道后需替换本依赖）
    """
    gateway = PaymentGatewayRegistry.get("memory")
    if not isinstance(gateway, InMemoryPaymentGateway):
        raise RuntimeError(
            "支付渠道未装配为内存渠道：请检查 main.py 中 PaymentGatewayRegistry.register(\"memory\", ...)"
        )
    return gateway


def get_payment_dispatcher(request: Request) -> PaymentCallbackDispatcher:
    """获取支付回调分发器（main.py 装配：注册了订单支付回调处理器）

    :param request: FastAPI 请求
    :return: 回调分发器
    :raises RuntimeError: 分发器未装配（生成项目未勾选支付模块或 main.py 未装配）
    """
    dispatcher = getattr(request.app.state, "payment_dispatcher", None)
    if dispatcher is None:
        raise RuntimeError("支付回调分发器未装配：请在 main.py 中设置 app.state.payment_dispatcher")
    return dispatcher


router = APIRouter(prefix="/v1/payments", tags=["订单支付"])


@router.post("/orders/{order_id}/pay", summary="订单发起支付")
async def prepay(order_id: int, service: OrderPaymentService = Depends(get_order_payment_service)) -> Result:
    """订单发起支付（下单）：按订单金额向渠道创建支付单，返回调起支付参数"""
    return Result.success(data=await service.prepay(order_id))


@router.post("/notify", summary="支付回调入口")
async def notify(
    callback: PaymentCallback,
    gateway: InMemoryPaymentGateway = Depends(get_payment_gateway),
    dispatcher: PaymentCallbackDispatcher = Depends(get_payment_dispatcher),
) -> Result:
    """支付回调入口：渠道骨架通用校验（金额/attach/状态机，规范 §4.3/§4.5）通过后
    分发到业务处理器（支付成功 → 订单状态机 PAY）。
    演示（内存渠道）直接透传回调体；生产接入真实渠道后由 PaymentCallbackVerifier
    验签解密后构造本结构，再经骨架 validate_callback 完成业务校验。"""
    await gateway.validate_callback(callback)
    await dispatcher.dispatch(callback)
    return Result.success()


@router.get("/{out_trade_no}", summary="查询支付单")
async def query_order(out_trade_no: str, service: OrderPaymentService = Depends(get_order_payment_service)) -> Result:
    """按商户订单号查单（支付结果以渠道查询/回调为准）"""
    order = await service.query_order(out_trade_no)
    if order is None:
        raise CommonErrorCode.COMMON_NOT_FOUND.to_exception(message="支付单不存在")
    return Result.success(data=order)
