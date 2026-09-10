#!/usr/bin/env bash
# ReturnGuard · 测试 + 覆盖率门禁（P1-11）
# 运行方式与门禁：
#   bash demo/tests/run_with_coverage.sh
# 依赖：pytest-cov（pip install pytest-cov）。未安装时改用普通 pytest 跑测试，不强制门禁。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if python -c "import pytest_cov" 2>/dev/null; then
  echo "== 运行测试并采集覆盖率（门禁 fail_under=70%）=="
  python -m pytest --cov=demo --cov-report=term-missing --cov-branch -q
else
  echo "== pytest-cov 未安装，退回普通 pytest 跑测试（不强制覆盖率门禁）=="
  echo "   安装：pip install pytest-cov 后重跑本脚本即启用门禁。"
  python -m pytest -q
fi
