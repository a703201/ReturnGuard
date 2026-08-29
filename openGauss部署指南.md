# ReturnGuard · openGauss 部署与真实数据自动导入指南

> 适用：复赛部署期使用国产数据库 openGauss 承载**全部业务数据**——demo / real / auth 三库均落在 openGauss（`db:5432/returnguard`），用户库不再落容器 SQLite、跨重启不丢。
> 开发期仍可零依赖用 SQLite，部署期仅改环境变量，**业务代码零改动**（双轨隔离已在 `db.py` 预埋）。

---

## 1. 前置条件

- Docker 中已启动 openGauss（用户环境已就绪）。示例连接信息：
  - 主机：`localhost`（或容器映射端口 `5432`）
  - 库：`postgres` / 自建 `returnguard`
  - 用户：`gaussdb` / 密码：`<你的密码>`
- 部署依赖已装：`pip install -r requirements.txt`（含 `psycopg2-binary` 连接驱动）

> openGauss 兼容 PostgreSQL 协议，ReturnGuard 用 `postgresql+psycopg2://` 方言即可连接，无需官方方言包。

---

## 2. 切到 openGauss（Docker Compose 一键部署，推荐）

仓库 `docker/docker-compose.yml` 已内置 openGauss 服务（`rg_opengauss`）与应用服务（`rg_app`），**三库全部指向 openGauss**：

```bash
cd returnguard/docker
docker compose up -d --build
# 应用映射 127.0.0.1:65432:8000，由 Cloudflare Tunnel 反代到公网
```

compose 中已设：

```yaml
environment:
  DATABASE_URL:        postgresql+psycopg2://gaussdb:${GS_PASSWORD:-Gauss-2026}@db:5432/returnguard
  AUTH_DATABASE_URL:   postgresql+psycopg2://gaussdb:${GS_PASSWORD:-Gauss-2026}@db:5432/returnguard
  REAL_DATABASE_URL:   postgresql+psycopg2://gaussdb:${GS_PASSWORD:-Gauss-2026}@db:5432/returnguard
```

> 关键：demo / real / auth **三库均指向同一 openGauss `returnguard` 库**（按 `source` 物理隔离），用户库不再落容器 SQLite，跨容器重启不丢账号与令牌。

### 2.1 手动环境变量方式（非容器，可选）

```bash
# 三库全部指向 openGauss
export DATABASE_URL="postgresql+psycopg2://gaussdb:你的密码@localhost:5432/returnguard"
export AUTH_DATABASE_URL="postgresql+psycopg2://gaussdb:你的密码@localhost:5432/returnguard"
export REAL_DATABASE_URL="postgresql+psycopg2://gaussdb:你的密码@localhost:5432/returnguard"

# 可选：写接口鉴权（生产必开）
export ANALYZE_API_KEY="一个强随机串"
# 可选：上传图清理阈值（小时）
export UPLOAD_MAX_AGE_HOURS=24
```

启动后 `db.py` 的 `get_engine` 会自动建表（`Base.metadata.create_all`）+ 列迁移（`_migrate_case_columns`），无需手动建表。

> 兼容性补丁：openGauss 的 `SELECT version()` 返回 `(openGauss 5.0.0 ...)`，SQLAlchemy PG 方言会误判；`db.py` 已内置 `_patch_opengauss_dialect`，仅在连接 openGauss/PostgreSQL 时挂接，提取主版本号，导入期无副作用。

---

## 3. 真实数据自动导入（开机即回流）

部署期设置 `RG_AUTO_IMPORT_CSV` 指向一份真实退货 CSV，服务启动即批量导入 **real 源**（即 openGauss）：

```bash
export RG_AUTO_IMPORT_CSV="/path/to/returnguard/demo/seed_real.csv"
uvicorn main:app --host 0.0.0.0 --port 8000
```

仓库已附 `demo/seed_real.csv`（20 条样例，覆盖 US/UK/DE/FR/ES/RU/BR 与 5–9 月，便于验证时间序列+预测与地区维度）。

### 自动导入特性

- **幂等**：`dedupe=True` 按自然键 `(sku, 日期, 相似度)` 跳过 real 源中已存在的行，容器重启重复挂载同一份 CSV **不会重复堆积**。
- **案件号补齐**：导入行自动生成 `RG-XXXXXXXX` 案件号（原链路缺 case_id → NULL，导致无法按 ID 删除/去重；现已与 `/api/cases` 手动录入一致）。
- **失败不阻断启动**：导入异常仅记日志，服务照常启动。
- **仅落 real 源**：CSV 导入强制落到 real（真实业务库），绝不污染 demo 种子库。

### CSV 列映射（`importer._COL_MAP`，大小写/下划线/中文不敏感）

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
# 健康检查（容器映射 127.0.0.1:65432 → 容器 8000；公网经 Cloudflare Tunnel）
curl http://127.0.0.1:65432/health
curl http://127.0.0.1:65432/api/config        # 应返回 "version": "1.1.2"

# 看板应基于 real 源、含自动导入的数据
curl "http://127.0.0.1:65432/api/insights?source=real&mode=mock" | python -m json.tool | head -20

# 确认 demo 源已重播 1206 条
curl "http://127.0.0.1:65432/api/cases?source=demo&slim=1" | python -c "import sys,json;print('demo 源案件数:',len(json.load(sys.stdin)))"
```

重启服务再次确认：real 源案件数**不翻倍**（幂等生效）。

---

## 5. 平台连接器（进阶，可选）

待 Amazon SP-API / AliExpress 凭证就绪，`importer.import_from_connector(connector)` 可直接把平台退货数据落库，接口已预留，不改变 CSV 导入主链路。

---

## 6. 注意事项

- **三库物理隔离在 openGauss 内**：demo 永远来自种子，real 来自录入/导入，auth 存账号/令牌；三者按 `source`/`tenant_id` 隔离，切换零代码（`?source=demo|real` 或前端顶栏）。
- **`sku_name` 长度**：模型定义为 `VARCHAR(256)`；cases.json 中有商品名长达 145 字符，openGauss 严格长度校验会在 `VARCHAR(128)` 下批量插入报 `DataError`，已扩列规避。
- **Docker 本地 SQLite 绑挂载坑**：若用 `docker-compose.local.yml`（SQLite + 绑挂载）在 Windows 上启动会遇 `PRAGMA journal_mode=WAL` 的 `disk I/O error`，可设 `SQLITE_NO_WAL=1` 改用 DELETE 日志模式；**生产部署请用本指南的 openGauss compose**，无此问题。
- 多 worker 部署（gunicorn -w N）下：聚合代际计数与限流/登录锁已外置为独立 SQLite（`rg_kv` / `shared_state.py`，SEC-12），状态跨 worker 一致；其余运行指标仍为进程内，openGauss 生产多实例建议上层加 Redis 共享（后续优化项，非阻断）。
- 上传图（客户 PII）已改为 HMAC 签名短链 `/api/file/{sig}`（SEC-8），不再经 `/uploads` 公开挂载；对外部署无需再处理静态可读问题。
- **版本号读取**：容器镜像已确保 `main.py` 能读到 `/app/VERSION`（Dockerfile `COPY demo/ ./demo/` + entrypoint `cd demo`），`/api/config.version` 返回 `1.1.2`；若误显示 `unknown`，检查镜像构建是否把 `demo/` 拍平到了 `/app`。
