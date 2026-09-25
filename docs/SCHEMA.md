# ReturnGuard 数据库表结构（SCHEMA）

> 适用版本：2.1.1（仓库根 `VERSION` 为单一来源）
> 对应代码：`demo/db.py` 的 `Case` 模型（ORM 单一来源）
> 本文件与 `demo/schema.sql` 互为镜像：本文档给人看，`.sql` 给数据库用。

## 1. 总览

| 项 | 值 |
|----|----|
| 数据库 | **openGauss**（开发与部署统一）；demo 与 auth 落 `returnguard` 库，**real 落独立库 `returnguard_real`**（compose 内网 `db:5432`，本地经 `localhost:5432`）；仅离线 / CI 才显式回退 SQLite |
| demo 源 | openGauss `returnguard` 库 `cases` 表（**1206 条**真实退货案件，由 `cases.json` 播种，共享只读演示库） |
| real 源 | openGauss **`returnguard_real`** 库 `cases` 表（初始空库，供网页端录入 / 删除，按 `tenant_id` 隔离） |
| 表名 | `cases`（两库表结构完全一致） |
| 隔离方式 | demo / real **双源物理隔离**（**不同数据库**），各自独立引擎 + 独立代际计数，schema 完全一致 |
| 字段数 | **28**（1 个自增主键 `id` + 27 个业务字段，含多租户键 `tenant_id`） |
| 索引 | **6** 个：`case_id` / `sku` / `category` / `supplier` / `platform` / `tenant_id` |

> ⚠️ 历史勘误：早期版本本表曾写作「demo/real/auth 三库均 `returnguard`」，与实际部署不符——**real 源使用独立库 `returnguard_real`**（见 `docker/docker-compose.yml` 的 `REAL_DATABASE_URL`），写库绝不污染演示库。

## 2. 字段说明

| # | 字段名 | 类型 | 索引 | 含义 | 来源 / 备注 |
|---|--------|------|------|------|------------|
| 1 | `id` | INTEGER | PK | 自增行 ID（系统内部主键） | ORM 自动维护 |
| 2 | `case_id` | VARCHAR(64) | ✅ | 案件编号 `RG-000001`；单案上传时先用临时 `rid` | 业务主键 |
| 3 | `sku` | VARCHAR(64) | ✅ | 商品 SKU 编码 | 种子 / 录入 |
| 4 | `sku_name` | VARCHAR(256) | | 商品名称 | cases.json 实测最长 145 字符，openGauss 严格长度校验下原 `VARCHAR(128)` 会 `DataError`；已扩至 256 |
| 5 | `category` | VARCHAR(64) | ✅ | 品类：3C数码 / 饰品配件 / 小家电 / 服饰鞋包 | |
| 6 | `supplier` | VARCHAR(32) | ✅ | 供应商编号 S1~S8 | |
| 7 | `supplier_name` | VARCHAR(128) | | 供应商名称 | |
| 8 | `platform` | VARCHAR(32) | ✅ | 销售平台（9 个）：Amazon / AliExpress / Temu / SHEIN / eBay / Shopee / Lazada / Walmart / TikTok Shop | |
| 9 | `language` | VARCHAR(16) | | 举证语种 | 单案上传时附带；取值见 `constants.TTS_VOICES`（`zh`/`en`/`es`/`pt`/`de`/`fr`/`ja`/`ko`） |
| 10 | `region` | VARCHAR(32) | | 销售地区 | |
| 11 | `amount` | FLOAT | | 退款 / 争议金额（¥） | |
| 12 | `date` | DATE | | 案件日期 `YYYY-MM-DD` | 存 `Date` 类型，仓储层做 `str↔date` 双向转换 |
| 13 | `similarity` | FLOAT | | 与本店主图相似度 | |
| 14 | `same_item` | BOOLEAN | | 是否同一件商品 | |
| 15 | `defect_tags` | JSON | | 瑕疵标签 `list[str]` | |
| 16 | `defect_description` | TEXT | | 瑕疵文字描述 | |
| 17 | `consistency` | TEXT | | 与 listing 承诺一致性判定 | |
| 18 | `outcome` | VARCHAR(32) | | 赢 / 部分退款 / 输 / 未知 / 待分析 | |
| 19 | `mode` | VARCHAR(32) | | 数据来源标记：`manual`（网页录入）/ `mock`（演示/回退）/ `live`（真实模型）/ `synthetic`（早期合成种子，已由真实数据集替换，仅存量数据可能保留该值） | |
| 20 | `listing_text` | TEXT | | 商品详情页文案 | 单案上传时附带，种子数据可能为空 |
| 21 | `priority_score` | FLOAT | | 优先级评分 | |
| 22 | `returned_image` | VARCHAR(256) | | 退货实拍图路径 / URL | |
| 23 | `product_image` | VARCHAR(256) | | 本店主图路径 / URL | |
| 24 | `dossier` | TEXT | | 举证报告正文 | 单案取证完整留存；规模部署建议改对象存储 URL |
| 25 | `voice_text` | TEXT | | 母语语音陈述文本 | |
| 26 | `voice_audio_b64` | TEXT | | 语音 base64（演示用） | 演示用；规模部署建议改对象存储 URL |
| 27 | `defect_boxes` | JSON | | 关键帧缺陷示意框（归一化坐标 0~1） | 红框标注回放用 |
| 28 | `tenant_id` | VARCHAR(64) | ✅ | **多租户隔离键**（一个用户 = 一个租户） | real 源按此隔离；demo 源恒为 `"demo"`（共享演示库，不参与隔离）；历史/匿名数据为 `NULL`，查询时按显式 `public` 桶处理（SEC-P0，不再隐式共享） |

## 3. 与 API 契约的关系

- `demo/schemas.py` 是 **API 层 Pydantic 契约**（请求 / 响应校验），与本表结构近似但不等同（例如录入接口 `ManualCase` 只要求 `sku`，其余带默认值）。
- 本文件是 **存储层 DB schema**（ORM 模型）。两者字段命名保持一致，便于前后端对齐。
- 列表接口 `/api/cases?slim=1`（默认）仅投影 `db._LIST_FIELDS` 的 **10 个列表展示字段**：`case_id` / `sku` / `sku_name` / `category` / `supplier` / `supplier_name` / `amount` / `outcome` / `date` / `platform`；**不含** `dossier`(24)、`voice_text`(25)、`voice_audio_b64`(26) 等大字段——详情卷宗页才读全量（`slim=0`）。
- 洞察聚合另走 `load_filtered_cases`，在行→dict 后剔除 `voice_audio_b64` / `dossier`，避免 1206 行 × 大对象的无谓 IO 与内存放大（P1-12）。

## 4. 重建 / 校验

- 重建表结构（openGauss 统一，离线回退 SQLite）：开发与部署均走 `create_all` + `_migrate_case_columns` 演进；如需全量重播设 `FORCE_RESEED=1` 并清 `ogdata` 卷。离线 SQLite 回退时可用 `sqlite3 cases.db < demo/schema.sql`（重置需先 `DROP TABLE IF EXISTS cases;`）。
- 部署期（openGauss）：`docker compose -f docker/docker-compose.yml up -d` 会自动 `create_all` + `_migrate_case_columns` 演进；如需全量重播设 `FORCE_RESEED=1` 并清 `ogdata` 卷。
- 模型与磁盘 schema 已核对一致（见 `docs/CODE_REVIEW.md` 六、及日常 `FORCE_RESEED=1` 重建流程）。
- 新增 / 修改字段时：**先改 `db.py` 的 `Case` 模型 → 同步更新本文件与 `demo/schema.sql` → 旧库走 `FORCE_RESEED=1` 或写迁移**，避免 `create_all` 不 ALTER 旧表导致 `no such column`。
