# 多 AI 平台接口适配与兼容说明（AI_PROVIDERS）

> 适用版本：2.1.2（仓库根 `VERSION` 为单一来源）
> 代码单一来源：[`demo/providers.py`](../demo/providers.py)（平台声明）、[`demo/models_router.py`](../demo/models_router.py)（能力调用）
> 关联文档：[`DECISION_LOGIC.md`](DECISION_LOGIC.md)、[`ARCHITECTURE.md`](ARCHITECTURE.md)、[`API.md`](API.md)

---

## 1. 设计原则

| 原则 | 说明 |
|---|---|
| **按能力编程，不按厂商编程** | 业务代码只声明「我要做视觉理解 / 语音合成」，不关心是谁提供的。厂商差异全部收敛在 `providers.py` 的声明里 |
| **配置即接口契约** | 新增一个平台 = 在注册表加一条声明（地址 / 鉴权 / 模型 / 能力），**不改任何调用代码** |
| **能力缺口如实声明** | 平台不提供某项能力时标记为不支持，运行期由「能力闸」拦下并标记回退——绝不配一个必然 404 的模型名来假装支持 |
| **密钥只来自环境变量** | 注册表不含任何凭据；公开接口不泄露基地址、模型标识与密钥状态 |
| **一切可覆盖** | 模型名与基地址都可经环境变量覆盖，平台改版无需改代码 |

---

## 2. 六类能力（业务语义）

| 能力 | 业务用途 | 请求形状 | 关键约束 |
|---|---|---|---|
| `text` | 一致性结论、举证卷宗、母语陈述、洞察归因 | `POST {base}/chat/completions`，`{model, messages, stream:false}` | 要求**同步**可用（部分推理模型仅支持 stream，故默认选同步模型） |
| `vl` | 瑕疵识别、双图判同款、缺陷红框定位 | `POST {base}/chat/completions`，content 为 `[{type:text},{type:image_url,image_url:{url}}]` | 需支持多图入参（双图对比） |
| `ocr` | 提取本店图文承诺，做货不对板核验 | 同 `vl` 的 chat 形状，提示词要求"提取图中文字" | 通常复用 `vl` 模型，也可用专用 OCR 模型 |
| `embed` | 退回件 vs 主图的**图像**向量相似度 | `POST {base}/embeddings`，`{model, input:{"image":<dataURI>}}` | ⚠️ 这是百炼视觉向量的**扩展形状**；**文本**嵌入模型不适用本能力（见 §4.3） |
| `rerank` | 单案优先级（与本地公式 5:5 融合） | `POST {base}/rerank`，`{model, query, documents}` | 需返回 `results[].relevance_score` |
| `tts` | 母语语音陈述 | `POST {base}/audio/speech`，`{model, input, voice}` | 需返回音频二进制（服务端 base64 编码后回传） |

> 图像入参统一由 `models_router._img_source()` 归一化为 **base64 data URI 内联**（本地路径 → 内联；
> `http(s)://` 原样透传）。因此**本机直跑也能跑通视觉能力**，不依赖公网图床。

---

## 3. 支持矩阵（由 `providers.py` 实测导出）

| 平台 (`MODEL_ROUTER_PROFILE`) | 展示名 | 协议 | 密钥变量 | text | vl | ocr | embed | rerank | tts | 本仓已验证 |
|---|---|---|---|---|---|---|---|---|---|---|
| `tokenplan` | 阿里云百炼 · Token Plan 网关 | `openai` | `MODEL_ROUTER_API_KEY` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `official` | 阿里云百炼 · 官方 Model Router | `openai` | `MODEL_ROUTER_OFFICIAL_KEY` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `dashscope` | 阿里云百炼 · 国内站按量付费 | `openai` | `DASHSCOPE_API_KEY` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `openai` | OpenAI | `openai` | `OPENAI_API_KEY` | ✅ | ✅ | ✅ | — | — | ✅ | — |
| `deepseek` | DeepSeek | `openai` | `DEEPSEEK_API_KEY` | ✅ | — | — | — | — | — | — |
| `moonshot` | Moonshot AI（Kimi） | `openai` | `MOONSHOT_API_KEY` | ✅ | ✅ | ✅ | — | — | — | — |
| `zhipu` | 智谱 AI（GLM） | `openai` | `ZHIPU_API_KEY` | ✅ | ✅ | ✅ | — | ✅ | — | — |
| `siliconflow` | SiliconFlow（硅基流动） | `openai` | `SILICONFLOW_API_KEY` | ✅ | ✅ | ✅ | — | ✅ | ✅ | — |
| `openrouter` | OpenRouter（多模型聚合） | `openai` | `OPENROUTER_API_KEY` | ✅ | ✅ | ✅ | — | — | — | — |
| `ollama` | Ollama（本机 / 内网自托管） | `openai` | `OLLAMA_API_KEY`（**可留空**） | ✅ | ✅ | ✅ | — | — | — | — |
| `azure_openai` | Azure OpenAI | `azure` | `AZURE_OPENAI_API_KEY` | ✅ | ✅ | ✅ | — | — | ✅ | — |
| `anthropic` | Anthropic Claude（原生 Messages API） | `native` | `ANTHROPIC_API_KEY` | — | — | — | — | — | — | — |
| `gemini` | Google Gemini（原生 generateContent） | `native` | `GEMINI_API_KEY` | — | — | — | — | — | — | — |
| `custom` | 自建 / 其他 OpenAI 兼容端点 | `openai` | `RG_CUSTOM_API_KEY` | 需自配 | 需自配 | 需自配 | 需自配 | 需自配 | 需自配 | — |

说明：

- **「本仓已验证」** = 用真实 Key 跑通过 live 链路。其余为**配置模板**：地址 / 鉴权 / 能力矩阵按公开文档填写，
  但**模型标识随平台版本变动，请按控制台实际可用项用 `RG_MODEL_*` 覆盖**。
- `custom` 六个能力默认留空 = 未配置 → 运行期判为「不支持」并如实回退；用 `RG_MODEL_*` 声明后才生效。
- `ollama` 的 `key_env` 仅用于一致的结构，实际 `key_required=false`（本地推理无需密钥）。
- `anthropic` / `gemini` 的原生协议与 OpenAI 形状不同，本适配层**不直接对接**（见 §4.4）。

---

## 4. 对接方式与差异适配

### 4.1 请求 / 响应形状（OpenAI 兼容族）

```jsonc
// ① text：文本生成
POST {base}/chat/completions
{ "model": "…", "messages": [{"role":"user","content":"…"}], "stream": false }
→ { "choices": [ { "message": { "content": "…" } } ] }

// ② vl：视觉理解（可传多张图）
POST {base}/chat/completions
{ "model": "…", "temperature": 0, "messages": [ { "role":"user", "content": [
    { "type": "text", "text": "列出视觉瑕疵，逗号分隔" },
    { "type": "image_url", "image_url": { "url": "data:image/png;base64,…" } },
    { "type": "image_url", "image_url": { "url": "data:image/png;base64,…" } }   // 第二张=双图对比
] } ] }

// ③ embed：图像向量（⚠️ 百炼扩展形状，非 OpenAI 标准）
POST {base}/embeddings
{ "model": "…", "input": { "image": "data:image/png;base64,…" } }
→ { "data": [ { "embedding": [ … ] } ] }

// ④ rerank
POST {base}/rerank
{ "model": "…", "query": "…", "documents": ["…"] }
→ { "results": [ { "relevance_score": 0.83 } ] }

// ⑤ tts
POST {base}/audio/speech
{ "model": "…", "input": "陈述文本", "voice": "Chelsie" }
→ 音频二进制（服务端转 base64）
```

**响应解析的兼容处理**：文本类调用统一兼容 `choices[0].message.content` 与
`message.reasoning_content`（部分推理模型把思考放在后者、`content` 为空）；
JSON 抽取（`_extract_json`）兼容 markdown 围栏、`<think>` 思考链、截断与多段 JSON。

### 4.2 鉴权差异

| 风格 | 头 | 使用平台 |
|---|---|---|
| `bearer`（默认） | `Authorization: Bearer <KEY>` | 除 Azure 与本地外的全部平台 |
| `api-key` | `api-key: <KEY>` | Azure OpenAI |
| `none` | 无 | Ollama 等本地端点 |

### 4.3 能力语义差异（最容易踩的一类）

| 差异 | 说明 | 处理 |
|---|---|---|
| **`embed` 是「图像向量」而非文本向量** | 请求体为 `{"input": {"image": …}}`（百炼视觉向量扩展）。OpenAI `text-embedding-3-*`、`bge-m3`、`nomic-embed-text` 都只能嵌入**文本**，与本能力用途不符 | 因此**未在那些平台声明 `embed`**；需要图像向量时请用百炼系，或自建兼容服务并选 `custom` |
| `rerank` 端点并非人人都有 | OpenAI / DeepSeek / Moonshot / OpenRouter / Ollama 无 rerank HTTP 接口 | 如实声明不支持，运行期回退**本地可解释公式** |
| `tts` 端点形状各异 | 智谱等平台的语音走独立协议（非 OpenAI `/audio/speech`） | 声明不支持；如需可经兼容网关（`custom`）接入 |
| 多图入参支持度不同 | 双图对比（瑕疵识别 / 判同款）需要平台支持一次传多张图 | 不支持时该能力调用会失败并回退，`capabilities` 如实标注 |
| 模型标识命名风格 | 百炼 official 必须带 `qwen/`；Ollama 用 `模型:标签`；SiliconFlow 用 `org/model`；OpenRouter 用 `厂商/模型` | 已按平台固化在注册表，切换平台时**模型标识与 base_url、key 联动切换** |

### 4.4 URL 形状差异

| 风格 | 拼接规则 | 使用平台 |
|---|---|---|
| `openai` | `{base}/{segment}`，segment ∈ `chat/completions` `embeddings` `rerank` `audio/speech` | 大多数平台 |
| `azure` | `{base}/openai/deployments/{部署名}/{segment}?api-version={版本}` | Azure OpenAI（模型字段填**部署名**；`AZURE_OPENAI_API_VERSION` 默认 `2024-10-21`） |
| `native` | 不处理，直接抛错 | Anthropic / Gemini——原生协议（`x-api-key` + `anthropic-version` / `generateContent`）与 OpenAI 形状不同，本适配层**刻意不做半成品适配** |

**要用 Anthropic / Gemini 怎么办**：在其前面加一层 OpenAI 兼容网关
（如 one-api、LiteLLM、vLLM 的兼容模式），然后把 `MODEL_ROUTER_PROFILE=custom`、
`RG_CUSTOM_BASE_URL` 指向该网关，并用 `RG_MODEL_*` 声明模型即可——这样「协议转换」交给专业网关，
本服务保持只对接一种稳定形状（减少维护面与出错面）。

### 4.5 自建 / 私有化接入

支持任意 OpenAI 兼容服务（vLLM、TGI、one-api、LiteLLM、自研网关）：

```bash
export MODEL_ROUTER_PROFILE=custom
export RG_CUSTOM_BASE_URL=http://10.0.0.5:8000/v1
export RG_CUSTOM_API_KEY=local-any        # 若网关不校验可留空
export RG_MODEL_TEXT=qwen2.5-7b-instruct
export RG_MODEL_VL=qwen2.5-vl-7b
# …其余能力按网关实际支持声明；未声明的能力运行期判为「不支持」并回退
```

> 选择 `ollama` 或 `custom` 指向内网服务时，**数据完全不出境**，是合规要求高的场景的推荐形态。

---

## 5. 切换与覆盖

### 5.1 切换平台

只改一个变量，`base_url` + 密钥 + 模型标识三者随平台声明联动：

```bash
export MODEL_ROUTER_PROFILE=dashscope     # 值 = /api/providers 返回的 key
# 兼容别名（等价，优先级低于 MODEL_ROUTER_PROFILE）：
export RG_AI_PROVIDER=dashscope
```

> ⚠️ 变量名 `MODEL_ROUTER_PROFILE` 是历史命名（最初只有百炼网关），语义上就是「AI 平台」。

### 5.2 覆盖优先级

| 配置项 | 覆盖变量 | 说明 |
|---|---|---|
| 基地址 | 各平台独立变量（`OPENAI_BASE_URL` / `DASHSCOPE_BASE_URL` / `RG_CUSTOM_BASE_URL` / `OLLAMA_BASE_URL` …） | **每个平台用各自的覆盖变量**，避免某平台的地址污染其它平台（历史踩坑：tokenplan 的 `MODEL_ROUTER_BASE_URL` 曾把 official/dashscope 端点改错） |
| 模型 | `RG_MODEL_TEXT` / `RG_MODEL_VL` / `RG_MODEL_OCR` / `RG_MODEL_EMBED` / `RG_MODEL_RERANK` / `RG_MODEL_TTS` | 逐能力覆盖，优先级最高 |
| 模型（历史变量） | `MODEL_ROUTER_TEXT_MODEL` | 仅覆盖文本模型，保留向后兼容 |
| 密钥 | 平台声明的 `key_env` | 例如 `OPENAI_API_KEY`、`ZHIPU_API_KEY` |

覆盖技巧：某平台只差一个模型名时**不必新增平台**，用 `RG_MODEL_*` 覆盖即可。

---

## 6. 失败与缺口的处理（不静默、不伪装）

```
能力调用
  ├─ 平台未声明该能力 → 能力闸抛错 ─┐
  ├─ 网关 4xx          → 直接抛错  ├─→ live_analyze 逐能力 try/except
  ├─ 网关 429 / 5xx    → 重试后退避┘   → capabilities[cap] = false（前端显示「回退」）
  ├─ 网络瞬断 / 超总预算 → 抛 TimeoutError     → mode 按比例给 live(partial) / mock(fallback)
  └─ 连续失败达阈值     → 熔断，冷却期内快速失败  → 避免持续冲击故障网关
```

三条硬约束（有测试守护）：

1. **不静默降级**：`/api/analyze`、`/api/insights?mode=live`、`/api/export_pdf?mode=live` 超配额一律 `429` + 明确原因。
2. **不冒称真实**：`mode` / `capabilities` / `defect_boxes_live` / `degraded` 必须如实反映真实调用情况。
3. **失败回退结果不入缓存**：避免一次瞬时故障被缓存「粘住」导致持续显示失败。

可观测入口：

- `GET /api/providers` —— 平台目录与能力矩阵（**不含**基地址 / 密钥 / 密钥状态，避免匿名探测）；
- `GET /api/config` → `provider` —— 当前平台的展示名、协议风格、能力矩阵、模型映射（供前端如实呈现）；
- `GET /metrics`（需管理员）—— AI 网关调用量 / 错误数 / 平均时延 / token 用量 / 最近错误；
- 启动日志 —— 打印当前平台、端点、密钥是否已配置、可用能力清单。

---

## 7. 新增一个平台：改动清单

1. 在 `demo/providers.py` 的 `PROVIDERS` 增一条 `_p(...)` 声明：
   `label` / `api_style` / `base_url` / `base_url_env` / `key_env` / `auth` / `key_required` / `models` / `doc` / `note`。
   - **只声明平台真正具备的能力**（拿不准就先不声明，运行期会如实回退）；
   - `verified` 保持 `False`，直到你用真实 Key 跑通。
2. 在 `demo/.env.example` 与 `docker/.env.example` 补充该平台的密钥（与覆盖）变量说明。
3. 在本文档 §3 矩阵与 `docs/DEPLOYMENT.md` 的环境变量表各加一行。
4. 跑 `pytest demo/tests/test_providers.py`（注册表完整性 / 能力矩阵 / URL 形状 / 信息泄露收敛会自动校验）。
5. 若要让它成为「已验证」，用真实 Key 跑一次 `live` 取证与 `live` 洞察，并把 `verified` 改为 `True`。

> 不需要改 `models_router.py`、不需要改路由、不需要改前端——这是本层设计的核心收益。

---

## 8. 密钥与合规注意

- **密钥永不入库、永不入前端、永不入镜像**：只经环境变量注入（`.env` 已 gitignore；`.dockerignore` 已排除）。
- **公开接口不泄露拓扑**：`/api/providers` 只说明「有哪些平台、支持哪些能力」，不返回地址与密钥状态。
- **数据出境**：选用国际平台意味着图片/文本会离开本地。
  视觉输入默认内联 base64，因此「内联」不等于「不出境」——真正决定数据边界的是**平台所在区域**。
  合规要求高时请选百炼国内站、`ollama` 或内网 `custom`。
- **本地推理**：`ollama` / 内网 `custom` 是数据零出境方案（代价是模型能力与稳定性自行承担）。
- **计费**：live 链路真实扣费，已加 SEC-13 三层配额闸（全局日 / 租户日 / IP 小时）兜底。
- **重试与熔断**：重试会放大调用量（计费），默认 `LLM_MAX_RETRIES=1`；如网关稳定可调高，如成本敏感可置 `0`。
