# ReturnGuard 仓颉后端（当前主力实现）

> 技术栈与档案管理系统（AMS）对齐：**仓颉 Cangjie 1.2.0 + stdx.net.http**。
> 本目录是后端**主力实现**（与旧 Python 后端 `demo/` 并存兼容），2026-11-20 收官。
> 编译产物 18 包 + exe（Windows `build/rg-server.exe` / Linux `build-linux/rg-server`），3 容器部署（`127.0.0.1:58080`）。
> 覆盖：核心 API（30 操作）、**账户安全加固**（审计链/时序/枚举/弱口令/jti）、**单库+演示账户**、**openGauss 全量持久化**（重启不丢）、
> **国密 SM3/SM4 + TOTP**、**配额跨 worker（DB 表）**、**服务端会话（即时吊销 + refresh 轮换 + 并发上限）**、
> **14 平台 AI 适配（含本地 Ollama，设置页可选并保存、重启生效）**、**analyze/live/pdf 双传输**、**CSV/XLSX 导入**、**OAuth2 开放平台**、**Docker 部署（含自愈）**。
> 连接池代码保留但默认禁用（`RG_DB_POOL=0`，仓颉池并发 dead lock，见「登录卡死防护」）。

## 分层结构（对齐 AMS 包组织）

```
backend/
├── rg-kernel/      错误类型 / 日志 / 轻量 JSON（Obj/Arr/FlatJson）
├── rg-data/        store（内存 Store，租户隔离）+ db（openGauss 连接 + 三 Repo，MERGE upsert）
├── rg-security/    audit（SHA256 哈希链审计）、authn（SHA256/HMAC/PBKDF2 + 令牌 + 锁定）、quota（三层配额）
├── rg-api/         http（请求/响应/路由）、server（stdx 分发器 + 静态托管）、routes（端点）
├── rg-ai/          轻量 OpenAI 兼容客户端（stdx.net.http，失败关闭 + 诚实回退）
├── rg-server/      可执行入口 main.cj
├── drv/            opengauss-driver 纯仓颉驱动产物（14 cjo + 14 a，从 AMS 复用）
├── build.sh        子包 staticlib → exe 构建（cjc；drv 用 Windows 风格路径规避中文乱码）
└── build/          rg-server.exe + stdx/运行时 DLL（构建时自动拷贝）
```

## 构建与运行

```bash
cd returnguard/backend
bash build.sh                 # 全量构建 -> build/rg-server.exe（自动拷 DLL）

# 运行（默认 127.0.0.1:8001，同端口托管 Vue 前端 demo/webapp）
# 持久化模式：设置 RG_DB_HOST 即启用 openGauss；不设则回退内存（开发/CI）
cd build
RG_HTTP_PORT=8001 \
RG_WEB_DIR=<绝对路径>/demo/webapp \
RG_VERSION=3.0.0 \
AUTH_SECRET=<生产必填，≥32字节> \
RG_DB_HOST=127.0.0.1 RG_DB_PORT=15432 \
RG_DB_NAME=returnguard_cj RG_DB_USER=gaussdb RG_DB_PASSWORD=<口令> \
./rg-server.exe
```

> openGauss 容器（对齐 AMS 需 `--privileged --user omm`）：
> `docker run -d --name rg_cj_db --privileged --user omm -e GS_PASSWORD=<口令> -e LD_LIBRARY_PATH=/usr/local/opengauss/lib -p 127.0.0.1:15432:5432 --memory 2g enmotech/opengauss:5.0.0`
> 首次启动默认建 gaussdb 用户与 postgres 库；本工程用 psycopg2 或 gsql 建 `returnguard_cj` 库即可（三张表由后端 `initSchema()` 幂等创建）。

环境变量：
| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RG_HTTP_HOST` | `127.0.0.1` | 监听地址 |
| `RG_HTTP_PORT` | `8001` | 监听端口 |
| `RG_WEB_DIR` | `../demo/webapp` | Vue 产物目录（空字符串=不托管） |
| `RG_VERSION` | `3.0.0` | `/api/config` 返回版本 |
| `RG_THRESHOLD_PCT` | `82` | 同款一致性阈值（百分号整数） |
| `AUTH_SECRET` | 随机 | 令牌签名密钥；**生产必须显式提供**（失败关闭） |
| `RG_DB_HOST` | 空 | openGauss 主机；**非空即启用持久化**，空=内存模式 |
| `RG_DB_PORT` | `15432` | 数据库端口 |
| `RG_DB_NAME` | `returnguard_cj` | 数据库名 |
| `RG_DB_USER` | `gaussdb` | 数据库用户 |
| `RG_DB_PASSWORD` | 空 | 数据库口令 |

`/api/config` 的 `persistence` 字段如实返回 `opengauss` / `memory`。

> Windows/Git Bash 坑：DLL 必须放 exe 同目录（构建脚本已处理）；`cjc` 链接参数含 `-l:xxx`，
> 构建脚本用 `MSYS2_ARG_CONV_EXCL='*'` 禁用 MSYS 转换，否则被转义成 `-l;xxx` 报找不到库。

## Docker 部署（仓颉版，2026-11-19 实测通过）

仓颉后端是 Linux ELF（不是 Windows exe），可完整容器化。因仓颉**不支持交叉编译**，
Windows 开发机需借 Linux 工具链镜像 `ams-cj:1.2.0-beta.03`（内含 Linux cjc + stdx）编译，
再打运行镜像。相关文件（均在 `docker/`）：

| 文件 | 作用 |
| --- | --- |
| `backend/build-linux.sh` | 容器内编译脚本（18 包 + ELF + 全套 .so） |
| `backend/drv-linux/` | opengauss 驱动 Linux 产物（14 .a + 14 .cjo，复用 AMS） |
| `docker/build-cangjie-docker.sh` | 一键：容器内编译 → 打镜像 `returnguard-cj:latest` |
| `docker/Dockerfile.cangjie` | 运行镜像（ubuntu:22.04 + ELF + Vue 产物，312MB） |
| `docker/docker-compose.cangjie.yml` | 编排：**3 容器单库结构**——`rg_cj_opengauss`（唯一 DB，独立卷 `cjogdata`）+ `rg_cj_app` + `rg_cj_autoheal`（自愈守护） |

```bash
cd returnguard
bash docker/build-cangjie-docker.sh                          # 编译 + 打镜像
docker compose -f docker/docker-compose.cangjie.yml up -d   # 启动（db 首次初始化较慢）
```

**构建要点（踩坑记录）**：
- 链接静态库须用**裸** `--start-group/--end-group`（cjc 把 `--link-options` 原样传给 ld，
  不能加 `-Wl,` 前缀），解决 api → kernel 交叉引用。
- stdx 动态库**不能全链**：须排除 `syntax/unittest*/plugin.manager/aspect*/fuzz`
  等编译器/工具链专用库，否则 Linux ld 报 `undefined reference to Cangjie::Parser::...`。
- 运行库需补 `libcangjie-dynamicLoader-opensslFFI.so`（cjc runtime 不含，从 AMS Linux 备份补）。
- app 首次启动 openGauss 未就绪会重启几次，最终 healthy（compose `depends_on` 仅等进程）。

**实测证据**：`rg_cj_app` / `rg_cj_opengauss` 均 Up(healthy)；`/api/config`
`persistence=opengauss, quota=opengauss, sources=['unified']`；核心18项/国密11项/会话10项/
AI+PDF 四套端到端全 PASS；Playwright 前端零 console 错误；容器重启后旧令牌仍有效、
注册用户仍在、1206 案件不丢。

> 本机 65xxx 端口被 Windows 保留（WinError 10013），compose 宿主端口已做成可配置：
> `CJ_APP_PORT`（默认 58080）/ `CJ_DB_PORT`（默认 15433），均只绑定回环。

**登录卡死防护（2026-11-19 实测，最终结论）**：真正根因是**仓颉 `PooledDatasource` 并发下内部死锁**
（日志 `Exception: dead lock`、DB 侧连接数 0），并非 session_timeout。三层防护：
1. 🔴 **`RG_DB_POOL=0` 禁用连接池**（compose 默认）：每次新建连接，连接串 `connection_timeout=5000`
   兜底；单容器性能损失可忽略。200 次并发混合 DB 请求实测 0.7s 全 OK、无死锁。
   ⚠️ 本工程不要用仓颉连接池（AMS 可用是因其并发模式不同）。
2. `/health` 深探针执行 `SELECT 1`，DB 不可用返回 503（不再误报 healthy）；
3. `rg_cj_autoheal` 监听 unhealthy 事件自动重启 app（故障注入实测 6s 内恢复）。
> 运维：如仍需手动恢复，`docker restart rg_cj_app` 即可；数据库端口映射已统一，无重复 DB 容器。

## 已实现端点（27 个操作，完整契约见 `docs/openapi.yaml`，SDK 见 `sdk/python/`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 `{"status":"ok"}`（深探针含 DB `SELECT 1`，DB 坏返回 503） |
| GET | `/api/config` | 版本 / 阈值 / 供应商 / 语言 / **当前 AI provider + 能力矩阵**（扁平字段） |
| GET | `/api/platforms` | 平台举证包目录（9 大平台完整规则：退货窗口/响应时限/运费/举证偏向/必备材料/常见失分/特殊条款/能力映射） |
| GET | `/api/ai/providers` | **14 平台能力矩阵**（公开、无密钥）：text/vl/ocr/embed/rerank/tts；含本地 Ollama |
| GET | `/api/ai/settings` | 读取完整 AI 配置（需登录）：provider/baseUrl/model/enabled/onlineAllowed + 密钥脱敏（apiKeySet/apiKeyMask，apiKey 恒空），**密钥绝不回传** |
| POST | `/api/ai/settings` | 保存完整 AI 配置（需登录）：写入 `RG_AI_CONFIG_FILE`（默认 `/app/data/ai_config.env`，容器卷 `cjappdata` 持久化），apiKey 留空不改 / `clearKey=true` 清空；校验端点格式与换行注入；**重启服务后生效**，部署侧环境变量仍可强制覆盖 |
| POST | `/api/auth/register` | 注册（一个用户=一个租户），返回 `{ok,token,refresh_token,username}`；弱口令拒绝 + 重复用户名模糊提示 |
| POST | `/api/auth/register-sm3` | 国密 SM3 口令注册（存量 sha256 用户向前兼容） |
| POST | `/api/auth/login` | 登录，PBKDF2/SM3 + 失败锁定 + 时序防护，返回 `{token,refresh_token}` |
| POST | `/api/auth/refresh` | **一次性轮换** access+refresh；重放检测触发全会话撤销 |
| GET | `/api/auth/me` | 当前用户（需 Bearer 令牌） |
| POST | `/api/auth/logout` | 登出（自增 token_version 使所有令牌失效 + 审计） |
| GET | `/api/auth/totp/{setup,enable,verify,disable,status}` | TOTP 双因素（Base32 密钥、6 位码 30s ±1） |
| GET | `/api/auth/sessions` · POST `/revoke` | 会话列表 / 远程踢出 |
| GET | `/api/insights` | 群体洞察聚合（mock 规则），**需登录按租户隔离**。字段：`sourcing_advice`/`supplier_blacklist`/`sku_insights`/`root_cause_dist`/`sku_ranking`/`anomaly_alerts`/`supplier_scorecard`/`region_view`/`season_view`/`platform_supplier_matrix`/`total_return_cost`/`logistics_cost`，全部真实规则生成 |
| POST | `/api/analyze` | 单案分析（mock/live，逐能力回退如实标注） |
| GET | `/api/export_pdf` | 报告导出；默认 base64 JSON，`?format=binary` 返回真 `application/pdf` 字节流 |
| GET | `/api/cases` | 当前租户最近案件（最多 50 条，需登录） |
| POST | `/api/cases` | 手动录入一条案件（写入内存并落库，需登录；SKU 必填） |
| POST | `/api/cases/import` | **批量 CSV 导入**（中英文列名兼容，SKU 必填；XLSX 明确拒绝不伪装） |
| DELETE | `/api/cases/:caseId` | 删除单条案件（严格按 tenant 隔离，防越权删除） |
| GET | `/api/crypto/capabilities` | 国密能力声明（不含密钥） |
| GET | `/api/audit/verify` | 审计链自证（需登录），返回 `{ok,events,first_bad_seq,head}` |
| GET | `/api/audit/list?limit=` | **审计事件分页检索**（append-only，需登录） |
| POST | `/api/oauth/register` | OAuth2 客户端注册（需登录；client_secret 仅返回一次） |
| POST | `/api/oauth/token` | OAuth2 client_credentials 换令牌（公开；令牌绑定注册者租户） |
| GET | `/api/oauth/clients` | 列出客户端（脱敏，需登录；注册表持久化，重启不丢） |
| POST | `/api/oauth/rotate` | 轮换客户端密钥（需登录；旧 secret 校验通过后立即失效，新密钥仅返回一次） |

安全基线（参考 AMS `docs/03-安全设计专章.md`）：
- 口令：PBKDF2-HMAC-SHA256 40 万轮 + 每用户随机盐；**注册拒绝弱口令**（常见字典 + 纯数字 + 短口令）；
- 令牌：`hex(username).hex(HMAC).exp.ver.jti`（5 段，jti 随机防重放），服务端校验过期/版本/签名，登出即全端失效；
- 暴力破解：连续 5 次失败锁定 15 分钟；**用户不存在时也跑等价 PBKDF2**（抹平时序差，防撞库枚举）；失败响应统一文案；
- 枚举防护：注册对已存在用户返回「若该用户名可用，账户已创建」模糊提示；
- **审计链**：认证事件（注册/登录/失败/登出）append-only 写入，每条含 `prev_hash`，SHA256 哈希链，`/api/audit/verify` 可自证篡改；
- 配额：SEC-13 三层闸（全局日 300 / 租户日 60 / IP 小时 20，配置留后续接环境变量）；
- 静态托管：`/api/*` 永不回落 HTML（JSON 404）、目录穿越四重校验、资产长缓存 + no-sniff。

## 单库 + 演示账户（取消 demo/real 双源）

- 数据层**只有一套案件库**，按 `tenant` 严格隔离（`Store.casesOf` 无 public 旁路）；
- 演示种子归属 `demo` 租户；**未登录不能看数据**（`/api/insights` 返回 401 提示登录）；
- 前端「体验演示账户」走真实 `/api/auth/login`（demo/demo123），拿租户令牌后拉取本租户数据；
- 普通账户登录后看到自己的空库（可后续导入数据），与 demo 数据互不污染。

## openGauss 全量持久化（5 张表，重启不丢数据）

- **五张表**（`Database.initSchema()` 幂等创建）：`rg_users`（账户/令牌版本/锁定/TOTP/算法）、`rg_cases`（案件按 tenant 隔离）、
  `rg_audit`（审计链 append-only）、`rg_quota`（配额计数跨 worker）、`rg_sessions`（令牌摘要会话，即时吊销）。
- **驱动**：复用 AMS 纯仓颉 `opengauss-driver`（`drv/`，14 cjo + 14 a）；须 `import cangjie_tpc::opengauss.driver.*`
  触发顶层注册；`RG_DB_POOL` 控制连接池（compose 默认 **0=无池**：仓颉池并发有死锁 bug，见上「登录卡死防护」）。
- **兼容性**：openGauss 5.0 不支持 `ON CONFLICT` / `ADD COLUMN IF NOT EXISTS`，分别用 `MERGE INTO` / `information_schema` 查列后 ALTER。
- 🔴 **连接泄漏坑**：只 `query().next()` 不读到 EOF 会让连接无法归还、最终阻塞所有 DB 操作——所有 Repo 的查询必须 `while (rs.next())` 读到尾。
- **回退**：未设 `RG_DB_HOST` 自动回退内存模式（离线/CI），`/api/config.persistence` / `quota_backend` 如实返回。
- **写路径**：注册/登录/登出 → `UserRepo`；认证事件 → `AuditRepo`；demo 种子 → `CaseRepo` 批量 MERGE；
  令牌签发 → `SessionRepo`（SHA256 摘要，不存原文）；live 配额 → `QuotaRepo`（MERGE 原子递增）。
- **加载**：启动时从库恢复用户/案件/审计链，重建哈希链 head；令牌因 token_version 落库而重启后仍有效。

## 安全与能力（已实现）

- **国密**：`rg.security.crypto` 复用 AMS SM3/SM4/PBKDF2-HMAC-SM3；注册可选 `/api/auth/register-sm3`（存量 sha256 用户向前兼容）；
  `/api/crypto/capabilities` 如实声明能力。
- **TOTP**：`/api/auth/totp/{setup,enable,verify,disable,status}`，密钥 Base32、6 位码 30s 窗口 ±1，绑定写库并审计。
- **服务端会话**：access 令牌登记会话表，`verify()` 校验会话存在性 → 支持即时吊销；`/api/auth/sessions` 列出会话、`/revoke` 远程踢出；登出撤销全部会话。
- **AI 重活 + 多服务商**：`rg.ai` 配置化 14 平台注册表（tokenplan/official/dashscope/openai/deepseek/moonshot/zhipu/
  siliconflow/openrouter/ollama/azure_openai/anthropic/gemini/custom），OpenAI 兼容 + 本地 Ollama（`127.0.0.1:11434/v1`，免密钥）；
  密钥只从环境变量读、不进任何响应；`/api/analyze` 逐能力回退并如实标注 `capabilities`，无密钥时 mock 不伪装成功。
- **PDF 双传输**：`/api/export_pdf` 默认 base64 JSON（向前兼容），`?format=binary` 返回真 `application/pdf` 字节流（含合法 xref/EOF）。
- **令牌刷新轮换**：登录返回 `{token, refresh_token}`；`/api/auth/refresh` 一次性轮换，refresh 摘要落会话表，`used` 标记重放检测——
  旧 refresh 重用即撤销该用户全部会话。access 令牌仍受 jti + token_version 即时吊销保护。

## 会话增强 + XLSX + OAuth2（2026-11-20 新增）

- **会话并发 + 空闲超时**：`RG_SESSION_MAX`（默认 5，0=不限）登录签发前撤销最旧会话；`RG_SESSION_IDLE_MS`（默认 24h，0=禁用）滑动窗口——每次令牌校验刷新 `rg_sessions.last_used_ms`，超时即撤销（401）。与绝对有效期（7 天）+ jti 即时吊销叠加。
- **XLSX 导入**：`POST /api/cases/import` 的 `source=xlsx` + `content=<base64>`，轻量 ZIP（store/deflate）+ OpenXML 解析，读首个 sheet、共享字符串/数字/inlineStr，转 CSV 复用导入逻辑；中文表头/数据已实测。
  - 边界：只读 `sheet1.xml`（多表/隐藏表不支持）；复杂格式（合并单元格/富文本/公式）取可见文本，非精确还原；解压上限 20MB 防 zip bomb。
- **OAuth2 开放平台**：`POST /api/oauth/register`（需登录，secret 仅返回一次）→ `POST /api/oauth/token`（client_credentials）→ 标准 Bearer 令牌（绑定注册者租户）。`GET /api/oauth/clients` 脱敏列出；`POST /api/oauth/rotate` 轮换密钥。
  - 加固：客户端注册表与令牌 scope 落本地文件（`/app/data/oauth_clients.txt` + `oauth_scopes.txt`，容器卷持久化，重启不丢）；只读 scope（如 `insights:read`）令牌经 Router 全局 guard 禁止写端点（403）；密钥只存 SHA256 摘要。
  - 边界：无刷新令牌、无动态 scope 授予（注册时固定）。

## 诚实边界（仍未做）

- **AI 未配密钥**：本机未配置外部服务商密钥，live 路径走"诚实回退 mock"；真实模型调用逻辑已实现但未在本机实跑验证（界面保存密钥后重启即可验证真模型）。
- **付费/商业生态**：无计费订阅、无第三方真实用户实证、无 benchmark 固化（产品化决策，非技术债）。

## 验证证据（2026-11-19 实际执行）

- `bash build.sh`：18 个包 + exe 全量编译成功，链接 opengauss 驱动 14 个 .a；
- 核心 API（`verify_cj2.py`）**18 项全 PASS**；国密+TOTP（`verify_crypto.py`）**11 项全 PASS**；
  会话即时吊销（`verify_session.py`）**10 项全 PASS**；analyze/PDF（`verify_ai.py`）全 PASS；
- **重启验证**（`persist_step1/step2.py`）全 PASS：旧令牌重启后仍有效、审计链连续自证 ok、案件 1206 条仍在、租户隔离；
- **PDF 实测**：base64 解码得 707 字节、头 `%PDF-1.4`、尾 `%%EOF` 的合法 PDF；
- Playwright（`verify_ui2.py`）：未登录引导、演示账户登录、真实数据看板、零 console 错误；
- Python 测试守护：`pytest demo/tests` 195 passed，零回归。
