# ReturnGuard · openGauss 部署与数据导入指南

> **🟢 当前实现（仓颉单一栈）**：compose（`docker/docker-compose.cangjie.yml`）为 **3 容器单库结构**——openGauss 容器 `rg_cj_opengauss`
>（宿主 `127.0.0.1:15433` → 容器 `5432`，库 `returnguard_cj`，卷 `cjogdata`）、仓颉 app `rg_cj_app`（`127.0.0.1:58080`）、自愈守护 `rg_cj_autoheal`。
> app 通过 `RG_DB_HOST=db` 连接，`RG_DB_POOL=0`（仓颉池并发 dead lock，禁用）。
>
> **历史记录说明**：历史版本记录保留当时叙事，当前事实以 [`backend/README.md`](backend/README.md)、根 [`README.md`](README.md) 与
> [`docker/docker-compose.cangjie.yml`](docker/docker-compose.cangjie.yml) 为准。
>
> 适用：生产部署期使用国产数据库 openGauss 承载**全部业务数据**——仓颉后端连接单库 `returnguard_cj`（`rg_users` / `rg_cases` / `rg_audit` / `rg_sessions` 等表），
> 按 `tenant_id` 做租户隔离，**不再有 demo/real 双库**。

---

## 1. 前置条件

- Docker 已就绪，并按 `docker/.env.example` 准备 `docker/.env`（`GS_PASSWORD` / `AUTH_SECRET` 必填）。
- openGauss 由 compose 的 `rg_cj_opengauss` 容器提供（镜像 `enmotech/opengauss:5.0.0`）。示例连接信息：
  - 主机：`127.0.0.1`，端口 `15433`（`CJ_DB_PORT`，容器内 `5432`）
  - 库：`returnguard_cj`（`GS_DB`），卷 `cjogdata`
  - 用户：`gaussdb`（`GS_USERNAME`）/ 密码：`GS_PASSWORD`
- 仓颉镜像已内置连接驱动，无需额外语言依赖。

> openGauss 兼容 PostgreSQL 协议，仓颉后端通过 `RG_DB_HOST` / `RG_DB_PORT` / `RG_DB_NAME` / `RG_DB_USER` / `RG_DB_PASSWORD` 连接，无需官方方言包。

---

## 2. 切到 openGauss（Docker Compose 一键部署，推荐）

仓库 `docker/docker-compose.cangjie.yml` 内置 **3 容器单库结构**：`rg_cj_opengauss`（唯一 DB）/ `rg_cj_app`（仓颉后端 + Vue 前端）/ `rg_cj_autoheal`（unhealthy 自动重启）：

```bash
cd returnguard
cp docker/.env.example docker/.env       # 填 GS_PASSWORD / AUTH_SECRET
bash docker/build-cangjie-docker.sh      # 构建仓颉后端镜像
docker compose -f docker/docker-compose.cangjie.yml up -d --build
# 应用映射 127.0.0.1:58080:8000，DB 映射 127.0.0.1:15433:5432（仅绑宿主机回环）
```

compose 中已设：

```yaml
environment:
  RG_DB_HOST: db
  RG_DB_PORT: 5432
  RG_DB_NAME: returnguard_cj
  RG_DB_USER: gaussdb
  RG_DB_PASSWORD: ${GS_PASSWORD}
  RG_DB_POOL: ${RG_DB_POOL:-0}    # 禁用仓颉连接池（并发 dead lock），每次新建连接
  AUTH_SECRET: ${AUTH_SECRET:?必须在 docker/.env 显式设置}
```

> 关键：**单库 `returnguard_cj`，按 `tenant_id` 做租户隔离**，不再有 demo/real 双库，也不落容器 SQLite。数据库卷 `cjogdata` 持久化，容器重建数据不丢；`/health` 为含 DB 的深探针（DB 故障返回 503），由 `rg_cj_autoheal` 兜底重启。

### 2.1 本地仓颉后端直跑（非容器，可选）

```bash
cd returnguard
bash backend/build.sh                     # 生成 build/rg-server.exe
RG_WEB_DIR=$PWD/demo/webapp \
RG_DB_HOST=127.0.0.1 RG_DB_PORT=15433 RG_DB_NAME=returnguard_cj \
RG_DB_USER=gaussdb RG_DB_PASSWORD='<GS_PASSWORD>' \
AUTH_SECRET='<≥32字节密钥>' \
./build/rg-server.exe                     # 默认 http://127.0.0.1:8001
```

> 写接口须登录会话（`Authorization: Bearer` / `X-Token`），内置演示账号 `demo` / `demo123`；管理端点须 `AUTH_SECRET` 或登录令牌。
> 端口由 `RG_HTTP_HOST` / `RG_HTTP_PORT` 调整（本机直跑默认 `8001`，容器内 `8000`）；非提权进程绑低端口在 Windows 上会报 `winerror 10013`。

> 表结构由仓颉持久层初始化时建好（`backend/rg-data/src/db/db.cj`，含 `CREATE TABLE`），无需手动建表。
> 更完整的部署 / 环境变量 / 故障排查说明见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) 与 [`backend/README.md`](backend/README.md)。

---

## 3. 真实数据导入（CSV / XLSX）

仓颉后端通过 `POST /api/cases/import` 批量导入真实退货数据，落到单库 `returnguard_cj` 并按 `tenant_id` 隔离：

```bash
curl --noproxy '*' -X POST http://127.0.0.1:58080/api/cases/import \
  -H "Authorization: Bearer <你的令牌>" -H "Content-Type: application/json" \
  -d '{"csv":"sku,category,supplier,platform,amount,date,similarity,outcome\nSKU-001,3C数码,S1,Amazon,299,2026-01-15,0.91,赢"}'
```

> `POST /api/cases/import` 的 JSON 体用 `csv` 传 CSV 文本；XLSX 用 `content` 传 base64 并设 `source=xlsx`（读首个 sheet）。写接口须登录会话。
> 演示数据集共 1206 条案件 · 9 平台，原始文件已移出仓库存于项目外归档目录；可按下列列映射整理后导入验证。

### 导入特性

- **幂等**：按自然键 `(sku, 日期, 相似度)` 跳过已存在的行，重复导入同一份文件**不会重复堆积**。
- **案件号补齐**：导入行自动生成 `RG-XXXXXXXX` 案件号，与 `/api/cases` 手动录入一致。
- **租户隔离**：导入数据落 `returnguard_cj` 并归属当前租户，不污染其它租户数据；无 demo/real 双库。

### CSV 列映射（大小写 / 下划线 / 中文不敏感）

| CSV 列名 | 含义 | 备注 |
|---|---|---|
| sku / 产品 | SKU 编号 | **必填**，缺失行跳过 |
| 品类 / category | 品类 | 3C数码/饰品配件/小家电/服饰鞋包 |
| 供应商 / supplier | 供应商编号 | S1~S8 |
| 平台 / platform | 平台 | Amazon/AliExpress/Temu/SHEIN/eBay/Shopee/Lazada/Walmart/TikTok Shop |
| 地区 / region | 销售地区 | US/UK/DE/FR/ES/RU/BR |
| 金额 / 退款 / amount | 退款金额(¥) | 数值 |
| 日期 / date | 案件日期 | YYYY-MM-DD，驱动时间序列 |
| 相似度 / similarity | 与本店主图相似度 | 0~1，驱动同款判定 |
| 结果 / outcome | 维权结果 | 赢/部分退款/输 |
| 缺陷 / 瑕疵 / defect_tags | 瑕疵标签 | 支持 `;` `,` `、` 多值 |

---

## 4. 验证部署

```bash
# 健康深探针（含 DB，故障返回 503；如需公网访问，自行前置反向代理 / CDN）
curl --noproxy '*' http://127.0.0.1:58080/health
curl --noproxy '*' http://127.0.0.1:58080/api/config        # 应返回 "version": "3.1.0"
curl --noproxy '*' http://127.0.0.1:58080/api/ai/providers  # 14 平台能力矩阵（公开、无密钥）

# 登录后查询案件与洞察（单库 returnguard_cj，按 tenant_id 隔离）
curl --noproxy '*' -H "Authorization: Bearer <你的令牌>" \
  "http://127.0.0.1:58080/api/insights?mode=mock"
curl --noproxy '*' -H "Authorization: Bearer <你的令牌>" \
  "http://127.0.0.1:58080/api/cases"
```

重启服务再次确认：导入的案件数**不翻倍**（幂等生效）。

---

## 5. 平台连接器（进阶，可选）

平台连接器位已预留（见根 `README.md`「主要能力」），待 Amazon SP-API / AliExpress 凭证就绪后可接入，不改变 CSV / XLSX 导入主链路。

---

## 6. 注意事项

- **租户隔离**：单库 `returnguard_cj` 内按 `tenant_id` 严格隔离（一个用户 = 一个租户）；不再有 `?source=demo|real` 切换，也无 demo/real 双库。
- **字段长度**：`sku` / `category` / `supplier` / `listing_text` 等字段按表结构长度约束，超长值需在写入前截断或校验（参见 `backend/README.md`）。
- **统一容器编排**：部署请统一用 `docker/docker-compose.cangjie.yml`（3 容器单库）。仓颉连接池并发有 dead lock，compose 默认 `RG_DB_POOL=0`（每次新建连接，连接串 5s 超时兜底），勿擅自开启。
- **卷与自愈**：`cjogdata` 持久化数据库，`cjappdata` 持久化 AI 配置（含 API Key）；`/health` 深探针含 DB `SELECT 1`，DB 故障返回 503，`rg_cj_autoheal` 发现 unhealthy 即重启 app。
- **上传图（客户 PII）**：默认内联 base64 送模型，退货图不出境；远端对象存储接口预留但默认关闭。
- **版本号读取**：`/api/config.version` 返回 `3.1.0`（与仓库根 `VERSION` 一致）；若误显示 `unknown`，检查 `RG_VERSION` 与镜像构建（见 `backend/README.md`）。
