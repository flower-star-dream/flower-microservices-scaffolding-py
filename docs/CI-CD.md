# flower 微服务脚手架 CI/CD 文档

> 本文档说明本项目的持续集成（CI）与持续交付（CD）流水线：触发时机、前置条件、流水线结构、门禁策略、本地复现与镜像推送规范。
>
> - 上位框架：[flower-web-infrastructure CI/CD 文档](https://github.com/flower-star-dream/flower-web-infrastructure/blob/main/docs/CI-CD.md)（框架流水线负责构建/推送框架镜像）
> - 工作流文件：[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
> - 平台：GitHub Actions（组织 `flower-star-dream`）
> - 关联文件：各服务 `Dockerfile`、根 `.dockerignore`

## 目录

- [1. 触发时机与前置条件](#1-触发时机与前置条件)
- [2. 流水线结构](#2-流水线结构)
- [3. 门禁策略](#3-门禁策略)
- [4. 镜像推送（已启用）](#4-镜像推送已启用)
- [5. 本地复现](#5-本地复现)
- [6. 镜像保留与清理](#6-镜像保留与清理)
- [7. 维护指南](#7-维护指南)
- [8. 常见问题](#8-常见问题)
- [9. 仓库配置（Settings / Secrets）](#9-仓库配置settings--secrets)

## 1. 触发时机与前置条件

### 1.1 触发时机

| 事件 | 分支/范围 | 说明 |
| ---- | ---- | ---- |
| `push` | `main` | 合并到主干后运行全量流水线，并推送三服务测试标签镜像（含 `latest`） |
| `push` | `v*` 版本 tag | 打版本标签时运行全量流水线，并推送三服务正式版镜像（SemVer + `latest`）。**无条件触发**（不受 `paths-ignore` 影响） |
| `pull_request` | 任意 | PR 提交/更新时运行，作为合入门禁；只构建/扫描/冒烟，**不推送**镜像 |

> **非代码变更不触发**（`push` main / PR 均生效）：仅修改文档与非代码文件（`*.md`、`docs/**`、`LICENSE`、`.gitignore`、`.env.example`、`db/**`、`data/**`）时不运行流水线。版本 tag 发布除外。

### 1.2 前置条件（跨仓库访问）

1. **检出框架仓库**（`test` Job）：`actions/checkout` 检出 `flower-star-dream/flower-web-infrastructure`。框架仓库公开则无需配置；私有则需配置 `FRAMEWORK_PAT`。
2. **构建框架依赖**（`build-image` Job）：各服务 `Dockerfile` 在 build 阶段经 `git+https://github.com/flower-star-dream/flower-web-infrastructure.git` 安装框架（`min-microservice,migrate` extras）。框架仓库公开则无需配置；私有则需在镜像构建环境配置凭据（GitHub Actions 的 `actions/checkout` 之外，git+ URL 需要 `.netrc`/token，私有仓库场景建议改用自建镜像源或提前构建框架基础镜像后修改 Dockerfile FROM）。
3. 与单体脚手架不同，**本脚手架不依赖框架 GHCR 基础镜像**：三服务镜像自包含构建（runtime 仅拷贝 site-packages + 业务代码），无需在 `build-image` Job 拉取 `flower-web-infrastructure:latest`。

## 2. 流水线结构

流水线包含两个 Job，`build-image`（三服务矩阵）依赖 `test`：

```
CI
├── test          (静态检查 + 单元测试)
└── build-image   (矩阵 × [gateway, user-service, order-service]：构建镜像 + 漏洞扫描 + 冒烟 + 推送 GHCR)  needs: test
```

### 2.1 test —— 静态检查 + 单元测试

运行环境：`ubuntu-latest`，Python 3.11。

| 步骤 | 命令 | 行为 |
| ---- | ---- | ---- |
| 检出脚手架 | `actions/checkout@v4` | 拉取本仓库代码 |
| 检出框架仓库 | `actions/checkout@v4`（`repository: flower-star-dream/flower-web-infrastructure`） | CI 远程拉取框架源码，随后以 editable 方式安装 |
| 安装 Python | `actions/setup-python@v5` | Python 3.11，启用 pip 缓存 |
| 安装框架依赖 | `pip install -e ./flower-web-infrastructure[mysql,redis,migrate]` | 测试用内存注册中心/MQ，无需 Nacos/RocketMQ/MinIO |
| 安装脚手架依赖 | `pip install -e ".[dev]"` | 工作区工具链（pytest / pytest-asyncio / pytest-cov / httpx / pyright） |
| 静态类型检查 | `pyright` | 覆盖三服务源码（根 pyproject `include`），新增代码必须 0 错误 |
| 单元测试 | `pytest -q` | 覆盖三服务 + CLI 脚本测试；硬性门禁：任一失败即中断流水线 |

### 2.2 build-image —— Docker 业务镜像构建与验证（三服务矩阵）

`strategy.matrix.service: [gateway, user-service, order-service]`，三服务并行执行（各自独立 runner）：

| 步骤 | 行为 |
| ---- | ---- |
| 登录 GHCR | `docker/login-action@v3`，`ghcr.io`，使用 `secrets.GITHUB_TOKEN`（Job 已声明 `packages: write`） |
| 构建业务镜像 | `docker build -t flower-microservices-<service>:ci -f services/<service>/Dockerfile services/<service>`；build 阶段 git+ 安装框架 `[min-microservice,migrate]`，runtime 仅拷贝 site-packages + 业务代码 + `application.yml`，非 root 运行 |
| 镜像漏洞扫描 | Trivy 扫描（`HIGH,CRITICAL`，`exit-code=1`），存在高危/严重漏洞即阻断（规范 §20.2） |
| 冒烟验证 | 启动容器并轮询 `GET /health/live`（30 次 × 1s，存活探针，整改 S19-1）；服务注册到 Nacos 失败时优雅降级（日志告警），不影响存活 |
| 推送镜像（GHCR） | 已启用：push `main` 推测试标签 + `latest`；版本 tag `v*` 推 SemVer + `latest`；PR 不推送。详见 [4. 镜像推送](#4-镜像推送已启用) |

## 3. 门禁策略

| 检查项 | 门禁级别 | 说明 |
| ---- | ---- | ---- |
| 单元测试（pytest） | 硬性 | 失败即阻断合并与镜像构建 |
| 静态类型检查（pyright） | 软性 | 新增代码本地须保持 0 错误（本地门禁） |
| 镜像漏洞扫描（Trivy） | 硬性 | 存在高危/严重漏洞即阻断镜像留存（规范 §20.2） |
| 镜像构建 + `/health/live` 冒烟 | 硬性 | 三服务镜像均必须可启动且存活探针通过（整改 S19-1） |

## 4. 镜像推送（已启用）

工作流已启用 GHCR 推送，镜像地址**按服务维度命名**：`ghcr.io/<org>/<repo>-<service>`。以本仓库为例：`ghcr.io/flower-star-dream/flower-microservices-scaffolding-py-gateway`、`-user-service`、`-order-service`。CI 内部构建标签固定为 `flower-microservices-<service>:ci`，仅用于流水线内构建/扫描/冒烟，不对外推送。

**推送标签规范**（整改 S20-3，每个服务独立一套标签）：

| 触发 | 推送标签 | 说明 |
| ---- | ---- | ---- |
| push `main` | `main-<时间戳>-<构建号>` | 测试版，如 `main-20260816103000-42` |
| push `main` | `latest` | 跟随最新 main 构建 |
| 版本 tag `v*` | `<SemVer>` | 正式版，如 tag `v0.1.0` → 推送 `0.1.0`（与 `pyproject.toml` 版本号保持一致） |
| 版本 tag `v*` | `latest` | 正式版发布时覆盖为最新正式版 |
| PR | 不推送 | 只构建/扫描/冒烟，避免测试镜像污染仓库 |

## 5. 本地复现

在提交前执行与 CI 相同的检查：

```bash
# 安装依赖（默认 Git 远程拉取框架；本机已 clone 框架时可改用本地 editable）
.venv\Scripts\python.exe -m pip install "flower-web-infrastructure[mysql,redis,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 静态类型检查
.venv\Scripts\pyright.exe

# 单元测试
.venv\Scripts\python.exe -m pytest

# 镜像构建与冒烟（本机需安装 Docker；构建需要可访问框架仓库）
docker build -t flower-microservices-gateway:ci -f services/gateway/Dockerfile services/gateway
docker run -d --name scaffold-smoke -p 18000:8000 flower-microservices-gateway:ci
curl http://127.0.0.1:18000/health/live
docker rm -f scaffold-smoke
```

## 6. 镜像保留与清理

> 规范 §20.5：镜像保留策略 + 悬空清理 + 回收审计属**运维配置**（框架边界），CI 负责按标签规范推送，仓库侧保留规则与清理任务由运维按环境配置。基线建议与配置入口见 [框架 CI/CD 文档 §5](https://github.com/flower-star-dream/flower-web-infrastructure/blob/main/docs/CI-CD.md#5-镜像保留与清理)，本仓库按同一策略执行（三服务镜像分别配置）。

## 7. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 调整触发分支 | `ci.yml` 中 `on.push.branches` |
| 新增服务 | `ci.yml` 的 `build-image` Job `matrix.service` 追加服务名；同步确认该服务 `Dockerfile` 的端口与冒烟端口映射 |
| 更换框架仓库地址 | `ci.yml` 中 checkout 的 `repository`、各服务 `Dockerfile` 中 git+ URL，同步更新 [1.2](#12-前置条件跨仓库访问) 与本文档 |
| 更换 GHCR 目标仓库 | `build-image` Job 登录与推送步骤（`IMAGE=ghcr.io/${{ github.repository }}-${{ matrix.service }}` 自动跟随当前仓库，无需改动） |
| 升级 Python 版本 | `ci.yml` 中 `setup-python.python-version`，同步确认各服务 `Dockerfile` 的 `python:3.11-slim` |
| 版本发布 | 遵循 SemVer，同步更新根及三服务 `pyproject.toml` 版本号，然后打 `v<版本>` tag 触发正式版镜像推送（三服务 SemVer + `latest`） |
| 配置/变更 Secret 或包权限 | 见 [9. 仓库配置（Settings / Secrets）](#9-仓库配置settings--secrets) |

## 8. 常见问题

- **pytest 失败**：`test` Job 中断，镜像不构建。按 `pytest` 输出定位失败用例，修复后重新推送/更新 PR。
- **检出框架仓库 404 / Permission denied**：`GITHUB_TOKEN` 无法访问其他仓库，见 [1.2](#12-前置条件跨仓库访问)：公开仓库无需配置，私有仓库需 PAT。
- **镜像构建失败（git+ 拉取框架仓库认证失败）**：各服务 `Dockerfile` 经 git+ URL 安装框架。框架仓库为私有时需在构建环境配置凭据（`.netrc` / build-arg token），或改用自建 pip 源 / 预先构建框架镜像后修改 `FROM`。
- **冒烟验证超时**：容器 30 秒内 `/health/live` 不可达。查看 Job 输出的 `docker logs`，常见原因：`application.yml` 配置异常、业务代码 import 报错、启动端口与 `Dockerfile` `CMD` 端口不一致。
- **GHCR 推送失败（403 / denied）**：确认 `build-image` Job 的 `permissions.packages: write` 已声明；首次推送时需在 GitHub Settings → Packages 中授权镜像包（三个服务各一个包）。

## 9. 仓库配置（Settings / Secrets）

`GITHUB_TOKEN` 由 GitHub 自动注入（`build-image` Job 已声明 `packages: write`，无需配置）；其余配置项按是否跨仓库访问决定是否必需。Secret 名称必须与 `ci.yml` 中的引用（`secrets.XXX`）完全一致。

| 配置项 | 类型 | 配置位置 | 必需性 | 用途与说明 |
| ---- | ---- | ---- | ---- | ---- |
| `FRAMEWORK_PAT` | Actions Secret | 本仓库 Settings → Secrets and variables → Actions → New repository secret | 可选（**框架仓库为私有时必需**） | `test` Job 检出框架仓库的凭据。PAT 权限要求：fine-grained 需对框架仓库 `Contents: Read`；classic 需 `repo`。配置后取消 `ci.yml` 中 checkout 步骤的 `token` 注释。框架仓库公开时无需配置 |
| 框架仓库 git+ 拉取凭据 | 镜像构建环境 | 各服务 `Dockerfile` build 阶段 | 可选（**框架仓库为私有时必需**） | 镜像构建经 git+ 安装框架。私有仓库需在构建环境配置凭据（GitHub Actions Secrets + 注入 `.netrc`），或改用自建源 |
| 本仓库镜像包可见性 | 包设置 | 本仓库 Settings → Packages（gateway / user-service / order-service 三个包） | 首次推送后配置 | 首次 CI 推送成功后在 GitHub 生成镜像包，设置可见性（public/private）与组织成员读权限；私有包需为拉取方（如部署环境）配置读权限 |
| `GITHUB_TOKEN` | 自动注入 | 无需配置 | — | GHCR 登录与推送凭据（`packages: write` 已在 ci.yml 声明） |

**配置顺序建议**（首次接入时按序执行）：

1. （框架仓库私有时）在本仓库创建 Secret `FRAMEWORK_PAT`，并取消 `ci.yml` 中 checkout 的 `token` 注释；
2. 推送本仓库 `main`，观察流水线；首次推送成功后到 Settings → Packages 设置三个镜像包的可见性。
