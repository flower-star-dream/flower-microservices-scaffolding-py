# =====================================================================
# order-service 业务镜像（自包含多阶段构建）
# @Author: 花海
# @Date: 2026/08/16
# @Description: 与 user-service 同构：微服务形态需要 nacos/rocketmq/minio SDK，框架基础镜像仅含
#               min-monolith + migrate extras，故 build 阶段安装
#               flower-web-infrastructure[min-microservice,migrate] 后仅拷贝 site-packages 到 runtime。
#               构建前置：可访问框架仓库（默认 git+https://github.com/flower-star-dream/flower-web-infrastructure.git）。
# =====================================================================
FROM python:3.11-slim AS build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN pip install --upgrade pip && \
    pip install "flower-web-infrastructure[min-microservice,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git" && \
    # 清理构建期工具（Trivy 高危/严重阻断修复，与框架 Dockerfile 一致）
    pip uninstall -y setuptools wheel pip && \
    rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info

FROM python:3.11-slim

LABEL org.opencontainers.image.title="order-service" \
      org.opencontainers.image.description="flower 微服务脚手架示例服务：订单管理" \
      org.opencontainers.image.licenses="MIT"

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 拷贝 build 阶段安装的全部第三方依赖（含 web_infra 包与 nacos/rocketmq 等 SDK）
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# 业务代码与运行配置（src 加入 PYTHONPATH）
COPY src ./src
COPY application.yml ./application.yml

# 清理基础镜像自带构建期工具 + 非 root 运行（安全基线）
RUN rm -rf /usr/local/lib/python3.11/site-packages/pip \
           /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/lib/python3.11/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3.11/site-packages/pkg_resources \
           /usr/local/lib/python3.11/site-packages/pkg_resources-*.dist-info \
           /usr/local/lib/python3.11/site-packages/_distutils_hack \
           /usr/local/lib/python3.11/site-packages/distutils-precedence.pth \
           /usr/local/lib/python3.11/site-packages/wheel \
           /usr/local/lib/python3.11/site-packages/wheel-*.dist-info \
    && useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src

EXPOSE 8002

# 用 python -m uvicorn 启动（基础镜像只拷贝 site-packages，运行时无控制台脚本）
CMD ["python", "-m", "uvicorn", "order_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
