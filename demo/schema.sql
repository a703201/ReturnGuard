-- ReturnGuard 案件表 DDL
-- 与 demo/db.py 中 SQLAlchemy `Case` 模型 100% 对齐（已由 create_all 实际生成的 schema 核对）
--
-- 用法：
--   新建空库:  sqlite3 cases.db < schema.sql
--   重置现有库(会清空数据):
--     sqlite3 cases.db "DROP TABLE IF EXISTS cases;"
--     sqlite3 cases.db < schema.sql
--
-- 说明：
--   * 本文件只定义结构，不导入数据；种子数据由 demo/generate_dataset.py + db.init_db 负责。
--   * demo 源 = cases.db（约 672 条种子）；real 源 = cases_real.db（初始空库，供网页端录入）。
--   * 双源物理隔离，各自独立建表，schema 完全一致。

CREATE TABLE cases (
    id INTEGER NOT NULL,
    case_id VARCHAR(64),
    sku VARCHAR(64),
    sku_name VARCHAR(128),
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
    PRIMARY KEY (id)
);

CREATE INDEX ix_cases_case_id ON cases (case_id);
CREATE INDEX ix_cases_sku ON cases (sku);
CREATE INDEX ix_cases_category ON cases (category);
CREATE INDEX ix_cases_supplier ON cases (supplier);
CREATE INDEX ix_cases_platform ON cases (platform);
