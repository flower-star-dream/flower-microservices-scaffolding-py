"""
新建项目 / 新增服务脚本测试（test_new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 覆盖 scripts/new_project.py 的参数派生、文本替换（含运行时实例属性保护）、
              new 整体派生端到端生成、new-service 新增服务重命名、upgrade 升级三路合并、
              snapshot 快照排除。用 importlib 加载脚本模块，不依赖脚手架仓库完整内容，测试轻量且隔离。
"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

# 加载脚本模块（scripts/ 不在包内，用 importlib 按路径加载）
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "new_project.py"
_spec = importlib.util.spec_from_file_location("new_project", _SCRIPT_PATH)
np = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(np)


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """构造迷你 Monorepo 模板（含需替换标识与需保护的运行时实例属性）。"""
    root = tmp_path / "mini-repo"
    root.mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "services" / "order-service" / "src" / "order_service").mkdir(parents=True)
    (root / "services" / "order-service" / "src" / "order_service" / "api" / "v1").mkdir(parents=True)
    (root / "services" / "order-service" / "tests").mkdir(parents=True)

    (root / "pyproject.toml").write_text(
        'name = "flower-microservices-scaffolding"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / ".env.example").write_text(
        "USER_DATABASE_URL=.../flower_user\nORDER_DATABASE_URL=.../flower_order\n", encoding="utf-8"
    )
    (root / "services" / "order-service" / "application.yml").write_text(
        "app:\n  name: order-service\n  db:\n    database: ${APP_DB_ORDER_MYSQL_DATABASE:flower_order}\n",
        encoding="utf-8",
    )
    (root / "services" / "order-service" / "src" / "order_service" / "main.py").write_text(
        "SERVICE_NAME = 'order-service'\n"
        "from order_service.api.v1.order_controller import router\n"
        "app.include_router(router)\n"
        "# <<<MODULE:payment>>>\n"
        "from order_service.payment.order_payment_service import OrderPaymentService\n"
        "app.state.payment_dispatcher = None\n"
        "# <<</MODULE:payment>>>\n"
        "# <<<MODULE:state_machine>>>\n"
        "from order_service.state.order_state_machine import OrderEvent\n"
        "# <<</MODULE:state_machine>>>\n"
        "app.state.db  # 运行时实例属性，不能被替换\n",
        encoding="utf-8",
    )
    (root / "services" / "order-service" / "src" / "order_service" / "model.py").write_text(
        "class OrderModel:\n"
        "    __tablename__ = 't_order'\n"
        "    ORDER_STATUS_CREATED = 1\n"
        "    TOPIC = 'order.created'\n",
        encoding="utf-8",
    )
    (root / "services" / "order-service" / "src" / "order_service" / "api" / "v1" / "order_controller.py").write_text(
        "from order_service.model import OrderModel\n", encoding="utf-8"
    )
    (root / "services" / "order-service" / "tests" / "test_order_module.py").write_text(
        "from order_service.model import OrderModel\n", encoding="utf-8"
    )
    # 能力示例模块文件（供 --modules 裁剪测试）
    (root / "services" / "order-service" / "src" / "order_service" / "payment").mkdir(parents=True)
    (root / "services" / "order-service" / "src" / "order_service" / "payment" / "order_payment_service.py").write_text(
        "class OrderPaymentService:\n    pass\n", encoding="utf-8"
    )
    (root / "services" / "order-service" / "src" / "order_service" / "state").mkdir(parents=True)
    (root / "services" / "order-service" / "src" / "order_service" / "state" / "order_state_machine.py").write_text(
        "class OrderEvent:\n    PAY = 'pay'\n", encoding="utf-8"
    )
    (root / "services" / "order-service" / "tests" / "test_payment_module.py").write_text(
        "assert True\n", encoding="utf-8"
    )
    (root / "services" / "order-service" / "tests" / "test_state_machine_module.py").write_text(
        "assert True\n", encoding="utf-8"
    )
    (root / "docs" / "使用说明.md").write_text(
        "参考 flower-microservices-scaffolding 脚手架，库名 flower_user / flower_order\n",
        encoding="utf-8",
    )
    (root / "scripts" / "keep_me.txt").write_text("scripts 目录应被整体删除\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# flower 微服务脚手架（flower-microservices-scaffolding-py）\n", encoding="utf-8"
    )
    (root / "tests" / "test_new_project.py").write_text("assert False  # CLI 测试，业务项目不需要\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# 参数派生
# ---------------------------------------------------------------------------
class TestDeriveNames:
    """参数派生与校验。"""

    def test_new_derives_db_names(self):
        names = np._derive_new_names(np._parse_args(["new", "my-project"]))
        assert names["project_name"] == "my-project"
        assert names["repo_name"] == "my-project"
        assert names["db_name"] == "my_project"
        assert names["version"] == "0.1.0"

    def test_new_invalid_project_name_raises(self):
        with pytest.raises(SystemExit):
            np._derive_new_names(np._parse_args(["new", "Bad..Name"]))

    def test_service_derives_domain(self):
        names = np._derive_service_names(np._parse_args(["new-service", "payment-service"]))
        assert names["service_name"] == "payment-service"
        assert names["package"] == "payment_service"
        assert names["domain"] == "payment"
        assert names["pascal"] == "Payment"
        assert names["upper"] == "PAYMENT"

    def test_service_without_suffix_uses_name_as_domain(self):
        names = np._derive_service_names(np._parse_args(["new-service", "inventory"]))
        assert names["domain"] == "inventory"
        assert names["pascal"] == "Inventory"
        assert names["upper"] == "INVENTORY"


# ---------------------------------------------------------------------------
# 文本替换
# ---------------------------------------------------------------------------
class TestTextReplacements:
    """文本替换规则。"""

    def test_new_replacements_basic(self):
        names = np._derive_new_names(np._parse_args(["new", "my-project"]))
        text = (
            'name = "flower-microservices-scaffolding"\n'
            "org = flower-star-dream/flower-microservices-scaffolding-py\n"
            "db = flower_user / flower_order\n"
        )
        updated = np._apply_new_replacements(text, names)
        assert "flower-microservices-scaffolding" not in updated
        assert "flower-microservices-scaffolding-py" not in updated
        assert "flower_user" not in updated
        assert "flower_order" not in updated
        assert "my-project" in updated
        assert "my_project_user" in updated
        assert "my_project_order" in updated

    def test_service_replacements(self):
        names = np._derive_service_names(np._parse_args(["new-service", "payment-service"]))
        text = (
            "SERVICE_NAME = 'order-service'\n"
            "from order_service.model import OrderModel\n"
            "class OrderModel:\n"
            "    __tablename__ = 't_order'\n"
            "    ORDER_STATUS_CREATED = 1\n"
            "    TOPIC = 'order.created'\n"
            "    body = {'order_id': '1', 'order_no': 'N1'}\n"
            "    .order_by(Model.id.desc())\n"
            "flower_order\n"
        )
        updated = np._apply_service_replacements(text, names)
        assert "order-service" not in updated
        assert "order_service" not in updated
        assert "t_order" not in updated
        assert "flower_order" not in updated
        assert "SERVICE_NAME = 'payment-service'" in updated
        assert "from payment_service.model import PaymentModel" in updated
        assert "class PaymentModel" in updated
        assert "__tablename__ = 't_payment'" in updated
        assert "PAYMENT_STATUS_CREATED" in updated
        assert "TOPIC = 'payment.created'" in updated
        assert "body = {'payment_id': '1', 'payment_no': 'N1'}" in updated
        assert "flower_payment" in updated
        # SQLAlchemy order_by 方法保留（不应被误伤为 payment_by）
        assert ".order_by(Model.id.desc())" in updated
        assert "payment_by" not in updated

    def test_service_app_instance_attrs_protected(self):
        """app.state / app.include_router 等运行时实例属性必须原样保留。"""
        names = np._derive_service_names(np._parse_args(["new-service", "payment-service"]))
        text = "from order_service.api.v1 import router\napp.include_router(router)\nx = app.state.db\n"
        updated = np._apply_service_replacements(text, names)
        assert "from payment_service.api.v1 import router" in updated
        assert "app.include_router(router)" in updated
        assert "app.state.db" in updated
        assert "@@FLOWER_APP_INSTANCE" not in updated


# ---------------------------------------------------------------------------
# 集成测试：整体派生（new）
# ---------------------------------------------------------------------------
class TestNewEndToEnd:
    """从迷你 Monorepo 复制生成新项目并校验替换结果。"""

    def _generate(self, monkeypatch, mini_repo: Path, tmp_path: Path, *extra_args: str) -> Path:
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target), *extra_args])
        return target

    def test_generate_basic(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        target = self._generate(monkeypatch, mini_repo, tmp_path)
        # 项目名 / 分库名替换
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "my-project"' in pyproject
        env = (target / ".env.example").read_text(encoding="utf-8")
        assert "my_project_user" in env
        assert "my_project_order" in env
        assert "flower_user" not in env
        assert "flower_order" not in env
        # 服务配置替换（order-service 保持服务名，库名替换）
        yml = (target / "services" / "order-service" / "application.yml").read_text(encoding="utf-8")
        assert "name: order-service" in yml
        assert "my_project_order" in yml
        # README 已覆盖、scripts 已删除、CLI 测试已排除
        readme = (target / "README.md").read_text(encoding="utf-8")
        assert readme.startswith("# my-project")
        assert not (target / "scripts").exists()
        assert not (target / "tests" / "test_new_project.py").exists()
        # 升级元数据已写入（脚手架类型 / 版本 / 替换参数）
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["scaffold"] == "flower-microservices-scaffolding-py"
        assert info["scaffold_version"] == "0.1.0"
        assert info["params"]["db_name"] == "my_project"
        # 源模板目录保持不动（--dir 模式只读复制）
        assert (mini_repo / "scripts" / "keep_me.txt").exists()


# ---------------------------------------------------------------------------
# 集成测试：新增服务（new-service）
# ---------------------------------------------------------------------------
class TestNewServiceEndToEnd:
    """从迷你 order-service 模板复制生成新服务并校验重命名。"""

    def _generate(self, monkeypatch, mini_repo: Path) -> Path:
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        np.main(["new-service", "payment-service"])
        return mini_repo / "services" / "payment-service"

    def test_generate_service(self, monkeypatch, mini_repo: Path):
        target = self._generate(monkeypatch, mini_repo)
        # 目录 / 包目录重命名
        assert target.exists()
        assert (target / "src" / "payment_service").exists()
        assert not (target / "src" / "order_service").exists()
        # 模板服务保持不动
        assert (mini_repo / "services" / "order-service" / "src" / "order_service").exists()
        # 主代码替换（服务名 / 包名 / 类名 / 常量 / 表名 / 控制器文件名与引用一致）
        main_py = (target / "src" / "payment_service" / "main.py").read_text(encoding="utf-8")
        assert "SERVICE_NAME = 'payment-service'" in main_py
        assert "from payment_service.api.v1.payment_controller import router" in main_py
        assert "app.include_router(router)" in main_py  # 实例属性保留
        assert (target / "src" / "payment_service" / "api" / "v1" / "payment_controller.py").exists()
        model_py = (target / "src" / "payment_service" / "model.py").read_text(encoding="utf-8")
        assert "class PaymentModel" in model_py
        assert "__tablename__ = 't_payment'" in model_py
        assert "PAYMENT_STATUS_CREATED" in model_py
        assert "TOPIC = 'payment.created'" in model_py
        # 测试文件重命名且内容替换
        assert (target / "tests" / "test_payment_module.py").exists()
        test_py = (target / "tests" / "test_payment_module.py").read_text(encoding="utf-8")
        assert "from payment_service.model import PaymentModel" in test_py


def test_module_importable():
    """脚本可独立加载（语法与导入无异常）。"""
    assert callable(np.main)
    assert callable(np._apply_new_replacements)
    assert callable(np._apply_service_replacements)


# ---------------------------------------------------------------------------
# 集成测试：升级（upgrade）
# ---------------------------------------------------------------------------
class TestUpgrade:
    """生成项目 → 模拟新版模板 → 三路合并升级（微服务：服务目录保留，无 src/app 重命名）。"""

    def _generate_project(self, monkeypatch, mini_repo: Path, tmp_path: Path) -> Path:
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target)])
        return target

    def _make_base_snapshot(self, mini_repo: Path) -> Path:
        """把当前迷你仓库拷贝为 base 快照（模拟脚手架发版时的 v0.1.0 基线）。"""
        base = mini_repo / "scaffold" / "versions" / "v0.1.0"
        shutil.copytree(mini_repo, base, ignore=shutil.ignore_patterns("scaffold", "scripts"))
        return base

    def test_upgrade_three_way(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        self._make_base_snapshot(mini_repo)
        target = self._generate_project(monkeypatch, mini_repo, tmp_path)

        # 新版模板变更（theirs）
        env_tmpl = mini_repo / ".env.example"
        env_tmpl.write_text(env_tmpl.read_text(encoding="utf-8") + "NEW_FLAG=1\n", encoding="utf-8")
        yml_tmpl = mini_repo / "services" / "order-service" / "application.yml"
        yml_tmpl.write_text(yml_tmpl.read_text(encoding="utf-8") + "template: new\n", encoding="utf-8")
        (mini_repo / "new_file.md").write_text("new template doc\n", encoding="utf-8")
        # 业务改动 order-service/application.yml（ours 与 base/theirs 均不同 → conflict）
        yml_proj = target / "services" / "order-service" / "application.yml"
        yml_proj.write_text(yml_proj.read_text(encoding="utf-8") + "biz: xxx\n", encoding="utf-8")

        # dry-run：预览不写盘
        stats = np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target), "--dry-run"])))
        assert ".env.example" in stats["updated"]
        assert "new_file.md" in stats["added"]
        assert "services/order-service/application.yml" in stats["conflict"]
        assert "NEW_FLAG" not in (target / ".env.example").read_text(encoding="utf-8")

        # 实跑升级
        stats = np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target)])))
        assert ".env.example" in stats["updated"]
        assert "services/order-service/application.yml" in stats["conflict"]
        assert "NEW_FLAG=1" in (target / ".env.example").read_text(encoding="utf-8")
        assert (target / "new_file.md").exists()
        # 冲突文件未被覆盖（保留业务改动）
        yml_now = (target / "services" / "order-service" / "application.yml").read_text(encoding="utf-8")
        assert "biz: xxx" in yml_now
        assert "template: new" not in yml_now
        # 脚手架版本已更新
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["scaffold_version"] == "0.1.0"

    def test_upgrade_framework_version(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        """--framework-version 更新 .scaffold-info.json 的 framework_pin。"""
        self._make_base_snapshot(mini_repo)
        target = self._generate_project(monkeypatch, mini_repo, tmp_path)
        np._run_upgrade(np._derive_upgrade_args(
            np._parse_args(["upgrade", str(target), "--framework-version", "0.2.0"])
        ))
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["framework_pin"] == "0.2.0"

    def test_upgrade_missing_scaffold_info(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        """非脚手架生成项目（缺 .scaffold-info.json）应报错。"""
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        with pytest.raises(SystemExit):
            np.main(["upgrade", str(plain)])

    def test_upgrade_modules_preserved(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        """upgrade 保持项目模块勾选：--modules none 生成的项目升级后不新增模块文件、标记块不残留。"""
        self._make_base_snapshot(mini_repo)
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target), "--modules", "none"])

        # 模拟新版模板对模块文件的修改（theirs 已存在模块文件）
        module_py = mini_repo / "services" / "order-service" / "src" / "order_service" / "payment" / "order_payment_service.py"
        module_py.write_text("class OrderPaymentService:\n    pass\n", encoding="utf-8")
        # 升级：未勾选模块（payment/state_machine/jwt_spi/social_login）不进入项目
        np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target)])))
        assert not (target / "services" / "order-service" / "src" / "order_service" / "payment").exists()
        assert not (target / "services" / "order-service" / "src" / "order_service" / "state").exists()
        main_py = (target / "services" / "order-service" / "src" / "order_service" / "main.py").read_text(encoding="utf-8")
        assert "<<<MODULE" not in main_py
        # .scaffold-info.json 保留模块勾选记录
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["modules"] == []


# ---------------------------------------------------------------------------
# 集成测试：快照（snapshot）
# ---------------------------------------------------------------------------
class TestSnapshot:
    """模板快照生成与脚手架专属内容排除。"""

    def test_snapshot_excludes_template_only(self, monkeypatch, mini_repo: Path):
        (mini_repo / "docs" / "创建新项目.md").write_text("howto\n", encoding="utf-8")
        (mini_repo / "tests" / "test_new_project.py").write_text("x\n", encoding="utf-8")
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = np._run_snapshot("0.1.0")
        assert (target / "pyproject.toml").exists()
        assert (target / "services" / "order-service" / "application.yml").exists()
        assert (target / "docs" / "使用说明.md").exists()
        # 脚手架专属内容 / 脚本 / 快照自身均被排除
        assert not (target / "scripts").exists()
        assert not (target / "docs" / "创建新项目.md").exists()
        assert not (target / "tests" / "test_new_project.py").exists()


# ---------------------------------------------------------------------------
# 能力示例模块（--modules 解析与裁剪）
# ---------------------------------------------------------------------------
class TestModules:
    """--modules 参数解析、依赖校验与生成裁剪（文件删除 + 标记块移除 + 空目录清理）。"""

    def test_parse_modules_all_none(self):
        assert np._parse_modules("all") == list(np.MODULES)
        assert np._parse_modules("none") == []

    def test_parse_modules_list(self):
        modules = np._parse_modules("payment,state_machine")
        assert modules == ["payment", "state_machine"]

    def test_parse_modules_unknown_raises(self):
        with pytest.raises(SystemExit):
            np._parse_modules("foo")

    def test_parse_modules_dependency_raises(self):
        """payment 依赖 state_machine：只勾 payment 应报错。"""
        with pytest.raises(SystemExit):
            np._parse_modules("payment")

    def test_remove_marker_block(self):
        text = (
            "keep1\n"
            "# <<<MODULE:payment>>>\n"
            "drop me\n"
            "# <<</MODULE:payment>>>\n"
            "keep2\n"
            "# <<<MODULE:state_machine>>>\n"
            "drop too\n"
            "# <<</MODULE:state_machine>>>\n"
        )
        updated = np._remove_module_blocks(text, ["payment", "state_machine"])
        assert "keep1\nkeep2\n" == updated
        assert "<<<MODULE" not in updated

    def test_new_none_prunes_modules(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        """new --modules none：删除模块文件 + 移除 main.py 标记块 + 清理空目录 + 记录 modules。"""
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target), "--modules", "none"])

        # 模块专属文件已删除（含空包目录清理）
        assert not (target / "services" / "order-service" / "src" / "order_service" / "payment").exists()
        assert not (target / "services" / "order-service" / "src" / "order_service" / "state").exists()
        assert not (target / "services" / "order-service" / "tests" / "test_payment_module.py").exists()
        assert not (target / "services" / "order-service" / "tests" / "test_state_machine_module.py").exists()
        # main.py 标记块已移除，其余代码保留
        main_py = (target / "services" / "order-service" / "src" / "order_service" / "main.py").read_text(encoding="utf-8")
        assert "<<<MODULE" not in main_py
        assert "payment_dispatcher" not in main_py
        assert "OrderPaymentService" not in main_py
        assert "app.state.db" in main_py
        # .scaffold-info.json 记录模块勾选
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["modules"] == []

    def test_new_custom_modules_keeps_selected(self, monkeypatch, mini_repo: Path, tmp_path: Path):
        """new --modules state_machine：仅保留状态机（payment 因未勾选被裁剪）。"""
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target), "--modules", "state_machine"])

        assert not (target / "services" / "order-service" / "src" / "order_service" / "payment").exists()
        assert (target / "services" / "order-service" / "src" / "order_service" / "state" / "order_state_machine.py").exists()
        main_py = (target / "services" / "order-service" / "src" / "order_service" / "main.py").read_text(encoding="utf-8")
        assert "payment_dispatcher" not in main_py
        assert "OrderEvent" in main_py  # state_machine 标记块保留
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["modules"] == ["state_machine"]

    def test_new_service_none_prunes(self, monkeypatch, mini_repo: Path):
        """new-service --modules none：payment/state 模块文件删除 + main.py 标记块移除（路径按新包名/域名映射）。
        模板业务测试 test_order_module.py 重命名占位 test_payment_module.py（保留），
        模块测试（冲突改名 test_payment_module_test.py / 原名 test_state_machine_module.py）删除。"""
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        np.main(["new-service", "payment-service", "--modules", "none"])
        target = mini_repo / "services" / "payment-service"

        assert not (target / "src" / "payment_service" / "payment").exists()
        assert not (target / "src" / "payment_service" / "state").exists()
        # 模块测试已删除（冲突改名产物 + state 模块测试）
        assert not (target / "tests" / "test_payment_module_test.py").exists()
        assert not (target / "tests" / "test_state_machine_module.py").exists()
        # 模板业务测试保留（重命名为 test_payment_module.py）
        assert (target / "tests" / "test_payment_module.py").exists()
        main_py = (target / "src" / "payment_service" / "main.py").read_text(encoding="utf-8")
        assert "<<<MODULE" not in main_py
        assert "payment_dispatcher" not in main_py

    def test_prompt_modules_interactive(self, monkeypatch):
        """交互式询问：输入 y 才勾选（默认不选）。"""
        monkeypatch.setattr("builtins.input", lambda prompt: "y\n" if "支付" in prompt else "\n")
        selected = np._prompt_modules()
        assert selected == ["payment"]


# ---------------------------------------------------------------------------
# 单元测试：组件选择（微服务：注册中心强制 Nacos、禁止内存实现）
# ---------------------------------------------------------------------------
class TestMicroComponents:
    """微服务组件选择：registry 强制 Nacos、--components 解析、标记块裁剪与骨架宿主。"""

    def test_registry_forced_nacos(self):
        """微服务派生：注册中心强制 nacos（内存实现被禁止）、缓存默认 redis（docker-compose 提供）。"""
        names = np._derive_new_names(np._parse_args(["new", "my-project"]))
        assert names["components"]["registry"] == "nacos"
        assert names["components"]["cache"] == "redis"
        ids = [opt["id"] for opt in np.COMPONENTS["registry"]["options"]]
        assert "memory" not in ids

    def test_parse_components_defaults_nacos(self):
        """微服务形态默认：未显式指定的组件取默认（注册中心 nacos、缓存 redis）。"""
        comps = np.resolve_components("cache:redis", defaults={"registry": "nacos", "cache": "redis"})
        assert comps["cache"] == "redis"
        assert comps["registry"] == "nacos"
        comps = np.resolve_components(None, defaults={"registry": "nacos", "cache": "redis"})
        assert comps["registry"] == "nacos"
        assert comps["cache"] == "redis"   # 微服务缓存默认实现必须是 redis
        # 显式 cache:memory 仍允许（默认非强制）
        comps = np.resolve_components("cache:memory", defaults={"registry": "nacos", "cache": "redis"})
        assert comps["cache"] == "memory"

    def test_apply_components_to_text_service_yml(self):
        """服务 application.yml 组件块：块内 type 替换（redis->memory）与整块保留（registry 强制）。"""
        text = (
            "app:\n"
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: redis\n"
            "  # <<</COMPONENT:cache>>>\n"
            "  # <<<COMPONENT:mq>>>\n"
            "  mq:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:mq>>>\n"
            "  # <<<COMPONENT:registry>>>\n"
            "  registry:\n"
            "    type: nacos\n"
            "  # <<</COMPONENT:registry>>>\n"
        )
        comps = np.resolve_components("cache:memory,mq:rocketmq", defaults={"registry": "nacos", "cache": "redis"})
        updated = np.apply_components_to_text(text, comps)
        assert "cache:\n    type: memory" in updated
        assert "mq:\n    type: rocketmq" in updated
        assert "type: nacos" in updated          # registry 强制 nacos 保留
        assert "COMPONENT:registry" in updated

    def test_apply_components_to_text_off_removes_block(self):
        """cache=off：组件块整块移除（服务回落框架默认内存缓存）。"""
        text = (
            "app:\n"
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: redis\n"
            "  # <<</COMPONENT:cache>>>\n"
        )
        comps = np.resolve_components("cache:off", defaults={"registry": "nacos", "cache": "redis"})
        updated = np.apply_components_to_text(text, comps)
        assert "COMPONENT:cache" not in updated
        assert "cache:" not in updated

    def test_render_capabilities(self):
        """能力装配清单：默认最小化（必选 db + 形态覆盖 registry/cache），显式选择后能力收敛。"""
        # 非交互默认最小化：仅 db/cache/registry（cache/registry 为微服务形态默认）
        comps = np.resolve_components(None, defaults={"registry": "nacos", "cache": "redis"})
        assert np.render_capabilities(comps) == ["db", "cache", "registry"]
        # 显式选择支付等业务组件后能力追加（未提及组件默认 off，不再全量给出）
        comps = np.resolve_components(
            "payment:wechat,mq:rocketmq", defaults={"registry": "nacos", "cache": "redis"}
        )
        assert np.render_capabilities(comps) == ["db", "cache", "mq", "registry", "pay"]
        # 显式关闭业务组件后能力收敛
        comps = np.resolve_components("payment:off,jwt:off,social:off,security:off", defaults={"registry": "nacos", "cache": "redis"})
        assert "pay" not in np.render_capabilities(comps)
        assert "authn" not in np.render_capabilities(comps)

    def test_apply_capabilities_to_text(self):
        """能力装配段渲染：服务模板 enabled: [] 替换为项目能力清单（按最小化默认 + 显式选择）。"""
        text = "app:\n  capabilities:\n    enabled: []\n  cache:\n    type: redis\n"
        comps = np.resolve_components("payment:wechat", defaults={"registry": "nacos", "cache": "redis"})
        updated = np.apply_capabilities_to_text(text, comps)
        assert 'enabled: ["db", "cache", "registry", "pay"]' in updated

    def test_generate_spi_skeleton_host_service(self, mini_repo: Path, monkeypatch, tmp_path: Path):
        """new --components=cache:custom,mq:custom：骨架生成到宿主服务（cache->user-service / mq->order-service）。"""
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main([
            "new", "my-project", "--dir", str(target),
            "--components", "cache:custom,mq:custom", "--modules", "none",
        ])
        cache_sk = target / "services" / "user-service" / "src" / "user_service" / "spi" / "cache_custom.py"
        mq_sk = target / "services" / "order-service" / "src" / "order_service" / "spi" / "mq_custom.py"
        assert cache_sk.exists()
        assert mq_sk.exists()
        assert "CacheBackendInterface" in cache_sk.read_text(encoding="utf-8")
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["components"]["cache"] == "custom"
        assert info["components"]["registry"] == "nacos"

    def test_generate_db_strategy_skeleton_host_service(self, mini_repo: Path, monkeypatch, tmp_path: Path):
        """new --components=db:orm_custom：骨架生成到宿主服务 user-service（db_orm_custom.py），
        且各服务 db 块 type 保持 mysql（策略型实现不写 type）。"""
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_repo)
        target = tmp_path / "generated"
        np.main([
            "new", "my-project", "--dir", str(target),
            "--components", "db:orm_custom", "--modules", "none",
        ])
        sk = target / "services" / "user-service" / "src" / "user_service" / "spi" / "db_orm_custom.py"
        assert sk.exists()
        assert "OrmCustomDatabaseSession" in sk.read_text(encoding="utf-8")
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["components"]["db"] == "orm_custom"
