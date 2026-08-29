# ReturnGuard 部署方案（容器化 · 在 Docker 中用 openEuler 运行 openGauss）

> 适用：复赛交付 / 公网演示。把本地「SQLite 文件库 + 单进程」升级为
> **「在 Docker 容器内用 openEuler 运行 openGauss」+ 应用容器编排**的标准部署形态。
> 核心理念：**openGauss 官方镜像本身即基于 openEuler 构建**（tag 后缀 `-openEuler22.03`），
> 所以"openEuler 跑 openGauss"由容器镜像天然保证——宿主是 openEuler、Ubuntu 还是
> Windows+WSL2 都可以，**无需把 openEuler 当成专门跑 Docker 的宿主机**。
> 业务代码**零改动**——延续 `db.py` 的双轨设计，仅通过 `DATABASE_URL` 环境变量切换。

---

## 1. 目标与适用场景

| 维度 | 初赛 / 本地开发 | 复赛 / 公网部署（本方案） |
|------|----------------|---------------------------|
| 操作系统（宿主） | 任意（Win/Mac/Linux） | openEuler 24.03 / Ubuntu / Windows+WSL2 皆可（openGauss 容器自带 openEuler 基底） |
| 数据库容器基底 | — | **openEuler**（openGauss 镜像内置；亦可单独 `docker pull openeuler/openeuler:24.03-lts-sp4`） |
| 数据库 | SQLite 文件库 | **openGauss 5.0.0**（华为开源，兼容 PG 协议；使用社区维护更稳的 `enmotech/opengauss:5.0.0`） |
| 运行方式 | `python main.py` | Docker 容器（`docker compose up -d`） |
| 数据持久化 | 随进程/文件 | 持久卷（容器重建不丢） |
| 并发/可用 | 演示级 | 容器编排 + 自动重启 + 健康检查 |
| 信创契合 | — | 国产 OS + 国产 DB，贴合大赛「自主可控」导向 |

**为什么这么选**
- **openGauss** 是华为开源、兼容 PostgreSQL 协议的国产关系型数据库，与现有
  SQLAlchemy（`postgresql+psycopg2` 方言）**协议级兼容**，DB 切换不改一行业务代码。
- **openEuler** 是 openGauss 的「原配」基底（官方镜像本就基于 openEuler 构建），
  二者组合信创叙事最完整，且对 ARM/x86 都支持。
- **容器化**让「开发即生产」：本地 `docker compose` 一键起，复赛服务器同一份配置直接跑。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  部署宿主机（openEuler 24.03 / Ubuntu / Windows+WSL2 均可）      │
│                                                               │
│   ┌──────────────────────┐      ┌────────────────────────┐   │
│   │  rg_app  (容器)       │      │  rg_opengauss (容器)     │   │
│   │  ReturnGuard FastAPI  │─────▶│  openGauss 5.0.0         │   │
│   │  python:3.11-slim     │ 5432 │  数据卷 ogdata 持久化    │   │
│   │  :8000 对外            │      │  (enmotech/openGauss     │   │
│   │                       │      │   5.0.0, openEuler 基底) │   │
│   └──────────┬───────────┘      └────────────────────────┘   │
│              │ 8000                                               │
│          ┌───┴───────┐                                           │
│          │ 公网/域名  │  ← 安全组放通 8000（生产建议反代 + HTTPS）  │
│          └───────────┘                                           │
└─────────────────────────────────────────────────────────────┘

数据流：浏览器 → rg_app(/api/*) → SQLAlchemy → rg_opengauss(returnguard 库)
```

两个容器通过 compose 内部网络互访（`db:5432`），应用对外的只有 8000 端口。

---

## 3. 环境准备（部署宿主）

### 3.1 系统（宿主）
- 本方案**不强制宿主是 openEuler**：openGauss 的 openEuler 基底在容器镜像里已自带，
  宿主用 **openEuler 24.03 LTS SP4 / Ubuntu 22.04 / Windows+WSL2** 均可（x86_64 或 aarch64 均可）。
- 云上：华为云 ECS（同可用区网络更稳）；本地：VirtualBox / VMware 装 openEuler 或任意 Linux；
  Windows 用 Docker Desktop（WSL2 后端）。

### 3.2 安装 Docker（openEuler 专属坑）
openEuler 的 `$releasever` 是 `24.03`，Docker 官方源只认 CentOS 的 `7/8/9`，
直接添加源会 404。修复办法是**把源里的版本号强制改成 7**，再装 Docker CE。

```bash
# 1) 加 Docker 源（用华为云镜像加速）
sudo dnf config-manager --add-repo https://repo.huaweicloud.com/docker-ce/linux/centos/docker-ce.repo

# 2) 关键：把 $releasever 替换为 7，否则路径不存在
sudo sed -i 's/\$releasever/7/g' /etc/yum.repos.d/docker-ce.repo

# 3) 安装（--nogpgcheck 规避跨发行版 GPG 校验失败）
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin --nogpgcheck

# 4) 启动 + 开机自启
sudo systemctl enable --now docker

# 5)（可选）配置国内镜像加速，避免拉镜像超时
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.mirrors.ustc.edu.cn"] }
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker

# 6) 验证
docker --version && docker compose version
```

> 若用 root 操作可省略 `sudo`；生产建议把部署账号加入 `docker` 组。

---

## 4. 容器化交付物（已与源码解耦，落地在 `returnguard/docker/`）

> **部署配置与源码解耦**：编排/镜像等部署文件统一放在仓库 `docker/` 目录，业务源码留在 `demo/`。
> `docker-compose.yml` 的 `build.context` 指向仓库根（`..`），`dockerfile` 指向 `docker/Dockerfile`，
> 由 `Dockerfile` 内的 `COPY demo/ .` 引入源码。这样改业务代码不会动部署配置，反之亦然。

| 文件 | 位置 | 作用 |
|------|------|------|
| `Dockerfile` | `docker/` | 应用镜像：`python:3.11-slim` + 依赖 + 代码，入口 `entrypoint.sh`；`build.context: ..`，`COPY demo/` 引入源码 |
| `docker-compose.yml` | `docker/` | 编排 `db`(openGauss) + `app`(应用)，含健康检查与依赖顺序；`build.context: ..` |
| `docker-compose.pg.yml` | `docker/` | 本地验证兜底：用 PostgreSQL 替代 openGauss，业务代码零改动 |
| `entrypoint.sh` | `docker/` | 启动前等待 DB 端口 → 建表/灌种子 → 起 uvicorn |
| `.dockerignore` | 仓库根 `returnguard/` | 排除 `.git`、文档、本地 `cases.db`/`.env` 等（**不**排除 `docker/`，否则 `COPY docker/entrypoint.sh` 失败） |
| `.env.example` | `docker/` | 环境变量模板（密码、Key、图床前缀），复制为 `.env` 使用 |
| `deploy.sh` | `docker/` | 一键部署脚本：生成 `.env` → `compose up -d --build` → 健康检查 |
| `requirements.txt` | 新增 `SQLAlchemy`、`psycopg2-binary`（连接 openGauss 必需） |
| `db.py` | 已就绪：读 `DATABASE_URL` 环境变量；新增 `pool_pre_ping` 探活 |

> 应用镜像用 Debian slim 而非 openEuler 基底——**宿主已是 openEuler**，容器内 OS
> 与宿主解耦即可。若要求 100% 信创基底，见第 8 节「全 openEuler 基底」。

---

## 5. openGauss 部署要点

镜像 `enmotech/opengauss:5.0.0`（基于 openEuler 构建），关键参数：

| 项 | 值 | 说明 |
|----|----|------|
| 镜像 | `enmotech/opengauss:5.0.0` | Docker Hub 社区维护的稳定 LTS tag，容器内基底为 openEuler |
| 容器内端口 | `5432` | `GS_PORT` 默认 |
| 提权 | `privileged: true` | openGauss 需调内核参数，**必须** |
| 超级用户 | `omm` | 密码由 `GS_PASSWORD` 设定 |
| 业务用户 | `gaussdb`（默认 `GS_USERNAME`） | 应用用它连库 |
| 初始库 | `returnguard`（`GS_DB`） | 容器首次启动自动创建 |
| 密码强度 | ≥8 位，含大小写+数字+特殊符号 | 否则容器拒绝启动 |
| 持久化 | 卷 `ogdata → /var/lib/opengauss` | 容器重建数据不丢 |

**连接串（应用侧，已写入 compose）**
```
postgresql+psycopg2://gaussdb:<GS_PASSWORD>@db:5432/returnguard
```
> 注意：若 `<GS_PASSWORD>` 含 `@`/`#` 等 URL 保留字符，必须做 URL 编码（`@`→`%40`，`#`→`%23`）。
> 默认密码 `Gauss-2026` 已避开这些字符，可直接使用。

openGauss 兼容 PostgreSQL 协议，标准 `psycopg2` 驱动直接可用；
进阶可用官方方言 `opengauss+psycopg2://`（需 `pip install opengauss-sqlalchemy`）。

> ### ⚠️ SQLAlchemy 版本号解析补丁（必须）
> openGauss 的 `SELECT version()` 返回 `(openGauss 5.0.0 build ...) compiled at ...`，
> 而 SQLAlchemy 2.0 的 PG 方言只认 `PostgreSQL XX.X` 格式，会在 `create_engine` 时抛
> `AssertionError: Could not determine version from string '(openGauss 5.0.0 ...'`。
> **已在 `demo/db.py` 顶部对 `PGDialect._get_server_version_info` 打了 monkeypatch**：
> 检测到 `openGauss` 字样时，从字符串中抽出主版本号（如 `5.0.0`）返回，App 即可正常连库。
> 该补丁**无额外依赖、不影响 SQLite 路径**（仅在真正连 openGauss 时命中 `SELECT version()`），
> 因此双轨切换依旧零代码改动。若改用官方方言 `opengauss+psycopg2://` 可去掉此补丁，
> 但 `opengauss-sqlalchemy` 对 SQLAlchemy 2.0 的适配不一定及时，故本方案默认保留补丁。

> ### ⚠️ 镜像版本说明：为什么用 enmotech/opengauss:5.0.0
> - **Docker Hub 上 `opengauss/opengauss` 仓库目前（2026-08）没有 6.0.x 稳定 tag**，
>   仅有 `5.0.0`、`3.1.0` 与 `7.0.0-RCx` 预览版系列。直接写 `opengauss/opengauss:6.0.2` 会报 `not found`。
> - **7.0.0-RC3.B025 预览版镜像存在启动 bug**：容器内启动 `gaussdb` 时报
>   `error while loading shared libraries: libopenblas.so.0: cannot open shared object file`，
>   镜像本身缺少依赖库，健康检查永远无法通过。**因此本地/初赛验证不推荐 RC 版。**
> - **`opengauss/opengauss:5.0.0` 在 Docker Desktop（WSL2 后端）下偶发不稳定**：
>   表现为 cgroup 告警、初始化阶段内存吃紧、健康检查无法通过。该镜像更适合原生 Linux 宿主机。
> - **`enmotech/opengauss:5.0.0` 为国内社区最常用的稳定镜像**，与官方 openGauss 协议/参数完全兼容，
>   同样支持 `GS_PASSWORD`/`GS_USERNAME`/`GS_DB`；在 Docker Desktop/WSL2 环境下启动成功率更高。
>   本方案默认使用它，把 `image:` 改成 `opengauss/opengauss:5.0.0` 或下载的 6.0.5 tar 均可互换。
> - **容器方式（本方案采用）——完全没问题。** `enmotech/opengauss:5.0.0` 是
>   自包含镜像，内部自带 openEuler 用户态。容器与宿主只共享内核、用户态互相隔离，
>   所以宿主是 openEuler 24.03 还是其他 Linux/Windows+WSL2 都能跑（Windows 需 WSL2 后端）。
> - **你问的"在 docker 里用 openEuler 跑 openGauss"——这正是镜像做的事。**
>   openGauss 镜像本就基于 openEuler 构建（tag 可带 `-openEuler22.03` 后缀），
>   openGauss 直接运行在这层 openEuler 之上；**宿主是什么 OS 无所谓**。
>   换言之，无需专门准备一台 openEuler 宿主机去"跑 Docker"，容器内部已经是 openEuler。
> - **Docker Hub 上能拉到 openEuler 吗？能。** 官方仓库 `openeuler/openeuler` 提供多架构镜像，
>   例如：`docker pull openeuler/openeuler:24.03-lts-sp4`（另有 `latest`/`24.03`/`22.03-lts` 等 tag）。
>   本方案默认不依赖它（openGauss 镜像已自带 openEuler 基底）；若你想让**应用镜像也用 openEuler 基底**，
>   见第 8.2 节（把 `Dockerfile` 的 `FROM python:3.11-slim` 换成 `openeuler/openeuler:24.03-lts-sp4`）。
> - **如果复赛/生产要求 6.0.x 稳定版**，请走华为云 OBS tar 包（Docker Hub 无 6.x）：
>   `docker load -i openGauss-Docker-6.0.5-x86_64.tar`，加载后镜像 tag 为 `opengauss:6.0.5`，
>   把 compose 中 `image:` 改成该 tag 即可。
> - 综上：本地/初赛验证用 **容器 + enmotech/opengauss:5.0.0** 最稳；要追新再考虑下载 6.0.5 tar 或等 7.0 GA。

---

## 6. 双轨切换（零代码改动）

`db.py` 已支持环境变量覆盖：
```python
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///.../cases.db")
```
- 本地开发：不设 `DATABASE_URL` → 自动用 SQLite，免部署。
- 复赛部署：compose 注入上面的 openGauss 串 → 自动切库，业务/前端/接口全部不变。

---

## 7. 一键部署步骤

```bash
# 1) 把代码弄到 openEuler 主机（二选一）
##  a. 从 Git 拉（需先 push 到 origin）
git clone <你的仓库> returnguard && cd returnguard/docker
##  b. 或直接 scp 整个 returnguard/ 目录上去后 cd 进 docker/

# 2) 准备环境变量（在 docker/ 目录内，.env.example 在此）
cp .env.example .env
vi .env            # 至少改 GS_PASSWORD 为高强度密码

# 3) 一键起（构建镜像 + 起 openGauss + 起应用）
./deploy.sh
# 或手动：docker compose up -d --build

# 4) 看状态
docker compose ps
docker compose logs -f app     # 观察初始化与启动日志
```

### 验证
```bash
# 案件库接口（应返回 JSON 数组，首次约 1206 条）
curl -s http://localhost:8000/api/cases | head -c 200; echo

# 洞察看板（阶段B 核心）
curl -s "http://localhost:8000/api/insights?mode=mock" | python -m json.tool | head -n 20

# 数据库内确认落库（示例密码 Gauss-2026）
docker exec -it rg_opengauss bash -c \
  "su - omm -c \"gsql -d returnguard -U gaussdb -W'Gauss-2026' -c 'SELECT count(*) FROM cases;'\""
```

### 7.1 Docker Desktop（WSL2 后端）特别说明
- **内存**：openGauss 容器首次初始化需要 ≥4GB 内存。请在 Docker Desktop
  **Settings → Resources → Memory** 中把内存调到 **4GB 或更高**，否则初始化极慢或 OOM 退出。
- **WSL 集成**：确保 Docker Desktop → Settings → Resources → WSL Integration
  中已开启你正在使用的 WSL 发行版（如 Ubuntu/openEuler）。
- **镜像加速**：若拉取 `enmotech/opengauss:5.0.0` 较慢，可在 Docker Engine 配置里加国内镜像站：
  ```json
  { "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.mirrors.ustc.edu.cn"] }
  ```

### 7.2 本地验证兜底：PostgreSQL 版 compose
如果 openGauss 镜像在你的 Windows+WSL2 环境下实在起不来（已确认内存足够、privileged 已开），
可以用同目录下的 `docker-compose.pg.yml` 先跑通应用全链路：

```bash
cd returnguard/docker
docker compose -f docker-compose.pg.yml up -d
```

该文件使用官方 `postgres:15-alpine`，业务代码、接口、前端**完全不变**，仅把 DB 换成 PG。
等换成原生 Linux/openEuler 宿主机或下载 openGauss tar 包后，再切回 `docker-compose.yml` 即可。

---

## 8. 进阶

### 8.1 openGauss 向量能力 → 替代 mock 相似度（选品避坑增强）
当前「图向量相似度」是 mock。openGauss 具备向量检索能力，可把退回图/主图的
embedding 存入向量列，做**真实相似商品检索**（同一 SKU 历史退货聚类、撞图预警）。
落地路径：新增 `vector` 类型列 → embedding 落库 → `ORDER BY embedding <-> :q LIMIT k`。
这能让「退货情报站」的选品避坑从规则升级为数据驱动，强化大赛技术亮点。

### 8.2 全 openEuler 基底（彻底信创）
把 `Dockerfile` 的 `FROM python:3.11-slim` 换成：
```dockerfile
FROM openeuler/openeuler:24.03-lts-sp4
RUN dnf install -y python3 python3-pip gcc && dnf clean all
```
其余不变，即应用镜像也为 openEuler，与宿主机、数据库三者统一。

### 8.3 公网暴露与复赛交付
- 安全组放通 `8000`；生产建议前置 Nginx 反代 + HTTPS（Let's Encrypt）。
- 录屏/演示：服务常驻后台，直接访问 `http://<公网IP>:8000`。
- 交付物清单：本仓库 + 本方案 + 演示视频 + 技术说明 + GitCode 镜像。

---

## 9. 故障排查

| 现象 | 原因 / 解决 |
|------|------------|
| `rg_app` 一直 restart | 看 `docker compose logs app`；多半是 `DATABASE_URL` 错（如密码含 `@` 未 URL 编码）或 DB 未就绪 |
| openGauss 起不来 | 密码不符合强度策略；或忘了 `privileged: true`；或 WSL2 内存不足 |
| `db` 健康检查始终失败 | 首次初始化慢（60s~180s），等 `start_period` 过后重试；确认 `5432` 端口；检查内存是否 ≥4GB |
| 连接报 `database "returnguard" does not exist` | 旧卷残留；`docker compose down -v` 清卷后重起 |
| 中文乱码 | 确认 `TZ: Asia/Shanghai` 与库 `encoding='UTF8'`（默认即是） |
| Windows WSL2 下 openGauss 实在跑不通 | 先用 `docker compose -f docker-compose.pg.yml up -d` 跑 PostgreSQL 兜底验证全链路 |

---

## 10. 提交与回滚

- 改动全部纳入 Git：`git add demo && git commit`。
- 回滚：保留上个镜像 `docker compose down` 后切回旧 `DATABASE_URL`（SQLite）即可本地复现。
- 数据备份：`docker exec rg_opengauss su - omm -c "gs_dump returnguard -U gaussdb -F c -f /tmp/rg.dmp"`。
