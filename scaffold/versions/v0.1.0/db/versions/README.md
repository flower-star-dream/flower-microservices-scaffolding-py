# 增量脚本目录（db/versions）

数据库结构 / 数据增量变更脚本（规范 §13.2）：

- 命名：`V{版本号}-{模块}-{变更描述}-ddl.sql` / `-dml.sql`，同一变更的 DDL 与 DML 必须同版本成对提供。
- 基线不可回改：`db/init/` 只随大版本基线重建；已发布的表结构变更一律通过新增版本脚本演进，禁止修改既有基线脚本。
- DDL/DML 配套：涉及存量数据语义变更（回填 / 清洗 / 转换）必须提供幂等的 DML（带 `WHERE` 过滤已完成处理的行）。
- 服务分库：user-service 对应 `flower_user`（库内表前缀 t_）、order-service 对应 `flower_order`，增量脚本同样按库拆分。
- 脚本头统一携带 `@Author / @Date / @Description`，与代码注释规范一致。
- **Alembic 为权威变更管理工具**（各服务 `alembic/versions/`），本目录手工 SQL 保留供 DBA / 非 Python 环境参考。
