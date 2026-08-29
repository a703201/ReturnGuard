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
#   builder  仅负责把 requirements.txt 解析为离线 wheel 缓存（无需联网/索引）；
#   runtime  只装运行期依赖，不含编译器/头文件，镜像更小、攻击面更小。
# psycopg2-binary 自带 libpq，故运行期无需 gcc / libpq-dev。
# ============================================================
# ---------- 阶段 1：依赖解析（离线 wheel 缓存）----------
FROM python:3.11-slim AS builder
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY demo/requirements.txt .
RUN pip wheel --no-cache-dir -r requirements.txt -w /wheels

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

# 业务源码（demo/ 完整目录 → /app）
COPY demo/ .

# 版本文件（仓库根 VERSION → /app/VERSION，main.py 启动时读取）
COPY VERSION .

# 启动脚本（位于 docker/，与 compose 同目录），置于 /app 并赋可执行权限
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN mkdir -p uploads \
    && chmod +x /app/entrypoint.sh \
    && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app

# ---- 非 root 运行（大厂容器加固基线）----
USER appuser

EXPOSE 8000

# 启动前会等待 openGauss 就绪并初始化数据（见 entrypoint.sh）
ENTRYPOINT ["./entrypoint.sh"]
