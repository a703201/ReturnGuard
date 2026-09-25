# 更新日志（Changelog）

本文件记录 ReturnGuard（退货情报站）各版本的变更。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（主.次.修订）。

---

## [2.1.1] — 2026-09-25

> 修订版：修复**网络受限环境下镜像构建失败**的问题（不改变任何产品行为）。

### 修复（Fixes）

- **构建期依赖下载不再必需联网**：新增**离线 wheel 缓存**机制。
  - `docker/Dockerfile` 的 builder 阶段先 `COPY docker/wheels/`；若目录内含 `*.whl`，
    则用 `pip wheel --no-index --find-links=/tmp/offline-wheels` **完全离线**解析依赖，
    否则回退为原来的联网解析（行为与历史一致）。构建日志会打印
    `[build] 使用离线 wheel 缓存：N 个 wheel` 便于确认。
  - 新增 `scripts/fetch_wheels.py`：在本机按目标平台（默认 linux/amd64 + CPython 3.11）预下载全部依赖。
  - `.gitignore` 忽略 `docker/wheels/*.whl`（约 20MB 且与平台相关，不入库），
    仅保留 `docker/wheels/.gitkeep` 占位以保证 Dockerfile 的 `COPY` 不因目录缺失失败。
- **构建期 pip 源可配置**：`Dockerfile` 新增 `ARG PIP_INDEX_URL`（默认官方 PyPI，行为不变），
  `docker-compose.yml` 通过 `build.args` 透传 `${PIP_INDEX_URL:-https://pypi.org/simple}`，
  并在 `docker/.env.example` 说明。国内网络可设为镜像源提速。
  同时把 pip 默认超时提到 120s、重试提到 10 次，降低弱网下的偶发失败率。
- `docs/DEPLOYMENT.md` 新增 **§2.1 离线构建**：症状（`DO NOT MATCH THE HASHES` / `TimeoutError`）、
  对策（`scripts/fetch_wheels.py` + 构建命中判断）、以及 `PIP_INDEX_URL` 的适用范围说明。

### 背景（实测）

在某网络环境下，容器内直连 PyPI 或国内镜像下载仅 **100–200 kB/s** 且频繁 `read timed out`：
第一次构建以 `THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE` 失败
（本质是 wheel 下载损坏），改用国内镜像后仍在 `pydantic-core` 下载中途超时。
改为「本机预下载 + 容器内离线安装」后，**构建 2.9s 完成**（29 个 wheel / 24.4MB，全程不联网），
随后 `docker-compose up -d` 重建 `rg_app` 并 healthy。

### 已知坑（已内置处理）

- `uvloop` 带环境标记 `sys_platform != "win32"`，在 Windows 上执行 `pip download -r requirements.txt`
  会被**静默跳过**，而 Linux 容器必需 → 离线解析报 `No matching distribution found for uvloop`。
  `scripts/fetch_wheels.py` 在常规下载后**再显式单独下载**这类「目标平台专属」包。
  **不要手工只用一条 pip 命令生成该缓存。**

### 部署验证

- `rg_app` 重建后 `Up (healthy)`，`/api/config` 返回 `version: 2.1.1`；
  `/api/providers` 14 个平台、`is_current` 唯一、无基址/密钥泄露；
  `/api/insights?mode=mock` 1206 条 / 胜诉率 0.346，品类与季节维度均带 `decided`；
  首页与静态资源（`app.js` / `i18n.js` …）全部 200；容器日志无 `ERROR` / `Traceback`。

---

## [2.1.0] — 2026-09-25

> 三件事：把**退货判定逻辑**与**功能实现逻辑**写成可查的文档；把 AI 调用从「阿里云百炼专用」
> 升级为**多厂商平台适配**；新增**首次开启引导页**。另修正一处胜诉率口径不一致。

### 新增（Features）

- **`docs/DECISION_LOGIC.md` —— 退货判定逻辑说明**：逐条给出「输入 → 规则/阈值 → 输出 → 边界与回退」。
  覆盖：同款一致性（含三级回退与阈值标定）、瑕疵标签、货不对板/一致性结论、卷宗与母语陈述、
  优先级 5:5 融合、缺陷红框真伪标记、`outcome` 与胜诉率口径、代理争议率、品类热力、
  供应商质量分与红黑榜分级、根因归因桶、SKU 异常预警阈值、时序 OLS 预测与趋势判定、
  ROI 回测口径与双重约束、LLM 数字对账容差、持久层写入收敛、接口入参边界、结果可信度标注；
  末尾附「想改某条判定该动哪里」的代码索引。
- **`docs/ARCHITECTURE.md` —— 功能实现逻辑说明**：分层与模块职责、依赖方向约束、
  两条主链路（单案取证 / 群体洞察）的逐步执行顺序、三层缓存与失效条件、
  AI 调用的韧性机制表（重试 / 退避 / 熔断 / 总预算 / 能力闸 / 指标）、
  隔离与安全收口、前端实现要点（状态派生 / 静态资源版本化 / i18n / 首启引导）、可观测性与质量门禁、
  已知取舍与后续方向。
- **`demo/providers.py` —— 多 AI 平台注册表（声明式）**：14 个平台可选
  （百炼三 profile + OpenAI / DeepSeek / Moonshot / 智谱 / SiliconFlow / OpenRouter / Ollama /
  Azure OpenAI / custom + 两个原生协议平台的显式「不支持」声明）。
  每个平台声明 `base_url`、基地址覆盖变量、`key_env`、鉴权风格、模型映射、能力矩阵、是否实跑验证；
  `demo/models_router.py` 的 `_MODEL_ROUTER_PROFILES` 改为指向该注册表（单一来源）。
- **能力闸 `models_router._require_capability()`**：调用前校验平台是否具备该能力，
  不具备直接抛错 → 由既有逐能力 try/except 标记 `capabilities[cap] = False`（前端显示「回退」），
  **不伪装成功**。
- **URL 形状适配 `providers.build_url()`**：支持 OpenAI 兼容风格与 **Azure 部署风格**
  （`/openai/deployments/<部署名>/{chat/completions,embeddings,audio/speech}?api-version=…`）；
  未知路径与原生协议平台直接抛错（宁可启动即失败，也不打错端点）。
- **鉴权风格适配 `providers.auth_headers()`**：`bearer` / `api-key`（Azure）/ 无鉴权（本地端点）。
- **逐能力模型覆盖**：`RG_MODEL_TEXT` / `RG_MODEL_VL` / `RG_MODEL_OCR` / `RG_MODEL_EMBED` /
  `RG_MODEL_RERANK` / `RG_MODEL_TTS`；平台改版或接入自建端点无需改代码。
- **`GET /api/providers`（新增端点）**：返回平台目录与能力矩阵、OpenAI 兼容性、是否实跑验证、
  密钥变量名、当前平台标记。**不返回**基地址 / 模型标识 / 密钥配置状态（信息泄露收敛）。
- **`/api/config` 新增 `provider` 字段**：当前平台展示名、协议风格、能力矩阵、模型映射，
  供前端与新引导页如实呈现「哪些能力走真实模型」。
- **`docs/AI_PROVIDERS.md` —— 多平台接口对接与兼容说明**：支持矩阵、六类能力的请求/响应形状、
  鉴权差异、URL 形状差异、**能力语义差异**（重点澄清「图像向量 ≠ 文本嵌入」）、
  自建/私有化接入、切换与覆盖优先级、缺口回退语义、可观测入口、新增平台改动清单、密钥与合规注意。
- **首次开启引导页（onboarding）**：`index.html` 新增 5 步引导 overlay + 顶栏「使用引导」按钮；
  `app.js` 新增 `openOnboard / closeOnboard / renderOnboardStep / renderOnbAiInfo / maybeAutoOpenOnboard`。
  流程：① 这是什么 ② 数据与登录 ③ 页面导览（可一键跳 Tab）④ AI 通路与诚实性（动态读取当前平台能力矩阵）
  ⑤ 边界与隐私。交互含上一步/下一步（末步「开始使用」）/跳过/×/Esc/点遮罩关闭、进度点与页码；
  「不再自动显示」默认勾选并写 `localStorage.rg_onboarded`；顶栏按钮可随时重开且不改动该标记。
  文案三语（zh/en/fr），切语言时同步重渲染。

### 修复（Fixes）

- **胜诉率分母口径不一致**：`category_heatmap` 与 `season_view` 此前用「案件数」作分母，
  而平台 / 地区 / 交叉矩阵用「已判定案件数」，导致「待分析」案件把品类与季节胜诉率
  稀释成接近 0（出现「所有品类都远低于大盘」的假象）。现五个维度统一用 `decided`，
  并输出 `decided` 字段，前端据此区分「真实 0%」与「尚无已判定案件」。
- **平台能力声明「假支持」**：为 OpenAI / Ollama / SiliconFlow / 智谱声明的 `embed` 实为
  **文本**嵌入模型，而本服务该能力的语义是**图像向量**（请求体为百炼扩展形状
  `{"input": {"image": …}}`）——配了必然失败。现仅在真正支持图像向量输入的平台声明
  （百炼系 + `custom`），其余如实标为不支持；`CAPABILITY_LABELS.embed` 改为「图像向量」以消歧义。
- **`live_analyze` 的密钥校验**：原先一律要求 `API_KEY` 非空，会让 `ollama` 这类
  `key_required=false` 的本地平台被误判为「未配置」而整体回退；现按平台声明判断。

### 测试

- 新增 `demo/tests/test_providers.py`（19 例）：注册表完整性（字段 / 能力键 / `unsupported` 一致性）、
  默认平台与未知回退、official 的 `qwen/` 前缀契约、多厂商覆盖度、能力矩阵正确性
  （DeepSeek 仅文本 / OpenAI 无 rerank / 原生协议平台全不支持 / Ollama 无需密钥）、
  **图像向量只在其真正支持处声明**、能力闸抛错语义、`custom` 未配置即不可用、
  URL 形状（OpenAI / Azure / 未知路径 / 原生协议）、鉴权三种风格、基地址覆盖、
  `/api/config` 与 `/api/providers` 的**信息泄露收敛**、与 `models_router` 的单一来源衔接。
- `demo/tests/test_i18n.py` 15 → 20 例：新增首启引导的结构完整性（5 步 + 全部控件 + 默认勾选）、
  顶栏重开按钮、`rg_onboarded` 持久化、第 3 步跳转目标必须真实存在、第 4 步读 `/api/config` 的 provider。
- 测试总数 **168 → 195 passed 全绿**（文档一致性守护 18 → 21 例）。

---

## [2.0.0] — 2026-09-25

> **项目定位变更（MAJOR）**：由「一次性活动作品」转为**常规工程**。
> 清除全仓历史项目语境、移除已停用的公网体验地址与配套隧道配置；在此基础上完成一轮
> 全面的边界 / 异常处理补齐。**清理后项目可正常构建与运行**（测试全绿）。

### 移除（Breaking）

- **历史项目语境清零**：清除全仓活动名称、参与信息、评审语境、团队名与专用名词，
  覆盖 `README` / `CHANGELOG` / `docs/*` / 代码注释 / `.env*` / 前端 i18n（含 fr/en
  译文中的对应措辞）/ `docker/*`，并同步改写受影响的文案与交叉引用。
- **公网体验地址退役**（该地址已停用）：移除对外域名与隧道代理相关链接、配置与脚本引用——
  - 删除 `deploy/`（公网演示拉取脚本 + 隧道配置文件）；
  - 删除 `docker/returnguard-tunnel.service`；
  - `docker/docker-compose.yml` 中「暴露给隧道」的注释改为「仅绑定宿主机回环」。
- **历史归档移除**：删除 `docs/legacy/`（方案稿 / 表单文案 / 创意方向等 9 份）。
  其中的**网关接口参考**属可复用工程资料，迁出为 `docs/reference/ModelRouter_API.docx`。
- **弃用编排移除**：删除 `docker/docker-compose.local.yml`（SQLite 绑挂载版，历史
  遗留的 `disk I/O error` 来源）。
- **运行时残留清理**：删除 `.rg_tunnel.pid`、`demo/_tunnel.log`、`demo/_uvicorn*.log`
  与活动期图表产物 `assets/ReturnGuard_图表.pdf`；`.gitignore` / `.dockerignore`
  同步去除对应条目与「历史交付物目录」排除项。
- **启动脚本重写**：`start_rg.py` 由「容器 + 隧道」改为**纯容器生命周期脚本**，新增
  `--build`（重建镜像）；`stop_rg.py` 去掉隧道终止逻辑，新增 `--down`（compose down，
  保留数据卷）。两者路径全部由脚本自身位置推导，隧道相关环境变量（`CLOUDFLARED_*` /
  `RG_TUNNEL_CONFIG`）不再使用。

### 修复（Fixes）

- **数据源隔离的真实缺口（P0）**：`db.py` 中 `REAL_DATABASE_URL` 的默认值此前**等于
  demo 连接串**，即「未显式配置时 real 源会写进 demo 库」——「写入 real 绝不污染 demo
  看板」的承诺只在 compose（显式注入）下成立，本机直跑或自定义 `DATABASE_URL` 的场景
  会静默退化。现改为由 demo 串**派生独立库**（`_derive_real_url`：`returnguard` →
  `returnguard_real`，`cases.db` → `cases_real.db`），无法派生时打 `CRITICAL` 提示显式配置。
- **live 配额旁路（SEC-13）**：`/api/insights?mode=live` 与 `/api/export_pdf?mode=live`
  同样调用付费 LLM，却不受配额闸约束——不断切换过滤条件（每次产生新缓存键）即可持续
  消耗额度。现统一在 `common._get_insights` 内收口，语义与 `/api/analyze` 一致
  （超限 `429` + 明确文案，不静默降级）。
- **openGauss 口令硬编码**：`DEFAULT_OG` 不再把示例口令写死在源码，改为与部署侧同源
  （`GS_PASSWORD` / `GS_HOST` / `GS_PORT` / `GS_USERNAME`，缺失时才回退本地开发示例值）。
- **超长字段致 500**：openGauss 对 `VARCHAR(n)` 严格校验，超长字段此前直接 `DataError`
  → 接口 500（历史上仅靠种子数据手工规避 `sku_name`）。新增仓储层 `_clamp_values`
  统一收敛（按列长截断 + 日志留痕），一次覆盖手动录入 / 取证沉淀 / CSV·xlsx 导入三条链路。
- **非有限数值污染聚合**：`NaN` / `±Inf` 会被 `float()` 接受并入库，进而把金额与均值
  传染成 `NaN`。现持久层归零，接口层对 `/api/analyze` 的 `amount` 直接 400。
- **文档漂移**：`docs/API.md` 记录的 `LIVE_QUOTA_*` 变量名与 `quota.py` 实际读取的
  不一致（`..._DAILY` / `..._ACCOUNT_DAILY` / `..._HOURLY` vs `..._DAY` / `..._TENANT_DAY`
  / `..._IP_HOUR`），照文档配置等于没配；`auth.py` 模块 docstring 的 KDF 轮数停留在
  10 万（实际 60 万）；`/api/cases` 文档仍描述已移除的 `ANALYZE_API_KEY`。

### 新增与加固（Features / Hardening）

- **入参边界**：`/api/cases` 分页 `ge=1 / le=200`；`schemas.ManualCase` 全字段长度与
  数值范围约束（越界 422 并指明字段）；`/api/analyze` 的 `sku` / `category` / `supplier`
  / `listing_text` 长度上限与 `amount` 有限性校验（越界 400）；`/api/import_csv` 的表单
  直贴文本新增体积上限（此前只校验上传文件大小）；`/api/calibrate` 样本量上限 5000。
- **`/api/export_pdf` 限流**：报告生成为 CPU 重的同步任务且 demo 源允许匿名读，新增
  按 IP 限流（`EXPORT_PDF_RATE_LIMIT`，默认 20 次/分钟，`0` 关闭）。
- **`AnalyzeResult.persisted`**：显式声明落库标记（原先靠 `extra="allow"` 隐式通过），
  前端据此提示「本次取证未落库」。
- **`docker/docker-compose.pg.yml` 加固**：端口仅绑回环（此前 DB `5432:5432` 与
  APP `8000:8000` 等价暴露到 `0.0.0.0`）、口令强制必填、新增 `realdb-init` 创建独立
  real 库以保持物理隔离、补 `AUTH_SECRET` / `ADMIN_API_KEY` / `STATE_DB_URL` 等透传、
  挂载持久化卷。
- **文档一致性守护扩展**（`demo/tests/test_docs_consistency.py` 12 → 18 例）：
  - 全仓不得残留历史项目语境（词表命中即失败并给出行号）；
  - 不得出现已退役的公网地址 / 隧道关键字；
  - 历史归档目录与公网演示脚本必须已移除；
  - `package.json` 版本必须等于 `VERSION`（曾长期停在 1.1.2）；
  - `docs/API.md` 的 `LIVE_QUOTA_*` 变量名与 `quota.py` 双向一致；
  - `.env.example` 必须覆盖全部配额变量。
- **边界回归测试** `demo/tests/test_hardening.py`（12 例）：配额闸覆盖面（live 洞察 /
  mock 不受影响 / PDF 限流）、分页与字段边界、CSV 文本体积、标定样本量、`_clamp_values`
  收敛、real 连接串派生与双源隔离。
- **新增 `docs/DEPLOYMENT.md`**：容器化部署、环境变量清单、真实数据自动导入、故障排查。
- **README 重写**：去除历史项目语境与体验地址，补齐能力矩阵、环境变量清单、质量门禁与
  目录结构；`package.json` 版本对齐 `VERSION`。

### 测试

- 测试总数 **150 → 168 passed 全绿**；文档一致性守护 12 → **18 例**，边界回归 **12 例**。

---

## [1.1.5] — 2026-09-14

> 全项目文档与代码实现一致性收口：修正 3 处**事实性错误**，补齐 API 文档缺失的 8 个端点，并新增**文档漂移守护测试**防止再次失准。

### 文档修正（事实性错误）
- **`docs/SCHEMA.md` — real 源库名错误**：原文写「demo/real/auth 三库均 `db:5432/returnguard`」，与部署不符。实际 `docker/docker-compose.yml` 中 `REAL_DATABASE_URL` 指向**独立库 `returnguard_real`**（写库绝不污染演示库）。
- **`docs/SCHEMA.md` — 字段数错误且漏记关键列**：「27 字段」实为 **28**（1 主键 + 27 业务字段），且**完全漏记 `tenant_id`**——多租户隔离的核心键。已补入字段表并更新索引数 5 → **6**（含 `ix_cases_tenant_id`）。
- **`docs/CODE_REVIEW.md` — 图床默认值错误**：原文「默认 `self`」，实际链路优先级为 `self > public_base > local`，**未配置隧道/反代时默认 `local`**。
- **`demo/schema.sql` 与 ORM 脱节**：缺 `tenant_id`、`sku_name` 仍为 `VARCHAR(128)`（ORM 已扩至 256），注释仍称「约 672 条种子」（实为 1206）。已与 `db.Case` **28 列逐一对齐**（含索引），并改注为「离线参考 DDL；正常由 `create_all` 自动建表」。

### 接口文档补齐（`docs/API.md`）
- **补齐 8 个已上线但未入档的端点**：`GET /health`、`GET /api/config`、`GET /api/platforms`、`GET /api/img/{key}`、`GET /api/export_pdf`、`POST /api/import_file`、`GET /api/calibrate`，并新增「接口一览」总表（3.1 ~ 3.15）。
- **`POST /api/analyze`**：补 `category` / `supplier` / `platform` / `language` 四个请求参数；补 `language` / `voice` / `capabilities` / `defect_boxes_live` / `returned_image_url` / `platform` / `platform_evidence` 响应字段。
- **`GET /api/insights`**：补 `region` / `season` 下钻参数；补 `region_view` / `season_view` / `supplier_blacklist` / `logistics_cost` / `total_return_cost` / `dispute_rate_note` / `reconciled_from` / **`roi_backtest`**（含子结构表）响应字段。
- **`GET /api/cases`**：补 `slim` / `page` / `page_size` / `region` / `outcome` 参数与响应信封（原文档仅写「返回数组」）。
- **`PUBLIC_IMAGE_BASE` 由「必需」改为「可选」**：视觉输入现已默认**内联 base64**（`models_router._img_source`），无需公网图床或对象存储同步。
- 模型能力表改为 `official` / `tokenplan` **双列对照**；主路径更正为 **VL 双图直接判同款**（向量降为备选）；补八语种 TTS 音色映射表。
- 安全章节范围 SEC-1~12 → **SEC-1~13**（补 live 配额闸与数据库回环监听）。

### 其他文档
- `README.md`：SEC 范围补 13、测试数更新、`docs/API.md` 交叉引用修正（§3.6 → §3.10）、目录补全（`routers/` / `quota.py` / `i18n.js` / `check_i18n.py` 等）、快速开始补容器方式与端口说明。
- `demo/README.md`：重写目录树（对齐 `routers/*` 拆分后的实际结构）、图片地址改注为**可选**、补测试与校验命令。
- `docs/PRD.md`：v1.0 → **v2.1**；补维度扩展 / ROI 回测 / 平台举证包 / 多租户 / i18n 三语四节；§7 环境变量与 §11 依赖更正（移除「必需公网图床」）；里程碑 M2~M5 状态更新。
- `openGauss部署指南.md`：`/api/config.version` 期望值 1.1.2 → 1.1.5；本地直跑改 `127.0.0.1`。

### 新增
- **`demo/tests/test_docs_consistency.py`（12 例）—— 文档漂移守护**：`schema.sql` 列名/顺序与 ORM 一致、索引齐全、`SCHEMA.md` 字段数与 ORM 一致且不漏列、real 库名正确、**全部已注册路由都已入档**、`/api/analyze` 与 `/api/insights` 关键参数已记录、各文档版本号与 `VERSION` 一致、CHANGELOG 首条 == `VERSION`、API.md 语种集合与 `i18n.js` 一致、SEC 范围含 13。
- `demo/db.py`：`Case.mode` 注释补 `manual`（网页录入实际写入值，原注释缺）。
- 测试总数 **138 → 150 passed**。

---

## [1.1.4] — 2026-09-14

> 修复「**本机正常、公网升级不生效**」的根因：中间 CDN 覆写缓存头。改为**静态资源 URL 版本化**，从机制上不依赖链路是否遵守缓存协议。

### 缺陷修复
- **根因定位**：1.1.3 把 `/static/*` 的 `max-age=60` 改成 `no-cache` 后，`localhost` 已正常，但经 CDN 的公网入口仍显示旧版（法语选项可见但切语言无效、下拉显示裸 key `lang.fr`）。实测抓包对比：
  | 链路 | `Cache-Control` |
  |---|---|
  | origin（本机） | `no-cache` ✅ |
  | 公网（经 Cloudflare） | **`max-age=14400`** ❌ |
  Cloudflare 的 **Browser Cache TTL** 把 origin 的 `no-cache` 覆写成 **4 小时强缓存**再下发给浏览器（`cf-cache-status: REVALIDATED` 说明边缘是新的，是**浏览器**被要求 4 小时不回源）。因 HTML 默认不被 CDN 缓存，才出现「HTML 新 / JS 旧」的撕裂。
- **修复方案：静态资源 URL 版本化**（不依赖任何一层的缓存策略）
  - 新增 `main.VersionedStaticFiles`：接管 `/static`，对 JS 的相对 import 批量追加 `?v=<APP_VERSION>`，覆盖整条依赖链（`app.js → render.js/api.js/i18n.js → store.js`）。
  - `index.html` 入口改为 `/static/app.js?v=__ASSET_VER__`，由 `routers/frontend.py` 按 `VERSION` 替换。
  - `/static/*` 改发 `no-store`（任何层级都无正当理由缓存）；页面 / 接口仍 `no-cache`。
  - 效果：**发版即换 URL**，浏览器与 CDN 都不可能有旧副本 → 公网升级立即生效；即便某代理无视 `no-store` 也无影响。
- **新增回归测试**（`demo/tests/test_i18n.py` 12 → 15 例）：`/static/*` 必须 `no-store` 且无 `max-age`、入口脚本带版本号且 `__ASSET_VER__` 已被替换、子模块 import 全部版本化、改写后 JS 仍为合法模块。
- 测试总数 **135 → 138 passed**。

> 运维建议：Cloudflare 侧可将 **Browser Cache TTL** 由具体时长改为 `Respect Existing Headers`；不改也不影响本修复（URL 已版本化）。

---

## [1.1.3] — 2026-09-14

> 界面本地化新增法语（fr），语言由 zh/en 扩展为 zh/en/fr；补齐数字与日期格式本地化，并修复多处此前漏抽的硬编码文案。

### 国际化（i18n）
- **新增 fr 字典**：`demo/static/i18n.js` 增加完整法语块，三语各 **332 键**，键集合逐一对齐（含 `data-i18n` 静态键 130 处与 `t()` 动态键 205 处）。
- **语言切换器**：`index.html` 的 `#langSel` 增加 `Français` 选项；`render.js` 的离线兜底 `LANGS` 同步补 `fr`（音色 Serena）。
- **数字 / 日期格式**：`locale` 键驱动 `toLocaleString` / `toLocaleTimeString`，法语取 `fr-FR`（千分位为窄不换行空格、小数点为逗号、日期为 DD/MM/YYYY）；修复 `app.js` 中 ROI 面板硬编码 `zh-CN` 的两处金额与一处案件数格式化。
- **`html[lang]` 修正**：`setLang()` 原仅按 en/zh 二值设置，现按 `zh-CN` / `en-US` / `fr-FR` 映射，保证断词、拼写与无障碍朗读语言正确。

### 补齐漏抽文案
- **登录 / 注册弹窗**：标题、用户名 / 密码 / 企业名标签、提示语、提交与切换按钮（含 `auth.*` 新键），静态 `data-i18n` 与 JS 动态文案双向接入。
- **数据录入删除流程**：确认弹窗（`{id}` 占位符）、删除中 / 删除失败 / 网络错误等状态文案。
- **ROI 真实回测来源说明**：`roi.realSrc` 带 `{n}` / `{src}` / `{wr}` 占位符，替代原硬编码中文长句。

### 校验与测试
- **`scripts/check_i18n.py` 升级**：由「断言 zh==en」改为「以 zh 为基准校验全部语言（`LANGS`）」，并新增**块内重复键**检查（重复键会静默覆盖，是文案漂移隐患）、识别 `data-i18n-label`（`<optgroup>` 专用）。
- **新增 `demo/tests/test_i18n.py`**（12 例，纯静态 + 2 例缓存回归）：语言块齐全 / 三语键一致 / 无重复键 / `locale` 与语言对应 / 选择器列出全部语言 / 后端 `SUPPORTED_LANGUAGES` 覆盖前端 / 法语音色确定 / 未知语言回退默认音色 / 表单枚举 value 未被翻译 / optgroup 用 label 属性 / 静态资源必须回源校验。
- 测试总数 **123 → 135 passed**。

### 缺陷修复
- **前端「升级后不生效」第一步修复**：`no_cache_middleware` 原对 `/static/*` 下发 `max-age=60, must-revalidate`，60 秒窗口内浏览器直接用本地旧副本、不回源，导致「HTML 新 / JS 旧」撕裂。已改为 `no-cache`（每次回源校验）。
  > ⚠️ **该修复不完整**：本机正常但公网仍失效——中间 CDN 会覆写该头部。最终方案见 **[1.1.4]**（URL 版本化 + `no-store`）。
- **法语界面顶栏错位**：拉丁语系文案比中文长 **2.5–4.75 倍**（`app.sub` 达 3.63 倍、149 字符），原 `.brand` 无宽度约束，长副标题把 KPI 条挤到下一行。已给 `.hrow1 .brand` 加 `flex:1 1 320px; min-width:0` + `h1` 省略号，`.hrow1 .kpis` 加 `margin-left:auto`；`.bar-top select` 的 `max-width` 由 130px 放宽到 190px（原值会把 `Toutes plateformes` 截断）。
- **补齐数据录入表单本地化**：标题 / 描述 / 全部字段标签 / 供应商与平台 `optgroup` 分组名 / 判定结果选项等 24 处。**表单 `value` 保持中文枚举不变**（`赢`/`部分退款`/`输`/`待分析` 是入库契约，翻译会破坏聚合与筛选），只本地化显示文案。

---

## [1.1.2] — 2026-08-27

> Live 合规清单 + 平台规则出处核验 + 交付物总览；**演示数据集真实化（1206 条）+ 平台扩展至 9 个**；并根治「official profile 模型标识错配」导致无法一键切官方 Model Router 的缺陷。

### 数据集与维度扩展（重大变更）
- **真实数据集替换**：demo 演示库由固定种子合成案件替换为 **1206 条真实退货案件**（`demo/cases.json`），胜诉率 **34.6%**；原合成集留存为 `demo/cases_synthetic_backup.json`。
- **平台由 4 个扩展至 9 个**：Amazon / AliExpress / Temu / SHEIN / **eBay / Shopee / Lazada / Walmart / TikTok Shop**（`platforms.py`），平台对比、平台×供应商交叉、平台举证包等看板维度同步扩容。
- **图床激活**：七牛云对象存储接入并启用（`storage.py`，优先级 qiniu > oss > public_base > local），`/api/config` 返回 `image_bed: qiniu`、`image_bed_public: true`，上传图回传真实公网 URL 供模型服务端回源。
  > ⚠️ **后续更正（P3-17）**：已去云端化——图床改为**本地自持**（`local` 签名短链 / `self` 自托管隧道 / `public_base` 自建反代，默认 `self`），七牛等远端对象存储改为**预留接口**（`IMAGE_BED=qiniu` 显式开启，默认关闭）。本条为历史记录，当前状态以 README §一分钟速览 为准。

### Live 合规（对齐官方 Model Router_API.docx）
- **模型标识 profile 化**：`_MODEL_ROUTER_PROFILES` 新增 `models` 字典，文本/VL/OCR/向量/rerank/TTS 标识随 profile 固化并由 `MODELS[...]` 统一下发，杜绝 base_url 与模型名错配。
- **修复 official 错配**：旧代码在 official profile 下仍向官方端点发无前缀模型名（`qwen3.7-max` / `qwen-audio-3.0-tts-plus` / `qwen3-rerank`），官方会 404。现 official 用 `qwen/qwen3.7-max` / `qwen/qwen3-tts-instruct-flash` / `qwen/qwen3-rerank`。
- **文本模型前缀补齐**：official 下若 `.env` 遗留 tokenplan 风格无前缀命名，自动补 `qwen/` 前缀，保证「改一个 `MODEL_ROUTER_PROFILE` 即一键切官方」。
- 新增交付物：`docs/LIVE_COMPLIANCE.md`（逐项核对表 + 一键切换步骤 + 风险点）、`docs/PLATFORM_SOURCES.md`（Amazon/AliExpress/Temu/SHEIN 四个核心平台官方政策 URL 核验 + 准确性判定；其余 5 个平台待核验）、交付物总览（提交清单 + 阶段成果 + 体验指引 + GitCode 镜像说明）。
  > ⚠️ **后续更正（2.0.0）**：上述交付物随历史材料一并移出仓库；其中的**网关接口参考**保留为 `docs/reference/ModelRouter_API.docx`，其余不再随仓库分发。
- README 顶部新增「一分钟速览」（访问方式 / 测试账号 / 版本 / live 合规指针）。

### 修复（Fixes）
- **P0 安全三洞**：大厂标准审查发现的 3 项 P0 安全问题已修复并回归验证。
- **SQLite WAL 失控**：WAL 文件无节制增长问题已收口（checkpoint 策略修正）。
- **AI 诚实性标注补齐**：真实模型输出与 mock 回退在前端与接口层均显式区分标注，杜绝把回退结果当真实能力呈现。
- **CI 转绿**：流水线恢复全绿；当前测试 **88 passed**（含 `/api/export_pdf` 与 `/api/import_csv` 两条此前零覆盖关键链路的补齐用例）。

### 文档（Docs）
- **全仓文档一致性整改**：版本号统一为 1.1.2；案件总数统一为 1206、胜诉率统一为 34.6%、平台数统一为 9；图床状态更正为「本地自持（远端接口预留）」。
- **开发与部署统一 openGauss**：`db.py` 默认连接改为 openGauss（本地 `localhost:5432/returnguard`，需先 `docker compose -f docker/docker-compose.yml up -d db`），移除「开发期回退 SQLite」表述；架构图、README/PRD/SCHEMA/常见问题/部署指南同步更新；GitCode 镜像地址补全为 https://gitcode.com/a703201/ReturnGuard；`docker-compose.local.yml`（SQLite 版）标记弃用（**2.0.0 已删除**）。
- `docs/CODE_REVIEW.md` 新增第十一节「大厂标准审查结论摘要」（综合 5.8/10 六维评分 + 已闭环项 + 待跟进项）。
- 过程性草稿与方向探讨材料曾归档至 `docs/legacy/`（**2.0.0 已整体移除**，仅保留可复用的网关接口参考 `docs/reference/ModelRouter_API.docx`）。

### 2026-08-29 部署加固与稳定性修复（同版本 1.1.2 内的补丁集合）

> 审查报告 26 项路线图全部收口后，针对「公网演示」做的部署层收口。版本号维持 1.1.2（`VERSION` 与 `/api/config` 一致），不另行发版。

- **前端 ESM 拆分收口（#24 / 8cbf308）**：前端拆为 `store.js`(单一状态源) + `api.js` + `render.js` + `app.js`(入口编排)；修复拆分时遗留、会导致整文件 JS 语法损坏的游离字符；并修复 `$` 函数未从 `render.js` 导出导致 `init` 抛 `ReferenceError`、页面点击无反应的 bug。
- **零覆盖测试补齐（#11）**：新增 `demo/tests/test_coverage_gap.py`，覆盖 `GET /api/export_pdf` 与 `POST /api/import_csv` 两条此前 0 覆盖链路；测试 **86 → 88 passed**。
- **openGauss 部署切换（610fb0e）**：部署主力由 SQLite 版（`docker-compose.local.yml`）切到 openGauss 版（`docker-compose.yml`），**demo / real / auth 三库全部落在 openGauss**（`db:5432/returnguard`），用户库不再落容器内 SQLite、跨重启不丢；app 端口统一为 `127.0.0.1:65432:8000`（仅绑宿主机回环）。
- **sku_name 长度溢出修复（610fb0e）**：`db.py` 中 `sku_name` 由 `String(128)` 扩至 `String(256)`——cases.json 中有商品名长达 145 字符，openGauss 严格长度校验在批量插入种子时抛 `DataError: value too long for type character varying(128)`；重建镜像 + 清 `ogdata` 卷重播种子，openGauss 现承载 **1206 条** demo 案件。
- **Docker 本地 WAL 崩溃修复（e614140）**：Docker 把主机 `demo/` 绑挂载进容器时，SQLite 在 `PRAGMA journal_mode=WAL` 因 `-shm`/mmap 在 Windows 挂载点不支持而抛 `disk I/O error`、启动即崩；新增 `SQLITE_NO_WAL` 环境变量开关（默认关），本地部署设 `1` 时改用 DELETE 日志模式，宿主机原生 fs / openGauss 不受影响。
- **版本号 Vunknown 修复（c4b12ed）**：Dockerfile 原 `COPY demo/ .` 把源码拍平到 `/app`，使 `main.py` 按 `__file__/../VERSION` 计算版本时路径断裂、返回 `unknown`；改为 `COPY demo/ ./demo/` 保持与本地一致的目录结构，entrypoint 启动前 `cd demo`，并为 `_read_app_version()` 增加 `../VERSION → ./VERSION` fallback。现 `/api/config.version` 正确返回 `1.1.2`。

### 2026-09-08 对外材料合规与全仓文档口径统一（同版本 1.1.2 内的补丁集合）

> 针对「对外发布材料」做的合规整改与文档收口。**仅改文档与提交材料，不改运行时逻辑**，版本号维持 1.1.2。
> ⚠️ 本节涉及的对外提交材料（模板填写版 / 各分册 / 检查报告等）已于 **2.0.0** 随项目转为常规工程一并移出仓库，
> 以下仅作为变更历史保留。

- **模型标识合规（P0）**：对外材料原按 `tokenplan` 命名书写，统一改为 Model Router（`official`）口径，全部补 `qwen/` 前缀。
- **TTS 模型更正（P0）**：原材料写的 `qwen-audio-3.0-tts-plus` **不在 `ModelRouter_API.docx` 的 126 个官方模型名单内**；官方 TTS 仅 `qwen/qwen3-tts-instruct-flash` 一个，已统一更正并对照官方名单核验。
- **产品命名统一**：全仓统一为「**ReturnGuard 退货情报站**」。旧称「退件法医 / 跨境退货举证官」不再使用（此前审查报告第 14 项「产品名三套并存」至此收口）。
- **全仓模型命名整改**：
  - `README.md` 模型映射表改为 **official / tokenplan 双列**对照，并修正误写的 `qwen/qwen3-max` → `qwen/qwen3.7-max`；删除不存在的 `qwen/deepseek-r1`（洞察层复用文本模型，`deepseek-v4-pro` 等仅存在于 `compare_models.py` 对比实验）。
  - `demo/README.md` 补全三 profile 对照表与命名差异警告。
  - `docs/PRD.md`、`docs/API.md` 同步改为 official 口径。
- **陈旧表述清理**：对外一页纸材料中的「双 SQLite 物理隔离」更正为 openGauss 独立库（`returnguard` / `returnguard_real`）；演示录屏脚本的旧镜序标注作废、指向新版。

### 2026-09-10 大厂标准审查 P1 / P2 全量收口（同版本 1.1.2 内的补丁集合）

> 针对大厂标准多维审查报告的工程质量与赛后打磨项做全量收口，**不改变外部行为**，版本号维持 1.1.2（`VERSION` 与 `/api/config` 一致）。测试 **88 → 107 passed 全绿**（含 /api/export_pdf、/api/import_csv 等链路补齐，以及 `test_storage.py` 重写对齐当前存储层）。

- **P1-5 提示词注入防护**：`prompts.py` 新增 `sanitize_user_content`（中英文指令注入黑名单 + 控制字符剥离 + 截断），卖家数据用 `<<<SELLER_DATA>>>` / `<<<END_DATA>>>` 边界包裹并附护栏说明；`models_router.live_analyze` 入口对 `listing_text` 净化；新增 `tests/test_prompt_injection.py`（7 例）。
- **P1-9 `main.py` 上帝文件拆分**：`common.py` 承载配置 / 依赖 / 限流 / 中间件 / 聚合辅助；`routers/{frontend,forensic,insights,auth,calibration,import_}.py` 按域拆分；`main.py` 收敛为装配层（app 创建、中间件注册、静态挂载、路由聚合、lifespan），端点路径 / 方法 / 契约逐行一致；全部 P1 项测试转 `monkeypatch.setattr(common, ...)`。
- **P1-10 网关契约测试**：新增 `tests/test_gateway_contract.py`（5 例），monkeypatch `models_router._post` 录制请求体并断言 url / model / messages 结构，覆盖 `llm` / `llm_json` 响应解析鲁棒性（markdown 围栏 / think / 截断 / 多段 JSON / 空串）与 official `qwen/` 前缀命名契约。
- **P2-5 connector 批量去 N+1**：`import_from_connector` 改用 `bulk_upsert_cases` 单事务批量写入，消除逐行 `save_case` 的 N+1 旧链路。
- **P2-9 提示词版本管理 / A-B**：`prompts.py` 新增 `PROMPT_VERSION` 常量与 `_PROMPT_VARIANTS` 注册表（`current_prompt_variant()`），insights system persona 注入 `[提示词版本：X / variant=Y]` 标识，便于回滚与 A/B 对照。
- **P2-12 CI 安全门禁**：`.github/workflows/ci.yml` 将 mypy 由「continue-on-error 不阻断」升级为**阻断门禁**；新增 `bandit` 源码安全审计与 `pip-audit` 依赖 CVE 扫描（先以可见性优先运行，基线稳定后可去 `continue-on-error` 转阻断）。
- **P2-14 幻觉数值校验**：`pipeline._reconcile_insights` 新增 LLM 输出与真实聚合数值一致性校验——win_rate / total_cases / 各维胜诉率与聚合偏差超阈值即回退 mock 聚合并标注 `reconciled_from='aggregate'`，不再仅靠 prompt 约束防幻觉。
- **P2-6 前端骨架屏 + 构建链路**：`index.html` 加 shimmer 骨架屏样式，首屏数据抵达前显示占位（渲染覆盖后自然消失）；新增 `package.json` + `scripts/minify.mjs` 轻量 terser 压缩构建链路（建议项，**不接入 CI** 以免破坏演示）。
- **P2-7 前端 i18n**：新增 `demo/static/i18n.js`（zh/en 字典 + `t()` / `setLang()` / `applyI18n()`），顶栏新增语言切换并持久化偏好；可见标签抽取 `data-i18n` 接线（默认 zh 与现界面一致，en 为对照译本）。
- **P2-1 平台分布口径说明**：数据集本身不均衡（Amazon 444/37% vs Lazada 38/3%），"9 平台均衡"为按「品类 × 地区」重映射的演示展示口径，已在新手指引与平台举证包文案中如实标注，代码中不伪造均衡分布。

### 2026-09-10 第二轮多维度复查收口（图床 / rerank / 供应商 / ROI / i18n / 构建）

> 针对第二轮大厂标准多维复查（`ReturnGuard_大厂标准多维审查_20260910.md`）发现的问题做全量修复。版本号维持 1.1.2。测试 **107 → 111 passed 全绿**（新增存储后端与 rerank 接通用例），四道门禁本地全通过（覆盖率 76.7%）。

- **N1/N2 图床后端化（本地默认 + 远端预留）**：`storage.py` 重构为**可插拔后端注册表**（`local` 签名短链 / `self` 自托管隧道 / `public_base` 自建反代；`qiniu` 远端对象存储为**预留接口**，`IMAGE_BED=qiniu` 显式开启、SDK 缺失自动降级）；新增 `test_storage.py` 覆盖"远端未配置安全降级"与"未显式开启不进自动链"；修正 README / CHANGELOG / CODE_REVIEW 中"七牛云已激活"的**口径漂移**；启动日志与 `/api/config` 透出实际后端；`.env.example` 补充 `IMAGE_BED` 与远端预留说明。
- **N5 单案优先级接入 rerank**：`models_router.live_analyze` 新增 ⑤ 优先级 rerank 调用（语义化 query + 单案文档 → 相关性分，与本地公式 5:5 融合），`capabilities["rerank"]` 如实标注；新增 2 条专项用例（接通 / 回退）。
- **N8 供应商维度扩充**：新增 `demo/suppliers.py`（供应商分配单一来源：缺陷定池 + SKU 熵），`convert_datasets.py` / `dataset_parse.py` 改为委托；重映射 `cases.json` 供应商由 **3 家（S2/S3/S6）扩展到 8 家（S1~S8）**，红黑榜与「平台 × 供应商」交叉条目显著增加；同步修正前端"质量分<50"文案（实际按档位判定）。
- **N6 ROI 面板接入真实数据**：`app.js` 新增 `syncRoi()`，客单价（退款 ÷ 案件数）与争议占比（代理嫌疑率）按当前看板**真实值**自动填入并标注「真实 / 假设」，附数据来源行。
- **N3 i18n 扩容**：`data-i18n` 由 14 处扩展到 **30 处**（15 张卡片标题 + 登录门按钮），`i18n.js` 字典补齐 zh/en。
- **N4 构建链路可用化**：`scripts/minify.mjs` 输出到 `demo/static/dist/` 并**重写 ESM 相对导入**、生成 `dist/index.html`；`routers/frontend.py` 新增 `SERVE_MINIFIED=1` 开关（默认发未压缩源）；实测压缩 **-31%**；`dist/` 与 `node_modules/` 已 gitignore。

### 2026-09-11 四项收口（正文级 i18n / 母语多语 TTS / ROI 回测 + A/B 台架 / 告警清零）

> 第二轮审查报告（`ReturnGuard_大厂标准多维审查_20260910.md`）遗留四项全量收口。版本号维持 1.1.2。测试 **112 → 123 passed 全绿**，ruff / mypy（31 files）/ pytest 四道门禁本地全通过。

- **#1 母语多语 TTS**：TTS 音色不再硬编码 `Chelsie`。`constants.py` 新增语言→音色映射与 `DEFAULT_LANGUAGE`（单一来源）；`models_router.tts()` 按 `language` 选音色；`live_analyze()` 新增 `language` 入参（LLM 用目标语言生成陈述、TTS 用对应音色）；`prompts.voice_statement()` 提供多语陈述模板（mock 与 live 文本回退共用同一口径，未知语言回退中文）；`/api/analyze` 接收 `language`、`/api/config` 下发 `languages` 清单；前端取证表单新增语言选择器，结果区展示「语言 · 音色」。新增 4 条回归用例。
- **#2 正文级 i18n**：`data-i18n` 由 30 处扩展到 **116 处**（卡片 desc / 表头 / ROI 面板 / 新手指引 / 取证与录入表单标签）；**动态渲染层首次接入**——`render.js` / `app.js` 中 185 处硬编码中文改为 `t()` 调用（看板正文、供应商下钻、平台举证包、报告导出、状态提示、分页、导入结果）；`i18n.js` 字典 zh/en 各 **316 键**（原 119），键完整性由脚本逐项对账（无缺失、无冗余）；切换语言后会重渲染动态区块（此前动态区仍是旧语言）。后端返回的**数据值**（洞察正文、缺陷标签、供应商名）仍为其原始语言，已在 `docs/` 与注释中声明边界。
- **#3 A/B 对照 + ROI 回测实证**：
  - **ROI 回测**：`pipeline._roi_backtest()` 基于**真实聚合值**（案件量/退款/争议占比/胜诉率/物流成本）输出**保守 / 基准 / 乐观**三档可挽回区间 + 单因子敏感性（案件量、争议占比 ±20%），胜诉率提升受「上限 − 当前」双重约束不会溢出；`method` 与 `disclaimer` **随结果强制下发**并声明「模型回测，非 A/B 实测因果」；接入 `/api/insights` 与前端 ROI 面板（与上方全假设 what-if 并列展示）。新增 7 条回归用例（含诚实性字段断言）。
  - **A/B 台架**：新增 `demo/ab_experiment.py`，同一批案件、同一模型、同一聚合输入下对比 prompt 变体 A/B，量化 JSON 可用率、幻觉对账 mismatch、耗时、字段填充率；`--mode mock` 可零成本干跑验证台架。⚠️ 修复台架自身缺陷：连跑 A/B 时变体 B 会**命中变体 A 的洞察缓存**（实测 0.01s 返回、mismatch 与 A 完全相同），已在每次运行前清空 `_ins_cache`。
- **#4 SQLAlchemy DeprecationWarning 清零**：`auth.py` 的 `Column(DateTime, default=datetime.utcnow)` 改为 naive-UTC 等价实现（保持列类型与存储格式不变、零迁移），19 条 `datetime.utcnow()` 弃用告警 → **0**，规避未来 SQLAlchemy 版本移除该 API 导致的升级 break。

---

## [1.1.1] — 2026-08-27

> 安全复审全量闭环（公网部署语境）：第八节安全专项复审发现项 SEC-1 ~ SEC-12 **全部清零**。测试 65 → 85，安全面由 A- 提升至 A 区间。

### 安全加固（Security · SEC-1 ~ SEC-12）
- **SEC-1 写接口鉴权全开**：新增 `_require_session`（写接口须登录会话）+ `_require_admin`（`/api/calibrate`、`/metrics` 须 `ADMIN_API_KEY` 或登录）；`/api/analyze`、`POST/DELETE /api/cases`、`/api/import_csv` 收口。匿名写接口 → **401**（公网实测一致）。
- **SEC-2 `AUTH_SECRET` 静默忽略**：`auth.py` 顶部补 `load_dotenv()`（pytest 守卫），`_SECRET` 统一转 bytes，支持 `secrets.token_hex(32)` 配置；令牌跨重启可验。
- **SEC-3 代理 IP 误判**：`get_client_ip` 优先采纳 `CF-Connecting-IP`（反向代理 / CDN），部署 `AUTH_TRUSTED_PROXIES=127.0.0.1`；限流/防爆破在多 worker 下生效。
- **SEC-4 停用 `?token=` 传令牌**：仅读 `Authorization: Bearer` / `X-Token` 头，避免令牌经 URL/日志泄露。
- **SEC-5 数据变更须登录**：写接口统一 `_require_session`，`public` 基准亦须登录态。
- **SEC-6 公网关注册**：`REGISTRATION_ENABLED=false`（使用内置 demo/demo123），保留可选 `REGISTRATION_INVITE_CODE`。
- **SEC-7 `/metrics` 收口**：纳入 `_require_admin`（匿名 401）；`/api/config` 保留开放（仅透出非敏感常量）。
- **SEC-8 上传图签名短链（PII 收敛）**：删除 `/uploads` 静态公开挂载；本地兜底 URL 改由 `storage.sign_upload_url()` 生成 HMAC 签名 + TTL 短链 `/api/file/{sig}?f=&e=`，含路径穿越防护；OSS/七牛公网 URL 不受影响。匿名 `/uploads/任意` → **404**；有效签名 → **200**，伪造/过期 → **404**。
- **SEC-9 CSP nonce 硬化**：首页每请求生成 `secrets.token_urlsafe(16)` nonce 注入内联 `<script>`，CSP `script-src 'self' 'nonce-…'` 去 `unsafe-inline`（style-src 保留 unsafe-inline 为已知权衡）。
- **SEC-10 登录侧信道 / KDF 轮数**：未知用户也跑等代价 pbkdf2（消用户枚举时序差）；pbkdf2 10 万轮 → **60 万轮**，存量账户 rehash-on-login 渐进升级。
- **SEC-11 API Key 常量时间比较**：`_require_api_key`/`_require_admin` 改用 `hmac.compare_digest`。
- **SEC-12 多 worker 共享状态外置**：新增 `shared_state.py`（独立 SQLite `rg_state.db` 存限流/登录锁，滑动窗口防爆破）；`db.py` 代际计数落库 `rg_kv` 表，根治多 worker 陈旧缓存。

### 前端 / 用户体验
- 金额配色提亮、胜诉率环图还原、使用者引导横幅、空态文案优化。

### 修复（Fixes）
- 修 `storage` 密钥导入期捕获漂移（改动态 `auth._SECRET`）。
- 修安全回归测试 Windows 文件锁 flaky（`unlink` 5 次重试）。
- XSS 测试数据清理（`<script>` 占位行删除 + 测试自清理）。
- SQLite WAL + `busy_timeout` 抗并发。
- `*.db`（含 `rg_state.db` / `users.db` / `cases.db`）全部 `.gitignore` 不入库。

### 文档（Docs）
- `docs/CODE_REVIEW.md` 第八~十节：安全专项复审 + SEC-1~12 全量修复记录（含公网实测）。
- `docs/API.md`：补全鉴权、签名 URL、限流/防爆破、CSP、管理端点等章节。
- `README.md` / `demo/README.md` / `openGauss部署指南.md`：同步安全现状与 `/uploads` 改为签名短链。

---

## [1.1.0] — 2026-08-21

> 上线冲刺版本：A 组「假能力变真」、B 组「数据闭环」、C 组「多租户 + 合规 + 国产化部署」全部落地；测试 30 → 65，lint 门禁清零。

### A 组 · 把「假能力」变真（live 就绪 + 图床 + 逐能力回退）
- **A1 真·同款图像向量比对**：live 模式接入图向量余弦（`tongyi-embedding-vision-plus`），图床回源；gateway 未开通时自动回退确定性 mock，逐能力标记真实/回退（`capabilities` 映射）。
- **A2 真·瑕疵视觉识别 + 真实红框**：live 接入 `qwen3-vl-plus` 缺陷识别，返回归一化缺陷框；未开通回退示意框。
- **A3 真·OCR + rerank**：listing 承诺 OCR（`qwen-vl-ocr`）+ 案件优先级 rerank（`qwen3-rerank`）链路就绪。
- **A4 live 图床落地**：新增 `storage.py` 统一图床抽象（OSS / `PUBLIC_IMAGE_BASE` / 本地回退），上传图同步为公网 URL 供模型服务端回源；`/api/config` 暴露图床状态。
- **逐能力回退**：视觉/向量/OCR/TTS 各自 try/except，任一能力失败不影响其余；gateway 渐进开通即生效，无需改代码。

### B 组 · 真实数据闭环
- **B1 时间序列 + 预测预警**：洞察新增 `time_series`（按月案件/退款）、`forecast`（线性回归外推次月 + 趋势）、`forecast_alerts`（环比激增预警），前端新增趋势图与预测卡片。
- **B2 真实数据回流**：新增 `importer.py` CSV 批量导入（列名映射/类型转换/中文表头不敏感）+ Amazon SP-API / AliExpress 连接器位；`POST /api/import_csv` 上线。
- **B3 相似度阈值自标定**：新增 `calibration.py`，用真同款/真调包样本按 Youden J 最优分离点标定阈值（`POST /api/calibrate`），pipeline 与 live 统一读取，消除三处写死 0.82 的漂移。
- **B4 选品避坑闭环**：洞察新增 `sourcing_checklist`（可执行选品避坑建议：换供应商/修 listing/停售 SKU 等），前端新增「选品避坑」卡片。

### C 组 · 多租户 + 合规 + 国产化部署
- **C1 多租户 + 账户体系**：新增 `auth.py`（pbkdf2 加盐哈希 + HMAC 签名令牌，零新依赖）；`POST /api/auth/register|login`、`GET /api/auth/me`；real 源案件按 `tenant_id` 隔离（私有数据严格隔离，`public` 公共基准共享，demo 源保持共享演示库）；前端登录弹窗 + 令牌持久化。
- **C2 XSS 转义（P1-3）**：修复 SKU/品类/供应商/根因标签/平台举证材料等漏转义点，统一 `esc()`；后端新增 CSP / `X-Content-Type-Options` / `Referrer-Policy` 防御纵深。
- **C3 负向 / 一致性测试（P3-3）**：新增 `tests/test_negative.py`（非法输入 4xx、mock 确定性、安全响应头、鉴权、CSV 缺行跳过）与 `tests/test_auth.py`（注册/登录/租户隔离/跨租户删除拦截）。
- **C4 region / season 维度扩展**：前端新增地区（US/UK/DE/FR/ES/RU/BR）与季节筛选，与 `/api/insights` 的 `region`/`season` 下钻联动。
- **C5 openGauss 部署 + 自动导入**：`RG_AUTO_IMPORT_CSV` 启动自动导入 real 源（幂等去重、失败不阻断）；附 `seed_real.csv` 样例与 `openGauss部署指南.md`（含连接参数、验证、注意事项）。

### 修复（Fixes）
- **mock 相似度确定性回归**：`_mock_similarity` 由「文件名哈希」改为「图片内容哈希」，修复上传随机 rid 文件名导致同图结果漂移（确定性、可复现）。
- **CSV 导入缺案件号**：导入行补齐 `RG-XXXXXXXX` 稳定 case_id（原为 NULL，导致无法按 ID 删除/去重）。
- **多租户迁移**：存量 cases 表缺 `tenant_id` 列时自动 `ALTER TABLE` 追加，部署期 schema 演进不破坏。
- **lint 门禁清零**：demo 与仓库根脚本 ruff check + format 全绿（修 import 排序、未用导入、B905 strict、E731 lambda、E702 分号等 35 项）。

### 文档（Docs）
- 新增 `openGauss部署指南.md`（真实数据自动导入 + 验证）。
- 更新 `docs/CODE_REVIEW.md`（终审结论：P1 清零、测试与 lint 门禁全绿）。

### 已知限制（Known Issues）
- live 视觉/向量/OCR/TTS 仍依赖 Model Router gateway 开通对应模型；未开通自动回退 mock 并逐能力标记（演示不中断，开通即生效）。
- openGauss 多 worker 部署：聚合代际计数与限流/登录锁已在 v1.1.1 外置为独立 SQLite（`shared_state.py` / `rg_kv`，SEC-12），单进程缓存陈旧问题已根治；生产多实例仍建议上层 Redis 共享其余指标（非阻断）。
- `/uploads` 公开挂载已在 v1.1.1 改为 HMAC 签名短链 `/api/file/{sig}`（SEC-8），退货 PII 图不再长期公开可读。

---

## [1.0.0] — 2026-08-16

> 交付基线版本。首次将「退货情报站」作为完整产品形态对外交付：群体洞察看板为产品核心，单案取证为数据采集管道。

### 新增（Features）
- **大屏市场洞察看板**：9 张卡片（品类热力 / 根因归因 / 供应商红黑榜 / 平台对比 / 异常预警 / SKU 明细 / 老板报告 / 下一步建议 / 平台×供应商交叉矩阵），适配电脑 / 平板 / 电视多比例，单页占满不整页滚动。
- **维权胜诉率 KPI**：顶部环形图实时展示胜诉率，颜色随高低红绿渐变。
- **供应商透视**：红黑榜排序 + 点击下钻（SKU 清单 / 平台分布 / 缺陷构成），受顶部品类·平台筛选联动。
- **单案取证**：上传退货图 + 本店主图，自动比对同款、标注缺陷红框、生成可提交平台仲裁的举证材料与语音说明；每处理一单看板实时 +1。
- **平台举证包**：Amazon / AliExpress / Temu / SHEIN 规则对照与必备材料清单，单案选平台即带出。
- **可观测性**：`GET /metrics` 运行指标 + 结构化日志；`GET /api/config` 暴露前端常量（阈值 / 版本）。
- **工程化加固**：写接口鉴权 + 限流、XSS 转义、数据污染修复（未判定单案归「待分析」、缺失维度跳过噪声桶）、聚合代际缓存、依赖锁版、`/uploads` 过期清理、`FORCE_RESEED` 重置。

### 修复（Fixes）
- P1-1 数据污染（上传单案稀释胜诉率分母）。
- P1-2 取证原子性（异常清理孤立图、优先返回取证结果）。
- P1-3 动态文本 XSS 面。

### 文档（Docs）
- 大厂标准代码审查报告（`docs/CODE_REVIEW.md`「六、」章节，综合评级 B-，落地 P1/P2/P3 共 17 项）。
- 录屏脚本 V1.0（3 分钟精华版，纯分镜/口播）。

### 已知限制（Known Issues）
- 单案取证的缺陷红框为演示示意框，未接入真实视觉模型（live 红框标注待做）。
- live 全链路（真实 LLM 归因 + 公网图床）尚未真跑，缺 `MODEL_ROUTER_API_KEY` 与 `PUBLIC_IMAGE_BASE`。
- 容器化公网部署待做。

---

## 版本规则

- **主版本（MAJOR）**：不兼容的架构/产品定位变更（如产品方向调整）。
- **次版本（MINOR）**：向后兼容的功能新增（如新增洞察维度、新增平台）。
- **修订（PATCH）**：向后兼容的问题修复（如 bug 修复、文案微调）。
- 每次发版在本文档新增一个 `## [x.y.z]` 区块，并更新仓库根 `VERSION` 文件为同一版本号。
