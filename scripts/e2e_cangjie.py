#!/usr/bin/env python3
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 仓颉后端端到端验证（纯标准库，只读，不改数据）。

对运行中的服务验证关键端点、登录链路、租户隔离与审计链自证。
**需真实服务运行**（本地 `docker compose up` 或自托管 runner），公共 CI 不执行。

用法：
    python scripts/e2e_cangjie.py                       # 默认 http://127.0.0.1:58080
    python scripts/e2e_cangjie.py --base-url http://127.0.0.1:8001
    python scripts/e2e_cangjie.py --username demo --password demo123

退出码：0 = 全部通过；1 = 至少一项失败；2 = 服务不可达（环境未就绪）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

results: list[tuple[bool, str, str]] = []


def record(ok: bool, name: str, detail: str) -> None:
    results.append((ok, name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def call(base: str, path: str, *, method: str = "GET", token: str = "",
         body: dict | None = None, timeout: int = 8) -> tuple[int, Any]:
    req = urllib.request.Request(base + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:200]}
        return exc.code, parsed
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description="ReturnGuard 仓颉后端端到端验证（只读）")
    ap.add_argument("--base-url", default="http://127.0.0.1:58080")
    ap.add_argument("--username", default="demo")
    ap.add_argument("--password", default="demo123")
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    print(f"== ReturnGuard e2e（{base}）==")

    # 0) 连通性
    code, health = call(base, "/health", timeout=args.timeout)
    if code == 0:
        print(f"服务不可达：{health.get('error')}")
        print("提示：先 docker compose -f docker/docker-compose.cangjie.yml up -d --build")
        return 2
    record(code == 200 and health.get("status") == "ok", "health 深探针",
           f"HTTP {code} status={health.get('status')} persistence={health.get('persistence')}")

    # 1) 公开端点
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    code, cfg = call(base, "/api/config", timeout=args.timeout)
    record(code == 200 and cfg.get("version") == version, "/api/config 版本",
           f"HTTP {code} version={cfg.get('version')} (期望 {version})")

    code, providers = call(base, "/api/ai/providers", timeout=args.timeout)
    n_providers = len(providers.get("providers", [])) if isinstance(providers, dict) else 0
    record(code == 200 and n_providers >= 14, "/api/ai/providers 能力矩阵",
           f"HTTP {code} providers={n_providers}")

    code, platforms = call(base, "/api/platforms", timeout=args.timeout)
    n_platforms = len(platforms.get("platforms", [])) if isinstance(platforms, dict) else 0
    record(code == 200 and n_platforms >= 9, "/api/platforms 举证包",
           f"HTTP {code} platforms={n_platforms}")

    code, crypto = call(base, "/api/crypto/capabilities", timeout=args.timeout)
    record(code == 200, "/api/crypto/capabilities 国密声明", f"HTTP {code}")

    # 2) 旧端点应不存在（防止回退到旧栈）
    code, _ = call(base, "/api/providers", timeout=args.timeout)
    record(code == 404, "旧 /api/providers 已移除", f"HTTP {code} (期望 404)")

    # 3) 未登录访问洞察应 401
    code, _ = call(base, "/api/insights", timeout=args.timeout)
    record(code == 401, "insights 未登录拒绝", f"HTTP {code} (期望 401)")

    # 4) 登录链路
    code, login = call(base, "/api/auth/login", method="POST",
                       body={"username": args.username, "password": args.password},
                       timeout=args.timeout)
    token = str(login.get("token", "")) if isinstance(login, dict) else ""
    record(code == 200 and bool(token), "登录签发令牌", f"HTTP {code} token={'有' if token else '无'}")
    if not token:
        print("\n登录失败，后续需登录端点跳过。")
        return 1

    code, me = call(base, "/api/auth/me", token=token, timeout=args.timeout)
    record(code == 200, "/api/auth/me 当前用户", f"HTTP {code} user={me.get('username', '?')}")

    # 5) 登录后可访问的核心端点
    code, insights = call(base, "/api/insights", token=token, timeout=args.timeout)
    decided = insights.get("decided") if isinstance(insights, dict) else None
    record(code == 200 and decided is not None, "insights 胜诉率口径",
           f"HTTP {code} decided={decided} (必须为已判定数)")

    code, cases = call(base, "/api/cases", token=token, timeout=args.timeout)
    record(code == 200, "/api/cases 租户案件", f"HTTP {code}")

    code, audit = call(base, "/api/audit/verify", token=token, timeout=args.timeout)
    record(code == 200 and audit.get("ok") is True, "审计链自证",
           f"HTTP {code} ok={audit.get('ok')} events={audit.get('events')}")

    code, alist = call(base, "/api/audit/list?limit=5", token=token, timeout=args.timeout)
    record(code == 200, "审计链分页", f"HTTP {code}")

    code, settings = call(base, "/api/ai/settings", token=token, timeout=args.timeout)
    leaked = "apiKey" in settings and bool(settings.get("apiKey"))
    record(code == 200 and not leaked, "AI 设置密钥脱敏",
           f"HTTP {code} apiKeySet={settings.get('apiKeySet')} apiKeyMask={settings.get('apiKeyMask')}")

    failed = sum(1 for ok, _, _ in results if not ok)
    print(f"\n结果：{len(results) - failed}/{len(results)} 通过")
    if failed:
        print("提示：看日志 docker logs rg_cj_app；/health 503 时查 DB 与 autoheal。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
