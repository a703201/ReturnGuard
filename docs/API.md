# ReturnGuard 接口文档（API.md）

> **服务**：ReturnGuard Demo（FastAPI）
> **最后更新**：2026-08-16
> **关联文档**：`docs/PRD.md`、`ModelRouter_API.docx`（模型能力参考）

---

## 1. 概述
- **本地 Base URL**：`http://localhost:8000`
- **前端页面**：`GET /` 返回「退货情报站」HTML 页面（上半部洞察看板、下半部单案举证入口）。
- **数据格式**：JSON（`/api/analyze` 除外，为 `multipart/form-data`）。
- **双模式**：多数接口支持 `mode=mock|live`，默认 `mock`。

---

## 2. 通用约定
- **金额**：单位 ¥（float）；**日期**：`YYYY-MM-DD`。
- **错误响应**：HTTP 状态码 + FastAPI 默认 `{ "detail": "..." }`。
- **live 回退**：live 模式失败时**不报 5xx**，返回 `200` 并带 `mode="mock(fallback)"` 与 `error` 字段，保证前端不中断。
- **兼容键**：`/api/insights` 始终返回 `total_cases` / `sku_ranking` / `defect_distribution`，前端无需按模式分支。

---

## 3. 接口

### 3.1 `GET /`
返回前端页面（`text/html`）。

---

### 3.2 `POST /api/analyze` —— 阶段 A 个案举证
**Content-Type**：`multipart/form-data`

**请求参数**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `returned_image` | form-data(file) | file | 是 | 退回商品图 |
| `product_image` | form-data(file) | file | 是 | 本店主图 / 详情图 |
| `listing_text` | form-data | string | 否 | 本店文字承诺（默认 `""`） |
| `sku` | form-data | string | 否 | SKU（默认 `"SKU-未知"`） |
| `amount` | form-data | float | 否 | 订单金额 ¥（默认 `0.0`） |
| `mode` | form-data | string | 否 | `mock`（默认）/ `live` |

**响应字段（200, application/json）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 本次取证案件 ID（uuid 前 8 位） |
| `similarity` | number | 同款一致性相似度（0~1） |
| `same_item` | bool | ≥0.82 视为同一件 |
| `defect_tags` | string[] | 瑕疵标签（如「功能故障」「无明显瑕疵」） |
| `defect_description` | string | 瑕疵标签拼接 |
| `consistency` | string | 与 listing 承诺一致性结论 |
| `dossier` | string | 结构化举证报告文本 |
| `voice_text` | string | 母语口头陈述文本 |
| `voice_audio_b64` | string | 语音音频（base64，mock 为占位 WAV） |
| `priority_score` | number | 案件优先级评分（0~1，越高越先处理） |
| `defect_boxes` | object[] | 缺陷区域示意框（归一化坐标 `{label,x,y,w,h}`，0~1）；live 接通后由视觉模型返回真实检测框，mock 为确定性占位 |
| `returned_image_b64` | string | 退回商品图 base64（前端叠加红框标注用） |
| `mode` | string | `mock` / `live` / `mock(fallback)` |
| `error` | string | 仅回退时出现，失败原因 |

**示例（mock）**
```bash
curl -F "returned_image=@ret.jpg" -F "product_image=@prod.jpg" \
     -F "sku=SKU-123" -F "amount=89.9" -F "mode=mock" \
     http://localhost:8000/api/analyze
```

**示例（live）**
```bash
curl -F "returned_image=@ret.jpg" -F "product_image=@prod.jpg" \
     -F "sku=SKU-123" -F "amount=89.9" -F "mode=live" \
     http://localhost:8000/api/analyze
```

---

### 3.3 `GET /api/insights` —— 阶段 B 群体洞察
**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `mode` | string | 否 | `mock`（默认）/ `live` |
| `category` | string | 否 | 按品类下钻 |
| `platform` | string | 否 | 按平台下钻 |

**响应字段（200, application/json）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `total_cases` | int | 案件总数 |
| `total_refund` | number | 累计退款额 ¥ |
| `win_rate` | number | 胜诉率（0~1） |
| `avg_dispute_rate` | number | 平均纠纷率（1−平均相似度） |
| `outcome_dist` | object | 结果分布 |
| `sku_ranking` | object[] | SKU 纠纷明细（退款额排序，含 `anomaly` 标记） |
| `defect_distribution` | object | 缺陷分布 |
| `category_heatmap` | object[] | 品类退货热力 |
| `supplier_scorecard` | object[] | 供应商红黑榜（质量分 + 等级） |
| `platform_view` | object[] | 平台胜诉对比 |
| `platform_supplier_matrix` | object[] | 平台×供应商交叉视图（每格含 `win_rate`/`cases`/`refund`，前端画交叉热力） |
| `root_cause_dist` | object | 根因分布 |
| `anomaly_alerts` | object[] | 近 30 天异常预警 |
| `sourcing_advice` / `recommendations` | string[] | 选品 / 品控建议 |
| `report` | string | 洞察报告正文 |
| `root_cause` | string | 根因结论（live 由 LLM 生成） |
| `sku_insights` | object[] | Top SKU 洞察（live 由 LLM 生成） |
| `mode` | string | `mock` / `live` / `mock(fallback)` |

**示例**
```bash
curl "http://localhost:8000/api/insights?mode=live&category=3C"
```

---

### 3.4 `GET /api/cases` —— 案件库
返回已沉淀案件数组（`application/json`），用于调试 / 演示验证。

```bash
curl http://localhost:8000/api/cases
```

---

## 4. 数据模型

### 4.1 Case 对象（单笔退货）
| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 案件 ID |
| `sku` | string | SKU |
| `amount` | number | 订单金额 ¥ |
| `category` | string | 品类 |
| `supplier` | string | 供应商 |
| `platform` | string | 平台 |
| `similarity` | number | 同款一致性相似度 |
| `same_item` | bool | 是否同一件 |
| `defect_tags` | string[] | 瑕疵标签 |
| `consistency` | string | 一致性结论 |
| `outcome` | string | 仲裁结果（如「赢」） |
| `date` | string | 日期 `YYYY-MM-DD` |

### 4.2 Insights 对象
见 §3.3 响应字段表（`build_insights` 聚合输出）。

---

## 5. ModelRouter 集成（专项）

### 5.1 概述
live 模式经**阿里云百炼 Model Router** 调用多模态大模型，协议兼容 OpenAI。所有调用封装在 `demo/models_router.py`，由 `pipeline` 在 live 模式下编排。

### 5.2 基础信息
- **Base URL**：`https://model-router.edu-aliyun.com/v1`
- **认证**：`Authorization: Bearer <MODEL_ROUTER_API_KEY>`
- **必需环境变量**：
  - `MODEL_ROUTER_API_KEY`：赛事发放的算力 Key。
  - `PUBLIC_IMAGE_BASE`：上传图片可**公网访问**的基础 URL（Model Router 服务端回源拉图，localhost 不可达）。

### 5.3 模型能力映射表
| 能力 | 模型标识 | 调用端点 |
|---|---|---|
| ① 同款一致性比对 | `qwen/tongyi-embedding-vision-plus` | `POST /v1/embeddings` |
| ② 瑕疵视觉识别 | `qwen/qwen3-vl-plus` | `POST /v1/chat/completions` |
| ③ Listing 承诺提取 | `qwen/qwen-vl-ocr` | `POST /v1/chat/completions` |
| ④ 卷宗 / 陈述 / 聚类归因 | `qwen/qwen3-max`（可选 `deepseek-r1`） | `POST /v1/chat/completions` |
| ⑤ 案件优先级排序 | `qwen/qwen3-rerank` | `POST /v1/rerank` |
| ⑥ 母语语音陈述 | `qwen/qwen3-tts-instruct-flash` | `POST /v1/audio/speech` |

> 模型清单与更多端点（图片 / 视频生成、ASR 等）见参考文档 `ModelRouter_API.docx`。

### 5.4 各能力调用详情（引用 ModelRouter_API.docx）

**① 同款一致性 —— `POST /v1/embeddings`**
```json
{ "model": "qwen/tongyi-embedding-vision-plus",
  "input": { "image": "<公网图片URL>" } }
```
返回 `data[0].embedding`（float[]），两图向量取**余弦相似度**得 `similarity`。

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
模型 `qwen/qwen3-max`，`stream: false`。洞察归因使用 `llm_json()` 稳健抽取 JSON（兼容 `deepseek-r1` 的 `<think>` 包裹）。
> 注：`deepseek-r1` / `qwq` 系列**仅支持 stream**，本服务统一用 `qwen3-max` 保证同步可用。

**⑤ 优先级重排 —— `POST /v1/rerank`**
```json
{ "model": "qwen/qwen3-rerank", "query": "<追回价值描述>",
  "documents": ["案件A描述", "案件B描述"] }
```
返回 `results[]`；赛事未发放额度时 `pipeline` 退化为本地公式。

**⑥ 母语语音 —— `POST /v1/audio/speech`**
```json
{ "model": "qwen/qwen3-tts-instruct-flash",
  "input": "<陈述文本>", "voice": "Chelsie" }
```
`voice` 可用：`Chelsie` / `Ethan` / `Serena`；返回音频二进制（本服务 base64 编码为 `voice_audio_b64`）。

### 5.5 live 模式流程与回退
```
live_analyze:
  校验 API_KEY / PUBLIC_IMAGE_BASE → 组装双图公网 URL
  → ① embed 双图 + 余弦 → ② vl_chat 瑕疵 → ③ ocr 承诺
  → ④ llm 一致性 + 卷宗 + 陈述 → ⑥ tts 语音 → ⑤ 优先级公式
  → 任意异常 → pipeline 回退 _mock，mode="mock(fallback)" + error

build_insights_live(aggregated):
  将 pipeline._aggregate 的统计喂给 qwen3-max（JSON 输出）
  → {root_cause, sku_insights, recommendations, report}
  → 异常回退 mock 归因
```

### 5.6 配置与开通
- live 模式需在运行环境注入 `MODEL_ROUTER_API_KEY` 与 `PUBLIC_IMAGE_BASE`（Docker 见 `docker/.env.example`）。
- 图片须置于对象存储（如阿里云 OSS）并配置公网可读地址；localhost 图片 Model Router 无法回源。
- 无 Key / 无图床时，接口自动以 mock 模式运行，功能演示不中断。
