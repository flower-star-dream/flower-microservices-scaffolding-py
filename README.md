# flower 微服务脚手架（flower-microservices-scaffolding-py）

[![version](https://img.shields.io/badge/version-v0.1.0-blue)](https://github.com/flower-star-dream/flower-microservices-scaffolding-py)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/flower-star-dream/flower-microservices-scaffolding-py)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/flower-star-dream/flower-microservices-scaffolding-py)
[![framework](https://img.shields.io/badge/framework-flower--web--infrastructure-blue)](https://github.com/flower-star-dream/flower-web-infrastructure)
[![CI](https://img.shields.io/github/actions/workflow/status/flower-star-dream/flower-microservices-scaffolding-py/ci.yml?label=CI&logo=github)](https://github.com/flower-star-dream/flower-microservices-scaffolding-py/actions)

> 基于 [flower-web-infrastructure](https://github.com/flower-star-dream/flower-web-infrastructure) 的**微服务脚手架**（Monorepo 多服务同仓）：
> gateway + user-service + order-service，演示注册发现、Feign 远程调用、消息队列、熔断降级与网关路由，开箱即用。
> 单体版本见 [flower-monomer-scaffolding-py](https://github.com/flower-star-dream/flower-monomer-scaffolding-py)。

| 项目     | 值                                                             |
| -------- | -------------------------------------------------------------- |
| 当前版本 | v0.1.0                                                         |
| Python   | >= 3.10                                                        |
| 依赖框架 | flower-web-infrastructure（min-microservice 形态，本地 editable 默认） |
| 仓库形态 | Monorepo（gateway / user-service / order-service）             |
| 数据库   | MySQL 服务分库（flower_user / flower_order）                    |

## 1. 服务组成与端口

| 服务           | 端口 | 说明                                                           |
| -------------- | ---- | -------------------------------------------------------------- |
| `gateway`      | 8000 | API 网关：`/api/{service_key}/{path}` 按路由表经注册中心转发到下游服务 |
| `user-service` | 8001 | 用户管理（独立库 `flower_user`），Redis 缓存，注册到 Nacos     |
| `order-service`| 8002 | 订单管理（独立库 `flower_order`），创建订单 Feign 调用 user-service 校验用户，发布订单事件（MQ） |

服务间调用链路：`gateway → order-service →（FeignClient 服务发现 + 熔断）→ user-service`；`order-service → MQ`（内存/生产 RocketMQ）。

## 2. 目录结构

```
flower-microservices-scaffolding-py/
├── application.yml（无，各服务自持）        # 各服务配置见 services/<service>/application.yml
├── .env.example               # 仓库根敏感配置模板（复制为 .env 填写）
├── pyproject.toml             # 工作区根：dev 工具链 + pytest/pyright 覆盖全部服务
├── docker-compose.yml         # 本地外部依赖：MySQL / Redis / Nacos / RocketMQ / MinIO
├── db/                        # 手工 SQL（基线 init + 增量 versions，按服务分库）
│   └── init/init-mysql.sh     # docker-compose 初始化脚本（ddl/dml 自动执行）
├── services/
│   ├── gateway/               # API 网关（路由转发，FeignClient）
│   │   ├── src/gateway/       # main / bootstrap / proxy_router
│   │   ├── application.yml / pyproject.toml / Dockerfile / tests/
│   ├── user-service/          # 用户服务（CRUD + Redis 缓存 + Nacos 注册）
│   │   ├── src/user_service/  # api / service / repository / model / schema / constants
│   │   ├── alembic/           # 权威迁移（0001_user_init.py）
│   │   ├── application.yml / pyproject.toml / Dockerfile / tests/
│   └── order-service/         # 订单服务（Feign 调用 user-service + MQ 事件）
│       ├── src/order_service/ # api / service / client / mq / repository / model / schema / constants
│       ├── alembic/           # 权威迁移（0001_order_init.py）
│       ├── application.yml / pyproject.toml / Dockerfile / tests/
├── scripts/new_project.py     # 派生新项目 / 新增服务（见 docs/创建新项目.md）
├── docs/                      # 使用说明 / CI-CD / 创建新项目
└── .github/workflows/ci.yml   # CI/CD：静态检查 + 单测 + 三服务镜像构建/扫描/冒烟/推送
```

## 3. 快速开始

### 3.1 创建虚拟环境并安装依赖

```bash
# 1) 创建虚拟环境（Windows）
python -m venv .venv
.venv\Scripts\activate

# 2) 安装框架依赖（extras 按脚手架生成时的组件选择而定，如 [mysql,redis,nacos,migrate]；默认 Git 远程拉取；
#    本机已 clone 框架时可改用 pyproject.toml 注释中的方式二）
pip install "flower-web-infrastructure[mysql,redis,nacos,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"

# 3) 安装工作区工具链（pytest / pyright）
pip install -e ".[dev]"
```

> 本地只跑测试可精简为 `pip install "flower-web-infrastructure[mysql,redis,migrate]"`（测试用内存注册中心/MQ，不依赖 Nacos/RocketMQ/MinIO）。

### 3.2 启动本地外部依赖（docker-compose）

```bash
docker compose up -d          # 一键拉起 MySQL / Redis / Nacos / RocketMQ / MinIO（MySQL 自动执行 db/init 基线 SQL）
cp .env.example .env          # 复制并填写敏感配置（docker-compose 默认 root/root）
```

### 3.3 初始化数据库（Alembic 权威迁移）

```bash
# 在仓库根执行（USER_DATABASE_URL / ORDER_DATABASE_URL 从 .env 自动加载）
alembic -c services/user-service/alembic.ini upgrade head
alembic -c services/order-service/alembic.ini upgrade head
```

### 3.4 启动服务

```bash
cd services/user-service && uvicorn user_service.main:app --host 0.0.0.0 --port 8001   # 终端 A
cd services/order-service && uvicorn order_service.main:app --host 0.0.0.0 --port 8002 # 终端 B
cd services/gateway && uvicorn gateway.main:app --host 0.0.0.0 --port 8000             # 终端 C
```

验证：

- 服务注册：Nacos 控制台（http://127.0.0.1:8848/nacos）应看到三个服务
- 直接调用：`curl http://127.0.0.1:8001/v1/users`、`curl http://127.0.0.1:8002/v1/orders?user_id=1`
- 网关转发：`curl http://127.0.0.1:8000/api/users/1`、`curl http://127.0.0.1:8000/api/orders`
- 健康检查：`curl http://127.0.0.1:8000/health/live`（每服务均有 `/health/live` `/health/ready` `/metrics` `/docs`）

## 4. 示例业务模块（用户 / 订单）

| 方法  | 路径（直连 / 网关）                             | 说明                                                         |
| ----- | ----------------------------------------------- | ------------------------------------------------------------ |
| GET   | `/v1/users/{user_id}` / `/api/users/{user_id}`  | 用户详情（Redis 缓存 + 空值防穿透）                          |
| POST  | `/v1/users` / `/api/users`                      | 创建用户（查重 + bcrypt 加密）                               |
| POST  | `/v1/orders` / `/api/orders`                    | 创建订单（Feign 调用 user-service 校验用户 + 发布 MQ 事件）   |
| GET   | `/v1/orders?user_id=1` / `/api/orders?user_id=1`| 按用户分页查询订单                                            |

接口统一返回 `Result`（`{ code, message, data }`）；业务异常经全局异常处理器转为统一错误响应。

> **常量与错误码以框架单一文档为权威**：完整清单见框架 [docs/常量与错误码.md](https://github.com/flower-star-dream/flower-web-infrastructure/blob/main/docs/常量与错误码.md)——HTTP 状态码统一引用框架 `HttpStatusConstant`（值复用 starlette.status），业务新增常量/错误码前先查阅该文档，防止冲突或重复定义。

## 5. 数据库变更

- **权威迁移工具**：各服务 `alembic/versions/`。`alembic/env.py` 已导入业务模型（`user_service.model` / `order_service.model`）：

```bash
# 仓库根执行（生成迁移后需更新配套 DDL/DML）
alembic -c services/user-service/alembic.ini revision --autogenerate -m "add_xxx"
alembic -c services/order-service/alembic.ini revision --autogenerate -m "add_xxx"
alembic -c services/user-service/alembic.ini upgrade head
```

- **手工 SQL 参考**：基线 `db/init/`（docker-compose 自动执行，禁止回改）、增量 `db/versions/`（`V{版本}-{模块}-{描述}-ddl/dml.sql` 成对，涉及存量数据语义变更必须提供幂等 DML）。

## 6. 测试与质量

```bash
.venv\Scripts\python.exe -m pytest                    # 全部服务测试（SQLite 内存库，无需外部服务）
.venv\Scripts\python.exe -m pytest services/order-service/tests -q
.venv\Scripts\pyright.exe                             # 静态类型检查（新增代码 0 错误）
```

## 7. Docker

```bash
# 各服务镜像自包含多阶段构建（安装框架 min-microservice extras，不依赖框架基础镜像）
docker build -t flower-microservices-gateway:latest -f services/gateway/Dockerfile services/gateway
docker build -t flower-microservices-user-service:latest -f services/user-service/Dockerfile services/user-service
docker build -t flower-microservices-order-service:latest -f services/order-service/Dockerfile services/order-service

docker run -d -p 8000:8000 --env-file .env flower-microservices-gateway:latest
docker run -d -p 8001:8001 --env-file .env flower-microservices-user-service:latest
docker run -d -p 8002:8002 --env-file .env flower-microservices-order-service:latest
```

> CI 中三服务镜像由流水线自动构建并推送 GHCR（`ghcr.io/<org>/<repo>-<service>`）；触发时机 / 门禁 / 标签规范见 [docs/CI-CD.md](docs/CI-CD.md)。

## 8. 扩展与派生

- **新增服务**：`python scripts/new_project.py new-service payment-service`（从 order-service 模板复制并重命名，详见 [docs/创建新项目.md](docs/创建新项目.md)）。
- **派生新项目**：GitHub "Use this template"（或手动 clone 清 git 历史）→ `python scripts/new_project.py new my-project`（**交互式选择组件/实现与能力示例模块**，或 `--components=name:impl,...` / `--modules` 参数跳过；注册中心强制 Nacos、禁止内存实现；组件清单见 [docs/创建新项目.md](docs/创建新项目.md) 6.5 节）。
- **扩展业务模块**：参照 [docs/使用说明.md](docs/使用说明.md) §6：model → schema → repository → service → api 分层新增，同时更新 Alembic 迁移、DDL/DML 与测试。
