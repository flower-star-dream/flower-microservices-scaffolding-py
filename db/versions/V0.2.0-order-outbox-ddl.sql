-- =====================================================================
-- V0.2.0-order-outbox-ddl.sql：order-service Outbox 本地事务表增量（规范 §13.2）
-- @Author: 花海
-- @Date: 2026/08/16 20:00
-- @Description: 订单事件可靠投递（规范 §21.3）：订单落库与事件记录同事务写入本表，
--               由框架 OutboxPublisher 轮询投递 MQ；状态 0 待发送 / 1 已发送 / 2 失败超限 / 3 死信。
--               投递失败按指数退避设置 next_retry_at（S9-4），重试超限投递死信主题（P0-3/S9-7）。
-- 说明：新表无初始数据（DML 无需提供）；已发送记录保留 7 天后由 outbox_cleaner 清理。
-- =====================================================================

CREATE TABLE IF NOT EXISTS message_outbox (
    id            BIGINT PRIMARY KEY AUTO_INCREMENT,
    msg_id        VARCHAR(64) NOT NULL COMMENT '消息幂等键组成之一（规范 §9.2）',
    biz_id        VARCHAR(64) NOT NULL COMMENT '业务键（幂等键组成之一，如 orderId）',
    topic         VARCHAR(128) NOT NULL COMMENT '目标 Topic',
    tag           VARCHAR(64) COMMENT 'Tag（对齐 §5.8 消息常量规范）',
    payload       TEXT NOT NULL COMMENT '消息体（JSON）',
    status        TINYINT NOT NULL DEFAULT 0 COMMENT '0 待发送 / 1 已发送 / 2 失败超限 / 3 死信队列',
    retry_count   INT NOT NULL DEFAULT 0 COMMENT '投递重试次数（§9.6）',
    created_at    DATETIME NOT NULL COMMENT '创建时间（清理判断依据）',
    updated_at    DATETIME COMMENT '最近一次投递/重试时间',
    cleaned_at    DATETIME COMMENT '清理时间（§21.3 清理策略）',
    next_retry_at DATETIME COMMENT '下次可重试时间（指数退避，NULL 立即重试，S9-4）',
    UNIQUE KEY uk_msg_biz (msg_id, biz_id),
    KEY idx_status_next_retry (status, next_retry_at)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'Outbox 本地事务表';
