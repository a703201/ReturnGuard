#!/usr/bin/env bash
# ReturnGuard 一键部署（在 openEuler 主机的 demo/ 目录下执行）
# 前置：已安装 docker + docker compose plugin
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env，请按需修改 GS_PASSWORD 等配置（vi .env）"
fi

echo ">>> 构建并启动 ReturnGuard（openGauss + 应用）..."
docker compose up -d --build

echo ">>> 等待服务就绪 ..."
sleep 5
docker compose ps

echo ">>> 健康检查："
if curl -fsS http://localhost:8000/api/cases >/dev/null 2>&1; then
  echo "应用 API 正常 ✅"
else
  echo "应用 API 异常 ❌，请查看：docker compose logs app"
fi
