# ReturnGuard 功能实现逻辑（ARCHITECTURE）

> 适用版本：2.1.2（仓库根 `VERSION` 为单一来源）
> 关联文档：[`DECISION_LOGIC.md`](DECISION_LOGIC.md)（判定规则与阈值）、[`AI_PROVIDERS.md`](AI_PROVIDERS.md)（多 AI 平台对接）、[`API.md`](API.md)（接口契约）、[`SCHEMA.md`](SCHEMA.md)（表结构）、[`DEPLOYMENT.md`](DEPLOYMENT.md)（部署运维）

本文回答：**这些功能在代码里是怎么串起来的**——模块边界、两条主链路的执行顺序、
缓存与失效、韧性降级、隔离与安全收口。判定「算成什么」见 `DECISION_LOGIC.md`。

---

## 1. 分层与模块职责

```
前端（demo/static，无构建 ESM）
  index.html  页面骨架 + 静态 i18n 接线（data-i18n）+ 首启引导 overlay
  app.js      入口与事件编排（含首启引导逻辑、登录态、洞察加载、录入）
  render.js   看板渲染（动态文案走 t()）；被 app.js 复用
  api.js      fetch 封装（自动附带令牌）
  store.js    单一状态源（洞察结果 / 分页 / 阈值 / 平台配置）
  i18n.js     zh / en / fr 字典 + t() / setLang() / applyI18n()
        │  HTTP /api/*（静态资源带 ?v=<版本>）
        ▼
装配层  demo/main.py        app 创建 · lifespan（建库/预置账号/WAL 巡检）· 中间件注册 ·
                            VersionedStaticFiles（静态资源 URL 版本化）
        demo/common.py      配置常量 · 依赖与鉴权辅助 · 限流 · 中间件函数 · 洞察聚合辅助
        ▼
路由层  demo/routers/      frontend / forensic / insights / auth / calibration / import_
        ▼
业务层  demo/pipeline.py   单案取证编排 + 群体洞察聚合 + ROI 回测 + 防幻觉对账
        demo/models_router.py  AI 能力调用（按能力，不按厂商）+ 逐能力回退 + 韧性
        demo/providers.py      AI 平台注册表（多厂商声明式适配，见 AI_PROVIDERS.md）
        demo/auth.py           账户 / 令牌 / 多租户
        demo/calibration.py    同款阈值自标定（Youden J）
        demo/importer.py       CSV / xlsx 数据回流
        demo/platforms.py      九平台举证规则引擎
        demo/constants.py      阈值 / 词表 / 分级（单一来源）
        demo/prompts.py        提示词集中管理 + 版本与变体 + 输入净化
        ▼
基础层  demo/db.py         仓储层（openGauss / SQLite 双源隔离 + 写入收敛）
        demo/cache.py      洞察聚合缓存（解耦 db ⇄ pipeline 循环依赖）
        demo/shared_state.py 跨 worker 共享状态（限流 / 登录锁 / 配额计数，SQLite）
        demo/quota.py      SEC-13 live 三层配额闸
        demo/storage.py    可插拔图床（local / self / public_base / qiniu）
        demo/logging_setup.py 结构化日志 + request_id
```

**依赖方向（单向，禁止成环）**：`routers → common → {pipeline, models_router, db, auth, …}`；
`pipeline → models_router`、`pipeline → db`、`db → cache`（**db 不反向 import pipeline**）。
跨模块共用的纯函数下沉到最底层（如 `imghash.content_seed()` 同时服务 mock 与 live 回退）。

---

## 2. 链路一：单案取证（`POST /api/analyze`）

```
客户端上传两张图 + 业务字段
  │
  ├─ ① 会话鉴权        _require_session()：写接口必须登录，匿名 401（SEC-1）
  ├─ ② 源归正          source=demo 被强制改为 real（保护共享演示种子库）
  ├─ ③ 限流            _check_rate_limit(ip, "analyze")：每 IP 每分钟（ANALYZE_RATE_LIMIT）
  ├─ ④ 参数校验        mode / platform 白名单 / language 白名单 / 长度 / amount 有限性
  ├─ ⑤ live 配额闸     mode=live → check_live_quota(tenant, ip)（SEC-13），超限 429
  ├─ ⑥ 图片校验落盘    _validate_image()（非空 / ≤10MB / PNG·JPEG 魔数）→ 随机前缀落盘
  ├─ ⑦ 图床           storage.upload() → 本地签名短链 / 自托管 / 公网反代（按后端优先级）
  ├─ ⑧ 取证编排        pipeline.analyze_case()
  │     ├─ mock：确定性规则（内容哈希驱动），命中内容指纹缓存直接返回
  │     └─ live：models_router.live_analyze() → 见 §4
  ├─ ⑨ 字段补全        case_id / platform / outcome=待分析 / category / supplier / 平台举证清单
  ├─ ⑩ 数据沉淀        db.save_case(source, …, tenant_id) 失败只记日志，返回 persisted 标记
  └─ ⑪ 返回            AnalyzeResult（含 mode / capabilities / defect_boxes_live / degraded）
```

**为什么写操作强制落 real 源**：demo 源是共享只读演示库（1206 条种子，数字恒定）；
若放任写入会「只增不减」永久污染演示基准，且删除被显式禁止，只能靠 `FORCE_RESEED` 重建。

**原子性**：落盘 → 取证 → 存库全程在一个 `try` 内；异常时清理已落盘的孤立图片，
并把底层异常替换为干净 500（`raise … from None`，原始堆栈只进服务端日志）。
`persisted=false` 时前端提示「本次取证未落库」，避免静默丢数据。

---

## 3. 链路二：群体洞察（`GET /api/insights` / `GET /api/export_pdf`）

```
common._get_insights(request, mode, category, platform, region, season)
  │
  ├─ ① 源解析 + real 源鉴权    real 未登录 → 返回带 requires_login 的空聚合（不报错，前端提示登录）
  ├─ ② 参数校验                mode / category / platform（白名单）/ season（春·夏·秋·冬）
  ├─ ③ live 配额闸             SEC-13 三层闸；**与 /api/analyze、/api/export_pdf 共用同一闸门**
  ├─ ④ 过滤下推 SQL            db.load_filtered_cases(source, tenant, category, platform, region)
  │                            → 行→dict 后剔除 voice_audio_b64 / dossier 两个大字段
  ├─ ⑤ season 二次过滤         日期 → 季节映射需在 Python 侧完成（不适用 SQL 下推）
  └─ ⑥ pipeline.build_insights(cases, mode, source)
        ├─ 缓存查询（键 = mode + source + 案件 id 指纹 + 代际）
        ├─ _aggregate()   确定性多维聚合（mock / live 共用底层）
        ├─ live：build_insights_live() → LLM 归因 → _reconcile_insights() 数值对账
        │        失败 → mock 归因 + mode="mock(fallback)" + 脱敏 error
        ├─ _build_sourcing_loop()  选品避坑可执行清单（mock/live 都执行）
        └─ _roi_backtest()         ROI 三档 + 敏感性（method / disclaimer 强制下发）
```

`/api/export_pdf` 复用同一函数取得聚合，再交给 `pdf_report.generate_insights_pdf()` 出中文 PDF；
它额外有**按 IP 限流**（`EXPORT_PDF_RATE_LIMIT`），因为 PDF 排版是 CPU 重的同步任务。

---

## 4. AI 能力调用与韧性（`models_router`）

### 4.1 调用顺序（`live_analyze`）

| 步骤 | 能力 | 真实调用 | 回退路径 | 回退后标记 |
|---|---|---|---|---|
| ① | 同款一致性 | VL 双图判同款 | → 图像向量 → 内容哈希 | `capabilities.similarity=false` |
| ② | 瑕疵识别 | VL 双图对比 | 确定性标签（内容哈希） | `capabilities.defects=false` |
| ②' | 缺陷定位 | VL 返回 bbox（归一化） | 确定性示意框 | `defect_boxes_live=false` + `capabilities.boxes=false` |
| ③ | OCR 承诺 | VL/OCR 读图 | 卖家自填 `listing_text` | `capabilities.ocr=false` |
| ③④ | 文本生成 | LLM（结论 / 卷宗 / 陈述） | 确定性模板 + 8 语种陈述模板 | `capabilities.text=false` |
| ⑥ | 语音合成 | TTS | 占位 WAV | `capabilities.tts=false` |
| ⑤ | 优先级 | rerank（5:5 融合） | 本地可解释公式 | `capabilities.rerank=false` |

**每个能力独立 try/except**：任一失败只降级该步，其余仍是真实模型；全部失败才整体
`mock(fallback)`。`_honest_mode()` 按真实比例给出 `live` / `live(partial)` / `mock(fallback)`。

### 4.2 韧性机制（统一收敛在 `_post()`）

| 机制 | 触发条件 | 行为 |
|---|---|---|
| 重试 + 指数退避 | `429` / `5xx` / 网络瞬断 | 重试 `LLM_MAX_RETRIES` 次，间隔 `base × 2^attempt` |
| 不重试 | 4xx（除 429） | 直接抛错（客户端错误重试无意义） |
| 熔断 | 连续失败 ≥ `LLM_CB_THRESHOLD` | 打开熔断，冷却 `LLM_CB_COOLDOWN` 秒内快速失败 |
| 半开试探 | 冷却结束 | 放行一次试探，成功即闭合 |
| 总超时预算 | 单次请求累计超 `LLM_TOTAL_BUDGET` | 抛 `TimeoutError` → 逐能力回退（用 `contextvars` 隔离并发请求） |
| 能力闸 | 平台未声明该能力 | 调用前抛错 → 该能力标记回退（不伪装成功） |
| 指标采集 | 每次调用 | 计数 / 时延 / token / 最近错误 → `GET /metrics` |

### 4.3 错误对外脱敏

`pipeline._safe_error_text()` 只按异常类型给出可操作提示（超时 / 服务不可用），
网关 URL、服务器路径、堆栈与密钥片段**只进服务端日志**，不外发。

---

## 5. 缓存体系（三层，各有明确失效条件）

| 层 | 位置 | 键 | 失效/淘汰 | 为什么需要 |
|---|---|---|---|---|
| 案件读取缓存 | `db._cache` | `source` | 任何写库（save/delete/bulk_upsert）即失效 | 避免每次洞察都全表重扫 |
| 聚合代际计数 | `db.rg_kv` 表（`GET/PUT generation`） | `gen:<source>` | 写库时自增 | 多 worker 下让所有进程同时感知「数据变了」 |
| 单案取证缓存 | `pipeline._analyze_cache`（LRU 256） | 图片内容指纹 + 业务入参 + 语言 | LRU；**仅 mock 结果入缓存** | 相同两图重复上传不再重算 |
| 洞察聚合缓存 | `cache._ins_cache`（LRU 64） | `mode + source + 案件 id 指纹 + 代际` | 写库清空；`mock(fallback)` **不写入** | 一次洞察含大量聚合与 LLM 调用 |

两条关键取舍：

1. **失败回退结果不入缓存**。否则一次瞬时故障（网关抖动 / DNS 抖动 / 超时）会被缓存
   「粘住」，前端持续显示「AI 实算失败」直到数据变化——本会话实测复现过该问题。
2. **缓存的返回与写入都用深拷贝**。调用方（路由层）会对结果就地补写 `case_id` / `platform`
   等字段，若与缓存对象别名，会把脏值带进后续请求。

---

## 6. 隔离与安全收口

| 目标 | 实现 |
|---|---|
| demo / real 物理隔离 | 两个独立库（`returnguard` / `returnguard_real`）；`REAL_DATABASE_URL` 未配置时由 demo 串**派生** `*_real`，杜绝默认同库 |
| 多租户隔离 | real 源按 `tenant_id` 过滤（`本租户 OR public`）；demo 源为共享只读库；归属不明数据由 `_backfill_null_tenant` 回填为显式 `public` |
| 写接口鉴权 | 统一 `_require_session`（登录会话）；管理端点 `_require_admin`（`ADMIN_API_KEY` 或登录） |
| 令牌 | HMAC-SHA256 无状态签名，载荷 `b64(user)|token_version|exp`；登出/吊销即自增版本使旧令牌立刻失效；`AUTH_SECRET` 不设则退化为进程内随机密钥（启动打 `CRITICAL`） |
| 口令 | pbkdf2-SHA256 **60 万轮**；未知用户也跑等代价哈希消除枚举时序差；登录成功时对低轮数账户渐进 rehash |
| 上传图 PII | `/uploads` 公开挂载已移除；改为 HMAC 签名 + TTL 短链 `/api/file/{sig}`；越界/伪造 → 404 |
| 限流 | 固定窗口计数落 `shared_state`（SQLite + `ON CONFLICT` 原子 upsert），多 worker 一致 |
| 登录防爆破 | 按用户名滑动窗口计数，达 `LOGIN_MAX_FAILS` 锁定 `LOGIN_LOCK_MIN` 分钟；锁定态与「凭证错误」**响应完全一致**（防用户名枚举） |
| live 配额 | `quota.check_live_quota` 三层（全局日 / 租户日 / IP 小时），覆盖 analyze + insights + export_pdf |
| XSS / CSP | 前端全部动态文本经 `esc()`；首页每请求生成 nonce；HTML 响应严格 CSP（`script-src 'self'`）；`/static/*.html` 直连一律 404 |
| 数据库暴露面 | compose 中仅绑宿主机回环 |
| 静态资源 | URL 版本化（见 §7.2） |

---

## 7. 前端实现要点

### 7.1 状态与数据源

- `store.js` 是唯一状态源；`source` 为**派生属性**：有令牌 → `real`，否则 → `demo`。
  所有数据请求经 `api.js` 的封装自动附带 `?source=` 与令牌，前端不再手工维护数据源开关。
- 登录态变化（登录 / 登出）后重新拉取洞察与录入列表，保证看板与租户一致。

### 7.2 静态资源版本化（重要）

前端是无构建 ESM，`app.js` 用相对路径 `import './i18n.js'` —— **子模块 URL 天然带不了版本号**。
若只靠响应头协商，中间 CDN 可能覆写 `no-cache`（实测被改成 `max-age=14400`），
表现为「HTML 新 / JS 旧」（新增语言选项可见但切换无效）。

最终方案：

1. 入口脚本 URL 带 `?v=<APP_VERSION>`（`index.html` 的 `__ASSET_VER__` 由 `routers/frontend.py` 替换）；
2. **服务端改写子模块的相对 import** 追加同一版本号（`main.VersionedStaticFiles`，覆盖整条依赖链）；
3. `/static/*` 下发 `no-store`。

→ **发版即换 URL**，从机制上不依赖任何一层是否遵守缓存头。

### 7.3 本地化（i18n）

- 静态文案：`data-i18n` / `data-i18n-label`（后者用于 `<optgroup>`，避免 `textContent` 清空子项）；
- 动态文案：`t()`（`render.js` / `app.js`），切语言后需重渲染动态区块；
- 数字/日期：`locale` 键驱动（`zh-CN` / `en-US` / `fr-FR`）；
- 键完整性：`scripts/check_i18n.py`（零缺失 / 三语一致 / 无块内重复键）；
- **边界**：后端返回的**数据值**（洞察正文、缺陷标签、供应商名）保持原始语言；
  表单 `value` 是入库枚举（`赢` / `部分退款` / `输` / `待分析`），不随翻译改变。

### 7.4 首次开启引导（onboarding）

| 项 | 设计与实现 |
|---|---|
| 触发 | 首访自动展示；`localStorage.rg_onboarded !== '1'` 即展示（`maybeAutoOpenOnboard()`） |
| 流程 | 5 步：① 这是什么 ② 数据与登录 ③ 页面导览 ④ AI 通路与诚实性 ⑤ 边界与隐私 |
| 交互 | 上一步 / 下一步（末步变「开始使用」）/ 跳过引导 / × 关闭 / Esc 关闭 / 点遮罩关闭；进度点 + `{i} / {n}` 页码 |
| 快捷跳转 | 第 3 步提供各 Tab 跳转按钮（点击即跳转并结束引导） |
| 不再打扰 | 「不再自动显示」默认勾选；关闭时写 `rg_onboarded`（勾选=1 / 取消=0） |
| 随时重开 | 顶栏「使用引导」按钮（不改动该标记） |
| 动态内容 | 第 4 步从 `/api/config` 的 `provider` 渲染当前 AI 平台与「可走真实模型的能力」，如实告知平台能力缺口 |
| 本地化 | 全部文案走 `data-i18n` + `t()`，zh/en/fr 三语；切语言时调用 `renderOnboardStep()` 同步 |
| 测试 | `test_i18n.py` 断言：overlay 结构完整、5 个步骤、默认勾选、跳转目标真实存在、标记持久化、`/api/config` 提供 provider |

---

## 8. 可观测性

| 能力 | 实现 |
|---|---|
| 结构化日志 | `logging_setup.configure_logging()`；请求经 `observe_middleware` 注入 `X-Request-Id`（并发安全，走 `contextvars`） |
| 运行指标 | `GET /metrics`（需管理员）：请求量 / 平均时延 / 5xx / 取证与洞察调用量 / AI 网关调用量·错误·时延·token |
| 链路追踪号 | live 取证生成 `trace_id` 并随响应返回，与日志一致，便于排障 |
| 健康探针 | `GET /health`（compose healthcheck / 负载均衡） |
| 启动自检 | 建库、预置演示账号、`AUTH_SECRET` 缺失告警、图床后端、平台与能力清单均打日志 |

---

## 9. 质量门禁

```bash
python -m pytest -q demo/tests                                  # 单元 + 集成 + 文档守护
python scripts/check_i18n.py                                    # 三语键完整性
ruff format --check demo && ruff check demo                     # 格式 / 静态检查
mypy demo --config-file pyproject.toml                          # 类型检查（增量门禁）
```

CI（`.github/workflows/ci.yml`）在 Python 3.11 / 3.12 上跑上述四项（`--cov-fail-under=75`），
并附加 bandit 安全扫描与 pip-audit 依赖 CVE 扫描。

**文档漂移守护**（`demo/tests/test_docs_consistency.py`）把「可机检的事实」固化成断言：
`schema.sql` ↔ ORM 列一致、文档版本号 ↔ `VERSION`、全部路由已入档 `API.md`、
`package.json` ↔ `VERSION`、`API.md` 的配额变量名 ↔ `quota.py`、`.env.example` 覆盖全部配额变量、
全仓无历史项目语境与已退役公网地址。任一侧改动而另一侧未同步 → CI 直接失败。

---

## 10. 已知取舍与后续方向

| 项 | 现状 | 影响 / 后续 |
|---|---|---|
| 跨 worker 共享状态 | 仅支持 SQLite（依赖 `ON CONFLICT` upsert） | 单主机多 worker 一致；**多主机需改方言无关 upsert 或 Redis** |
| 洞察缓存 | 进程内 LRU | 多 worker 各自缓存（正确性由代际计数保证，仅重复计算） |
| 上传音频/大图 | base64 存 `TEXT` 列 | 规模部署建议改对象存储 URL |
| 相似度阈值 | 经验初值 0.82 + 可标定 | 真实部署应先用历史样本标定 |
| LLM 归因 | 单轮 prompt + 数值对账 | 更复杂归因可引入多轮/工具调用 |
| 前端构建 | 无构建 ESM（可选 terser 压缩） | 换来「改完即生效」，代价是无打包优化 |
| 供应商维度 | 演示合成 S1–S8 | 接入真实 ERP / 供货记录后替换 |
