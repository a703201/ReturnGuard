# ============================================================
# ReturnGuard · 应用镜像
# ------------------------------------------------------------
# 部署配置与源码解耦：本文件位于仓库 docker/ 目录，
# build context 为仓库根（docker-compose.yml 中 build.context: ..），
# 业务源码在 demo/，由下方 COPY demo/ 引入，二者互不混杂。
# 基础镜像用 Debian slim（体积小、pip 生态全，构建稳定）；
# 若需 100% 信创基底，可把 FROM 换成 openeuler/openeuler:24.03-lts-sp4，
# 并改用 dnf 安装 python3 与 pip（详见《ReturnGuard_部署方案.md》）。
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖：psycopg2 编译/运行需要 libpq 头文件与运行时库
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存，代码改动不触发重装）
COPY demo/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷业务源码（demo/ 完整目录 → /app）
COPY demo/ .

# 拷入版本文件（仓库根目录 VERSION → /app/VERSION，main.py 启动时读取）
COPY VERSION .

# 拷入启动脚本（位于 docker/，与 compose 同目录），置于 /app 并赋可执行权限
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN mkdir -p uploads && chmod +x /app/entrypoint.sh

# ---- 非 root 运行（大厂容器加固基线）----
RUN useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 启动前会等待 openGauss 就绪并初始化数据（见 entrypoint.sh）
ENTRYPOINT ["./entrypoint.sh"]
