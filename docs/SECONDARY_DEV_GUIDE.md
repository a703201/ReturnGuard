# ReturnGuard 二次开发指南

> 适用版本：3.0.0（仓库根 `VERSION` 为单一来源）
> 关联文档：[`ARCHITECTURE.md`](ARCHITECTURE.md)（功能串联）、[`API.md`](API.md)（接口契约）、[`openapi.yaml`](openapi.yaml)（机器可读契约）、[`../backend/README.md`](../backend/README.md)（仓颉后端能力）、[`../sdk/README.md`](../sdk/README.md)（客户端 SDK）

本文说明**在现有工程上扩展**的入口、约束与升级兼容策略。目标是不改核心链路即可加平台、加洞察维度、加页面，且能被守护测试拦住回归。

## 1. 工程版图（开发前必读）

| 层 | 目录 | 角色 | 单一来源 |
|---|---|---|---|
| 仓颉后端（主力） | `backend/`（18 包） | API / 认证 / AI 网关 / 持久化 | `rg-app/src/app.cj`（装配）、`rg-api/src/routes/routes.cj`（路由表） |
| Vue3 前端（主力） | `web/` | 7 页 + 5 组件 | `web/src/router/index.ts`（路由）、`web/src/i18n/catalog.{zh,en,fr}.ts`（三语文案） |
| Python 后端（兼容） | `demo/` | FastAPI 原始实现，仍受守护测试保护 | `demo/config.py`、`demo/providers.py` |
| 离线构建 | `docker/wheels/` | Python 版离线 wheel（不入库） | `scripts/fetch_wheels.py` |
| 契约 | `docs/openapi.yaml` | 仓颉后端 32 操作的 OpenAPI 3.0 | 守护测试逐条比对路由 |
| 版本 | `VERSION` | 全局版本号 | `/api/config`、`package.json`、`CHANGELOG.md`、三份文档断言 |

🔴 **两套实现并存**：业务规则一致，但改主力功能只动 `backend/` + `web/`；`demo/` 的路由/字段/配额变量受 `demo/tests/test_docs_consistency.py` 守护，不要为了"对齐"去改它的接口事实。

## 2. 扩展点 A：新增 AI 平台

仓颉侧单一来源是 `backend/rg-ai/src/providers.cj` 的 `ProviderRegistry.init()`：

1. 在构造函数里 `add(ProviderSpec(key, label, baseUrl, baseUrlEnv, keyEnv, keyRequired, authStyle, textModel, vlModel, capabilities, supported))`。
2. `key` 要同步加进 `docs/AI_PROVIDERS.md` 的平台矩阵表——守护测试断言**文档矩阵 == 注册表 key 集合**。
3. 若平台非 OpenAI 兼容协议，设 `supported=false`，能力缺口如实标注，不伪造成功。
4. 密钥环境变量名填 `keyEnv`，**不要**把任何密钥写进注册表或响应。

前端下拉自动从 `GET /api/ai/providers` 读，无需改组件；如需在"允许数据出境"开关中分类，更新 `web/src/components/AiConfigForm.vue` 的 `onlineKeys`。

Python 版对应声明在 `demo/providers.py`，两侧 key 集合应保持一致。

## 3. 扩展点 B：新增洞察维度

洞察由案件数据规则派生，入口 `backend/rg-api/src/routes/insights.cj` 的 `insights(ctx, req)`：

- 只读派生：在函数中按 `platform/supplier/category/region/season` 分组聚合，复用 `rootCauseDist` / `sourcingAdvice` 的既有模式；**不写库、不臆造数据**。
- 前端卡片在 `web/src/views/DashboardView.vue`，加卡时同步三语 `set.*` / `dash.*` 键。
- 若新增筛选项，必须写进 `docs/API.md` 的 `/api/insights` 参数表（守护断言）。
- 判定阈值变化要同步 `docs/DECISION_LOGIC.md`（守护断言关键阈值）。

## 4. 扩展点 C：新增路由（API）

1. 在 `backend/rg-api/src/routes/routes.cj` 的 `registerRoutes()` 里注册，**并立即写进 `docs/openapi.yaml`**——`test_cangjie_routes_match_openapi_contract` 会逐条比对 `METHOD path`，漏写直接失败。
2. 需登录的端点用 `currentUser(ctx, req).isEmpty()` 判 401；OAuth 写操作受全局 guard 限制（只读 scope 自动 403）。
3. 响应统一用 `ApiResponse.ok/ fail`，错误语义用 `ErrKind`；不要把内部异常文本回传。
4. 涉及密钥/令牌的字段：GET 只回掩码与布尔，POST 留空表示不修改，`clearKey=true` 才是清空（参照 `/api/ai/settings`）。
5. 新增环境变量要写进 `docker/.env.example` 与 `docs/DEPLOYMENT.md`。

## 5. 扩展点 D：新增前端页面

1. `web/src/views/` 建 `XxxView.vue`，用现有 `AppIcon`（线性图标，无 emoji）与全局令牌（`--bg-*`/`--text-*`/`--accent`），不要新造配色。
2. `web/src/router/index.ts` 注册路由；导航项在 `web/src/App.vue` 的 `nav` 数组（辅助功能放 `side-bottom`）。
3. 三语文案写进三份 `catalog.*.ts`——守护要求三语键集合完全一致、零重复。
4. 图省事复制 `AiConfigForm.vue` 的表单范式（`.ai-field` / `.field` / `.field-err`），键盘与焦点样式已内建。
5. 可用组件契约（复用优先于新建）：

| 组件 | 用途 | 关键输入/事件 |
|---|---|---|
| `AiConfigForm.vue` | AI 配置表单 | `saved` 事件；内部读 `/api/ai/settings` |
| `OnboardingSheet.vue` | 首次引导 | `open` prop；`close` 事件 |
| `LoginSheet.vue` | 登录弹层 | `open` prop；`logged-in` / `close` |
| `AppIcon.vue` | 线性图标 | `name` / `size` / `stroke` |

## 6. 配置单一来源与环境变量

| 变量 | 默认 | 作用 | 读取处 |
|---|---|---|---|
| `RG_VERSION` | `3.0.0` | `/api/config.version` | `backend/rg-server/src/main.cj` |
| `AUTH_SECRET` | 进程内随机 | 令牌 HMAC 密钥（生产必填） | `AppContext` 构造 |
| `RG_DB_POOL` | `0` | 连接池大小，0=禁用（**勿改**，仓颉池并发死锁） | `AppContext` |
| `RG_SESSION_MAX` | `5` | 并发会话上限，0=不限 | `AppContext` |
| `RG_SESSION_IDLE_MS` | `86400000`（24h） | 会话空闲超时，0=禁用 | `SessionRepo` |
| `RG_AI_CONFIG_FILE` | `/app/data/ai_config.env` | AI 配置持久化文件 | `AiSettingsStore` |
| `RG_OAUTH_FILE` | `/app/data/oauth_clients.txt` | OAuth 客户端/scope 持久化 | `OAuthStore` |

🔴 密钥类配置**只存服务端文件/环境变量**，不进任何响应；`/app/data` 由 compose 卷 `cjappdata` 持久化，容器重建不丢。

## 7. 升级兼容策略

- **版本号**：语义化版本；大改升 major，兼容新增升 minor，修复升 patch。改 `VERSION` 必须同步 `package.json`、`web/package.json`、`openapi.yaml` 的 `info.version`、CHANGELOG 首条、README/SCHEMA/CODE_REVIEW 的版本声明——守护测试逐项断言。
- **契约兼容**：已发布的路由路径、字段名、i18n key 只增不改；确需破坏性变更时升 major 并在 CHANGELOG 独立分章说明迁移路径。
- **配置兼容**：新增配置必须有默认值；文件存储用"缺列即补"的幂等迁移（参照 `db.cj` 的 `hasColumn` + `ALTER TABLE`），旧文件缺字段按默认处理。
- **数据兼容**：表结构变更只加列不删列；`rg_sessions` 的 `refresh_hash`/`used`/`last_used_ms` 都是后加列，历史数据自动兼容。
- **双实现并存**：Python 版 `demo/` 是兼容基线，守护测试保护其接口事实；新功能先落仓颉主力，确认稳定后再决定是否同步 Python 版。

## 8. 构建与验证命令（必跑）

```bash
# 仓颉后端（Windows 本机）
cd backend && bash build.sh

# Linux 产物（复用 ams-cj 工具链镜像）
cd .. && bash docker/build-cangjie-docker.sh   # 或见 backend/build-linux.sh

# 前端
cd web && npx vue-tsc --noEmit && npx vite build   # 产物落 demo/webapp/

# 守护 + 全量测试
cd .. && python -m pytest -q demo/tests
python scripts/check_i18n.py

# 容器部署与判活
cd docker && docker compose -f docker-compose.cangjie.yml up -d --build
curl --noproxy '*' http://127.0.0.1:58080/api/config | python -m json.tool
```

**验收清单**：新增端点在 openapi 有对应 operation；三语键集合一致；`pytest demo/tests` 全绿；前端类型检查零错误；`curl` 判活版本与 `VERSION` 一致。涉及浏览器交互的改动需实际点一遍（新建账户 / AI 保存 / 引导流程），不能只靠静态检查宣称通过。
