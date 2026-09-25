# ============================================================
# ReturnGuard · 应用镜像（多阶段构建）
# ------------------------------------------------------------
# 部署配置与源码解耦：本文件位于仓库 docker/ 目录，
# build context 为仓库根（docker-compose.yml 中 build.context: ..），
# 业务源码在 demo/，由下方 COPY demo/ 引入，二者互不混杂。
# 基础镜像用 Debian slim（体积小、pip 生态全，构建稳定）；
# 若需 100% 信创基底，可把 FROM 换成 openeuler/openeuler:24.03-lts-sp4，
# 并改用 dnf 安装 python3 与 pip（详见《ReturnGuard_部署方案.md》）。
#
# 多阶段（B-部署）：
#   builder  仅负责把 requirements.txt 解析为离线 wheel 缓存（运行时不再联网装包）；
#   runtime  只装运行期依赖，不含编译器/头文件，镜像更小、攻击面更小。
# psycopg2-binary 自带 libpq，故运行期无需 gcc / libpq-dev。
#
# pip 源可配置（PIP_INDEX_URL）：国内网络直连 files.pythonhosted.org 常出现
# read timeout / 下载中断（实测最终报 wheel 哈希不匹配，本质是下载损坏）。
# 默认仍用官方源，保持不变；需要提速时在 docker/.env 设
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# 或构建时显式传 --build-arg PIP_INDEX_URL=<镜像地址>。
# ============================================================
# ---------- 阶段 1：依赖解析（离线 wheel 缓存）----------
FROM python:3.11-slim AS builder
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /build
COPY demo/requirements.txt .
# 离线 wheel 缓存（可选，强烈建议在网络受限/不稳定环境使用）：
# 若仓库 docker/wheels/ 下存在 *.whl，则**完全离线**解析依赖、不访问任何索引——
# 既避免「容器内下载慢/中断导致构建失败」，也让构建可复现（同批 wheel 同批次产出）。
# 该目录默认不进 git（只保留 .gitkeep），生成命令见 docs/DEPLOYMENT.md「离线构建」。
COPY docker/wheels/ /tmp/offline-wheels/
RUN set -eu; \
    if ls /tmp/offline-wheels/*.whl >/dev/null 2>&1; then \
        echo "[build] 使用离线 wheel 缓存：$(ls -1 /tmp/offline-wheels/*.whl | wc -l) 个 wheel"; \
        pip wheel --no-cache-dir --no-index --find-links=/tmp/offline-wheels \
            -r requirements.txt -w /wheels; \
    else \
        echo "[build] 未提供离线 wheel，改为联网解析（PIP_INDEX_URL=${PIP_INDEX_URL}）"; \
        pip wheel --no-cache-dir -r requirements.txt -w /wheels; \
    fi; \
    rm -rf /tmp/offline-wheels

# ---------- 阶段 2：运行期（精简、无编译工具链）----------
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 仅装运行期必需系统库（psycopg2-binary 自带 libpq，不再需要 gcc / libpq-dev）
COPY --from=builder /wheels /wheels
COPY demo/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# 业务源码（demo/ 完整目录 → /app/demo/，与本地仓库结构一致，
# 避免 main.py 用 __file__ 计算相对路径时断裂）
COPY demo/ ./demo/

# 版本文件（仓库根 VERSION → /app/VERSION，demo/main.py 通过 ../VERSION 读取）
COPY VERSION .

# 启动脚本（位于 docker/，与 compose 同目录），置于 /app 并赋可执行权限
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN mkdir -p uploads demo/state \
    && chmod +x /app/entrypoint.sh \
    && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app

# ---- 非 root 运行（大厂容器加固基线）----
USER appuser

EXPOSE 8000

# 启动前会等待 openGauss 就绪并初始化数据（见 entrypoint.sh）
ENTRYPOINT ["./entrypoint.sh"]
