# ReturnGuard 部署与运维指南

> 适用版本：2.0.0（仓库根 `VERSION` 为单一来源）
> 相关文档：[`openGauss部署指南.md`](../openGauss部署指南.md)（openGauss 细节与真实数据自动导入）、[`API.md`](API.md)、[`SCHEMA.md`](SCHEMA.md)

---

## 1. 目标与形态

| 维度 | 说明 |
|---|---|
| 运行形态 | Docker Compose：`db`（openGauss）+ `app`（FastAPI）+ `realdb-init`（一次性建 real 库） |
| 数据库 | **openGauss 5.0.0**（兼容 PostgreSQL 协议），demo / auth 落 `returnguard`，**real 落独立库 `returnguard_real`** |
| 对外暴露 | 应用与数据库**均只绑宿主机回环**（`127.0.0.1:65432` / `127.0.0.1:5432`）；公网发布由部署方前置反向代理 / CDN 并配置 HTTPS |
| 兜底形态 | 无 openGauss 环境时用 `docker-compose.pg.yml`（PostgreSQL 版，含同样的 real 库初始化与端口收敛） |
| 非容器形态 | 直接 `uvicorn main:app`（开发 / 联调），见 §5 |

> **为什么默认只绑回环**：非提权进程绑定 `0.0.0.0` 或低端口在 Windows 上会报 `winerror 10013`；
> 且应用与数据库直接暴露到局域网是常见事故源。需要公网访问时，正确做法是在前面加一层
> 反向代理（Nginx / Cloudflare 等）并设置 `AUTH_TRUSTED_PROXIES`。

---

## 2. 快速部署（openGauss）

```bash
cd returnguard

# 1) 准备环境变量（必填 GS_PASSWORD；缺失时 compose 直接报错中止）
cp docker/.env.example docker/.env
vi docker/.env

# 2) 构建并启动
docker compose -f docker/docker-compose.yml up -d --build app

# 3) 判活
curl -s http://127.0.0.1:65432/health
curl -s http://127.0.0.1:65432/api/config      # 应含 "version": "2.0.0"
```

一键脚本等价封装：

```bash
python start_rg.py            # 启动容器并等待 /health 就绪（首次含 openGauss 初始化，最多等 3 分钟）
python start_rg.py --build    # 改完代码后重建镜像再启动
python stop_rg.py             # 停止容器（保留容器，下次可 docker start 秒起）
python stop_rg.py --down      # 移除容器与网络（named volume 保留，数据不丢）
```

> ⚠️ 本机旧版 `docker compose` 插件不可用时，改用独立 `docker-compose -f docker/docker-compose.yml ...`。
> **服务名是 `db` / `app`**，重建要写 `--build app`。

## 3. 兜底部署（PostgreSQL）

openGauss 镜像在部分 Docker Desktop / WSL2 环境下不稳定时，可用官方 PostgreSQL 做本地全链路验证：

```bash
docker compose -f docker/docker-compose.pg.yml up -d --build
```

该编排与主 compose **口径对齐**：口令强制必填（`GS_PASSWORD`）、数据库与应用端口仅绑回环、
独立的 `realdb-init` 创建 `returnguard_real` 保持 demo/real 物理隔离、透传 `AUTH_SECRET` /
`ADMIN_API_KEY` / `STATE_DB_URL`，并挂载 `pgdata` / `pg_uploads` / `pg_state` 三个持久卷。

> 仅用于验证，不作为生产形态；生产请用 openGauss 编排。

---

## 4. 环境变量清单

### 4.1 数据库与存储

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | openGauss `localhost:5432/returnguard` | demo 源（共享只读演示库） |
| `REAL_DATABASE_URL` | **由 `DATABASE_URL` 推导 `*_real`** | real 源（真实数据，按租户隔离） |
| `AUTH_DATABASE_URL` | 同 `DATABASE_URL` | 账户 / 令牌库 |
| `STATE_DB_URL` | `demo/rg_state.db` | 限流 / 登录锁 / live 配额计数；**仅支持 SQLite**（依赖 `ON CONFLICT` upsert），容器内建议 `sqlite:////app/demo/state/rg_state.db` |
| `GS_PASSWORD` / `GS_HOST` / `GS_PORT` / `GS_USERNAME` | `Gauss-2026` / `localhost` / `5432` / `gaussdb` | openGauss 连接参数（compose 中 `GS_PASSWORD` 必填） |
| `FORCE_RESEED` | 空 | `1` = 启动时重建 demo 演示种子（real 源数据不动） |
| `RG_AUTO_IMPORT_CSV` | 空 | 启动时把该 CSV 导入 real 源（`dedupe` 幂等） |
| `UPLOAD_MAX_AGE_HOURS` | `24` | 上传图清理阈值 |
| `UPLOAD_URL_TTL` | `3600` | 上传图签名短链有效期（秒） |

> **real 源不会误写进 demo 库**：`REAL_DATABASE_URL` 留空时由 `DATABASE_URL` 派生独立库名；
> 若连接串形态导致无法派生，启动日志会打 `CRITICAL`，请显式配置。

### 4.2 安全（对外部署必设）

| 变量 | 说明 |
|---|---|
| `AUTH_SECRET` | 令牌 HMAC 签名密钥。**不设则每次重启进程内随机**，所有已签发令牌失效（应用启动打 `CRITICAL`） |
| `ADMIN_API_KEY` | `/api/calibrate`、`/metrics` 管理端点密钥；不设则退化为「要求登录」 |
| `AUTH_TRUSTED_PROXIES` | 可信反代网段（逗号分隔 IP/CIDR）。反代场景必设，否则限流/防爆破按 `127.0.0.1` 单桶计数而失效 |
| `REGISTRATION_ENABLED` | 注册开关，默认 `false`（secure-by-default） |
| `REGISTRATION_INVITE_CODE` | 邀请码；非空则注册须匹配 |
| `AUTH_REGISTER_LIMIT` / `AUTH_LOGIN_IP_LIMIT` | 每 IP 每分钟注册 / 登录上限（默认 10 / 30） |
| `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN` | 单用户名连续失败上限与锁定时长（默认 5 次 / 15 分钟） |
| `ANALYZE_RATE_LIMIT` | 分析接口每客户端每分钟上限（默认 60，`0` 关闭） |
| `EXPORT_PDF_RATE_LIMIT` | 报告导出每客户端每分钟上限（默认 20，`0` 关闭） |
| `CORS_ALLOW_ORIGINS` | 跨域白名单（逗号分隔具体域名，**禁止 `*`**）；留空 = 不挂 CORS |

生成密钥：

```bash
python -c "import secrets;print(secrets.token_hex(32))"   # AUTH_SECRET
python -c "import secrets;print(secrets.token_hex(24))"   # ADMIN_API_KEY
```

### 4.3 live 模型链路

| 变量 | 说明 |
|---|---|
| `MODEL_ROUTER_PROFILE` | `tokenplan`（默认）/ `official` / `dashscope` |
| `MODEL_ROUTER_API_KEY` | tokenplan profile 的 Key（**live 必需**） |
| `MODEL_ROUTER_OFFICIAL_KEY` / `MODEL_ROUTER_OFFICIAL_BASE_URL` | official profile 的 Key / 端点覆盖 |
| `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` | dashscope profile |
| `MODEL_ROUTER_TEXT_MODEL` | 覆盖默认文本模型（注意 official 下需带 `qwen/` 前缀） |
| `PUBLIC_IMAGE_BASE` / `RG_SELF_IMAGE_BASE` / `IMAGE_BED` | **可选**：仅在希望视觉能力走「公网 URL 回源」时配置；默认内联 base64，无需公网图床 |
| `LIVE_QUOTA_GLOBAL_DAY` / `LIVE_QUOTA_TENANT_DAY` / `LIVE_QUOTA_IP_HOUR` | SEC-13 三层 live 配额（默认 300 / 60 / 20，`0` 关闭该层） |

> 切换 profile 时 **base_url + key + 模型标识三者联动**，只改 `MODEL_ROUTER_PROFILE` 即可，
> 模型标识的单一来源是 `demo/models_router.py` 的 `_MODEL_ROUTER_PROFILES`。

### 4.4 其他

| 变量 | 说明 |
|---|---|
| `SERVE_MINIFIED` | `1` = 改发 `demo/static/dist/` 的压缩产物（需先 `npm run build`）；默认发未压缩源 |
| `SQLITE_NO_WAL` | `1` = SQLite 改用 DELETE 日志模式（绑挂载场景兜底） |
| `WAL_CHECKPOINT_INTERVAL_SEC` | SQLite WAL 巡检间隔（秒，`<=0` 关闭） |
| `RG_COMPOSE_FILE` | `start_rg.py` / `stop_rg.py` 使用的 compose 文件路径覆盖 |
| `RG_LOCAL_URL` | `start_rg.py` 判活与打开页面使用的本地地址 |

---

## 5. 非容器部署（开发 / 联调）

```bash
cd returnguard/demo
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

- 默认连 openGauss；无 openGauss 时显式回退 SQLite：`DATABASE_URL=sqlite:///./cases.db`。
- `real` 源会按 `_derive_real_url` 推导出 `cases_real.db`，与 demo 分库。
- 用 `127.0.0.1` 而非 `0.0.0.0`：非提权进程绑低端口 / 通配地址在 Windows 上可能报 `winerror 10013`。

---

## 6. 系统服务化（systemd，可选）

仓库提供 `docker/returnguard.service`（把 compose 栈注册为系统服务）：

```bash
sudo cp docker/returnguard.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now returnguard
systemctl status returnguard          # 判活
journalctl -u returnguard -f          # 日志
```

前提：仓库放在 `/opt/returnguard` 且同目录存在 `.env`（含 `GS_PASSWORD` / `AUTH_SECRET` 等，**切勿入库**）。

---

## 7. 验证部署

```bash
# 健康探针
curl -s http://127.0.0.1:65432/health

# 版本与运行态（图床后端、网关 profile、语种清单）
curl -s http://127.0.0.1:65432/api/config

# demo 源案件数（应稳定为 1206，不随 real 写入变化）
curl -s "http://127.0.0.1:65432/api/cases?source=demo&slim=1" \
  | python -c "import sys,json;print('demo 案件数:',len(json.load(sys.stdin)['items']))"

# real 源：须登录（匿名应 401）
TOK=$(curl -s -X POST http://127.0.0.1:65432/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"demo","password":"demo123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOK" \
  "http://127.0.0.1:65432/api/insights?source=real&mode=mock" | head -c 300
```

---

## 8. 故障排查

| 现象 | 排查与处置 |
|---|---|
| 容器起不来 / 应用连不上库 | `docker logs rg_opengauss`、`docker logs rg_app`；确认 `docker/.env` 里 `GS_PASSWORD` 已填（缺失时 compose 直接中止） |
| `DataError: value too long` | 理论上已被持久层 `_clamp_values` 按列长截断；若仍出现，检查是否绕过 `save_case` 直接写库 |
| `no such table: cases` | 表未初始化：确认 `entrypoint.sh` 正常执行（`init_db()`）；离线 SQLite 场景确认 `DATABASE_URL` 指向可写路径 |
| 重启后需重新登录 | `AUTH_SECRET` 未固化（进程内随机密钥）→ 设置高熵 `AUTH_SECRET` |
| 限流「所有人共用一个桶」 | 反代场景未设 `AUTH_TRUSTED_PROXIES` → 直连 IP 恒为 `127.0.0.1`，需把反代回环 IP 加入白名单 |
| 前端「升级后不生效」 | 静态资源已 URL 版本化（`?v=<VERSION>` + `no-store`）；若仍异常，用 `curl -D -` 对比 origin 与公网链路的 `Cache-Control` |
| 数据库连接被局域网访问 | 确认 compose 端口为 `127.0.0.1:5432:5432`（而非 `5432:5432`）；需本机直连时用 `127.0.0.1` 或进容器执行 |
| `SERVE_MINIFIED=1` 后前端报 404 | 未先生成压缩产物 → `npm run build`，或改回 `SERVE_MINIFIED=0` |

---

## 9. 备份与恢复

- **业务数据**：openGauss 数据在 named volume `ogdata`。备份建议在容器内用 `gs_dump`（或 `pg_dump` 兼容模式）导出，而非直接复制卷文件。
- **上传图 / 状态库**：分别是 `rg_uploads`、`rg_state` 两个 named volume。
  - `rg_state` 丢了的后果是限流与 live 配额计数清零（不影响业务数据），可接受；
  - `rg_uploads` 丢了会导致历史 case 的退货图打不开（签名短链 404）。
- **配置**：`docker/.env`（gitignored）与 `AUTH_SECRET` 是「基础设施即代码」的一部分，请纳入密钥管理；`AUTH_SECRET` 变更会让所有已签发令牌失效。
- `docker compose -f docker/docker-compose.yml down` **不会**删除 named volume；只有显式 `docker volume rm` 才清数据。
