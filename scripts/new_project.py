#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新建项目 / 新增服务 / 升级脚本（new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 微服务脚手架生命周期管理（使用场景详见 docs/创建新项目.md）：
    new <project-name>       整体派生新项目：替换项目名 / 仓库名 / 服务分库名（flower_user/flower_order）
                             / 版本 / 作者，覆盖 README，删除脚手架专属内容（scripts/ 等），
                             并在项目根写入 .scaffold-info.json（升级依据）。
                             组件与实现选择（框架全部能力）：交互式向导逐步询问，或
                             --components=name:impl,... 参数跳过（非交互/CI）；注册中心强制 Nacos、
                             禁止内存实现；未选组件配置段按标记块裁剪，选择 custom 生成自研 SPI 骨架。
    new-service <name>       仓库内新增服务：从 services/order-service 模板复制为 services/<name>，
                             替换包名 / 服务名 / 表名 / 库名 / 类名前缀，业务逻辑需按新域调整。
    upgrade <project-dir>    将已生成项目同步到新版脚手架（三路合并 diff+patch）：模板未变不触碰、
                             模板变更且业务未改则更新、模板与业务都改则报告冲突；可一并指定框架版本升级。
    snapshot <version>       生成模板快照基线（发版流程：改 TEMPLATE_VERSION → snapshot → 提交）。
    用法：python scripts/new_project.py new my-project [options]
          python scripts/new_project.py new-service payment-service [options]
          python scripts/new_project.py upgrade <project-dir> [options]
          python scripts/new_project.py snapshot <version>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# 加载同目录组件选择模块（组件目录 / 交互向导 / 标记块裁剪 / 自研骨架）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_components import (  # noqa: E402
    COMPONENTS,
    apply_capabilities_to_text,
    apply_components_to_text,
    generate_spi_skeletons,
    render_capabilities,
    render_extras,
    resolve_components,
)

# ---------------------------------------------------------------------------
# 脚手架固有标识（将被替换为新项目/新服务参数）
# ---------------------------------------------------------------------------
TEMPLATE_ORG_REPO = "flower-star-dream/flower-microservices-scaffolding-py"  # GitHub org/repo 完整引用
TEMPLATE_REPO_NAME = "flower-microservices-scaffolding-py"                   # 仓库名
TEMPLATE_PROJECT_NAME = "flower-microservices-scaffolding"                   # 项目名（根 pyproject / README / 镜像名）
TEMPLATE_DB_USER = "flower_user"                                             # user-service 分库名
TEMPLATE_DB_ORDER = "flower_order"                                           # order-service 分库名
TEMPLATE_VERSION = "0.1.0"                                                   # 脚手架当前版本
TEMPLATE_AUTHOR = "花海"                                                     # 脚手架作者

# 运行时实例属性（app 为 FastAPI 实例变量，不是包名，替换时必须原样保留）
APP_INSTANCE_ATTRS: Tuple[str, ...] = ("state", "include_router", "routes", "url_path_for")

# 需要文本替换的扩展名 / 文件名（白名单，避免触碰二进制与构建缓存）
TEXT_SUFFIXES: Tuple[str, ...] = (
    ".py", ".toml", ".yml", ".yaml", ".ini", ".sql", ".md", ".sh", ".txt", ".json", ".mako",
)
TEXT_FILENAMES: Tuple[str, ...] = ("Dockerfile", ".env.example", ".gitignore", ".dockerignore", "LICENSE")

# 遍历时忽略的目录（构建产物 / 版本控制 / 虚拟环境）
IGNORED_DIRS: Tuple[str, ...] = (".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache")

# 脚手架专属内容（整体派生新项目时排除：CLI 脚本 / CLI 测试 / 设计文档 / 构建产物 / 模板快照历史）
TEMPLATE_ONLY_PREFIXES: Tuple[str, ...] = (
    "scripts",
    "scaffold",
    "docs/superpowers",
    "tests/test_new_project.py",
    "docs/创建新项目.md",
)
TEMPLATE_ONLY_GLOBS: Tuple[str, ...] = ("*.egg-info",)

# 项目根升级元数据（new 时写入业务项目，upgrade 读取作为版本与替换依据）
SCAFFOLD_INFO_FILE = ".scaffold-info.json"
# 模板快照基线目录（脚手架仓库内，发版时 snapshot <version> 生成）
VERSIONS_ROOT = "scaffold/versions"
# 框架标识与安装 extras（upgrade --framework-version 时生成升级命令）
FRAMEWORK_NAME = "flower-web-infrastructure"
FRAMEWORK_EXTRAS = "min-microservice"
FRAMEWORK_GIT_URL = "https://github.com/flower-star-dream/flower-web-infrastructure.git"
# 业务文件（new 时被覆盖 / 业务专属，不参与模板三路合并，upgrade 提示手工比对）
BUSINESS_ONLY_FILES: Tuple[str, ...] = ("README.md",)

# 模板仓库根目录（由脚本位置推断，不依赖运行目录）
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 新增服务模板：order-service（含 Feign 远程调用 / MQ 事件 / 独立库等完整微服务形态）
SERVICE_TEMPLATE_NAME = "order-service"
SERVICE_TEMPLATE_PKG = "order_service"

# 自研 SPI 骨架宿主服务映射（选择策略型实现（custom / orm_custom 等）的组件生成到对应服务的 src/<pkg>/spi/）
MICRO_SPI_HOST: Dict[str, str] = {
    "db": "user-service",
    "cache": "user-service",
    "storage": "order-service",
    "mq": "order-service",
    "registry": "user-service",
    "config": "user-service",
    "mongo": "user-service",
    "payment": "order-service",
    "ai": "order-service",
    "security": "user-service",
    "jwt": "user-service",
    "social": "user-service",
    "task": "order-service",
    "idempotency": "order-service",
}
# 宿主服务 -> Python 包名
MICRO_SERVICE_PKG: Dict[str, str] = {
    "gateway": "gateway",
    "user-service": "user_service",
    "order-service": "order_service",
}

# ---------------------------------------------------------------------------
# 可选能力示例模块（new / new-service 时按 --modules 勾选，未勾选模块整体裁剪）
# 每个模块：
#   description  交互式询问时的说明文案
#   service      宿主服务（模板服务名：order-service / user-service）
#   files        模块专属文件（相对服务目录；new-service 时其中包名前缀按新包名映射）
#   requires     依赖的其他模块（勾选本模块时须一并勾选）
# 公共文件（main.py / application.yml 等）中的模块装配代码用成对标记块包裹：
#   # <<<MODULE:<name>>>   ...   # <<</MODULE:<name>>>
# 未勾选模块时生成器删除专属文件并移除标记块（含标记行）。
# ---------------------------------------------------------------------------
MODULES: Dict[str, dict] = {
    "payment": {
        "description": "支付示例（order-service：支付网关 SPI + 回调分发器，回调联动订单状态机）",
        "service": "order-service",
        "files": (
            "src/order_service/payment/__init__.py",
            "src/order_service/payment/order_payment_service.py",
            "src/order_service/payment/order_payment_callback_handler.py",
            "src/order_service/api/v1/order_payment_controller.py",
            "tests/test_payment_module.py",
        ),
        "requires": ("state_machine",),
    },
    "state_machine": {
        "description": "订单状态机示例（order-service：状态/事件/路由 + OrderService.transition）",
        "service": "order-service",
        "files": (
            "src/order_service/state/__init__.py",
            "src/order_service/state/order_state_machine.py",
            "tests/test_state_machine_module.py",
        ),
    },
    "jwt_spi": {
        "description": "JWT SPI 示例（user-service：密钥/Token 存储 SPI + 签发/校验/登出/刷新）",
        "service": "user-service",
        "files": (
            "src/user_service/security/__init__.py",
            "src/user_service/security/jwt_auth_service.py",
            "src/user_service/api/v1/auth_controller.py",
            "src/user_service/schema/auth_schema.py",
            "tests/test_jwt_module.py",
        ),
    },
    "social_login": {
        "description": "三方登录示例（user-service：平台 SPI + 未绑定自动注册 + 绑定/解绑）",
        "service": "user-service",
        "files": (
            "src/user_service/social/__init__.py",
            "src/user_service/social/social_auth_service.py",
            "src/user_service/api/v1/social_controller.py",
            "src/user_service/schema/social_schema.py",
            "tests/test_social_module.py",
        ),
    },
}
# 标记块行格式：# <<<MODULE:<name>>> / # <<</MODULE:<name>>>
_MARKER_START = "# <<<MODULE:{}>>>"
_MARKER_END = "# <<</MODULE:{}>>>"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="new_project",
        description="微服务脚手架生命周期：new 整体派生 / new-service 新增服务 / upgrade 升级项目 / snapshot 模板快照",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new_cmd = sub.add_parser("new", help="整体派生新项目")
    new_cmd.add_argument("project_name", help="新项目名，如 my-project（用于 pyproject/README/镜像名/GHCR 仓库名）")
    new_cmd.add_argument("--db-name", help="服务分库名前缀（默认：项目名转 snake_case，如 my-project -> my_project_user / my_project_order）")
    new_cmd.add_argument("--org", default="flower-star-dream", help="GitHub 组织名（默认 flower-star-dream，替换 README 徽章链接）")
    new_cmd.add_argument("--version", default=TEMPLATE_VERSION, help="初始版本号（默认 0.1.0）")
    new_cmd.add_argument("--author", help="作者名（替换 @Author: 花海 与 pyproject authors；缺省不替换）")
    new_cmd.add_argument(
        "--dir",
        help="目标输出目录（提供则从当前模板目录复制到目标后重命名，模板目录保持不动；缺省原地重命名）",
    )
    new_cmd.add_argument("--git-init", action="store_true", help="自动执行 git init + 首次提交（手动 clone 方式使用）")
    new_cmd.add_argument(
        "--components",
        help="组件与实现选择（逗号分隔 name:impl，如 cache:redis,mq:rocketmq；"
        "all=全部默认 / none=仅必选组件；缺省时交互式逐个询问，非交互环境默认全部默认值）。"
        f"可用组件：{'、'.join(COMPONENTS)}；注册中心强制 Nacos、禁止内存实现",
    )
    new_cmd.add_argument(
        "--modules",
        help="勾选能力示例模块（逗号分隔：payment,state_machine,jwt_spi,social_login；all=全部 / none=不包含；"
        "缺省时交互式逐个询问，非交互环境默认全部）",
    )

    svc_cmd = sub.add_parser("new-service", help="仓库内新增服务（从 order-service 模板复制并重命名）")
    svc_cmd.add_argument("service_name", help="新服务名，如 payment-service（用于目录/包名/注册中心服务名）")
    svc_cmd.add_argument("--package", help="Python 包名（默认：服务名转 snake_case，如 payment-service -> payment_service）")
    svc_cmd.add_argument(
        "--modules",
        help="勾选能力示例模块（仅作用于 order-service 宿主模块 payment/state_machine；"
        "all=全部 / none=不包含 / 缺省交互式询问，非交互环境默认全部）",
    )

    upgrade_cmd = sub.add_parser("upgrade", help="升级已生成项目到新版脚手架（三路合并，模板同步 + 框架版本）")
    upgrade_cmd.add_argument("project_dir", help="目标业务项目根目录（含 .scaffold-info.json）")
    upgrade_cmd.add_argument("--to", dest="to_version", help="目标脚手架版本（默认当前模板版本）")
    upgrade_cmd.add_argument(
        "--framework-version",
        dest="framework_version",
        help="目标框架版本（如 0.2.0），提供则更新 .scaffold-info.json 并输出框架升级命令",
    )
    upgrade_cmd.add_argument("--dry-run", action="store_true", help="只预览变更，不写盘")
    upgrade_cmd.add_argument(
        "--modules",
        help="覆盖能力示例模块勾选（默认沿用项目 .scaffold-info.json 记录；none 表示不新增模块文件）",
    )
    upgrade_cmd.add_argument(
        "--components",
        help="覆盖组件与实现选择（默认沿用项目 .scaffold-info.json 记录；注册中心强制 Nacos）",
    )

    snap_cmd = sub.add_parser("snapshot", help="生成模板快照基线（发版流程使用）")
    snap_cmd.add_argument("version", help="版本号（如 0.2.0，生成到 scaffold/versions/v<version>/）")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# 参数派生
# ---------------------------------------------------------------------------


def _derive_new_names(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生整体派生所需的参数。"""
    project = args.project_name.strip()
    if (
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", project)
        or project.endswith((".", "-"))
        or ".." in project
        or project.lower().endswith(".git")
    ):
        sys.exit(
            f"非法项目名：{project!r}（须为合法仓库名：字母/数字开头，仅含字母/数字/连字符/下划线/点，"
            "禁止连续点、点/连字符结尾与 .git 结尾）"
        )
    db_name = args.db_name or re.sub(r"[^a-zA-Z0-9]", "_", project).lower()
    # 组件与实现选择：--components 显式 > 交互式询问（TTY）> 非交互默认；
    # 微服务脚手架形态默认：注册中心强制 Nacos、缓存默认 Redis（docker-compose 提供），内存实现一律禁止
    components = resolve_components(args.components, defaults={"registry": "nacos", "cache": "redis"})
    components["registry"] = "nacos"
    return {
        "project_name": project,
        "repo_name": project.lower(),
        "db_name": db_name,
        "org": args.org,
        "version": args.version,
        "author": args.author,
        "git_init": args.git_init,
        "target_dir": args.dir,
        "components": components,
        "modules": _resolve_modules(args.modules),
    }


def _derive_service_names(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生新增服务所需的参数。

    域名推导：服务名去除 "-service" 后缀（如 payment-service -> payment），
    类名前缀取域名 PascalCase（payment -> Payment），常量前缀取大写（PAYMENT）。
    """
    name = args.service_name.strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name) or name.endswith((".", "-")):
        sys.exit(
            f"非法服务名：{name!r}（须为合法仓库名：字母/数字开头，仅含字母/数字/连字符/下划线/点）"
        )
    package = args.package or re.sub(r"[^a-zA-Z0-9]", "_", name).lower().strip("_")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", package):
        sys.exit(f"非法 Python 包名：{package!r}（须匹配 [a-zA-Z_][a-zA-Z0-9_]*，可用 --package 指定）")
    # 域名（类名/常量/表名前缀）：去除 "-service" 后缀；无后缀时直接用服务名
    domain = name[:-len("-service")] if name.endswith("-service") else name
    domain_snake = re.sub(r"[^a-zA-Z0-9]", "_", domain).lower().strip("_")
    pascal = "".join(part.capitalize() for part in domain_snake.split("_"))
    if not pascal:
        sys.exit(f"无法从服务名推导域名：{name!r}（类名前缀为空）")
    return {
        "service_name": name,
        "package": package,
        "domain": domain_snake,
        "pascal": pascal,
        "upper": domain_snake.upper(),
        "modules": _resolve_modules(args.modules),
    }


def _derive_upgrade_args(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生升级参数。"""
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        sys.exit(f"项目目录不存在：{project_dir}")
    to_version = args.to_version or TEMPLATE_VERSION
    if not re.fullmatch(r"\d+\.\d+\.\d+", to_version):
        sys.exit(f"非法版本号：{to_version!r}（须为 x.y.z，如 0.2.0）")
    if args.framework_version and not re.fullmatch(r"\d+\.\d+\.\d+", args.framework_version):
        sys.exit(f"非法框架版本号：{args.framework_version!r}（须为 x.y.z，如 0.2.0）")
    return {
        "project_dir": str(project_dir),
        "to_version": to_version,
        "framework_version": args.framework_version,
        "dry_run": args.dry_run,
        "modules": args.modules,
        "components": args.components,
    }


def _derive_snapshot_args(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生快照参数。"""
    version = args.version.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"非法版本号：{version!r}（须为 x.y.z，如 0.2.0）")
    return {"version": version}


# ---------------------------------------------------------------------------
# 能力示例模块选择（--modules / 交互式询问）
# ---------------------------------------------------------------------------


def _parse_modules(value: str) -> List[str]:
    """解析 --modules 取值：all=全部 / none=无 / 逗号分隔列表，并校验依赖关系。

    :param value: --modules 原始值
    :return: 勾选的模块名列表
    :raises SystemExit: 未知模块名 / 依赖模块未勾选
    """
    normalized = value.strip().lower()
    if normalized in ("all", "*"):
        return list(MODULES)
    if normalized == "none":
        return []
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in MODULES]
    if unknown:
        sys.exit(
            f"未知能力示例模块：{unknown}（可用：{'、'.join(MODULES)}，或 all / none）"
        )
    for name in names:
        for dep in MODULES[name].get("requires", ()):
            if dep not in names:
                sys.exit(f"模块 {name} 依赖 {dep}，请一并勾选（--modules {','.join(names + [dep])}）")
    return names


def _prompt_modules() -> List[str]:
    """交互式逐个询问勾选能力示例模块（默认不选，输入 y/yes 才包含）。

    :return: 勾选的模块名列表
    """
    print("请勾选脚手架能力示例模块（生成后仍可按需移除/补充）：")
    selected: List[str] = []
    for name, spec in MODULES.items():
        answer = input(f"  包含「{spec['description']}」？[y/N] ").strip().lower()
        if answer in ("y", "yes"):
            selected.append(name)
    return selected


def _resolve_modules(value: Optional[str]) -> List[str]:
    """解析模块选择：--modules 显式取值 > 交互式询问（TTY）> 默认全部（非交互环境）。

    :param value: --modules 参数值（None 表示未指定）
    :return: 勾选的模块名列表
    """
    if value is not None:
        return _parse_modules(value)
    if sys.stdin.isatty():
        return _prompt_modules()
    # 非交互环境（CI / 脚本 / 测试）：默认包含全部示例模块，保证生成脚手架开箱即用
    return list(MODULES)


# ---------------------------------------------------------------------------
# 模块裁剪（删除专属文件 + 移除标记块 + 清理空目录）
# ---------------------------------------------------------------------------


def _remove_marker_block(text: str, module: str) -> str:
    """移除单个模块的全部标记块（含标记行）：
    `# <<<MODULE:<name>>>` 到 `# <<</MODULE:<name>>>` 之间的内容按行删除。

    :param text: 文件原文
    :param module: 模块名
    :return: 移除标记块后的文本
    """
    start_marker = _MARKER_START.format(module)
    end_marker = _MARKER_END.format(module)
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == start_marker:
            inside = True
            continue
        if stripped == end_marker:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _remove_module_blocks(text: str, unselected: Iterable[str]) -> str:
    """从文本移除多个未勾选模块的标记块（upgrade 的 theirs 转换复用）。

    :param text: 文件原文
    :param unselected: 未勾选模块名集合
    :return: 移除标记块后的文本
    """
    for module in unselected:
        text = _remove_marker_block(text, module)
    return text


def _remove_empty_dirs(root: Path) -> None:
    """自底向上清理空目录（裁剪模块文件后可能留下空包目录）。"""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == str(root):
            continue
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def _prune_modules(root: Path, selected: Iterable[str]) -> None:
    """按勾选结果裁剪未包含模块：删除专属文件 + 移除公共文件标记块 + 清理空目录。

    :param root: 生成目标根目录（new 为项目根 / new-service 为目标服务目录）
    :param selected: 勾选的模块名集合
    """
    selected_set = set(selected)
    unselected = [name for name in MODULES if name not in selected_set]
    if not unselected:
        return
    for name in unselected:
        spec = MODULES[name]
        # 1) 删除模块专属文件（路径：services/<宿主服务>/<相对服务目录>）
        for rel in spec["files"]:
            path = root / "services" / spec["service"] / rel
            if path.exists():
                path.unlink()
    # 2) 移除公共文件中的标记块（main.py / application.yml 等全部文本文件）
    for path in _iter_text_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = _remove_module_blocks(content, unselected)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    # 3) 清理裁剪后遗留的空目录
    _remove_empty_dirs(root)


# ---------------------------------------------------------------------------
# 文本替换
# ---------------------------------------------------------------------------


def _protect_app_instances(text: str) -> Tuple[str, List[Tuple[int, str]]]:
    """将运行时实例属性 app.<attr> 替换为占位符，避免包名替换误伤。"""
    records: List[Tuple[int, str]] = []
    for attr in APP_INSTANCE_ATTRS:
        marker = f"@@FLOWER_APP_INSTANCE_{attr}@@"
        text = text.replace(f"app.{attr}", marker)
        records.append((0, attr))
    return text, records


def _restore_app_instances(text: str, records: List[Tuple[int, str]]) -> str:
    """将占位符恢复为原实例属性 app.<attr>。"""
    for _, attr in records:
        text = text.replace(f"@@FLOWER_APP_INSTANCE_{attr}@@", f"app.{attr}")
    return text


def _apply_new_replacements(text: str, names: Dict[str, str]) -> str:
    """整体派生：项目名 / 仓库名 / 服务分库名 / 版本 / 作者 替换（先长串后短串）。"""
    # 1) 先占位保护运行时实例属性（app.state 等，替换 app. 包引用时避免误伤）
    text, records = _protect_app_instances(text)
    # 2) 长串优先：org/repo 完整引用 -> 项目名 -> 分库名
    text = text.replace(f"{names['org']}/{TEMPLATE_REPO_NAME}", f"{names['org']}/{names['repo_name']}")
    text = text.replace(TEMPLATE_REPO_NAME, names["repo_name"])
    text = text.replace(TEMPLATE_PROJECT_NAME, names["project_name"])
    text = text.replace(TEMPLATE_DB_USER, f"{names['db_name']}_user")
    text = text.replace(TEMPLATE_DB_ORDER, f"{names['db_name']}_order")
    # 3) 版本号与作者（可选）
    text = text.replace(TEMPLATE_VERSION, names["version"])
    if names.get("author"):
        text = text.replace(f"@Author: {TEMPLATE_AUTHOR}", f"@Author: {names['author']}")
    # 4) 恢复运行时实例属性
    text = _restore_app_instances(text, records)
    return text


def _apply_service_replacements(text: str, names: Dict[str, str]) -> str:
    """新增服务：包名 / 服务名 / 表名 / 库名 / 类名前缀替换。

    替换顺序（先长串后短串，避免子串误伤）：
    order_service(包名) -> order-service(服务名) -> t_order(表名) -> flower_order(库名)
    -> Order(类名前缀，后接大写) -> ORDER_(常量前缀) -> order(域名词，独立单词)。
    """
    text = text.replace(f"{SERVICE_TEMPLATE_PKG}.", f"{names['package']}.")
    text = text.replace(SERVICE_TEMPLATE_PKG, names["package"])
    text = text.replace(SERVICE_TEMPLATE_NAME, names["service_name"])
    text = text.replace("t_order", f"t_{names['domain']}")
    text = text.replace(TEMPLATE_DB_ORDER, f"flower_{names['domain']}")
    # 消息体/变量前缀：order_id / order_no 等（下划线是单词字符，\border\b 无法匹配，需显式替换前缀；
    # 排除 SQLAlchemy 的 order_by 方法）
    text = re.sub(rf"\border_(?!by)", f"{names['domain']}_", text)
    # 类名前缀：OrderModel/OrderService/OrderVO 等（Order 后紧跟大写字母）
    text = re.sub(rf"\bOrder(?=[A-Z])", names["pascal"], text)
    # 常量前缀：ORDER_STATUS_CREATED / ORDER_EVENT_TOPIC 等
    text = re.sub(rf"\bORDER(?=_)", names["upper"], text)
    # 域名词（独立单词）：事件 Topic order.created、文档英文描述等
    text = re.sub(rf"\border\b", names["domain"], text)
    return text


# ---------------------------------------------------------------------------
# 文件遍历与处理
# ---------------------------------------------------------------------------


def _iter_text_files(root: Path) -> Iterable[Path]:
    """遍历目录中的文本文件（跳过忽略目录与脚手架专属内容）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS
            and not d.endswith(".egg-info")
            and d not in ("scripts", "scaffold")
        ]
        for name in filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(root)).replace("\\", "/")
            if _is_template_only(rel):
                continue
            if name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def _is_template_only(rel_path: str) -> bool:
    """判断相对路径是否属于脚手架专属内容（整体派生新项目时应排除）。"""
    if any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in TEMPLATE_ONLY_PREFIXES):
        return True
    return any(Path(rel_path).name.endswith(suffix) for suffix in TEMPLATE_ONLY_GLOBS)


def _remove_template_only_paths(root: Path) -> None:
    """删除脚手架专属内容（脚本 / CLI 测试 / 设计文档 / 构建产物）。"""
    for egg_info in root.rglob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
    for rel in TEMPLATE_ONLY_PREFIXES:
        target = root / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


# ---------------------------------------------------------------------------
# 整体派生（new）
# ---------------------------------------------------------------------------


def _render_new_readme(names: Dict[str, str]) -> str:
    """渲染整体派生后的新项目初始化 README（含组件选择结果与按选择的框架 extras）。"""
    repo_url = f"https://github.com/{names['org']}/{names['repo_name']}"
    extras = render_extras(names["components"])
    component_rows = "\n".join(
        f"| {COMPONENTS[name]['label']} | {_micro_impl_label(name, names['components'][name])} |"
        for name in COMPONENTS
        if names["components"].get(name) not in (None, "off")
    )
    return f"""# {names['project_name']}

[![version](https://img.shields.io/badge/version-v{names['version']}-blue)]({repo_url})
[![python](https://img.shields.io/badge/python-3.10%2B-blue)]({repo_url})
[![license](https://img.shields.io/badge/license-MIT-green)]({repo_url})
[![CI](https://img.shields.io/github/actions/workflow/status/{names['org']}/{names['repo_name']}/ci.yml?label=CI&logo=github)]({repo_url}/actions)

> 基于 [flower-web-infrastructure](https://github.com/flower-star-dream/flower-web-infrastructure) 的微服务项目，
> 由 [flower-microservices-scaffolding](https://github.com/flower-star-dream/flower-microservices-scaffolding-py) 脚手架生成。

| 项目     | 值                                        |
| -------- | ----------------------------------------- |
| 当前版本 | v{names['version']}                       |
| Python   | >= 3.10                                   |
| 依赖框架 | flower-web-infrastructure                 |
| 仓库形态 | Monorepo（gateway / user-service / order-service） |
| 数据库   | MySQL 服务分库（{names['db_name']}_user / {names['db_name']}_order） |

## 启用的组件（脚手架生成时选择）

| 组件     | 实现                                    |
| -------- | --------------------------------------- |
{component_rows}

## 快速开始

```bash
# 1) 创建虚拟环境（Windows）
python -m venv .venv
.venv\\Scripts\\activate

# 2) 安装框架依赖（extras 按组件选择生成；默认 Git 远程拉取；本机已 clone 框架时可改本地 editable）
pip install "flower-web-infrastructure[{extras}] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"

# 3) 安装工作区工具链
pip install -e ".[dev]"

# 4) 启动本地外部依赖并复制 .env
docker compose up -d
cp .env.example .env        # 填写敏感配置（docker-compose 默认 root/root）

# 5) 初始化数据库（Alembic 权威迁移，仓库根执行）
alembic -c services/user-service/alembic.ini upgrade head
alembic -c services/order-service/alembic.ini upgrade head

# 6) 启动服务（各服务目录执行）
cd services/user-service && uvicorn user_service.main:app --port 8001
cd services/order-service && uvicorn order_service.main:app --port 8002
cd services/gateway && uvicorn gateway.main:app --port 8000
```

> 详细说明见 [docs/使用说明.md](docs/使用说明.md)；CI/CD 见 [docs/CI-CD.md](docs/CI-CD.md)。
"""


def _micro_impl_label(name: str, impl: str) -> str:
    """返回组件实现的中文说明（供 README 组件表使用）。"""
    spec = COMPONENTS[name]
    for opt in spec["options"]:
        if opt["id"] == impl:
            return opt["label"]
    return impl


def _git_init_and_commit(root: Path, project_name: str) -> None:
    """执行 git init + 首次提交（--git-init 时调用）。"""
    try:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: 从 flower-microservices-scaffolding 脚手架初始化 {project_name} 项目"],
            cwd=root, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git 初始化失败：{exc.stderr.decode(errors='replace').strip() or exc}")


def _prepare_new_target(names: Dict[str, str]) -> Path:
    """确定整体派生的处理目录：原地重命名或复制到目标目录。"""
    if not names["target_dir"]:
        return PROJECT_ROOT
    target = Path(names["target_dir"])
    if target.exists() and any(target.iterdir()):
        sys.exit(f"目标目录已存在且非空：{target}")
    shutil.copytree(
        PROJECT_ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", "*.pyc",
            *TEMPLATE_ONLY_PREFIXES, *TEMPLATE_ONLY_GLOBS,
        ),
    )
    return target


def _generate_micro_spi_skeletons(root: Path, names: Dict[str, str]) -> List[str]:
    """按组件选择为 custom（自研 SPI）生成骨架到宿主服务的 src/<pkg>/spi/。

    Args:
        root: 生成目标根目录。
        names: _derive_new_names 返回值（components / custom_spis 记录）。

    Returns:
        已生成骨架的组件名列表。
    """
    generated: List[str] = []
    for name in COMPONENTS:
        impl = names["components"].get(name)
        if not impl or impl == "off":
            continue
        opt = next((o for o in COMPONENTS[name]["options"] if o["id"] == impl), None)
        if opt is None or not opt.get("strategy"):
            continue
        host = MICRO_SPI_HOST.get(name)
        if not host:
            continue
        service_root = root / "services" / host
        pkg = MICRO_SERVICE_PKG[host]
        generated += generate_spi_skeletons(service_root, pkg, {name: impl})
    return generated


def _run_new(names: Dict[str, str]) -> Path:
    """执行整体派生主流程（在目标目录内完成全部替换、组件裁剪与骨架生成）。"""
    root = _prepare_new_target(names)
    for path in _iter_text_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if _is_template_only(rel):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = _apply_new_replacements(content, names)
        # 按组件选择裁剪：移除未选组件标记块 + 替换已选组件实现（注册中心强制 Nacos 保留）
        updated = apply_components_to_text(updated, names["components"])
        # 能力依赖装配段（app.capabilities.enabled）按组件选择渲染
        updated = apply_capabilities_to_text(updated, names["components"])
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    (root / "README.md").write_text(_render_new_readme(names), encoding="utf-8")
    _remove_template_only_paths(root)
    # 按 --modules 勾选裁剪能力示例模块（未勾选：删除专属文件 + 移除公共文件标记块）
    _prune_modules(root, names["modules"])
    # 选择 custom（自研 SPI）的组件生成骨架到宿主服务 src/<pkg>/spi/
    names["custom_spis"] = _generate_micro_spi_skeletons(root, names)
    _save_scaffold_info(root, names)
    if names["git_init"]:
        _git_init_and_commit(root, names["project_name"])
    return root


# ---------------------------------------------------------------------------
# 升级（upgrade）：三路合并 diff+patch
# ---------------------------------------------------------------------------


def _save_scaffold_info(root: Path, names: Dict[str, str]) -> None:
    """在项目根写入 .scaffold-info.json（记录脚手架版本、替换参数、组件选择与能力模块，升级依据）。"""
    info = {
        "scaffold": TEMPLATE_REPO_NAME,
        "scaffold_version": TEMPLATE_VERSION,
        "framework": FRAMEWORK_NAME,
        "framework_pin": None,
        "components": names.get("components") or {},
        "modules": names.get("modules") or [],
        "params": {
            key: names.get(key)
            for key in ("project_name", "repo_name", "db_name", "org", "version", "author")
        },
    }
    (root / SCAFFOLD_INFO_FILE).write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_scaffold_info(project_dir: Path) -> Dict[str, object]:
    """读取项目根 .scaffold-info.json 并校验脚手架类型。"""
    path = project_dir / SCAFFOLD_INFO_FILE
    if not path.exists():
        sys.exit(
            f"不是本脚手架生成的项目（缺少 {SCAFFOLD_INFO_FILE}）：{project_dir}\n"
            "升级仅支持由 new 命令生成的、保留了 .scaffold-info.json 的项目。"
        )
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        sys.exit(f"{SCAFFOLD_INFO_FILE} 解析失败：{exc}")
    if not isinstance(info, dict):
        sys.exit(f"{SCAFFOLD_INFO_FILE} 格式错误：顶层应为 JSON 对象")
    if info.get("scaffold") != TEMPLATE_REPO_NAME:
        sys.exit(
            f"脚手架类型不匹配：{info.get('scaffold')!r} ≠ {TEMPLATE_REPO_NAME!r}\n"
            "请使用对应脚手架的 scripts/new_project.py 执行升级。"
        )
    return info


def _read_text_optional(path: Path) -> Optional[str]:
    """读取文本文件；不存在或无法按文本解码时返回 None。"""
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return None


def _three_way_merge(base: Optional[str], ours: Optional[str], theirs: Optional[str]) -> str:
    """三路合并判定。

    Args:
        base: 旧版模板内容（已转项目形态）；None 表示旧模板无此文件。
        ours: 项目当前内容；None 表示项目无此文件。
        theirs: 新版模板内容（已转项目形态）；None 表示新模板已废弃此文件。

    Returns:
        动作：skip（不处理）/ update（用新版覆盖）/ add（新增文件）/
              remove（删除文件）/ conflict（模板与业务均改动，需手工处理）/
              missing（业务删除了模板文件，需人工确认）。
    """
    if base is None:
        if ours is None:
            return "add"
        if ours == theirs:
            return "skip"
        return "conflict"
    if theirs is None:
        if ours is None:
            return "skip"
        if ours == base:
            return "remove"
        return "conflict"
    if theirs == base:
        return "skip"
    if ours is None:
        return "missing"
    if ours == base:
        return "update"
    if ours == theirs:
        return "skip"
    return "conflict"


def _run_upgrade(names: Dict[str, str]) -> Dict[str, List[str]]:
    """执行升级主流程：三路合并模板文件并（可选）更新框架版本。

    Args:
        names: _derive_upgrade_args 返回值（project_dir / to_version / framework_version / dry_run）。

    Returns:
        统计结果：updated / added / removed / conflict / missing 文件相对路径列表。
    """
    project_dir = Path(names["project_dir"])
    info = _load_scaffold_info(project_dir)
    params: Dict[str, object] = dict(info["params"])
    # 组件选择：沿用项目记录（旧版项目无记录时取默认，注册中心强制 Nacos、缓存默认 Redis）；--components 可覆盖
    components = _project_components(info)
    if names["components"] is not None:
        components = resolve_components(names["components"], defaults={"registry": "nacos", "cache": "redis"})
        components["registry"] = "nacos"
    old_ver = str(info.get("scaffold_version") or "")
    new_ver = names["to_version"]
    base_dir = PROJECT_ROOT / VERSIONS_ROOT / f"v{old_ver}"
    if not base_dir.is_dir():
        sys.exit(f"缺少旧版模板基线 {base_dir}：请先在脚手架仓库生成 v{old_ver} 快照后重试")

    # 能力示例模块：沿用项目记录（旧版项目无 modules 字段视为不包含示例模块），--modules 可覆盖；
    # 未勾选模块的模板文件不参与升级（不新增），公共文件标记块同步移除（保持勾选一致性）
    modules = info.get("modules")
    if not isinstance(modules, list):
        modules = []
    if names["modules"] is not None:
        modules = _parse_modules(names["modules"])
    selected_set = set(modules)
    unselected = [m for m in MODULES if m not in selected_set]
    excluded_rels = set()
    for m in unselected:
        spec = MODULES[m]
        excluded_rels.update(f"{spec['service']}/{rel}" for rel in spec["files"])

    # 模板文件集合：旧版基线 ∪ 当前模板（相对路径，模板形态；排除未勾选模块文件）
    base_files = {str(p.relative_to(base_dir)).replace("\\", "/") for p in _iter_text_files(base_dir)}
    theirs_files = {
        str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for p in _iter_text_files(PROJECT_ROOT)
        if str(p.relative_to(PROJECT_ROOT)).replace("\\", "/") not in excluded_rels
    }

    updated, added, removed, conflicts, missing = [], [], [], [], []
    for rel in sorted(base_files | theirs_files):
        if rel in BUSINESS_ONLY_FILES:
            continue
        ours_path = project_dir / rel
        base_proj = _to_project_text(base_dir / rel, params, components)
        theirs_proj = _to_project_text(PROJECT_ROOT / rel, params, components)
        if theirs_proj is not None and unselected:
            # 未勾选模块的标记块从新版模板文本中移除（与 new 生成裁剪保持一致）
            theirs_proj = _remove_module_blocks(theirs_proj, unselected)
        ours = _read_text_optional(ours_path)
        action = _three_way_merge(base_proj, ours, theirs_proj)
        if action == "update":
            updated.append(rel)
            if not names["dry_run"]:
                ours_path.write_text(theirs_proj, encoding="utf-8", errors="surrogateescape")
        elif action == "add":
            added.append(rel)
            if not names["dry_run"]:
                ours_path.parent.mkdir(parents=True, exist_ok=True)
                ours_path.write_text(theirs_proj, encoding="utf-8", errors="surrogateescape")
        elif action == "remove":
            removed.append(rel)
            if not names["dry_run"]:
                ours_path.unlink()
        elif action == "conflict":
            conflicts.append(rel)
        elif action == "missing":
            missing.append(rel)

    if not names["dry_run"]:
        info["scaffold_version"] = new_ver
        info["components"] = components
        info["modules"] = modules
        if names["framework_version"]:
            info["framework_pin"] = names["framework_version"]
        (project_dir / SCAFFOLD_INFO_FILE).write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return {"updated": updated, "added": added, "removed": removed,
            "conflict": conflicts, "missing": missing}


def _project_components(info: Dict[str, object]) -> Dict[str, str]:
    """返回项目的组件选择记录（旧版项目无 components 字段时取默认，注册中心强制 Nacos、缓存默认 Redis）。"""
    base = resolve_components("all", defaults={"registry": "nacos", "cache": "redis"})
    comps = info.get("components")
    if isinstance(comps, dict):
        for name, impl in comps.items():
            if isinstance(impl, str) and impl:
                base[name] = impl
    base["registry"] = "nacos"
    return base


def _to_project_text(template_path: Path, params: Dict[str, object], components: Optional[Dict[str, str]] = None) -> Optional[str]:
    """读取模板文件内容并应用替换映射转成项目形态（None 表示文件不存在）。"""
    content = _read_text_optional(template_path)
    if content is None:
        return None
    text = _apply_new_replacements(content, params)
    # 按项目组件选择裁剪：移除未选组件标记块 + 替换实现（注册中心强制 Nacos 保留）
    if components:
        text = apply_components_to_text(text, components)
        # 能力依赖装配段（app.capabilities.enabled）按项目组件选择渲染
        text = apply_capabilities_to_text(text, components)
    return text


def _print_upgrade_summary(names: Dict[str, str], stats: Dict[str, List[str]]) -> None:
    """输出升级结果：已更新 / 新增 / 删除 / 冲突 / 缺失 清单与下一步。"""
    dry = "（dry-run 预览，未写盘）" if names["dry_run"] else ""
    print("=" * 60)
    print(f"脚手架升级完成 {dry}：{names['to_version']}")
    print(f"  已更新 {len(stats['updated'])} 个模板文件")
    for rel in stats["updated"]:
        print(f"    ~ {rel}")
    print(f"  新增 {len(stats['added'])} 个模板文件")
    for rel in stats["added"]:
        print(f"    + {rel}")
    print(f"  删除 {len(stats['removed'])} 个已废弃模板文件")
    for rel in stats["removed"]:
        print(f"    - {rel}")
    if stats["conflict"] or stats["missing"]:
        print(f"  !! 冲突 {len(stats['conflict'])} / 缺失 {len(stats['missing'])}，需手工处理（未被修改）")
        for rel in stats["conflict"]:
            print(f"    ! 冲突：{rel}（模板与业务均有改动，请手工合并）")
        for rel in stats["missing"]:
            print(f"    ? 缺失：{rel}（业务已删除该模板文件，请确认）")
    if names["framework_version"]:
        print("=" * 60)
        print(f"框架升级到 v{names['framework_version']}（已在 .scaffold-info.json 记录）：")
        print(f'  pip install "{FRAMEWORK_NAME}[{FRAMEWORK_EXTRAS}] @ git+{FRAMEWORK_GIT_URL}@v{names["framework_version"]}"')
    print("=" * 60)
    print("说明：")
    print("  - README.md 为业务文件，未自动同步，请手工比对模板。")
    print("  - 业务新增的模板外文件（含 new-service 生成的服务）不受影响；升级前建议先提交当前改动（git commit）。")


# ---------------------------------------------------------------------------
# 快照（snapshot）：发版时生成模板基线
# ---------------------------------------------------------------------------


def _snapshot_ignore(src: str, names: List[str]) -> set:
    """copytree ignore 回调：按相对路径精确排除脚手架专属内容与运行产物。

    说明：shutil.ignore_patterns 无法匹配含路径分隔符的子路径模式（如 docs/superpowers，
    Windows 路径分隔符与模式不兼容），故按相对路径逐项判断。
    """
    ignored = set()
    src_path = Path(src)
    for name in names:
        rel = str((src_path / name).relative_to(PROJECT_ROOT)).replace("\\", "/")
        if (
            name in IGNORED_DIRS
            or name in ("data", "minio_data")
            or name.endswith((".pyc", ".egg-info"))
            or _is_template_only(rel)
        ):
            ignored.add(name)
    return ignored


def _run_snapshot(version: str) -> Path:
    """将当前模板拷贝为 scaffold/versions/v<version>/ 基线（供 upgrade 作为旧版对照）。"""
    target = PROJECT_ROOT / VERSIONS_ROOT / f"v{version}"
    if target.exists() and any(target.iterdir()):
        sys.exit(f"快照目录已存在且非空：{target}")
    target.mkdir(parents=True)
    shutil.copytree(PROJECT_ROOT, target, ignore=_snapshot_ignore, dirs_exist_ok=True)
    return target


def _print_snapshot_summary(version: str, target: Path) -> None:
    """输出快照生成结果与发版指引。"""
    print("=" * 60)
    print(f"模板快照已生成：v{version} -> {target}")
    print("发版流程：")
    print(f"  1. 确认 scripts/new_project.py 的 TEMPLATE_VERSION 已更新为 {version}")
    print(f"  2. 提交并推送 scaffold/versions/v{version}/ 与脚本变更")
    print(f"  3. 打 git tag v{version}（可选，便于追溯）")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 新增服务（new-service）
# ---------------------------------------------------------------------------


def _run_new_service(names: Dict[str, str]) -> Path:
    """执行新增服务主流程：从 order-service 模板复制为 services/<name> 并重命名。

    说明：业务逻辑（接口语义 / 消息体字段 / 端口 / 网关路由）复制自订单模板，
    生成后需按新域调整（见输出提示与 docs/创建新项目.md）。
    """
    template_dir = PROJECT_ROOT / "services" / SERVICE_TEMPLATE_NAME
    target = PROJECT_ROOT / "services" / names["service_name"]
    if target.exists() and any(target.iterdir()):
        sys.exit(f"目标服务目录已存在且非空：{target}")
    shutil.copytree(
        template_dir,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    # 重命名包目录 src/order_service -> src/<package>
    old_pkg_dir = target / "src" / SERVICE_TEMPLATE_PKG
    if old_pkg_dir.exists():
        old_pkg_dir.rename(target / "src" / names["package"])
    # 重命名含 order 的文件名（order_controller.py -> <domain>_controller.py，与 import 引用一致）
    _rename_service_files(target, names)
    # 文本替换
    for path in _iter_text_files(target):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = _apply_service_replacements(content, names)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    # 按 --modules 勾选裁剪能力示例模块（仅 order-service 宿主模块，文件路径按新包名映射）
    _prune_modules_for_service(target, names)
    return target


def _prune_modules_for_service(target: Path, names: Dict[str, str]) -> None:
    """new-service 裁剪：仅处理 order-service 宿主模块（payment/state_machine），
    模块文件相对路径中的包名前缀按新包名映射后删除，并移除公共文件标记块。

    :param target: 目标服务目录（services/<name>）
    :param names: _derive_service_names 返回值（含 modules / package）
    """
    selected_set = set(names["modules"])
    unselected = [
        m for m in MODULES
        if m not in selected_set and MODULES[m]["service"] == SERVICE_TEMPLATE_NAME
    ]
    if not unselected:
        return
    for name in unselected:
        spec = MODULES[name]
        for rel in spec["files"]:
            # 文件路径映射：包名 order_service → 新包名；文件名独立词 order → 域名
            # （与 _rename_service_files 重命名规则一致，如 order_payment_service.py → <domain>_payment_service.py）
            mapped = rel.replace(SERVICE_TEMPLATE_PKG, names["package"])
            mapped = re.sub(r"(?<![A-Za-z0-9])order", names["domain"], mapped)
            if mapped.startswith("tests/"):
                # 模块测试文件两种形态：
                #   1) 未与业务测试冲突保持原名 test_<module>_module.py（当新域名 ≠ 模块名时）
                #   2) 冲突改名 test_<module>_module_test.py（当新域名 == 模块名时，业务测试占位原名）
                # 删除时排除业务测试占位名 test_<domain>_module.py，避免误删模板业务测试。
                stem = Path(mapped).stem
                biz_test_stem = f"test_{names['domain']}_module"
                candidates = []
                original = target / "tests" / f"{stem}.py"
                if original.exists() and stem != biz_test_stem:
                    candidates.append(original)
                renamed = target / "tests" / f"{stem}_module_test.py"
                if renamed.exists():
                    candidates.append(renamed)
                for p in candidates:
                    p.unlink()
            else:
                path = target / mapped
                if path.exists():
                    path.unlink()
    for path in _iter_text_files(target):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = _remove_module_blocks(content, unselected)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    _remove_empty_dirs(target)


def _rename_service_files(target: Path, names: Dict[str, str]) -> None:
    """按域名重命名含 order 的文件名（如 order_controller.py -> <domain>_controller.py）。

    文本替换会把 import 引用同步改写（order_controller -> <domain>_controller），
    文件名必须保持一致，否则生成后 import 断裂。
    目标名被占用时（模板自带能力模块测试，如 test_<domain>_module.py 与重命名后的
    test_order_module.py 冲突）：原模块测试更名为 <stem>_module_test.py，
    业务测试文件占位重命名目标（两者内容经文本替换后均为新域）。
    """
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        # 文件名中 "order" 前可为文件起始或下划线（如 order_controller.py / test_order_module.py）
        new_name = re.sub(r"(?<![A-Za-z0-9])order", names["domain"], path.name)
        if new_name != path.name:
            new_path = path.with_name(new_name)
            if new_path.exists():
                # 目标被模块测试占用：模块测试更名为 <stem>_module_test.py，业务文件占位
                new_path.rename(new_path.with_name(new_path.stem + "_module_test.py"))
            path.rename(new_path)


# ---------------------------------------------------------------------------
# 输出与入口
# ---------------------------------------------------------------------------


def _print_new_summary(names: Dict[str, str], root: Path) -> None:
    """输出整体派生结果（含组件选择与自研骨架）与下一步指引。"""
    git_hint = "（已执行 git init + 首次提交）" if names["git_init"] else ""
    extras = render_extras(names["components"])
    components = names["components"]
    enabled = [name for name in COMPONENTS if components.get(name) not in (None, "off")]
    print("=" * 60)
    print(f"新项目已生成：{names['project_name']}  {git_hint}")
    print(f"  目录：{root}")
    print(f"  项目名：{names['project_name']}")
    print(f"  服务分库：{names['db_name']}_user / {names['db_name']}_order")
    print(f"  版本：{names['version']}")
    print(f"  启用组件（{len(enabled)}）：{'、'.join(enabled)}")
    modules = names.get("modules") or []
    print(f"  能力示例模块：{'、'.join(modules) if modules else '无'}")
    custom_spis = names.get("custom_spis") or []
    if custom_spis:
        print(f"  自研 SPI 骨架（各服务 src/<pkg>/spi/）：{'、'.join(custom_spis)}")
    print("=" * 60)
    print("下一步：")
    print(f"  1. cd {root}")
    print('  2. python -m venv .venv && .venv\\Scripts\\activate')
    print(f'  3. pip install "flower-web-infrastructure[{extras}] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"')
    print('  4. pip install -e ".[dev]"')
    print("  5. cp .env.example .env 并填写敏感配置")
    print("  6. docker compose up -d（外部依赖）")
    print("  7. alembic -c services/user-service/alembic.ini upgrade head && alembic -c services/order-service/alembic.ini upgrade head")
    print("  8. 按 README 启动三个服务")


def _print_service_summary(names: Dict[str, str], target: Path) -> None:
    """输出新增服务结果与手工调整清单。"""
    print("=" * 60)
    print(f"新服务已生成：{names['service_name']}")
    print(f"  目录：{target}")
    print(f"  Python 包：src/{names['package']}")
    print(f"  域名（类/常量/表前缀）：{names['pascal']} / {names['upper']} / t_{names['domain']}")
    print(f"  数据库：flower_{names['domain']}")
    print("=" * 60)
    print("生成后需手工调整（模板复制自 order-service，业务语义按新域改造）：")
    print(f"  1. 端口：src/{names['package']}/main.py 的 SERVICE_PORT 与 Dockerfile EXPOSE（默认复制为 8002，请改为空闲端口）")
    print("  2. 业务逻辑：接口 / 消息体字段 / 事件 Topic 按新域调整（api / service / mq / schema / constants）")
    print("  3. 数据库：db/init 新增基线 SQL（flower_<domain> 库），或直接编辑本服务 alembic/versions 迁移")
    print("  4. 网关路由：在 services/gateway/application.yml 的 app.gateway.routes 追加新服务路由")
    print(f"  5. 注册中心：服务启动后自动注册为 {names['service_name']}（application.yml app.name）")
    print(f"  6. 单元测试：运行 pytest services/{names['service_name']}/tests 验证复制后的模板测试")


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    args = _parse_args(argv)
    if args.command == "new":
        names = _derive_new_names(args)
        root = _run_new(names)
        _print_new_summary(names, root)
    elif args.command == "new-service":
        names = _derive_service_names(args)
        target = _run_new_service(names)
        _print_service_summary(names, target)
    elif args.command == "upgrade":
        names = _derive_upgrade_args(args)
        stats = _run_upgrade(names)
        _print_upgrade_summary(names, stats)
    elif args.command == "snapshot":
        names = _derive_snapshot_args(args)
        target = _run_snapshot(names["version"])
        _print_snapshot_summary(names["version"], target)
    else:
        sys.exit("未知子命令，仅支持 new / new-service / upgrade / snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
