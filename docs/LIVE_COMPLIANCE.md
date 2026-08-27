# ReturnGuard · Live 合规清单（阿里云百炼 Model Router）

> 整理日期：2026-08-27
> 依据文档：`ModelRouter_API.docx`（赛事组委会下发的「Model Router API 完整文档说明」）
> 配套代码：`demo/models_router.py`（v1.1.1，本次已做 profile 化改造）
> 结论：**代码侧已具备「一键切换到赛事指定 Model Router」的能力；唯一硬性待办是拿到组委会 Key 并向组委会确认 Token Plan 网关是否被认可。**

---

## 1. 结论速览

| 维度 | 状态 | 说明 |
|---|---|---|
| 官方端点接入 | ✅ 已就绪 | `official` profile 的 `base_url` 固定为 `https://model-router.edu-aliyun.com/v1` |
| 鉴权方式 | ✅ 已就绪 | Bearer Token，与官方一致；`official` 用独立变量 `MODEL_ROUTER_OFFICIAL_KEY` |
| 模型标识命名 | ✅ 本次修复 | 官方全部模型**必须带 `qwen/` 前缀**；已把模型标识按 profile 固化，杜绝错配 |
| 各能力模型映射 | ✅ 已对齐 | 文本/VL/OCR/向量/rerank/TTS 均已映射到官方文档列出的标识 |
| 赛事 Key | ⛔ 待用户提供 | `MODEL_ROUTER_OFFICIAL_KEY` 当前为空 → `/api/config` 显示 `model_router_key_set: False` |
| 合规确认 | ⚠️ 待确认 | Token Plan 网关是否被赛事认可（指南指定用 Model Router），需组委会书面确认 |
| 视觉/向量/rerank 在官方是否开通 | ❓ 待实测 | 文档列出这些模型，但能否在赛事 Key 下调用需拿到 Key 后实测 |

---

## 2. 官方 Model Router 规范要点（摘自 Model Router_API.docx）

- **Base URL**：`https://model-router.edu-aliyun.com/v1`
- **认证**：`Authorization: Bearer <your-api-key>`（赛事 Key，与 Token Plan Key 不通用）
- **协议**：全面 OpenAI 兼容
  - 文本对话：`POST /v1/chat/completions`
  - 图片生成：`POST /v1/images/generations`（新版同步 / 旧版异步）
  - 视频生成：`POST /v1/videos/generations`（异步，轮询 `/v1/tasks/{task_id}`）
  - TTS：`POST /v1/audio/speech`（voice 仅 `Chelsie`/`Ethan`/`Serena`）
  - ASR：`POST /v1/audio/transcriptions`（multipart）
  - 向量：`POST /v1/embeddings`
  - 排序：`POST /v1/rerank`
- **模型命名规则**：**全部带 `qwen/` 前缀**（与 Token Plan 网关的「文本/TTS 无前缀旧命名」不同）。

| 能力 | 官方模型标识（文档列出） |
|---|---|
| 文本旗舰 | `qwen/qwen3.7-max`、`qwen/qwen3-max`、`qwen/qwen3.6-plus` 等 |
| 文本快速 | `qwen/qwen3.6-flash`、`qwen/qwen3.5-flash`、`qwen/qwen-turbo` 等 |
| 视觉理解 | `qwen/qwen3-vl-plus`、`qwen/qwen3-vl-flash`、`qwen/qwen-vl-plus` |
| OCR | `qwen/qwen-vl-ocr`、`qwen/qwen-vl-ocr-latest` |
| 图像向量 | `qwen/tongyi-embedding-vision-plus`、`qwen/qwen3-vl-embedding` |
| 排序(rerank) | `qwen/qwen3-rerank`、`qwen/gte-rerank-v2`、`qwen/qwen3-vl-rerank` |
| TTS | `qwen/qwen3-tts-instruct-flash`（voice: Chelsie/Ethan/Serena） |
| ASR | `qwen/qwen3-asr-flash`、`qwen/paraformer-v2` |

> ⚠️ 文档列出的 TTS 模型是 `qwen/qwen3-tts-instruct-flash`，**不含** ReturnGuard 此前 Token Plan 用的 `qwen-audio-3.0-tts-plus`。切换官方后 TTS 模型必须改。

---

## 3. ReturnGuard 现状逐项核对表

| # | 能力 | 官方模型标识 | 当前代码（official profile） | 状态 | 差距/说明 |
|---|---|---|---|---|---|
| ① | 同款一致性（图向量） | `qwen/tongyi-embedding-vision-plus` | `MODELS["embed"]` = `qwen/tongyi-embedding-vision-plus` | ✅ 一致 | 官方 Key 到位即可测 |
| ② | 瑕疵视觉识别 | `qwen/qwen3-vl-plus` | `MODELS["vl"]` = `qwen/qwen3-vl-plus` | ✅ 一致 | — |
| ②' | 关键帧红框（bbox） | `qwen/qwen3-vl-plus` | 同 ② | ✅ 一致 | 真实 bbox 待视觉模型开通 |
| ③ | listing 承诺提取（OCR） | `qwen/qwen-vl-ocr` | `MODELS["ocr"]` = `qwen/qwen-vl-ocr` | ✅ 一致 | — |
| ④ | 文本生成 / 聚类归因 | `qwen/qwen3.7-max` | `MODELS["text"]` = `qwen/qwen3.7-max`（含 `.env` 遗留无前缀自动补齐） | ✅ 一致 | **本次新增前缀补齐逻辑** |
| ⑤ | 案件优先级排序（rerank） | `qwen/qwen3-rerank` | `MODELS["rerank"]` = `qwen/qwen3-rerank` | ✅ 一致 | 旧代码为无前缀 `qwen3-rerank`，**本次修复** |
| ⑥ | 母语语音（TTS） | `qwen/qwen3-tts-instruct-flash` | `MODELS["tts"]` = `qwen/qwen3-tts-instruct-flash` | ✅ 一致 | 旧代码 `qwen-audio-3.0-tts-plus`，**本次修复** |
| — | 端点 | `model-router.edu-aliyun.com/v1` | `official` base_url | ✅ 一致 | — |
| — | 鉴权 | Bearer | Bearer | ✅ 一致 | 独立 key 变量 |

### 历史漂移（已根治）
- 旧 `models_router.py` 在 `official` profile 下仍会向官方端点发送**无前缀**模型名（`qwen3.7-max` / `qwen-audio-3.0-tts-plus` / `qwen3-rerank`），官方端点将返回「模型不存在 / 404」。
- 根本原因：模型标识写死在调用处，未随 profile 切换。本次已将全部模型标识收口到 `_MODEL_ROUTER_PROFILES[...]["models"]`，并由 `MODELS[...]` 统一下发；文本模型在 official 下对 `.env` 遗留无前缀命名自动补 `qwen/` 前缀。
- **验证**：`MODEL_ROUTER_PROFILE=official` 下 `TEXT_MODEL=qwen/qwen3.7-max`、`tts=qwen/qwen3-tts-instruct-flash`、`rerank=qwen/qwen3-rerank`，模块 `py_compile` 通过；tokenplan 默认值不变，当前公网 Demo 行为零影响。

---

## 4. 仍待办（按优先级）

### P0 — 硬性门槛（需用户资源 / 决策）
1. **拿到组委会 Key**：填入 `demo/.env` 的 `MODEL_ROUTER_OFFICIAL_KEY`（不要与 Token Plan Key 混用）。
   - 填好后 `/api/config` 的 `model_router_key_set` 应变为 `True`，`model_router_profile` 切到 `official`。
2. **向组委会确认 Token Plan 网关合规性**：指南指定核心 AI 须调「Model Router」。当前线上跑的是 Token Plan 专属网关（同属阿里云百炼，但非指南指定端点/Key）。两种处置：
   - 若 Token Plan 被认可：保持现状，仅更新文档措辞；
   - 若必须走指定 Model Router：复赛提交演示前把 `.env` 的 `MODEL_ROUTER_PROFILE` 改为 `official` 并重启，即切到真·官方。

### P1 — 切换后实测（拿到 Key 后）
3. 用 `demo/verify_live.py` 跑 official profile 全链路，确认 ①~⑥ 哪些真实生效、哪些仍回退（逐能力 `capabilities` 标记）。
4. 若官方 Key 下视觉/向量/rerank 已开通，前端「关键帧红框」即从示意框升级为真实坐标——这是决赛讲透的加分点。

### P2 — 文档一致性
5. README 顶部「核心能力 → 模型映射」表已写官方前缀标识，与修复后代码一致，可保留。
6. `demo/README.md` 第 39 行示例提到的 live 模型名需与 `MODEL_ROUTER_PROFILE` 对应（当前示例偏 official，建议加一句「tokenplan 下为无前缀命名」）。

---

## 5. 一键切换操作（复赛提交演示时）

```bash
# 1) 在 demo/.env 填入组委会 Key
MODEL_ROUTER_OFFICIAL_KEY=sk-xxxx          # 赛事指定 Model Router Key
MODEL_ROUTER_PROFILE=official              # 切到官方 profile
# （可选）如要更快：MODEL_ROUTER_TEXT_MODEL=qwen/qwen3.6-flash

# 2) 重启服务（保持 127.0.0.1:65432 + Cloudflare Tunnel）
python -m uvicorn main:app --host 127.0.0.1 --port 65432

# 3) 自检
curl -s localhost:8000/api/config | python -m json.tool   # model_router_profile=official, key_set=True
python verify_live.py                                       # 全链路实测
```

> 当前默认仍为 `tokenplan`，公网体验地址 `https://rg.a703201sworld.top`（demo/demo123）不受影响，直至显式切换。

---

## 6. 评委视角风险

- **风险**：若评委按指南核查「是否调用指定 Model Router」，而线上仍是 Token Plan 网关且 `model_router_key_set=False`，可能被判定为未满足合规项。
- **缓解**：代码已就绪，拿到 Key 后 1 分钟可切；切换后在 `/api/config` 与前端编排链路面板（`capabilities` 真实/回退标记）均可佐证「确为官方 Model Router 驱动」。
- **诚实声明**：无论 tokenplan 还是 official，未开通的模型能力都会**逐能力回退 mock 并如实标注**，不虚构「已调用官方模型」的结果（守住「只取证不裁决」+ 不夸大 AI 能力）。
