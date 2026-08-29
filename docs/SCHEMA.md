# ReturnGuard 数据库表结构（SCHEMA）

> 适用版本：1.1.2（仓库根 `VERSION` 为单一来源）
> 对应代码：`demo/db.py` 的 `Case` 模型（ORM 单一来源）
> 本文件与 `demo/schema.sql` 互为镜像：本文档给人看，`.sql` 给数据库用。

## 1. 总览

| 项 | 值 |
|----|----|
| 数据库 | SQLite |
| demo 源 | `cases.db`（**1206 条**真实退货案件，由 `cases.json` 播种） |
| real 源 | `cases_real.db`（初始空库，供网页端录入 / 删除） |
| 表名 | `cases` |
| 隔离方式 | demo / real **双源物理隔离**，各自独立建表，schema 完全一致 |
| 字段数 | 27（1 个自增主键 `id` + 26 个业务字段） |
| 索引 | 5 个：`case_id` / `sku` / `category` / `supplier` / `platform` |

## 2. 字段说明

| # | 字段名 | 类型 | 索引 | 含义 | 来源 / 备注 |
|---|--------|------|------|------|------------|
| 1 | `id` | INTEGER | PK | 自增行 ID（系统内部主键） | ORM 自动维护 |
| 2 | `case_id` | VARCHAR(64) | ✅ | 案件编号 `RG-000001`；单案上传时先用临时 `rid` | 业务主键 |
| 3 | `sku` | VARCHAR(64) | ✅ | 商品 SKU 编码 | 种子 / 录入 |
| 4 | `sku_name` | VARCHAR(128) | | 商品名称 | |
| 5 | `category` | VARCHAR(64) | ✅ | 品类：3C数码 / 饰品配件 / 小家电 / 服饰鞋包 | |
| 6 | `supplier` | VARCHAR(32) | ✅ | 供应商编号 S1~S8 | |
| 7 | `supplier_name` | VARCHAR(128) | | 供应商名称 | |
| 8 | `platform` | VARCHAR(32) | ✅ | 销售平台（9 个）：Amazon / AliExpress / Temu / SHEIN / eBay / Shopee / Lazada / Walmart / TikTok Shop | |
| 9 | `language` | VARCHAR(16) | | 举证语种 | 单案上传时附带 |
| 10 | `region` | VARCHAR(32) | | 销售地区 | |
| 11 | `amount` | FLOAT | | 退款 / 争议金额（¥） | |
| 12 | `date` | DATE | | 案件日期 `YYYY-MM-DD` | 存 `Date` 类型，仓储层做 `str↔date` 双向转换 |
| 13 | `similarity` | FLOAT | | 与本店主图相似度 | |
| 14 | `same_item` | BOOLEAN | | 是否同一件商品 | |
| 15 | `defect_tags` | JSON | | 瑕疵标签 `list[str]` | |
| 16 | `defect_description` | TEXT | | 瑕疵文字描述 | |
| 17 | `consistency` | TEXT | | 与 listing 承诺一致性判定 | |
| 18 | `outcome` | VARCHAR(32) | | 赢 / 部分退款 / 输 / 未知 / 待分析 | |
| 19 | `mode` | VARCHAR(32) | | synthetic / mock / live | |
| 20 | `listing_text` | TEXT | | 商品详情页文案 | 单案上传时附带，种子数据可能为空 |
| 21 | `priority_score` | FLOAT | | 优先级评分 | |
| 22 | `returned_image` | VARCHAR(256) | | 退货实拍图路径 / URL | |
| 23 | `product_image` | VARCHAR(256) | | 本店主图路径 / URL | |
| 24 | `dossier` | TEXT | | 举证报告正文 | 单案取证完整留存；规模部署建议改对象存储 URL |
| 25 | `voice_text` | TEXT | | 母语语音陈述文本 | |
| 26 | `voice_audio_b64` | TEXT | | 语音 base64（演示用） | 演示用；规模部署建议改对象存储 URL |
| 27 | `defect_boxes` | JSON | | 关键帧缺陷示意框（归一化坐标 0~1） | 红框标注回放用 |

## 3. 与 API 契约的关系

- `demo/schemas.py` 是 **API 层 Pydantic 契约**（请求 / 响应校验），与本表结构近似但不等同（例如录入接口 `ManualCase` 只要求 `sku`，其余带默认值）。
- 本文件是 **存储层 DB schema**（ORM 模型）。两者字段命名保持一致，便于前后端对齐。
- 列表接口 `/api/cases?slim=1` 仅投影第 2–8、11、18、12 等录入列表所需字段（`db.list_cases`），不含 20–26 等大字段——详情卷宗页才读全量。

## 4. 重建 / 校验

- 重建表结构：`sqlite3 cases.db < demo/schema.sql`（重置需先 `DROP TABLE IF EXISTS cases;`）。
- 模型与磁盘 schema 已核对一致（见 `docs/CODE_REVIEW.md` 六、及日常 `FORCE_RESEED=1` 重建流程）。
- 新增 / 修改字段时：**先改 `db.py` 的 `Case` 模型 → 同步更新本文件与 `demo/schema.sql` → 旧库走 `FORCE_RESEED=1` 或写迁移**，避免 `create_all` 不 ALTER 旧表导致 `no such column`。
