"""
用户服务远程客户端（UserClient）

@Author: 花海
@Date: 2026/08/16
@Description: order-service 调用 user-service 的远程客户端封装（FeignClient，规范 §7 远程调用韧性）：
              注册中心发现实例 + 轮询负载均衡 + 指数退避重试 + 熔断降级（框架默认兜底）+ 服务链路头注入。
              降级兜底由 FeignClient 统一处理（未传 fallback 时框架默认返回统一 503"服务不可用"），
              本客户端只做业务响应解释，不重复实现兜底；如需自定义降级（如返回缓存数据），
              在构造 FeignClient 时传 fallback 参数覆盖。
              目标服务名与路径为常量，避免业务代码散落字符串。
"""
from typing import Any

from web_infra import CommonErrorCode
from web_infra.constants import HttpStatusConstant
from web_infra.http.feign_client import FeignClient


class UserClient:
    """用户服务远程客户端"""

    # 注册中心中的目标服务名（user-service 启动时注册）
    SERVICE_NAME = "user-service"
    # 用户详情接口路径（user-service 的 controller 路由）
    USER_DETAIL_PATH_TEMPLATE = "/v1/users/{user_id}"

    def __init__(self, feign: FeignClient) -> None:
        """初始化客户端

        :param feign: FeignClient（服务发现 + 负载均衡 + 重试 + 熔断，已启用框架默认兜底）
        """
        self._feign = feign

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        """查询用户详情（经注册中心发现 user-service 实例并调用）

        上游失败/熔断开启时，FeignClient 已按框架默认兜底返回统一 503"服务不可用"响应，
        本方法只做响应解释：404 表示用户不存在返回 None，5xx（含兜底 503）统一抛服务不可用。

        :param user_id: 用户 ID
        :return: 用户出参（统一响应 Result 的 data 字段）或 None（用户不存在）
        :raises BizException: 用户服务不可用（上游 5xx / 熔断兜底 503，统一 SYS_UNAVAILABLE）
        """
        resp = await self._feign.get(
            self.SERVICE_NAME, self.USER_DETAIL_PATH_TEMPLATE.format(user_id=user_id)
        )
        if resp is None:
            # 业务自定义 fallback 返回 None 时兜底（框架默认兜底返回 503 响应，不会走到这里）
            raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message="用户服务暂不可用（已降级兜底）")
        if resp.status_code == HttpStatusConstant.HTTP_NOT_FOUND:
            return None
        if resp.status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN:
            # 上游 5xx 或框架默认兜底 503：统一按"服务不可用"处理（规范 §7 远程调用韧性）
            raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message="用户服务暂不可用")
        body = resp.json()
        return body.get("data")
