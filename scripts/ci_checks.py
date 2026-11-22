#!/usr/bin/env python3
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 静态门禁（纯标准库，本地与 CI 共用）。

覆盖：版本一致性、路由↔OpenAPI 契约、compose↔启动器常量自洽、
禁用词/退役地址扫描、仓颉 catch 类型检查、文档死链、前端产物完整性。

用法：
    python scripts/ci_checks.py           # 全部门禁
    python scripts/ci_checks.py --list    # 只列出检查项
退出码：0 = 全通过；1 = 至少一项失败。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

CheckFn = Callable[[], tuple[bool, str]]
CHECKS: list[tuple[str, CheckFn]] = []


def register(name: str):
    def deco(fn: CheckFn) -> CheckFn:
        CHECKS.append((name, fn))
        return fn
    return deco


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 版本一致性
@register("版本一致性：VERSION / package.json / Cargo / openapi / CHANGELOG")
def check_version() -> tuple[bool, str]:
    version = read("VERSION").strip()
    errors: list[str] = []

    pkg = json.loads(read("package.json"))
    if pkg.get("version") != version:
        errors.append(f"package.json={pkg.get('version')}")

    cargo = read("launcher/Cargo.toml")
    m = re.search(r'^version\s*=\s*"([^"]+)"\s*$', cargo, re.M)
    if not m or m.group(1) != version:
        errors.append(f"launcher/Cargo.toml={m.group(1) if m else '<missing>'}")

    openapi = read("docs/openapi.yaml")
    m = re.search(r"^  version:\s*([^\s#]+)", openapi, re.M)
    if not m or m.group(1) != version:
        errors.append(f"openapi.yaml={m.group(1) if m else '<missing>'}")

    changelog = read("CHANGELOG.md")
    first = next((ln for ln in changelog.splitlines() if ln.startswith("## [")), "")
    if version not in first:
        errors.append(f"CHANGELOG 首条={first or '<missing>'}")

    if errors:
        return False, "；".join(errors)
    return True, f"{version} 五处一致"


# ---------------------------------------------------------- 路由 ↔ OpenAPI
ROUTE_RE = re.compile(r'router\.(get|post|put|delete|patch)\(\s*"([^"]+)"', re.I)
PARAM_RE = re.compile(r":([A-Za-z_]\w*)")


def norm_path(path: str) -> str:
    """仓颉路由用 :caseId，OpenAPI 用 {caseId}，统一为花括号形式。"""
    return PARAM_RE.sub(r"{\1}", path)


@register("契约一致性：routes.cj 全部路由已入档 openapi.yaml")
def check_routes_contract() -> tuple[bool, str]:
    routes_txt = read("backend/rg-api/src/routes/routes.cj")
    routes = {(m.group(1).upper(), norm_path(m.group(2))) for m in ROUTE_RE.finditer(routes_txt)}

    openapi_txt = read("docs/openapi.yaml")
    documented: set[tuple[str, str]] = set()
    in_paths = False
    current = ""
    for line in openapi_txt.splitlines():
        if line.strip() == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            current = line.strip()[:-1]
            continue
        m = re.match(r"^    (get|post|put|delete|patch):\s*$", line, re.I)
        if m and current:
            documented.add((m.group(1).upper(), current))

    if not routes:
        return False, "未能从 routes.cj 解析出任何路由"
    if not documented:
        return False, "未能从 openapi.yaml 解析出任何 operation"

    missing = sorted(routes - documented)
    extra = sorted(documented - routes)
    if missing or extra:
        parts = []
        if missing:
            parts.append("未入档: " + ", ".join(f"{m} {p}" for m, p in missing))
        if extra:
            parts.append("文档多余: " + ", ".join(f"{m} {p}" for m, p in extra))
        return False, "；".join(parts)
    return True, f"{len(routes)} 条路由与 {len(documented)} 个 operation 一一对应"


# ------------------------------------------------- compose ↔ 启动器常量自洽
@register("配置自洽：compose 容器名/端口 ↔ rg-core 常量")
def check_compose_alignment() -> tuple[bool, str]:
    compose = read("docker/docker-compose.cangjie.yml")
    config = read("launcher/crates/rg-core/src/config.rs")

    compose_names = set(re.findall(r"^\s*container_name:\s*(\S+)\s*$", compose, re.M))
    m = re.search(r"CONTAINERS:\s*\[&str;\s*\d+\]\s*=\s*\[(.*?)\];", config, re.S)
    core_names = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

    if not compose_names or not core_names:
        return False, f"解析失败：compose={sorted(compose_names)} core={sorted(core_names)}"
    if compose_names != core_names:
        return False, (
            f"容器名不一致：compose={sorted(compose_names)} / rg-core={sorted(core_names)}"
        )

    errors: list[str] = []
    for key, default in (("CJ_APP_PORT", "58080"), ("CJ_DB_PORT", "15433")):
        cm = re.search(rf"\$\{{{key}:-(\d+)\}}", compose)
        rm = re.search(rf'parse_port\(env\.get\("{key}"\),\s*(\d+)', config)
        if not cm or not rm or cm.group(1) != rm.group(1) or cm.group(1) != default:
            errors.append(
                f"{key}: compose={cm.group(1) if cm else '?'} "
                f"core={rm.group(1) if rm else '?'} expected={default}"
            )
    if errors:
        return False, "；".join(errors)
    return True, f"{len(compose_names)} 容器 + 两个默认端口一致"


# ------------------------------------------------------------ 禁用词/退役地址
FORBIDDEN = [
    "黑客松", "复赛", "决赛", "参赛", "赛道", "评委", "答辩", "赛事",
    "hackathon", "组委会",
    "a703201sworld", "cloudflared", "rg-tunnel", "trycloudflare",
]
SCAN_DIRS = ["README.md", "CHANGELOG.md", "docs", "backend", "web/src", "launcher", "docker", "scripts", ".github", ".gitea", ".gitcode"]
SCAN_SUFFIX = {".md", ".cj", ".ts", ".vue", ".yml", ".yaml", ".toml", ".json", ".py", ".sh", ".ps1"}
# 历史审查/变更记录中允许出现「赛事」字样吗？项目约定：不允许，连说明移除也不可写。
# 故此处不做白名单；如确需提及，用「历史项目语境」中性表述。


@register("内容红线：无赛事语境与退役公网地址")
def check_forbidden_terms() -> tuple[bool, str]:
    hits: list[str] = []
    for rel in SCAN_DIRS:
        p = ROOT / rel
        targets = [p] if p.is_file() else (p.rglob("*") if p.is_dir() else [])
        for f in targets:
            if not f.is_file() or f.suffix not in SCAN_SUFFIX:
                continue
            # 门禁脚本自身必须包含词表，跳过自身扫描
            if f.name == "ci_checks.py":
                continue
            if "target" in f.parts or "node_modules" in f.parts:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for term in FORBIDDEN:
                if term.lower() in text.lower():
                    hits.append(f"{f.relative_to(ROOT)}: {term}")
    if hits:
        return False, "命中 " + "; ".join(hits[:12])
    return True, f"扫描 {len(SCAN_DIRS)} 个路径，无命中"


# ------------------------------------------------------- 仓颉 catch 类型标注
@register("仓颉静态检查：catch 必须带类型标注")
def check_cangjie_catch() -> tuple[bool, str]:
    bad: list[str] = []
    pattern = re.compile(r"\bcatch\s*\(\s*([A-Za-z_]\w*)\s*\)")
    for f in (ROOT / "backend").rglob("*.cj"):
        if "build" in f.parts:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{i}")
    if bad:
        return False, "无类型 catch: " + ", ".join(bad[:12])
    return True, "全部 catch 带类型标注"


# ------------------------------------------------------------------ 文档死链
@register("文档完整性：本地链接无死链")
def check_doc_links() -> tuple[bool, str]:
    docs = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md")),
            ROOT / "backend/README.md", ROOT / "launcher/README.md"]
    dead: list[str] = []
    link_re = re.compile(r"\]\((?!https?://|#)([^)]+)\)")
    for d in docs:
        if not d.is_file():
            continue
        for m in link_re.finditer(d.read_text(encoding="utf-8", errors="ignore")):
            target = m.group(1).split("#")[0].strip()
            if target and not (d.parent / target).resolve().exists():
                dead.append(f"{d.relative_to(ROOT)} -> {target}")
    if dead:
        return False, "; ".join(dead[:12])
    return True, f"{len(docs)} 份文档链接有效"


# ------------------------------------------------------------ 前端产物完整性
@register("前端产物：demo/webapp 存在且入口引用有效")
def check_webapp_artifact() -> tuple[bool, str]:
    index = ROOT / "demo/webapp/index.html"
    if not index.is_file():
        return False, "缺少 demo/webapp/index.html"
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    # Vite build base='/new/'：入口形如 /new/assets/index-xxx.js，
    # 对应磁盘 demo/webapp/assets/index-xxx.js。
    assets: list[str] = []
    for r in refs:
        if r.startswith("data:") or "nonce" in r.lower():
            continue
        local = r[len("/new/"):] if r.startswith("/new/") else r.lstrip("/")
        if local.startswith(("http", "api/")):
            continue
        assets.append(local)
    assets = [a for a in assets if a]
    missing = [a for a in assets if not (ROOT / "demo/webapp" / a).is_file()]
    if not assets:
        return False, "index.html 未引用任何本地资产"
    if missing:
        return False, "缺失资产: " + ", ".join(missing)
    return True, f"{len(assets)} 个本地资产引用有效（含 /new/ 前缀映射）"


def main() -> int:
    if "--list" in sys.argv:
        for name, _ in CHECKS:
            print("-", name)
        return 0

    failed = 0
    print("== ReturnGuard 静态门禁 ==")
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # 门禁脚本自身异常也要阻断
            ok, detail = False, f"执行异常: {exc}"
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}\n       {detail}")
        if not ok:
            failed += 1

    print(f"\n结果：{len(CHECKS) - failed}/{len(CHECKS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
