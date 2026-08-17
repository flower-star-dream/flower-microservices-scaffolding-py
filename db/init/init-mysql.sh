#!/bin/sh
# =====================================================================
# flower-microservices-scaffolding 数据库初始化脚本（docker-entrypoint-initdb.d）
# @Author: 花海
# @Date: 2026/08/16
# @Description: MySQL 容器首次初始化时由官方 entrypoint 自动执行（source 方式，无需可执行位）：
#               依次执行 ddl 目录全部基线 DDL、dml 目录全部基线 DML（按文件名排序）。
#               脚本内 USE <database> 自带库切换（服务分库：flower_user / flower_order）。
# =====================================================================
set -e

for f in /docker-entrypoint-initdb.d/ddl/*.sql; do
  echo "==> 执行基线 DDL: $f"
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" < "$f"
done

for f in /docker-entrypoint-initdb.d/dml/*.sql; do
  echo "==> 执行基线 DML: $f"
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" < "$f"
done

echo "==> 数据库基线初始化完成"
