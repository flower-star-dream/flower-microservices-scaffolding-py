-- =====================================================================
-- 订单库基线 DDL（脚手架示例，脚本规范 §13.2；服务分库：order-service -> flower_order）
-- @Author: 花海
-- @Date: 2026/08/16
-- @Description: 订单库 flower_order 与订单表 t_order 基线结构（等价 services/order-service/alembic/versions/0001_order_init.py）。
--               订单服务创建订单时经注册中心发现并调用用户服务校验用户（演示服务间远程调用）。
-- =====================================================================

CREATE DATABASE IF NOT EXISTS flower_order DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE flower_order;

CREATE TABLE IF NOT EXISTS t_order (
    id         BIGINT        NOT NULL AUTO_INCREMENT COMMENT '主键',
    order_no   VARCHAR(64)   NOT NULL COMMENT '订单号（业务唯一）',
    user_id    BIGINT        NOT NULL COMMENT '下单用户 ID（关联 user-service 的用户）',
    amount     DECIMAL(12,2) NOT NULL COMMENT '订单金额',
    status     TINYINT       NOT NULL DEFAULT 1 COMMENT '状态：1 已创建 / 2 已支付 / 3 已发货 / 4 已完成 / 5 已取消',
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME      NULL COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_no (order_no),
    KEY idx_user_id (user_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '订单表';
