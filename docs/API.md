# ReturnGuard 接口文档（API.md）

> **服务**：ReturnGuard Demo（FastAPI）
> **最后更新**：2026-09-25（2.1.2）
> **关联文档**：`docs/PRD.md`、`docs/SCHEMA.md`、`docs/ARCHITECTURE.md`（功能实现逻辑）、`docs/DECISION_LOGIC.md`（判定逻辑）、`docs/AI_PROVIDERS.md`（多 AI 平台对接）、`docs/AB_ROI_实证说明.md`、`docs/CODE_REVIEW.md`、`CHANGELOG.md`、`docs/reference/ModelRouter_API.docx`（网关接口参考）

---

## 1. 概述
- **本地 Base URL**：`http://127.0.0.1:8000`（直接 `uvicorn main:app` 时）
- **容器 Base URL**：`http://127.0.0.1:65432`（compose 映射到宿主机回环）
  > 对外发布由部署方在其前置反向代理 / CDN 并配置 HTTPS；应用自身只绑回环，不直接暴露。
- **前端页面**：`GET /` 返回「退货情报站」单页应用，**5 个 Tab**：市场洞察 / 平台举证包 / 供应商透视 / 单案取证 / 数据录入。
- **数据格式**：JSON（`/api/analyze`、`/api/import_csv`、`/api/import_file` 为 `multipart/form-data`）。
- **双模式**：多数接口支持 `mode=mock|live`，默认 `mock`。
- **界面语言**：`zh` / `en` / `fr` 三语（`/api/config` 的 `languages` 为单一来源；后端语音支持 8 个语种，见 §5.4）。
- **交互式文档**：运行后 `GET /docs` 可看 FastAPI 自动生成的 OpenAPI（多数端点已挂 `response_model`）。

---

## 2. 通用约定
- **金额**：单位 ¥（float）；**日期**：`YYYY-MM-DD`。
- **错误响应**：HTTP 状态码 + FastAPI 默认 `{ "detail": "..." }`。
- **live 回退**：live 模式失败时**不报 5xx**，返回 `200` 并带 `mode="mock(fallback)"` 与 `error` 字段，保证前端不中断。**失败回退结果不写缓存**，避免网关恢复后仍返回旧降级值。
- **兼容键**：`/api/insights` 始终返回 `total_cases` / `sku_ranking` / `defect_distribution`，前端无需按模式分支。
- **鉴权（强制）**：写接口（`POST /api/analyze`、`POST/DELETE /api/cases`、`POST /api/import_csv`、`POST /api/import_file`）须携带登录会话；管理端点（`POST /api/calibrate`、`GET /metrics`）须 `ADMIN_API_KEY` 或登录会话。令牌经 `Authorization: Bearer <token>` 或 `X-Token: <token>` 头传递（**不再支持 `?token=` 查询参数**，SEC-4）。未携带 → `401`。
- **多租户**：`real` 源案件按 `tenant_id` 隔离；归属不明的历史数据归入显式 `public` 桶（**不再隐式共享**，SEC-P0）；`demo` 源为共享只读演示库。数据变更接口均须登录态，禁止匿名写入。
- **静态资源版本化**：`/static/*` 的 URL 带 `?v=<APP_VERSION>`（服务端注入），并下发 `Cache-Control: no-store`；发版即换 URL，避免浏览器 / CDN 命中旧前端产物。
- **live 配额闸（SEC-13）**：`mode=live` 受三层配额限制（全局日 / 账号日 / IP 小时，环境变量 `LIVE_QUOTA_GLOBAL_DAY` / `LIVE_QUOTA_TENANT_DAY` / `LIVE_QUOTA_IP_HOUR`，置 `0` 关闭该层），超限返回 `429` 并明确告知，**不静默降级为 mock**。该闸门覆盖**全部会消耗付费 Key 的链路**：`/api/analyze`、`/api/insights?mode=live`、`/api/export_pdf?mode=live`。

---

## 3. 接口一览

| # | 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|---|
| 3.1 | GET | `/` | 前端单页（5 Tab） | 公开 |
| 3.2 | GET | `/health` | 健康探针（编排 healthcheck） | 公开 |
| 3.3 | GET | `/api/config` | 前端常量单一来源（阈值 / 版本 / 数据源 / 供应商 / 语言 / 图床 / profile） | 公开 |
| 3.4 | POST | `/api/analyze` | 阶段 A · 单案举证 | 登录会话 |
| 3.5 | GET | `/api/insights` | 阶段 B · 群体洞察 | 公开（real 源需登录） |
| 3.6 | GET | `/api/export_pdf` | 导出洞察报告 PDF | 公开（real 源需登录） |
| 3.7 | GET | `/api/platforms` | 平台适配举证包（交付物 A） | 公开 |
| 3.8 | GET | `/api/cases` | 案件库查询（过滤 + 分页） | demo 公开 / real 登录 |
| 3.9 | POST · DELETE | `/api/cases` · `/api/cases/{case_id}` | 网页端录入 / 删除 | 登录会话 |
| 3.10 | GET | `/api/file/{sig}` | 上传图签名短链（SEC-8） | 签名 + TTL |
| 3.11 | GET | `/api/img/{key}` | 自托管取图（`RG_SELF_IMAGE_BASE`） | 不可猜测 key |
| 3.12 | POST | `/api/import_csv` · `/api/import_file` | 真实数据批量回流 | 登录会话 |
| 3.13 | GET · POST | `/api/calibrate` | 相似度阈值自标定（读 / 写） | 读公开 / 写管理员 |
| 3.14 | GET | `/metrics` | 运行指标 | 管理员 |
| 3.15 | — | `/api/auth/*` | 注册 / 登录 / 当前用户 / 登出 | 见 §3.15 |
| 3.16 | GET | `/api/providers` | AI 平台目录与能力矩阵（多厂商适配） | 公开 |

---

### 3.1 `GET /`
返回前端页面（`text/html`）。入口脚本为外部同源 ES module `/static/app.js?v=<版本>`；CSP 由服务端每请求生成 nonce 注入（SEC-9）。

---

### 3.2 `GET /health`
轻量健康探针，返回 `{"status": "ok"}`（`HealthResp`）。供 compose healthcheck / 负载均衡使用。

---

### 3.3 `GET /api/config` —— 前端常量单一来源
前端不再内嵌任何常量副本；阈值、版本、供应商花名册、语言清单均由此下发，避免前后端双份漂移。

| 字段 | 类型 | 说明 |
|---|---|---|
| `same_item_threshold` | number | **运行期生效**的同款判定阈值（标定值，默认 0.82） |
| `version` | string | 应用版本（读仓库根 `VERSION`）；前端徽标据此显示 |
| `sources` / `default_source` | string[] / string | 可用数据源（`demo` / `real`）与默认值 |
| `image_bed` / `image_bed_public` | string / bool | 当前图床后端（`local` / `self` / `public_base` / `qiniu`）与是否公网就绪 |
| `suppliers` | object | 供应商花名册（`{S1: "鼎峰精密", …}`），单一来源 `constants.SUPPLIERS` |
| `languages` | object[] | 语音语种 `[{code, label, voice}]`，单一来源 `constants.TTS_VOICES` |
| `default_language` | string | 默认语音语种（`zh`） |
| `model_router_profile` | string | 当前 AI 平台标识（= `provider.key`，保留字段名向后兼容） |
| `provider` | object | 当前 AI 平台的**公开**信息：`key` / `label` / `api_style` / `key_env` / `key_configured` / `capabilities`（能力→是否可用）/ `models`（能力→模型标识）。前端据此如实呈现「哪些能力走真实模型」 |

> 安全：不返回内部网关地址（`model_router_endpoint` 已移除，P2 信息泄露收敛）；
> `provider` 亦不含基地址与密钥。平台全量目录见 §3.16。

---

### 3.4 `POST /api/analyze` —— 阶段 A · 单案举证
**鉴权**：须登录会话（`Authorization: Bearer <token>` 或 `X-Token`），匿名 → `401`（SEC-1）。
**Content-Type**：`multipart/form-data`

**请求参数**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `returned_image` | form-data(file) | file | 是 | 退回商品图 |
| `product_image` | form-data(file) | file | 是 | 本店主图 / 详情图 |
| `listing_text` | form-data | string | 否 | 本店文字承诺（默认 `""`） |
| `sku` | form-data | string | 否 | SKU（默认 `"SKU-未知"`） |
| `amount` | form-data | float | 否 | 订单金额 ¥（默认 `0.0`） |
| `category` | form-data | string | 否 | 品类（补全维度，避免污染洞察聚合，P1-1） |
| `supplier` | form-data | string | 否 | 供应商编号 S1~S8（同上） |
| `platform` | form-data | string | 否 | 销售平台；填写后响应带该平台的**必备举证清单** |
| `language` | form-data | string | 否 | 母语语音语种（默认 `zh`）；取值见 §5.4，非法值 → `400` |
| `mode` | form-data | string | 否 | `mock`（默认）/ `live`（受 SEC-13 配额约束） |

> 写库归正：取证结果一律落 **real 源**（当前租户库），即便传 `source=demo` 也会被强制归正，避免污染共享演示种子库。

**入参边界（2.0.0 补齐）**

| 参数 | 约束 | 越界响应 |
|---|---|---|
| `amount` | 必须为有限数值且 `0 ~ 1e9` | `400` |
| `sku` / `category` / `supplier` | 长度 ≤ 64 / 64 / 32（与 `cases` 表列长对齐） | `400` |
| `listing_text` | 长度 ≤ 20000 | `400` |
| `platform` | 必须在平台举证包支持列表内 | `400` |
| `language` | 必须在 `constants.TTS_VOICES` 内 | `400` |
| `mode` | `mock` / `live` | `400` |

**响应字段（200, application/json · `AnalyzeResult`）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 本次取证案件 ID |
| `similarity` | number | 同款一致性相似度（0~1） |
| `same_item` | bool | 是否同一件（阈值取 `/api/config` 的运行期值） |
| `defect_tags` | string[] | 瑕疵标签（如「功能故障」「无明显瑕疵」） |
| `defect_description` | string | 瑕疵标签拼接 |
| `consistency` | string | 与 listing 承诺一致性结论 |
| `dossier` | string | 结构化举证报告文本 |
| `voice_text` | string | 母语口头陈述文本（按 `language` 生成） |
| `voice_audio_b64` | string | 语音音频（base64；mock 为占位 WAV） |
| `voice` | string | 实际使用的 TTS 音色（如 `Chelsie` / `Ethan` / `Serena`） |
| `language` | string | 本单陈述语种 |
| `priority_score` | number | 案件优先级评分（0~1，越高越先处理） |
| `defect_boxes` | object[] | 缺陷区域框（归一化 `{label,x,y,w,h,confidence}`，0~1） |
| `defect_boxes_live` | bool | 红框是否来自**真实视觉模型坐标**；`false` = 回退示意框（前端据此改色并如实标注） |
| `returned_image_url` | string | 退回图访问地址（签名短链，替代整图 base64 撑大响应，P3-5） |
| `platform` | string | 关联平台（回显入参） |
| `platform_evidence` | string[] | 该平台的必备举证材料清单（未传 `platform` 时为空） |
| `capabilities` | object | **逐能力**真实 / 回退标记（`similarity`/`defects`/`boxes`/`ocr`/`llm`/`rerank`/`tts`） |
| `mode` | string | `mock` / `live` / `mock(fallback)` |
| `error` | string | 仅回退时出现，失败原因 |

> 诚实性约定：`mode` 与 `defect_boxes_live`、`capabilities` 必须如实反映真实调用情况——红线是**不把演示示意说成真实模型输出**。红框不替代平台裁决。

**示例**

```bash
# mock（默认，零依赖）
curl -F "returned_image=@ret.jpg" -F "product_image=@prod.jpg" \
     -F "sku=SKU-123" -F "amount=89.9" -F "mode=mock" \
     http://127.0.0.1:65432/api/analyze

# live（需先登录拿令牌）
TOK=$(curl -s -X POST http://127.0.0.1:65432/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"demo","password":"demo123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -H "Authorization: Bearer $TOK" \
     -F "returned_image=@ret.jpg" -F "product_image=@prod.jpg" \
     -F "sku=SKU-123" -F "amount=89.9" -F "platform=Amazon" \
     -F "language=fr" -F "mode=live" \
     http://127.0.0.1:65432/api/analyze
```

---

### 3.5 `GET /api/insights` —— 阶段 B · 群体洞察（产品核心）
**鉴权**：`demo` 源公开可读（共享演示库、无买家 PII）；`real` 源**须登录**（返回本租户数据，匿名 → `401`）。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source` | string | 否 | `demo`（默认，未登录）/ `real`（登录后） |
| `mode` | string | 否 | `mock`（默认，规则归因可复现）/ `live`（LLM 归因，需 Key） |
| `category` | string | 否 | 按品类下钻 |
| `platform` | string | 否 | 按平台下钻（非法平台 → `400`） |
| `region` | string | 否 | 按销售地区下钻（维度扩展） |
| `season` | string | 否 | 按季节下钻：`春`/`夏`/`秋`/`冬`（维度扩展） |

**响应字段（200, application/json · `InsightsResponse`）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `total_cases` | int | 案件总数 |
| `total_refund` | number | 累计退款额 ¥ |
| `win_rate` | number | 胜诉率（0~1） |
| `avg_dispute_rate` | number | **代理指标**：1 − 平均相似度，非平台争议笔数 |
| `dispute_rate_note` | string | 代理指标口径说明（前端须同屏展示，防误读） |
| `outcome_dist` | object | 结果分布 |
| `category_heatmap` | object[] | 品类退货热力 |
| `supplier_scorecard` | object[] | 供应商红黑榜（质量分 + 等级） |
| `supplier_blacklist` | object[] | 黑名单档位（高风险 / 待改进，按分级判定） |
| `platform_view` | object[] | 平台胜诉对比 |
| `platform_supplier_matrix` | object[] | 平台 × 供应商交叉（每格含 `win_rate`/`cases`/`refund`） |
| `region_view` | object[] | 地区维度视图（维度扩展） |
| `season_view` | object[] | 季节维度视图（维度扩展） |
| `sku_ranking` | object[] | SKU 纠纷明细（退款额排序，含 `anomaly` 标记） |
| `anomaly_alerts` | object[] | 近 30 天异常预警 |
| `root_cause_dist` | object | 根因分布 |
| `root_cause` | string | 根因结论（live 由 LLM 生成） |
| `sku_insights` | object[] | Top SKU 洞察（live 由 LLM 生成） |
| `logistics_cost` | number | 物流成本估算（按地区） |
| `total_return_cost` | number | 退货总成本 = 退款 + 物流 |
| `sourcing_advice` / `recommendations` | string[] | 选品 / 品控建议（可执行清单） |
| `report` | string | 洞察报告正文 |
| `roi_backtest` | object | **ROI 真实回测**（保守 / 基准 / 乐观 + 敏感性），见下 |

> **胜诉率口径（各维度统一，2.1.0 收口）**：`win_rate` 的分母一律为 `decided`（已判定案件数 = 总案件 − 待分析），
> 与全局 `win_rate` 一致；`category_heatmap` 与 `season_view` 亦输出 `decided` 字段，
> 前端据 `decided == 0` 显示「待判定」而不是误导性的 0%。判定规则详见 `docs/DECISION_LOGIC.md` §2.1。
| `mode` | string | `mock` / `live` / `mock(fallback)` |
| `error` | string | 仅回退时出现 |
| `reconciled_from` | string | LLM 数值与聚合不一致被纠偏时出现（P2-14 防幻觉） |

**`roi_backtest` 子结构**
| 字段 | 说明 |
|---|---|
| `available` | 数据是否足够（不足时前端隐藏面板） |
| `scenarios[]` | 三档情景：`label` / `effective_delta`（胜诉率提升）/ `cases_won_back` / `recover_refund` / `recover_logistics` / `labor_hours_saved` |
| `basis` | 回测基准：`total_cases` / `dispute_cases` / `win_rate` / `avg_refund`（**真实聚合值**） |
| `sensitivity` | 案件量 ±20% 的单因子扰动区间 |
| `method` / `disclaimer` | **强制随结果下发**，声明这是**模型回测、非 A/B 实测因果** |

> ⚠️ 边界：`roi_backtest` 是**基于真实聚合值的模型估算**，不得表述为产品带来的因果收益实测。完整口径见 `docs/AB_ROI_实证说明.md`。

**示例**
```bash
curl "http://127.0.0.1:65432/api/insights?source=demo&mode=mock&platform=SHEIN&season=夏"
```

---

### 3.6 `GET /api/export_pdf` —— 导出洞察报告
按当前筛选条件生成 PDF 报告（`application/pdf`）。支持的 query 与 `/api/insights` 一致（`source` / `mode` / `category` / `platform` / `region` / `season`）。

> 限流（2.0.0 新增）：按客户端 IP 限制为 `EXPORT_PDF_RATE_LIMIT`（默认 20 次/分钟，置 `0` 关闭），超限 `429`。
> 原因：报告生成为 CPU 重的同步任务（reportlab 排版），而 demo 源允许匿名读，需防被反复触发。
> `mode=live` 时同样受 SEC-13 配额闸约束。

---

### 3.7 `GET /api/platforms` —— 平台适配举证包（交付物 A）
返回九大平台（Amazon / AliExpress / Temu / SHEIN / eBay / Shopee / Lazada / Walmart / TikTok Shop）的退货纠纷举证规则与 ReturnGuard 能力映射，形如 `{"platforms": [...]}`。

- 每项含 `key`（平台标识）与各维度字段：`退货窗口` / `响应时限` / `运费承担` / `举证偏向` / `必备举证材料` / `常见失分原因` / `平台特殊条款`。
- 单案取证时选择平台，即由 `platform_evidence` 自动带出该平台的必备材料清单（**只列客观要求，不做裁决结论**）。

---

**示例**
```bash
curl "http://127.0.0.1:65432/api/insights?source=demo&mode=mock&platform=SHEIN&season=夏"
```

---

### 3.8 `GET /api/cases` —— 案件库查询（过滤 + 分页）
**鉴权**：`demo` 源公开可读；`real` 源**须登录**（匿名 → `401`，SEC-P0），且登录后只返回**本租户**数据。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `source` | string | `demo` | `demo` / `real` |
| `slim` | bool | `true` | `true` 只投影录入列表所需字段（剔除 `dossier`、`voice_audio_b64` 等大字段），避免整库大响应 |
| `page` | int | `1` | 页码（`ge=1`，越界 → `422`） |
| `page_size` | int | `50` | 每页条数（`ge=1, le=200`，越界 → `422`） |
| `category` / `platform` / `region` / `outcome` | string | `""` | 等值过滤，**下推 SQL WHERE**（减少拉库与传输） |

**响应信封**

```json
{ "items": [...], "total": 1206, "page": 1, "page_size": 50,
  "source": "demo", "filters": { "category": "", "platform": "" } }
```

### 3.9 `POST /api/cases` · `DELETE /api/cases/{case_id}` —— 网页端录入 / 删除
- **`POST /api/cases`**（`201`）：按 `ManualCase` 契约写入一条案件，生成 `RG-<hex>` 的 `case_id`；须登录会话（匿名 → `401`）。请求体见 §4.1。
  > 字段边界（2.0.0 补齐）：`sku` ≤ 64、`sku_name` ≤ 256、`category` ≤ 64、`supplier` ≤ 32、`supplier_name` ≤ 128、`platform` / `region` / `outcome` / `mode` ≤ 32、`language` ≤ 16、`listing_text` ≤ 20000、`defect_description` / `consistency` ≤ 2000、`returned_image` / `product_image` ≤ 256、`defect_tags` ≤ 20 项；`amount` ∈ `[0, 1e9]`、`similarity` / `priority_score` ∈ `[0, 1]`。越界返回 `422` 并指明字段（不再等到落库时被截断或报 500）。
- **`DELETE /api/cases/{case_id}`**：删除指定案件（仅当前租户可删自己写入的；跨租户 → `403`/`404`）；须登录会话。
- **`demo` 源禁止删除**（共享演示库，公开测试账号不可删光种子数据，SEC-P0）。
- 两接口仅落**当前数据源**（`?source=demo|real`），互不污染。

### 3.10 `GET /api/file/{sig}` —— 上传图签名短链（SEC-8）
退货图（PII）不再经 `/uploads` 公开挂载，改为 HMAC 签名 + TTL 短链：
```
/api/file/{sig}?f=<filename>&e=<exp_unix>
```
- `sig = HMAC(filename|exp, AUTH_SECRET)[:32]`，`e` 为过期 Unix 时间戳（`UPLOAD_URL_TTL` 默认 3600s）。
- 服务端校验：签名一致 + 未过期 + 路径穿越防护 → `200 FileResponse`；否则 `404`（不泄露文件是否存在）。
- 伪造签名 / 过期时间戳 → `404`；匿名直接访问旧 `/uploads/...` → `404`（挂载已移除）。

### 3.11 `GET /api/img/{key}` —— 自托管取图（`RG_SELF_IMAGE_BASE`）
用于把本机上传图经本服务隧道暴露给视觉网关回源（`self` 图床后端）。`key` 为 **256-bit 不可猜测随机名**（`storage._public_object_key`），与七牛公网图同等级隐私；文件随 `UPLOAD_DIR` 24h 清理。越界 / 不存在 / 含路径符 → `404`。

> 说明：**视觉输入现已优先内联 base64 data URI**（`models_router._img_source`），无需公网图床即可跑通 live 视觉；`self` / `public_base` / `qiniu` 属于**可选增强**。

### 3.12 `POST /api/import_csv` · `POST /api/import_file` —— 真实数据批量回流
- **`/api/import_csv`**：CSV 文本导入（列名映射 / 类型转换 / 中文表头不敏感）。`csv_file` 可选（`File`），缺失时按 `RG_AUTO_IMPORT_CSV` 启动自动导入（幂等去重）。
  > 体积上限（2.0.0 补齐）：上传文件与表单直贴的 `csv_text` 均限 10MB，超限 `413`。
- **`/api/import_file`**：上传 `.xlsx` / `.csv` **文件**导入，自动识别数据集类型；响应含新增 / 更新 / 跳过计数。
- 两者均须登录会话（匿名 → `401`）。
- 导入的每一行都会经过持久层收敛（超长字符串按列长截断、非有限数值归零、`defect_tags` 归一），单行脏数据不会让整批导入失败。

### 3.13 `GET · POST /api/calibrate` —— 相似度阈值自标定
- **`GET`**：返回当前生效阈值（标定值或默认 0.82）与标定样本量。公开。
- **`POST`**：用真同款 / 真调包样本按 **Youden J** 最优分离点标定阈值并落盘（`CalibrateRequest`）；须 `ADMIN_API_KEY` 或登录会话，匿名 → `401`。
  > 样本量上限（2.0.0 补齐）：`same_sims` / `diff_sims` 各 ≤ 5000，越界 `422`。

### 3.14 `GET /metrics` —— 运行指标（SEC-1/7）
返回请求量 / 平均耗时 / 错误数 / 取证与洞察调用量等；须 `ADMIN_API_KEY` 或登录会话，匿名 → `401`。

### 3.15 账户与鉴权接口（v1.1.0+）
| 方法 / 路径 | 说明 | 鉴权 |
|---|---|---|
| `POST /api/auth/register` | 注册新账户（一个用户 = 一个租户），成功即返回令牌；受 `REGISTRATION_ENABLED` / `REGISTRATION_INVITE_CODE` 约束 | 公开（对外部署默认关闭） |
| `POST /api/auth/login` | 登录，返回 HMAC 签名令牌（无状态，7 天过期）；密码 pbkdf2 60 万轮 | 公开 |
| `GET /api/auth/me` | 返回当前登录用户 / 租户标识，供前端恢复会话 | 登录会话 |
| `POST /api/auth/logout` | 登出（自增 `token_version`，该用户已签发令牌立即全失效） | 登录会话 |

登录示例：
```bash
curl -X POST http://127.0.0.1:65432/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo123"}'
# → {"token":"<jwt-like>","username":"demo"}
```
失败登录按 `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN` 触发滑动窗口封禁（返回 `429`，SEC-12 共享状态，多 worker 一致）。

### 3.16 `GET /api/providers` —— AI 平台目录（多厂商适配）
返回所有**已声明**的 AI 平台及其能力矩阵，供部署方选择与前端说明。公开可读。

**响应（200, application/json · `ProvidersResp`）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `providers[]` | object[] | 平台列表，每项见下 |

单个平台项：

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 平台标识（即 `MODEL_ROUTER_PROFILE` 的取值） |
| `label` | string | 展示名 |
| `api_style` | string | 协议风格：`openai` / `azure` / `native` |
| `supported` | bool | 是否可被本适配层直接对接（`native` 为 `false`，需经兼容网关接入） |
| `verified` | bool | 是否在本仓用真实 Key 跑通过 |
| `key_env` | string | 该平台所需的密钥环境变量名 |
| `key_required` | bool | 是否必须密钥（本地自托管平台为 `false`） |
| `capabilities` | object | 六类能力 → 是否可用（`text`/`vl`/`ocr`/`embed`/`rerank`/`tts`） |
| `doc` | string | 平台文档地址 |
| `note` | string | 差异与注意事项（如「无 rerank 端点」） |
| `is_current` | bool | 是否当前生效平台（有且仅有一个为 `true`） |

**示例**
```bash
curl -s http://127.0.0.1:65432/api/providers | python -m json.tool | head -30
```

> 安全：**不返回**基地址、模型标识与「是否已配置密钥」——避免匿名访客探测服务端内网拓扑与凭据状态。
> 当前平台的模型映射经 `/api/config` 的 `provider` 字段下发（同样不含基地址与密钥）。
> 切换平台与应用方式见 [`AI_PROVIDERS.md`](AI_PROVIDERS.md)。

---

## 4. 数据模型

### 4.1 Case 对象（单笔退货）
存储层字段全量与类型见 **`docs/SCHEMA.md`**（`demo/db.py` 的 `Case` 模型，27 字段）。API 层常用字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 案件 ID（`RG-<hex>`） |
| `sku` / `sku_name` | string | SKU 编码 / 名称 |
| `amount` | number | 订单金额 ¥ |
| `category` / `supplier` / `platform` / `region` | string | 四个下钻维度 |
| `language` | string | 举证语种（`zh`/`en`/`es`/`pt`/`de`/`fr`/`ja`/`ko`） |
| `similarity` | number | 同款一致性相似度 |
| `same_item` | bool | 是否同一件 |
| `defect_tags` / `defect_description` | string[] / string | 瑕疵标签与描述 |
| `consistency` | string | 与 listing 承诺的一致性结论 |
| `outcome` | string | 仲裁结果：`赢` / `部分退款` / `输` / `待分析`（**入库枚举，前端展示文案可本地化，`value` 不变**） |
| `date` | string | 日期 `YYYY-MM-DD` |
| `mode` | string | `manual`（录入）/ `mock` / `live` |

**`POST /api/cases` 请求体（`ManualCase`）**：除 `sku` 必填外，其余字段均带默认值——`sku_name` / `category` / `supplier` / `supplier_name` / `platform` / `language` / `region` / `amount` / `date` / `similarity` / `same_item` / `defect_tags` / `defect_description` / `consistency` / `outcome` / `listing_text` / `priority_score` / `returned_image` / `product_image`。

### 4.2 Insights 对象
见 §3.5 响应字段表（`pipeline.build_insights` 聚合输出；`schemas.InsightsResponse` 为类型化契约，另开 `extra="allow"` 兼容派生字段）。

---

## 5. AI 平台集成（多厂商适配）

### 5.1 概述
live 模式经**多家可选 AI 平台**调用（默认阿里云百炼，协议兼容 OpenAI）。
业务代码只按「能力」调用，平台声明集中在 [`demo/providers.py`](../demo/providers.py)，
调用与回退封装在 `demo/models_router.py`，由 `pipeline` 在 live 模式下编排。
**完整的平台矩阵、差异适配与接入方式见 [`AI_PROVIDERS.md`](AI_PROVIDERS.md)。**

### 5.2 基础信息
- **当前平台**：`MODEL_ROUTER_PROFILE`（兼容别名 `RG_AI_PROVIDER`）决定，默认 `tokenplan`；
  可选值与能力矩阵见 `GET /api/providers`。
- **Base URL / 鉴权**：随平台声明联动（`bearer` / `api-key` / 无鉴权），无需手工拼装。
- **环境变量**：
  - 密钥：各平台各自的变量（如 `MODEL_ROUTER_API_KEY` / `OPENAI_API_KEY` / `DASHSCOPE_API_KEY` / `ZHIPU_API_KEY`…），见 §3.16 的 `key_env`。
  - `PUBLIC_IMAGE_BASE`（**可选**）：仅当希望视觉能力走「公网 URL 回源」时才需要。**默认不必配**——`models_router._img_source` 会把本地上传图**转成 base64 data URI 内联**后发给模型，无需图片公网可达，也无需对象存储同步。
  - `RG_MODEL_TEXT` / `RG_MODEL_VL` / `RG_MODEL_OCR` / `RG_MODEL_EMBED` / `RG_MODEL_RERANK` / `RG_MODEL_TTS`（**可选**）：逐能力覆盖模型标识，用于平台改版或接入自建端点。
  - 各平台的基地址覆盖变量（如 `OPENAI_BASE_URL` / `DASHSCOPE_BASE_URL` / `RG_CUSTOM_BASE_URL`）：**每个平台独立**，避免互相污染。

> 重要变更：早期版本要求图片必须公网可达（`PUBLIC_IMAGE_BASE` + 对象存储同步）才能真正跑通 live 视觉；现已改为**内联 base64**，本机直跑即可，`PUBLIC_IMAGE_BASE` 降级为可选增强项。

### 5.3 模型能力映射表（以阿里云百炼系为例）
`official`（官方网关，全部带 `qwen/` 前缀）与 `tokenplan`（Token Plan 网关）命名不同；
其他平台（OpenAI / DeepSeek / 智谱 / SiliconFlow / OpenRouter / Ollama / Azure …）的模型标识与能力覆盖见 `GET /api/providers`。

| 能力 | `official` | `tokenplan` | 调用端点 |
|---|---|---|---|
| ① 同款一致性比对（VL 直接判同款） | `qwen/qwen3-vl-plus` | 同左 | `POST /v1/chat/completions` |
| ② 瑕疵视觉识别 + 红框定位 | `qwen/qwen3-vl-plus` | 同左 | `POST /v1/chat/completions` |
| ③ Listing 承诺提取（OCR） | `qwen/qwen-vl-ocr` | 同左 | `POST /v1/chat/completions` |
| ④ 卷宗 / 陈述 / 聚类归因 | `qwen/qwen3.7-max` | `qwen3.7-max`（无前缀） | `POST /v1/chat/completions` |
| ⑤ 案件优先级排序 | `qwen/qwen3-rerank` | `qwen3-rerank` | `POST /v1/rerank` |
| ⑥ 母语语音陈述 | `qwen/qwen3-tts-instruct-flash` | `qwen-audio-3.0-tts-plus` | `POST /v1/audio/speech` |
| （备选）图像向量 | `qwen/tongyi-embedding-vision-plus` | 同左 | `POST /v1/embeddings` |

> - 模型标识单一来源：`demo/models_router.py` 的 `_MODEL_ROUTER_PROFILES`，由 `MODELS[...]` 统一下发。
> - `qwen-audio-3.0-tts-plus` **不在** `ModelRouter_API.docx` 的官方模型名单内；官方 TTS 仅有 `qwen/qwen3-tts-instruct-flash`，对外材料以 `official` 为准。
> - 洞察层（聚类归因 / 选品建议）复用文本模型；`demo/compare_models.py` 中的 `deepseek-v4-pro` / `kimi-k2.6` / `glm-5.2` 仅供对比实验，不在线上链路。
> - 模型清单与更多端点（图片 / 视频生成、ASR 等）见参考文档 `ModelRouter_API.docx`。

### 5.4 各能力调用详情（引用 ModelRouter_API.docx）

**① 同款一致性 —— 主路径走 VL，不依赖视觉向量**
线上主路径为 `qwen/qwen3-vl-plus` **同时看退回件与本店主图直接判同款**（更贴合「调包 / 同款」的业务判定）。原因是百炼 OpenAI 兼容模式不支持视觉向量模型。图像向量 `POST /v1/embeddings` 仅在通道开通后作备选；再不可用时回退到与 mock **同口径**的内容哈希（`demo/imghash.py` 的 `content_seed()`），保证两端结果一致。

图像入参：`models_router._img_source` 统一把来源规范为
- `data:image/...` → 原样透传；
- 本地文件路径 → 读文件转 **base64 data URI**（默认路径，无需公网可达）；
- `http(s)://` → 原样透传（配了 `PUBLIC_IMAGE_BASE` / `self` / `qiniu` 时）。

**② 瑕疵识别 —— `POST /v1/chat/completions`**
```json
{ "model": "qwen/qwen3-vl-plus", "stream": false,
  "messages": [{ "role": "user", "content": [
    { "type": "text", "text": "列出视觉瑕疵，逗号分隔简短中文标签" },
    { "type": "image_url", "image_url": { "url": "<公网图片URL>" } } ] }] }
```
返回 `choices[0].message.content`（文本标签）。若视觉模型支持检测框坐标，则同时解析为 `defect_boxes`（归一化 `{x,y,w,h}`），前端据此在退货图上绘制真实红框；不支持时由 pipeline 生成确定性示意框兜底。

**③ Listing 承诺提取 —— `POST /v1/chat/completions`**
模型 `qwen/qwen-vl-ocr`，messages 仅含 `image_url`，返回图文承诺文本。

**④ 文本生成 / 聚类归因 —— `POST /v1/chat/completions`**
模型 `qwen/qwen3.7-max`，`stream: false`。洞察归因使用 `llm_json()` 稳健抽取 JSON（兼容 `deepseek` / `qwen3.6+` 的 `<think>` 包裹）。
> 注：`deepseek` / `qwq` 系列**仅支持 stream**，本服务统一用 `qwen/qwen3.7-max` 保证同步可用。tokenplan 自测网关下该模型名为无前缀的 `qwen3.7-max`。

**⑤ 优先级重排 —— `POST /v1/rerank`**
```json
{ "model": "qwen/qwen3-rerank", "query": "<追回价值描述>",
  "documents": ["案件A描述", "案件B描述"] }
```
返回 `results[]`。单案优先级采用 **rerank 相关性 50% + 本地可解释公式 50%** 的 5:5 融合（`_PRIORITY_QUERY` 为语义化 query）；网关额度不可用或超时即回退**本地确定性公式**，并在 `capabilities["rerank"]` 如实标注。

**⑥ 母语语音 —— `POST /v1/audio/speech`**
```json
{ "model": "qwen/qwen3-tts-instruct-flash",
  "input": "<陈述文本>", "voice": "Chelsie" }
```
`voice` 取值由 `constants.TTS_VOICES` 单一来源决定；可用语种与音色：

| 语种 | 展示名 | 音色 |
|---|---|---|
| `zh` | 中文 | `Chelsie` |
| `en` | English | `Ethan` |
| `es` | Español | `Serena` |
| `pt` | Português | `Serena` |
| `de` | Deutsch | `Ethan` |
| `fr` | Français | `Serena` |
| `ja` | 日本語 | `Chelsie` |
| `ko` | 한국어 | `Serena` |

`/api/analyze` 传 `language=<code>` 即按上表选音色；非法值 → `400`。返回音频二进制（本服务 base64 编码为 `voice_audio_b64`）。

### 5.5 live 模式流程与回退
```
live_analyze:
  校验当前平台的密钥（key_required=false 的平台如 ollama 跳过）
  → 图片内联为 base64 data URI（无需公网图床）
  → 每个能力先过「能力闸」：平台未声明该能力 → 直接抛错 → 该能力标记回退
  → ① VL 双图判同款（备选：embeddings + 余弦）
  → ② vl_detect_boxes 瑕疵 + 红框 → ③ ocr 承诺
  → ④ llm 一致性 + 卷宗 + 陈述 → ⑥ tts 语音 → ⑤ rerank 优先级
  → 逐能力 try/except：任一不可用仅该步回退，其余仍真实
  → 全部失败 → pipeline 回退 _mock，mode="mock(fallback)" + error
  → capabilities 字典如实标注每步 真实 / 回退

build_insights_live(aggregated):
  将 pipeline._aggregate 的统计喂给当前平台的文本模型（JSON 输出）
  → {root_cause, sku_insights, recommendations, report}
  → _reconcile_insights 校验 LLM 数值与真实聚合一（P2-14 防幻觉），超阈回退 mock 归因
  → 异常回退 mock 归因（失败结果不写缓存）
```

### 5.6 配置与开通
- live 模式**必需**：当前平台声明的密钥变量（见 `GET /api/providers` 的 `key_env`；`ollama` 等本地端点不需要）。
- **可选**：`PUBLIC_IMAGE_BASE` / `RG_SELF_IMAGE_BASE` / `IMAGE_BED`——仅在希望走公网回源取图时才配置；默认内联 base64，无需对象存储。
- **可选**：`RG_MODEL_*` 逐能力覆盖模型标识；各平台基地址覆盖变量互相独立。
- 逐能力渐进开通：平台开通哪个模型，对应能力即自动变真，`capabilities` 会如实反映；未开通/不支持的 能力仅该步回退，其余不受影响。
- 无 Key（或密钥缺失）时接口自动以 mock 模式运行，功能不中断。
- SEC-13 配额：`LIVE_QUOTA_GLOBAL_DAY` / `LIVE_QUOTA_TENANT_DAY` / `LIVE_QUOTA_IP_HOUR`（置 `0` 关闭该层），超限 `429` 且**不静默降级**。该闸门同时覆盖 `/api/analyze`、`/api/insights?mode=live` 与 `/api/export_pdf?mode=live`（2.0.0 前仅覆盖 `/api/analyze`，洞察与导出可绕过）。

---

## 6. 安全（安全复审闭环，SEC-1~13 全清零）

公网部署语境下，安全发现项 **SEC-1 ~ SEC-13（另含 SEC-P0 系列）已全部清零**。设计要点：

- **鉴权**：写接口须登录会话（`_require_session`）；管理端点须 `ADMIN_API_KEY` 或登录（`_require_admin`）。令牌为无状态 HMAC 签名（7 天过期），经 `Authorization: Bearer` / `X-Token` 头传递；`?token=` 查询参数已停用（SEC-4）。
- **令牌密钥**：`AUTH_SECRET` 从 `.env` 加载（修复 dotenv 顺序 bug，SEC-2）；生产必设，否则每次重启令牌失效。支持 `secrets.token_hex(32)` 配置。
- **PII 收敛（SEC-8）**：客户退货图不再经 `/uploads` 公开挂载，改为 HMAC 签名 + TTL 短链 `/api/file/{sig}`；伪造/过期/枚举均返回 `404`，不泄露文件是否存在。自托管 `self` 图床另用 256-bit 不可猜测 key（SEC-P0）。
- **CSP（SEC-9）**：前端已外置为同源 ES module，由 `script-src 'self'` 放行；首页**每请求仍生成 nonce**（保留机制，防将来回嵌内联脚本）。`script-src` 去除 `unsafe-inline`；另含 `default-src 'self'`、`img-src 'self' data: https:`、`object-src 'none'`、`base-uri 'self'`、`frame-ancestors 'none'`、`X-Content-Type-Options: nosniff`、`Referrer-Policy` 等响应头。非 `/` 路由亦已收紧（SEC-P0）。
- **限流 / 防爆破（SEC-3/12）**：按客户端真实 IP（反向代理 / CDN 取 `CF-Connecting-IP`）限流；登录失败按滑动窗口封禁（`LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN`）。限流与登录锁状态外置为独立 SQLite（`rg_state.db`，`shared_state.py`），**多 worker 下一致**。
- **live 配额闸（SEC-13）**：`demo/quota.py` 三层闸门（全局日 / 账号日 / IP 小时），仅拦 `mode=live`，超限 `429` + 明确文案，**不静默降级**；覆盖分析、洞察与报告导出三条付费链路。计数库持久化于 named volume，重建容器不清零。
- **口令存储（SEC-10）**：pbkdf2 提至 **60 万轮**；未知用户也跑等代价哈希，消除用户枚举时序差；存量账户登录时渐进 rehash 升级。
- **密钥比较（SEC-11）**：API Key / 管理员密钥比较改用 `hmac.compare_digest`（常量时间）。
- **多 worker（SEC-12）**：聚合代际计数落库 `rg_kv`；限流/登录锁外置 `shared_state`。单 worker 演示零配置即可；多实例部署状态不再割裂。
- **数据库不对外（SEC-13 配套）**：compose 中 openGauss **仅监听本机回环**（原 `5432:5432` 等价暴露到 0.0.0.0，已改）。

> 实测：匿名写接口 → `401`；`/metrics` 匿名 → `401`（带 `ADMIN_API_KEY` → `200`）；匿名 `/uploads/任意` → `404`；签名短链有效 → `200`、伪造/过期 → `404`；5 次错密码 → 第 6 次 `429` 且锁定期内正确密码亦 `429`；live 超配额 → `429`。详见 `docs/CODE_REVIEW.md` 第八~十节。
