# ============================================================
# ReturnGuard · 应用镜像
# ------------------------------------------------------------
# 基础镜像用 Debian slim（体积小、pip 生态全，构建稳定）；
# 注意：「Linux 用 openEuler」指的是【部署宿主机】操作系统（见《ReturnGuard_部署方案.md》），
# 应用镜像运行在 openEuler 主机的 Docker 之上，二者解耦、互不影响。
# 若需 100% 信创基底，可把 FROM 换成 openeuler/openeuler:24.03-lts-sp4，
# 并改用 dnf 安装 python3 与 pip（详见部署方案文档「进阶 · 全 openEuler 基底」）。
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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY . .

RUN mkdir -p uploads && chmod +x entrypoint.sh

EXPOSE 8000

# 启动前会等待 openGauss 就绪并初始化数据（见 entrypoint.sh）
ENTRYPOINT ["./entrypoint.sh"]
