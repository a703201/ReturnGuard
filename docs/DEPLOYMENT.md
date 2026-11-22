# ReturnGuard 部署与运维指南

> **当前形态（2026-11-22）**：仓颉后端 18 包 + Vue3 前端 + Rust 二进制启动器，openGauss 单库。
> 主力部署：`docker/docker-compose.cangjie.yml` —— 3 容器：
> `rg_cj_app`（仓颉后端 + Vue 前端，`127.0.0.1:58080`）/ `rg_cj_opengauss`（唯一 DB，`15433`）/ `rg_cj_autoheal`（unhealthy 自动重启）。
> 构建：`bash docker/build-cangjie-docker.sh`（工具链镜像 `ams-cj:1.2.0-beta.03` 缺失时自动从 `D:/cangjie-sdk-cache` 重建）。
> 关键点：`RG_DB_POOL=0` 禁用仓颉连接池（并发 dead lock）；启动日志应显示「数据库连接已建立（无池）」。
>
> 适用版本：3.1.0（仓库根 `VERSION` 为单一来源）
> 相关文档：[`README.md`](../README.md)、[`backend/README.md`](../backend/README.md)、
> [`launcher/README.md`](../launcher/README.md)、[`openGauss部署指南.md`](../openGauss部署指南.md)

---

## 1. 目标与形态

| 维度 | 说明 |
|---|---|
| 运行形态 | Docker Compose：`db`（openGauss 5.0）+ `app`（仓颉后端，同端口托管 Vue 前端）+ `autoheal`（自愈守护） |
| 数据库 | **openGauss 5.0.0**（兼容 PG 协议），单库 `returnguard_cj`，五表 `rg_users` / `rg_cases` / `rg_audit` / `rg_sessions` / `rg_quota` |
| 对外暴露 | 应用与数据库**均只绑宿主机回环**（`127.0.0.1:58080` / `127.0.0.1:15433`）；公网发布由部署方前置反向代理 / CDN 并配置 HTTPS |
| 持久卷 | `cjogdata`（数据库）/ `cjappdata`（AI 配置 `/app/data`，设置页保存后重启不丢） |
| 非容器形态 | 本地 `rg-server.exe`（开发 / 联调），见 §5 |
| 桌面启动器 | `launcher/`：Windows WinUI 3 / Linux GTK4，可视化启停、状态、日志，见 [`launcher/README.md`](../launcher/README.md) |

> **为什么默认只绑回环**：非提权进程绑定 `0.0.0.0` 或低端口在 Windows 上会报 `winerror 10013`；
> 且应用与数据库直接暴露到局域网是常见事故源。需要公网访问时，正确做法是在前面加一层
> 反向代理（Nginx / Cloudflare 等）并设置 `AUTH_TRUSTED_PROXIES`。

---

## 2. 快速部署（openGauss）

```bash
cd returnguard

# 1) 准备环境变量（GS_PASSWORD、AUTH_SECRET 必填；缺失时 compose 直接中止）
cp docker/.env.example docker/.env
vi docker/.env

# 2) 构建仓颉后端镜像（Linux ELF，工具链容器内编译，非交叉编译）
bash docker/build-cangjie-docker.sh

# 3) 启动三容器
docker compose -f docker/docker-compose.cangjie.yml up -d --build

# 4) 判活（/health 为含 DB 的深探针，DB 故障返回 503）
curl --noproxy '*' http://127.0.0.1:58080/health
curl --noproxy '*' http://127.0.0.1:58080/api/config      # 应含 "version": "3.1.0"
```

也可以直接用桌面启动器（推荐日常使用）：构建后运行，界面点「启动服务」；
它封装了上述构建、启停、健康探测与日志查看，并会提示失败原因。

> ⚠️ 本机 `docker compose` 插件不可用时，改用独立 `docker-compose -f docker/docker-compose.cangjie.yml ...`。
> 服务名是 `db` / `app` / `autoheal`，容器名是 `rg_cj_opengauss` / `rg_cj_app` / `rg_cj_autoheal`。
> 本机 65xxx 段被 Windows 保留，故端口默认为 58080 / 15433；如需调整，改 `docker/.env` 的 `CJ_APP_PORT` / `CJ_DB_PORT`。

### 2.1 仓颉镜像构建说明

仓颉 SDK **不支持交叉编译**，本机 SDK 也没有 Linux 目标（PE32+ exe 跑不了 Linux 容器）。
构建复用本机已有的工具链镜像 `ams-cj:1.2.0-beta.03`（含 Linux cjc + stdx，免下 200MB SDK）
与 AMS Linux 备份的 openGauss 驱动 / FFI 库。要点：

- Linux 链接用裸 `--start-group`（无 `-Wl,`），stdx 排除 `syntax` / `unittest` / `plugin.manager` / `aspect*` / `fuzz`，补 `opensslFFI.so`。
- `build.sh` 的驱动 import-path 必须用 Windows 风格路径（cjc 会把中文路径乱码）。
- 驱动复用 AMS `backend/drv/`（14 cjo + 14 a），必须 `import cangjie_tpc::opengauss.driver.*` 触发顶层注册。

镜像构建脚本已封装这些细节，通常无需手工干预；失败时先看脚本输出与 `backend/README.md`「踩坑」章节。

---

## 3. 环境变量清单

### 3.1 服务与数据库

| 变量 | 默认 | 说明 |
|---|---|---|
| `RG_HTTP_HOST` / `RG_HTTP_PORT` | `127.0.0.1`（容器 `0.0.0.0`）/ `8001`（容器 `8000`） | 监听地址与端口 |
| `RG_WEB_DIR` | `../demo/webapp` | Vue 产物目录（空字符串 = 不托管） |
| `RG_VERSION` | `3.1.0` | `/api/config` 返回值 |
| `RG_THRESHOLD_PCT` | `82` | 同款一致性阈值（整数百分号） |
| `RG_DB_HOST` | 空 | openGauss 主机；**非空即启用持久化**，空 = 内存回退（开发 / CI） |
| `RG_DB_PORT` / `RG_DB_NAME` / `RG_DB_USER` / `RG_DB_PASSWORD` | `15432` / `returnguard_cj` / `gaussdb` / 空 | 连接参数 |
| `RG_DB_POOL` | `0` | **保持 0**：仓颉池并发存在 dead lock；每次新建连接，连接串 `connection_timeout=5000` |
| `CJ_APP_PORT` / `CJ_DB_PORT` | `58080` / `15433` | compose 宿主机映射端口（仅回环绑定） |
| `GS_PASSWORD` | 必填 | openGauss 初始口令 |

### 3.2 认证安全

| 变量 | 说明 |
|---|---|
| `AUTH_SECRET` | 令牌签名密钥，**生产必填 ≥32 字节**；不设则服务拒绝启动 |
| `RG_SESSION_IDLE_MS` | 会话空闲超时（毫秒，默认 24h，`0` = 禁用），滑动窗口刷新 `rg_sessions.last_used_ms` |
| `RG_SESSION_MAX` | 单账号并发会话上限（默认 5，`0` = 不限） |
| `AUTH_TRUSTED_PROXIES` | 可信反代网段（逗号分隔 IP/CIDR）。反代场景必设，否则限流 / 防爆破按 `127.0.0.1` 单桶计数而失效 |

生成密钥（任选一种）：

```bash
openssl rand -hex 32
# 或：python -c "import secrets;print(secrets.token_hex(32))"
```

### 3.3 AI 平台

| 变量 | 说明 |
|---|---|
| `RG_AI_PROVIDER`（兼容别名 `MODEL_ROUTER_PROFILE`） | 选择平台，默认 `tokenplan`；可选值见 `GET /api/ai/providers` 或 [`AI_PROVIDERS.md`](AI_PROVIDERS.md) |
| `RG_AI_BASE_URL` / `RG_AI_KEY` / `RG_AI_MODEL` | 启动注入的网关配置；无密钥时 `/api/analyze` 诚实回退 mock，不伪装成功 |
| 各平台密钥变量 | 见 [`AI_PROVIDERS.md`](AI_PROVIDERS.md)；设置页保存后写入卷 `cjappdata`，重启生效 |
| `RG_AI_CONFIG_FILE` | AI 配置持久化路径（默认 `/app/data/ai_config.env`） |

> 设置页读写端点 `GET/POST /api/ai/settings` **需登录**，密钥永不回传（只有 `apiKeySet` / `apiKeyMask`）。
> 平台能力缺口（如 OpenAI 无 rerank、DeepSeek 无视觉）在运行期如实回退并在响应中标注；
> 切换前建议先查 `GET /api/ai/providers` 的能力矩阵。数据出境与合规提示见 [`AI_PROVIDERS.md`](AI_PROVIDERS.md) §8。

---

## 4. 非容器部署（开发 / 联调）

```bash
cd returnguard
bash backend/build.sh                     # 生成 build/rg-server.exe
RG_HTTP_PORT=8001 \
RG_WEB_DIR=<绝对路径>/demo/webapp \
RG_DB_HOST=127.0.0.1 RG_DB_PORT=15433 \
RG_DB_NAME=returnguard_cj RG_DB_USER=gaussdb RG_DB_PASSWORD=<口令> \
AUTH_SECRET=<≥32字节密钥> \
./build/rg-server.exe
```

- 不设 `RG_DB_HOST` 时自动回退内存模式（离线 / CI），`/api/config.persistence` 如实返回。
- 用 `127.0.0.1` 而非 `0.0.0.0`：非提权进程绑低端口 / 通配地址在 Windows 上可能报 `winerror 10013`。
- 内存 Store 与 DB 是两层：直接删 DB 记录不会同步内存，需重启应用重载。

---

## 5. 系统服务化

仓库不再内置 systemd unit（原 unit 指向已归档的旧栈）。生产环境请按实际路径自建 unit，
核心 `ExecStart` 为：

```ini
ExecStart=/usr/bin/docker compose -f /opt/returnguard/docker/docker-compose.cangjie.yml up -d
WorkingDirectory=/opt/returnguard
Restart=on-failure
```

前提：仓库放在 `/opt/returnguard` 且 `docker/.env` 含 `GS_PASSWORD` / `AUTH_SECRET`（**切勿入库**）。

---

## 6. 验证部署

```bash
# 健康探针（含 DB 深探针）
curl --noproxy '*' http://127.0.0.1:58080/health

# 版本 / 运行态
curl --noproxy '*' http://127.0.0.1:58080/api/config

# 公开能力矩阵、平台举证包、国密能力
curl --noproxy '*' http://127.0.0.1:58080/api/ai/providers
curl --noproxy '*' http://127.0.0.1:58080/api/platforms
curl --noproxy '*' http://127.0.0.1:58080/api/crypto/capabilities

# 需登录的洞察接口：先登录拿令牌
TOK=$(curl --noproxy '*' -s -X POST http://127.0.0.1:58080/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"demo","password":"demo123"}' \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl --noproxy '*' -s -H "Authorization: Bearer $TOK" \
  http://127.0.0.1:58080/api/insights | head -c 300
```

> 沙箱环境有代理，不加拿 `--noproxy '*'` 会返回 502。

---

## 7. 故障排查

| 现象 | 排查与处置 |
|---|---|
| 容器起不来 / 应用连不上库 | `docker logs rg_cj_opengauss`、`docker logs rg_cj_app`；确认 `docker/.env` 的 `GS_PASSWORD` 已填 |
| 登录间歇卡死、`Exception: dead lock` | 仓颉连接池内部死锁 → 确认 `RG_DB_POOL=0`（compose 已默认）；重启 app 容器临时恢复，`autoheal` 会兜底 |
| `/health` 返回 503 | DB 深探针失败 → 查 DB 容器状态与卷 `cjogdata`；`autoheal` 发现 unhealthy 会自动重启 app |
| openGauss 初始化失败 | 启动必须 `--privileged --user omm -e LD_LIBRARY_PATH=/usr/local/opengauss/lib`，且**只设 `GS_PASSWORD`**（设 `GS_DBNAME` 会触发初始化 bug） |
| 查询挂起 / 连接耗尽 | openGauss 5.0 不支持 `ON CONFLICT` / `ADD COLUMN IF NOT EXISTS`；查询必须 `while(rs.next())` 读到 EOF，否则连接泄漏 |
| 重启后需重新登录 | `AUTH_SECRET` 未固化；设置后令牌才可跨重启有效 |
| 限流「所有人共用一个桶」 | 反代场景未设 `AUTH_TRUSTED_PROXIES` → 直连 IP 恒为 `127.0.0.1` |
| 前端「升级后不生效」 | 静态资源已 URL 版本化（`?v=<VERSION>` + `no-store`）；确认改前端后已 `cd web && npx vite build` 更新 `demo/webapp/` |
| 启动器显示「未创建」 | `docker` / `docker compose` 不在 PATH，或 compose 文件路径变更；检查启动器日志提示 |

---

## 8. 备份与恢复

- **业务数据**：openGauss 数据在 named volume `cjogdata`。备份建议在容器内用 `gs_dump`（或 `pg_dump` 兼容模式）导出，而非直接复制卷文件。
- **AI 配置**：卷 `cjappdata`（`/app/data/ai_config.env`，含设置页保存的端点与模型配置）。丢失后需重新在设置页填写。
- **配置**：`docker/.env`（gitignored）与 `AUTH_SECRET` 是「基础设施即代码」的一部分，请纳入密钥管理；`AUTH_SECRET` 变更会让所有已签发令牌失效。
- `docker compose -f docker/docker-compose.cangjie.yml down` **不会**删除 named volume；只有显式 `docker volume rm` 才清数据。
- openGauss 冷备演练脚本：`scripts/og_cold_backup.sh`。
