#!/usr/bin/env bash
# ReturnGuard 容器启动脚本
# 职责：① 等待 openGauss 端口就绪（容器首次启动需初始化，约 30~60s）
#       ② 建表 + 首次从 cases.json 灌入种子（库为空时）
#       ③ 启动 uvicorn
set -euo pipefail

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "[entrypoint] 等待数据库 ${DB_HOST}:${DB_PORT} ..."
for i in $(seq 1 60); do
  if python - <<'PY'
import socket, os, sys
host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "5432"))
s = socket.socket()
s.settimeout(2)
try:
    s.connect((host, port))
    print("[entrypoint] 数据库端口已开放")
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  then
    break
  fi
  echo "[entrypoint] 第 ${i} 次探测，2s 后重试 ..."
  sleep 2
done

# 业务源码在 /app/demo/，与本地仓库结构一致
cd demo

# 建表 + 首次种子导入（幂等：库已有数据则跳过）
python -c "from db import init_db; init_db()"

echo "[entrypoint] 启动 uvicorn ..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
