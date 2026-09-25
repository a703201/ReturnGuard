# ReturnGuard Demo（最小可运行版）

单笔退货**取证** → 多案聚合**洞察**的双闭环最小实现。前端单页（zh/en/fr 三语）+ FastAPI 后端，`mock` 模式零依赖即可运行，`live` 模式接真实阿里云百炼 Model Router。

## 目录

```
demo/
  main.py            # FastAPI 装配层：app 创建 / 中间件注册 / 路由聚合 / lifespan
                     #   + VersionedStaticFiles（静态资源 URL 版本化 + no-store）
  common.py          # 配置 / 依赖 / 限流 / 中间件 / 聚合辅助（含 SEC-13 配额收口）
  routers/           # 按域拆分（P1-9，替代原 1180 行「上帝文件」）
    frontend.py      #   / 首页 · /health · /api/config · /metrics · /api/platforms
                     #   /api/file/{sig} 签名短链 · /api/img/{key} 自托管取图
    forensic.py      #   /api/analyze 单案取证 · /api/cases 增删查
    insights.py      #   /api/insights 群体洞察 · /api/export_pdf 报告导出
    auth.py          #   /api/auth/{register,login,me,logout}
    calibration.py   #   /api/calibrate 阈值自标定（GET 读 / POST 写）
    import_.py       #   /api/import_csv · /api/import_file 真实数据回流
  pipeline.py        # 取证 + 洞察流水线（mock / live 双模式；含 _roi_backtest）
  models_router.py   # AI 能力调用（按能力，不按厂商；含能力闸与逐能力回退）
  providers.py       # AI 平台注册表（多厂商声明式适配，见 ../docs/AI_PROVIDERS.md）
  auth.py            # 账户/多租户（pbkdf2 60 万轮 + HMAC 签名令牌）
  quota.py           # SEC-13 live 三层配额闸（全局日 / 账号日 / IP 小时）
  shared_state.py    # 限流/登录锁外置 SQLite（多 worker 安全，SEC-12）
  storage.py         # 可插拔图床（local/self/public_base/qiniu）+ 签名短链（SEC-8）
  platforms.py       # 九平台举证规则引擎（平台适配举证包数据源）
  imghash.py         # 图片内容哈希单一口径（mock 与 live 回退共用）
  prompts.py         # 提示词版本 PROMPT_VERSION + 变体注册表（A/B 用）
  ab_experiment.py   # prompt 变体 A/B 台架（可复现对照）
  compare_models.py  # 模型对比实验（非线上链路）
  requirements.txt
  cases.json         # 案件种子库（1206 条演示数据）
  uploads/           # 上传图片落盘（经签名短链 /api/file/{sig} 访问，不再公开挂载）
  static/            # 单页前端（无构建 ESM）
    index.html       #   页面骨架 + i18n 静态接线（data-i18n）+ 首次开启引导 overlay
    app.js           #   入口 / 事件编排（含首启引导、登录态、洞察加载）
    render.js        #   看板渲染（动态文案走 t()）
    store.js         #   全局 state
    api.js           #   fetch 封装（自动带令牌）
    i18n.js          #   zh / en / fr 字典 + t() / setLang() / applyI18n()
    dist/            #   可选压缩产物（SERVE_MINIFIED=1 启用）
  tests/             # 测试套件
```

## 快速开始（mock 模式，无需 Key）

```bash
cd demo
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

> 容器部署见仓库根 `README.md`「快速开始 · 方式二」与 [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md)（映射到 `127.0.0.1:65432`）。
> 默认连 openGauss；无 openGauss 时显式回退 SQLite：`DATABASE_URL=sqlite:///./cases.db`。

- 切到「单案取证」Tab，上传「退回商品图」+「本店主图」→ 点「开始举证」：输出相似度、瑕疵标签、一致性、举证报告、母语语音、优先级，并展示**多模型协同编排链路**（逐能力真实 / 回退）。
- 切到「市场洞察」Tab，或点「刷新看板」：聚合历史案件，展示品类热力、根因归因、供应商红黑榜、平台 × 供应商交叉、预测预警、ROI 回测、选品建议。
- mock 相似度由**图片内容哈希**决定（`imghash.content_seed`），**同一对图结果可复现**。
- 顶栏可切换界面语言（中文 / English / Français）。
- **首次打开会弹出使用引导**（5 步：定位 / 数据与登录 / 页面导览 / AI 通路与诚实性 / 边界与隐私），
  可跳过、可勾选「不再自动显示」；顶栏「使用引导」按钮可随时重开。

## live 模式（接真实 AI 平台）

只需选平台 + 填该平台的密钥：

```bash
export MODEL_ROUTER_PROFILE=tokenplan        # 平台标识
export MODEL_ROUTER_API_KEY=sk-xxx           # 该平台的密钥（详见 providers.py 的 key_env）
```

> **图片无需公网可达**：视觉输入默认由 `models_router._img_source` 转成 **base64 data URI 内联**发送，本机直跑即可。
> `PUBLIC_IMAGE_BASE`（或 `RG_SELF_IMAGE_BASE` / `IMAGE_BED`）为**可选增强**——仅当希望走「公网 URL 回源」时才配置对象存储或自托管反向代理。

可选平台（改 `MODEL_ROUTER_PROFILE` 即切换；完整矩阵与差异见 [`../docs/AI_PROVIDERS.md`](../docs/AI_PROVIDERS.md)
或运行时 `GET /api/providers`）：

| 平台 | 说明 |
|---|---|
| `tokenplan`（默认）/ `official` / `dashscope` | 阿里云百炼系，六类能力齐全（本仓已实跑验证） |
| `openai` / `azure_openai` | OpenAI / Azure（无 rerank 端点） |
| `deepseek` | 仅文本对话 |
| `moonshot` / `zhipu` | Kimi / GLM |
| `siliconflow` / `openrouter` | 硅基流动 / 聚合平台 |
| `ollama` | 本机或内网推理，**免密钥、数据零出境** |
| `custom` | 任意 OpenAI 兼容自建端点（vLLM / one-api / LiteLLM…），用 `RG_MODEL_*` 声明各能力模型 |

前端模式选 `live` 即可走真实链路。平台未提供的能力会被**能力闸**拦下并如实标记为回退
（例如 DeepSeek 平台下只有文本是真实的，视觉/OCR/语音/重排均回退确定性结果）。

> ⚠️ 命名差异：百炼 tokenplan 下文本为 `qwen3.7-max`、TTS 为 `qwen-audio-3.0-tts-plus`（无 `qwen/` 前缀）；
> official 下**必须带 `qwen/` 前缀**；Ollama 用 `模型:标签`；SiliconFlow / OpenRouter 用 `org/model`。
> 这些差异已随平台声明固化，切换平台时无需手工对齐。
> （live 调用逐能力 try/except 回退；全部失败才整体回退 mock，保证服务不中断。）
> live 受 SEC-13 三层配额闸限制（`LIVE_QUOTA_*`），超限返回 `429` 且不静默降级。

## 测试与校验

```bash
# 从仓库根运行，coverage 路径与 pyproject 的 omit 规则据此匹配
python -m pytest -q demo/tests               # 195 passed
python scripts/check_i18n.py                 # 三语键完整性（零缺失 / 三语一致 / 无重复键）
```

## 入参边界（2.0.0 补齐）

- 写接口一律须登录会话；`/api/analyze` 的 `amount` 必须有限且 `0~1e9`，`sku` / `category` / `supplier` / `listing_text` 有长度上限。
- `/api/cases` 分页 `page ≥ 1`、`page_size ≤ 200`；手动录入字段长度与数值范围由 pydantic 校验（越界 422）。
- 导入链路（CSV / xlsx）在持久层统一收敛：超长字符串按列长截断、`NaN` / `±Inf` 归零，单行脏数据不会让整批失败。
- `/api/export_pdf` 按 IP 限流（`EXPORT_PDF_RATE_LIMIT`）；`/api/insights?mode=live` 与导出同样受 SEC-13 配额约束。
