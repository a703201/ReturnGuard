-- Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
-- SPDX-License-Identifier: Apache-2.0
-- ReturnGuard 案件表 DDL
-- 与 demo/db.py 中 SQLAlchemy `Case` 模型对齐（28 列：id + 27 业务字段）。
--
-- 定位：本文件是**离线 / CI 场景的参考 DDL**。开发与部署正常走 openGauss，
--       表结构由 db.init_db 的 `create_all` + `_migrate_case_columns` 自动创建并演进，
--       正常情况下**不需要手工执行本文件**。
--
-- 用法（仅在无 openGauss 的离线环境回退 SQLite 时）：
--   新建空库:  sqlite3 cases.db < schema.sql
--   重置现有库(会清空数据):
--     sqlite3 cases.db "DROP TABLE IF EXISTS cases;"
--     sqlite3 cases.db < schema.sql
--
-- 说明：
--   * 本文件只定义结构，不导入数据。
--   * demo 源 = openGauss `returnguard` 库（**1206 条**真实退货案件，由 cases.json 播种，共享只读）。
--   * real 源 = openGauss **独立库 `returnguard_real`**（初始空库，供网页端录入/删除，按 tenant_id 隔离）。
--     仅在离线 SQLite 回退时退化为 cases.db / cases_real.db 两个文件。
--   * 双源物理隔离（不同数据库），schema 完全一致。
--
-- ⚠️ 改字段时：先改 db.py 的 Case 模型 → 同步本文件与 docs/SCHEMA.md → 旧库走 FORCE_RESEED=1 或写迁移。

CREATE TABLE cases (
    id INTEGER NOT NULL,
    case_id VARCHAR(64),
    sku VARCHAR(64),
    sku_name VARCHAR(256),
    category VARCHAR(64),
    supplier VARCHAR(32),
    supplier_name VARCHAR(128),
    platform VARCHAR(32),
    language VARCHAR(16),
    region VARCHAR(32),
    amount FLOAT,
    date DATE,
    similarity FLOAT,
    same_item BOOLEAN,
    defect_tags JSON,
    defect_description TEXT,
    consistency TEXT,
    outcome VARCHAR(32),
    mode VARCHAR(32),
    listing_text TEXT,
    priority_score FLOAT,
    returned_image VARCHAR(256),
    product_image VARCHAR(256),
    dossier TEXT,
    voice_text TEXT,
    voice_audio_b64 TEXT,
    defect_boxes JSON,
    tenant_id VARCHAR(64),
    PRIMARY KEY (id)
);

CREATE INDEX ix_cases_case_id ON cases (case_id);
CREATE INDEX ix_cases_sku ON cases (sku);
CREATE INDEX ix_cases_category ON cases (category);
CREATE INDEX ix_cases_supplier ON cases (supplier);
CREATE INDEX ix_cases_platform ON cases (platform);
CREATE INDEX ix_cases_tenant_id ON cases (tenant_id);
