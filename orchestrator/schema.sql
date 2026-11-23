-- Agent Relay Skill v1 — 状态库 schema（SQLite，8 张表）
-- 来源：RELAY-AUTONOMY-POC-01 第二轮讨论（REVIEW-5 定稿）。
-- 使用说明：
--   * v1 默认权威来源是单写入者文件日志（orchestrator/file_log.py），不是这份 SQLite。
--   * 只有在文件持久化、重启恢复、并发写入三项验证通过后，SQLite 才能成为权威来源；
--     验证未通过之前，SQLite 只做只读镜像。
--   * 完整性规则：每次状态变更一个事务（BEGIN IMMEDIATE，WAL 模式，外键开启）；
--     去重靠 message_id / nonce / token_hash 上的唯一约束；每条消息信封带
--     content + content_len + content_sha256，接收方重算比对；单条消息上限 8000 字；
--     提案用乐观锁（base_version，UPDATE ... WHERE version = base_version，0 行
--     受影响即冲突，写入方重读、合并、重试）；提案只追加，旧版本保留。
--   * 本文件只建表，不含任何用户数据、地址、令牌或密码。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    goal         TEXT,
    status       TEXT NOT NULL DEFAULT 'CREATED',
    participants TEXT NOT NULL DEFAULT '[]',
    convergence  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id     TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects (project_id),
    sender         TEXT NOT NULL,
    turn_number    INTEGER NOT NULL,
    nonce          TEXT NOT NULL,
    reply_to       TEXT,
    content        TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_len    INTEGER NOT NULL,
    source_session TEXT,
    status         TEXT NOT NULL DEFAULT 'received',
    created_at     TEXT NOT NULL,
    UNIQUE (project_id, turn_number, nonce)
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id    TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects (project_id),
    version        INTEGER NOT NULL,
    base_version   INTEGER,
    author         TEXT NOT NULL,
    content        TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_len    INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    created_at     TEXT NOT NULL,
    UNIQUE (project_id, version)
);

CREATE TABLE IF NOT EXISTS objections (
    objection_id     TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects (project_id),
    proposal_version INTEGER NOT NULL,
    author           TEXT NOT NULL,
    content          TEXT NOT NULL,
    content_sha256   TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    resolved_by      TEXT,
    created_at       TEXT NOT NULL,
    resolved_at      TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id    TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects (project_id),
    message_id     TEXT REFERENCES messages (message_id),
    source         TEXT NOT NULL,
    detail         TEXT,
    content_sha256 TEXT NOT NULL,
    verified       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id        TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects (project_id),
    proposal_id        TEXT REFERENCES proposals (proposal_id),
    options            TEXT NOT NULL,
    recommended_option TEXT,
    evidence_refs      TEXT NOT NULL DEFAULT '[]',
    cost               TEXT,
    risk               TEXT,
    recommendation     TEXT,
    package_sha256     TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    deadline           TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id    TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL REFERENCES decisions (decision_id),
    token_hash     TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL DEFAULT 'pending',
    approver       TEXT,
    approved_option TEXT,
    decided_at     TEXT,
    channel        TEXT,
    replay_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    decision_id  TEXT NOT NULL REFERENCES decisions (decision_id),
    approval_id  TEXT NOT NULL REFERENCES approvals (approval_id),
    executor     TEXT NOT NULL,
    spec_sha256  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    started_at   TEXT,
    finished_at  TEXT,
    result_ref   TEXT,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_project_turn
    ON messages (project_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_objections_project_status
    ON objections (project_id, status);
CREATE INDEX IF NOT EXISTS idx_decisions_project_status
    ON decisions (project_id, status);
