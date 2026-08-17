# 模板快照目录（scaffold/versions）

> @Author: 花海
> @Date: 2026/08/16
> @Description: 存放微服务脚手架各版本模板基线快照，供 scripts/new_project.py 的 upgrade 命令作为
>               三路合并（diff+patch）的旧版对照（base）。快照保留模板原始标识（未做项目替换）。

## 目录结构

```
scaffold/versions/
├── v0.1.0/     # 各版本模板快照（完整脚手架内容，排除 scripts/、scaffold/、运行产物）
└── README.md   # 本说明
```

## 发版流程（脚手架维护者）

1. 在 `scripts/new_project.py` 中更新 `TEMPLATE_VERSION` 为新版本号；
2. 在脚手架仓库根执行 `python scripts/new_project.py snapshot <新版本>`（如 `0.2.0`）；
   - 快照自动排除：`scripts/`（CLI）、`scaffold/`（快照自身）、`docs/superpowers/`、
     `tests/test_new_project.py`、`docs/创建新项目.md`、`.venv`/`.git`/`__pycache__`、
     `*.egg-info`、`data/`、`minio_data/` 等运行产物；
3. 提交并推送 `scaffold/versions/v<新版本>/` 与脚本变更，可选打 `git tag v<新版本>`。

## 使用说明

- **不要手动修改** 已发布的快照目录（它是历史基线，upgrade 依赖其与生成时模板一致）；
- 已生成项目升级：`python scripts/new_project.py upgrade <project-dir>`（详见 docs/创建新项目.md 第 4 节）；
- `new` 派生新项目时快照目录不会复制进业务项目。
