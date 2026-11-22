# ReturnGuard 数据库表结构（SCHEMA）

> **🟢 当前技术形态（2026-11-22）**：仓颉后端（`backend/`）使用 openGauss **单库 `returnguard_cj`**，
> 5 张表 `rg_users` / `rg_cases` / `rg_audit` / `rg_quota` / `rg_sessions`（+ refresh 字段、并发会话上限），
> 建表幂等见 `backend/rg-data/src/db/db.cj`；数据库仅监听回环（compose 见 [`docker/docker-compose.cangjie.yml`](../docker/docker-compose.cangjie.yml)）。
>
> **说明**：下文 §2 ~ §3 为 Python 兼容版（历史实现）的 `Case` ORM 字段叙事，保留作为字段口径参考；**历史记录保留当时叙事，当前事实以 `backend/README.md` 与 `README.md` 为准**。当前库 / 表事实以上方说明与 `backend/rg-data/src/db/db.cj` 为准，平台/模型事实见 [`backend/rg-ai/src/providers.cj`](../backend/rg-ai/src/providers.cj)。
>
> 适用版本：3.1.0（仓库根 `VERSION` 为单一来源）
> 当前建表代码：`backend/rg-data/src/db/db.cj`（仓颉版单一来源）；完整能力与表说明见 [`backend/README.md`](../backend/README.md)。

## 1. 总览

| 项 | 值 |
|----|----|
| 数据库 | **openGauss 5.0 单库 `returnguard_cj`**（开发与部署统一）；compose 内网 `db:5432`，宿主 `127.0.0.1:${CJ_DB_PORT:-15433}`，仅绑回环 |
| 表 | **5 张**：`rg_users` / `rg_cases` / `rg_audit` / `rg_quota` / `rg_sessions`（建表幂等见 `backend/rg-data/src/db/db.cj`） |
| 隔离方式 | 单库多租户：案件按 `tenant_id` 隔离，归属不明数据归入显式 `public` 桶；当前**不再有 demo / real 双库** |
| 连接参数 | `RG_DB_HOST` / `RG_DB_PORT` / `RG_DB_NAME` / `RG_DB_USER` / `RG_DB_PASSWORD`（compose 见 `docker/docker-compose.cangjie.yml`）；`RG_DB_HOST` 为空 = 内存回退（开发 / CI）；`RG_DB_POOL=0`（连接池并发 dead lock，保持每次新建连接） |

> 下表 §2 的 28 字段为历史 Python 版 `cases` 表口径；当前 `rg_cases` 表结构以 `backend/rg-data/src/db/db.cj` 为准。
> 历史勘误（已不适用）：早期 Python 版曾为 demo / real 双库（`returnguard` / `returnguard_real`），现已收敛为单库 `returnguard_cj`。

## 2. 字段说明（历史 Python 版口径）

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

## 4. 建表 / 校验（当前仓颉版）

- 仓颉后端启动时按 `backend/rg-data/src/db/db.cj` 幂等建表（5 张表），无需 Python 版 `create_all` / `_migrate_case_columns` / `FORCE_RESEED` 流程。
- 容器部署：`docker compose -f docker/docker-compose.cangjie.yml up -d --build`，openGauss 数据落 `cjogdata` 卷；`AUTH_SECRET` / `GS_PASSWORD` 必填，应用绑回环（默认 `127.0.0.1:58080`）。
- 本地直跑：设置 `RG_DB_HOST` 等连接参数指向 openGauss；留空则内存回退（开发 / CI）。详见 [`backend/README.md`](../backend/README.md) 与 [`DEPLOYMENT.md`](DEPLOYMENT.md)。
- 新增 / 修改字段时：以 `backend/rg-data/src/db/db.cj` 的建表语句为单一来源，并同步更新 `docs/openapi.yaml` 契约与本文件字段口径。
