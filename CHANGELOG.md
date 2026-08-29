# 更新日志（Changelog）

本文件记录 ReturnGuard（退货情报站）各版本的变更。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（主.次.修订）。

---

## [1.1.2] — 2026-08-27

> Live 合规清单 + 平台规则出处核验 + 复赛交付物总览；**演示数据集真实化（1206 条）+ 平台扩展至 9 个**；并根治「official profile 模型标识错配」导致无法一键切官方 Model Router 的缺陷。

### 数据集与维度扩展（重大变更）
- **真实数据集替换**：demo 演示库由固定种子合成案件替换为 **1206 条真实退货案件**（`demo/cases.json`），胜诉率 **34.6%**；原合成集留存为 `demo/cases_synthetic_backup.json`。
- **平台由 4 个扩展至 9 个**：Amazon / AliExpress / Temu / SHEIN / **eBay / Shopee / Lazada / Walmart / TikTok Shop**（`platforms.py`），平台对比、平台×供应商交叉、平台举证包等看板维度同步扩容。
- **图床激活**：七牛云对象存储接入并启用（`storage.py`，优先级 qiniu > oss > public_base > local），`/api/config` 返回 `image_bed: qiniu`、`image_bed_public: true`，上传图回传真实公网 URL 供模型服务端回源。

### Live 合规（对齐官方 Model Router_API.docx）
- **模型标识 profile 化**：`_MODEL_ROUTER_PROFILES` 新增 `models` 字典，文本/VL/OCR/向量/rerank/TTS 标识随 profile 固化并由 `MODELS[...]` 统一下发，杜绝 base_url 与模型名错配。
- **修复 official 错配**：旧代码在 official profile 下仍向官方端点发无前缀模型名（`qwen3.7-max` / `qwen-audio-3.0-tts-plus` / `qwen3-rerank`），官方会 404。现 official 用 `qwen/qwen3.7-max` / `qwen/qwen3-tts-instruct-flash` / `qwen/qwen3-rerank`。
- **文本模型前缀补齐**：official 下若 `.env` 遗留 tokenplan 风格无前缀命名，自动补 `qwen/` 前缀，保证「改一个 `MODEL_ROUTER_PROFILE` 即一键切官方」。
- 新增交付物：`docs/LIVE_COMPLIANCE.md`（逐项核对表 + 一键切换步骤 + 评委风险）、`docs/PLATFORM_SOURCES.md`（Amazon/AliExpress/Temu/SHEIN 四个核心平台官方政策 URL 核验 + 准确性判定；其余 5 个平台待核验）、`docs/复赛交付物总览.md`（提交清单 + 阶段成果 + 体验指引 + GitCode 镜像说明）。
- README 顶部新增「一分钟速览」（体验地址 / 测试账号 / 版本 / live 合规指针）。

### 修复（Fixes）
- **P0 安全三洞**：大厂标准审查发现的 3 项 P0 安全问题已修复并回归验证。
- **SQLite WAL 失控**：WAL 文件无节制增长问题已收口（checkpoint 策略修正）。
- **AI 诚实性标注补齐**：真实模型输出与 mock 回退在前端与接口层均显式区分标注，杜绝把回退结果当真实能力呈现。
- **CI 转绿**：流水线恢复全绿；当前测试 **88 passed**（含 `/api/export_pdf` 与 `/api/import_csv` 两条此前零覆盖关键链路的补齐用例）。

### 文档（Docs）
- **全仓文档一致性整改**：版本号统一为 1.1.2；案件总数统一为 1206、胜诉率统一为 34.6%、平台数统一为 9；图床状态更正为「七牛云已激活」；公网体验地址更正为「已上线」（https://rg.a703201sworld.top ，`demo`/`demo123`）。
- **开发与部署统一 openGauss**：`db.py` 默认连接改为 openGauss（本地 `localhost:5432/returnguard`，需先 `docker compose -f docker/docker-compose.yml up -d db`），移除「开发期回退 SQLite」表述；01_技术文档架构图、README/PRD/SCHEMA/答辩Q&A/部署指南同步更新；GitCode 镜像地址补全为 https://gitcode.com/a703201/ReturnGuard；`docker-compose.local.yml`（SQLite 版）标记弃用。
- `docs/CODE_REVIEW.md` 新增第十一节「大厂标准审查结论摘要」（综合 5.8/10 六维评分 + 已闭环项 + 待跟进项）。
- 初赛过程材料归档至本仓库 `docs/legacy/`（9 份初赛文档于 2026-08-29 由工作区根目录统一归档，原散落的 `docs_legacy/` 亦并入；根目录仅保留仓库与 `复赛交付物/`）。

### 2026-08-29 部署加固与稳定性修复（同版本 1.1.2 内的补丁集合）

> 审查报告 26 项路线图全部收口后，针对「公网复赛演示」做的部署层收口。版本号维持 1.1.2（`VERSION` 与 `/api/config` 一致），不另行发版。

- **前端 ESM 拆分收口（#24 / 8cbf308）**：前端拆为 `store.js`(单一状态源) + `api.js` + `render.js` + `app.js`(入口编排)；修复拆分时遗留、会导致整文件 JS 语法损坏的游离字符；并修复 `$` 函数未从 `render.js` 导出导致 `init` 抛 `ReferenceError`、页面点击无反应的 bug。
- **零覆盖测试补齐（#11）**：新增 `demo/tests/test_coverage_gap.py`，覆盖 `GET /api/export_pdf` 与 `POST /api/import_csv` 两条此前 0 覆盖链路；测试 **86 → 88 passed**。
- **openGauss 部署切换（610fb0e）**：公网主力由 SQLite 版（`docker-compose.local.yml`）切到 openGauss 版（`docker-compose.yml`），**demo / real / auth 三库全部落在 openGauss**（`db:5432/returnguard`），用户库不再落容器内 SQLite、跨重启不丢；app 端口对齐隧道 `127.0.0.1:65432:8000`。
- **sku_name 长度溢出修复（610fb0e）**：`db.py` 中 `sku_name` 由 `String(128)` 扩至 `String(256)`——cases.json 中有商品名长达 145 字符，openGauss 严格长度校验在批量插入种子时抛 `DataError: value too long for type character varying(128)`；重建镜像 + 清 `ogdata` 卷重播种子，openGauss 现承载 **1206 条** demo 案件。
- **Docker 本地 WAL 崩溃修复（e614140）**：Docker 把主机 `demo/` 绑挂载进容器时，SQLite 在 `PRAGMA journal_mode=WAL` 因 `-shm`/mmap 在 Windows 挂载点不支持而抛 `disk I/O error`、启动即崩；新增 `SQLITE_NO_WAL` 环境变量开关（默认关），本地部署设 `1` 时改用 DELETE 日志模式，宿主机原生 fs / openGauss 不受影响。
- **版本号 Vunknown 修复（c4b12ed）**：Dockerfile 原 `COPY demo/ .` 把源码拍平到 `/app`，使 `main.py` 按 `__file__/../VERSION` 计算版本时路径断裂、返回 `unknown`；改为 `COPY demo/ ./demo/` 保持与本地一致的目录结构，entrypoint 启动前 `cd demo`，并为 `_read_app_version()` 增加 `../VERSION → ./VERSION` fallback。现 `/api/config.version` 正确返回 `1.1.2`。

---

## [1.1.1] — 2026-08-27

> 安全复审全量闭环（公网部署语境）：第八节安全专项复审发现项 SEC-1 ~ SEC-12 **全部清零**。测试 65 → 85，安全面由 A- 提升至 A 区间。

### 安全加固（Security · SEC-1 ~ SEC-12）
- **SEC-1 写接口鉴权全开**：新增 `_require_session`（写接口须登录会话）+ `_require_admin`（`/api/calibrate`、`/metrics` 须 `ADMIN_API_KEY` 或登录）；`/api/analyze`、`POST/DELETE /api/cases`、`/api/import_csv` 收口。匿名写接口 → **401**（公网实测一致）。
- **SEC-2 `AUTH_SECRET` 静默忽略**：`auth.py` 顶部补 `load_dotenv()`（pytest 守卫），`_SECRET` 统一转 bytes，支持 `secrets.token_hex(32)` 配置；令牌跨重启可验。
- **SEC-3 代理 IP 误判**：`get_client_ip` 优先采纳 `CF-Connecting-IP`（Cloudflare Tunnel），部署 `AUTH_TRUSTED_PROXIES=127.0.0.1`；限流/防爆破在多 worker 下生效。
- **SEC-4 停用 `?token=` 传令牌**：仅读 `Authorization: Bearer` / `X-Token` 头，避免令牌经 URL/日志泄露。
- **SEC-5 数据变更须登录**：写接口统一 `_require_session`，`public` 基准亦须登录态。
- **SEC-6 公网关注册**：`REGISTRATION_ENABLED=false`（评委用内置 demo/demo123），保留可选 `REGISTRATION_INVITE_CODE`。
- **SEC-7 `/metrics` 收口**：纳入 `_require_admin`（匿名 401）；`/api/config` 保留开放（仅透出非敏感常量）。
- **SEC-8 上传图签名短链（PII 收敛）**：删除 `/uploads` 静态公开挂载；本地兜底 URL 改由 `storage.sign_upload_url()` 生成 HMAC 签名 + TTL 短链 `/api/file/{sig}?f=&e=`，含路径穿越防护；OSS/七牛公网 URL 不受影响。匿名 `/uploads/任意` → **404**；有效签名 → **200**，伪造/过期 → **404**。
- **SEC-9 CSP nonce 硬化**：首页每请求生成 `secrets.token_urlsafe(16)` nonce 注入内联 `<script>`，CSP `script-src 'self' 'nonce-…'` 去 `unsafe-inline`（style-src 保留 unsafe-inline 为已知权衡）。
- **SEC-10 登录侧信道 / KDF 轮数**：未知用户也跑等代价 pbkdf2（消用户枚举时序差）；pbkdf2 10 万轮 → **60 万轮**，存量账户 rehash-on-login 渐进升级。
- **SEC-11 API Key 常量时间比较**：`_require_api_key`/`_require_admin` 改用 `hmac.compare_digest`。
- **SEC-12 多 worker 共享状态外置**：新增 `shared_state.py`（独立 SQLite `rg_state.db` 存限流/登录锁，滑动窗口防爆破）；`db.py` 代际计数落库 `rg_kv` 表，根治多 worker 陈旧缓存。

### 前端 / 评委体验
- 金额配色提亮、胜诉率环图还原、评委引导横幅、空态文案优化。

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

> 复赛冲刺版本：A 组「假能力变真」、B 组「数据闭环」、C 组「多租户 + 合规 + 国产化部署」全部落地；测试 30 → 65，lint 门禁清零。

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

> 复赛交付基线版本。首次将「退货情报站」作为完整产品形态对外交付：群体洞察看板为产品核心，单案取证为数据采集管道。

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
- 复赛录屏脚本 V1.0（3 分钟精华版，纯分镜/口播）。

### 已知限制（Known Issues）
- 单案取证的缺陷红框为演示示意框，未接入真实视觉模型（live 红框标注待做）。
- live 全链路（真实 LLM 归因 + 公网图床）尚未真跑，缺 `MODEL_ROUTER_API_KEY` 与 `PUBLIC_IMAGE_BASE`。
- 容器化公网部署待做。

---

## 版本规则

- **主版本（MAJOR）**：不兼容的架构/产品定位变更（如赛道方向调整）。
- **次版本（MINOR）**：向后兼容的功能新增（如新增洞察维度、新增平台）。
- **修订（PATCH）**：向后兼容的问题修复（如 bug 修复、文案微调）。
- 每次发版在本文档新增一个 `## [x.y.z]` 区块，并更新仓库根 `VERSION` 文件为同一版本号。
