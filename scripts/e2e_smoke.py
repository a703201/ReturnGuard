"""ReturnGuard 端到端冒烟：逐项验证「声明的功能」是否真能跑通。

用法：python scripts/e2e_smoke.py [base_url]
默认 base_url = http://127.0.0.1:65432
"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:65432"
IMG_A = "demo/test_a.png"
IMG_B = "demo/test_b.png"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": "ReturnGuard-E2E"})

    # ---- 1. 只读基线 ----
    r = s.get(f"{BASE}/health", timeout=10)
    check("GET /health", r.status_code == 200, r.text[:60])

    r = s.get(f"{BASE}/", timeout=10)
    html = r.text
    check("GET / 页面", r.status_code == 200 and "ReturnGuard" in html)
    csp = r.headers.get("Content-Security-Policy", "")
    check("CSP 头已下发", "default-src" in csp, csp[:70])

    r = s.get(f"{BASE}/api/config", timeout=10)
    cfg = r.json()
    check("GET /api/config", cfg.get("version") not in (None, "unknown"), f"version={cfg.get('version')}")

    r = s.get(f"{BASE}/api/platforms", timeout=10)
    plats = r.json().get("platforms", [])
    check("GET /api/platforms", len(plats) >= 4, f"{len(plats)} 个平台")

    # ---- 2. 匿名读 demo 洞察（看板首屏）----
    t0 = time.time()
    r = s.get(f"{BASE}/api/insights?source=demo", timeout=60)
    ins = r.json()
    check(
        "GET /api/insights (匿名 demo)",
        r.status_code == 200 and ins.get("total_cases", 0) > 0,
        f"案件 {ins.get('total_cases')} / 胜诉率 {ins.get('win_rate')} / {time.time()-t0:.1f}s",
    )
    for field in (
        "category_heatmap",
        "supplier_scorecard",
        "supplier_blacklist",
        "platform_view",
        "region_view",
        "season_view",
        "sku_ranking",
        "time_series",
        "forecast",
        "sourcing_checklist",
        "root_cause",
        "report",
    ):
        v = ins.get(field)
        ok = (len(v) > 0) if isinstance(v, (list, dict)) else bool(v)
        check(f"  洞察字段 {field}", ok, f"{type(v).__name__} len={len(v) if hasattr(v,'__len__') else v}")

    # ---- 3. 下钻过滤 ----
    r = s.get(f"{BASE}/api/insights?source=demo&season=夏", timeout=60)
    d = r.json()
    check("下钻 season=夏", r.status_code == 200 and d.get("total_cases", -1) != ins.get("total_cases"),
          f"案件 {d.get('total_cases')}")
    r = s.get(f"{BASE}/api/insights?source=demo&season=错误值", timeout=30)
    check("非法 season 拒绝", r.status_code == 400, f"HTTP {r.status_code}")
    r = s.get(f"{BASE}/api/insights?source=demo&platform=不存在的平台", timeout=30)
    check("非法 platform 拒绝", r.status_code == 400, f"HTTP {r.status_code}")

    # ---- 4. 未登录写接口必须 401（前端是否已引导登录）----
    try:
        with open(IMG_A, "rb") as a, open(IMG_B, "rb") as b:
            r = s.post(
                f"{BASE}/api/analyze",
                files={
                    "returned_image": ("a.png", a, "image/png"),
                    "product_image": ("b.png", b, "image/png"),
                },
                data={"sku": "E2E-001", "amount": 99.5, "category": "3C数码", "supplier": "SUP-1",
                      "platform": "Amazon", "mode": "mock"},
                timeout=90,
            )
        check("POST /api/analyze (未登录应 401)", r.status_code == 401, f"HTTP {r.status_code} {r.text[:80]}")
    except FileNotFoundError:
        check("POST /api/analyze (未登录应 401)", False, f"测试图片缺失 {IMG_A}/{IMG_B}")

    r = s.post(f"{BASE}/api/cases", json={"sku": "E2E-X", "amount": 1.0}, timeout=30)
    check("POST /api/cases (未登录应 401)", r.status_code == 401, f"HTTP {r.status_code}")

    r = s.get(f"{BASE}/api/insights?source=real", timeout=30)
    d = r.json()
    check("匿名 real 洞察被拦截", d.get("requires_login") is True, f"requires_login={d.get('requires_login')}")

    # ---- 5. 登录 ----
    r = s.post(f"{BASE}/api/auth/login", json={"username": "demo", "password": "demo123"}, timeout=30)
    check("POST /api/auth/login", r.status_code == 200, f"HTTP {r.status_code} {r.text[:80]}")
    if r.status_code != 200:
        return report()
    token = r.json()["token"]
    s.headers["Authorization"] = f"Bearer {token}"

    r = s.get(f"{BASE}/api/auth/me", timeout=20)
    check("GET /api/auth/me", r.status_code == 200, r.text[:80])

    # ---- 6. 已登录写接口 ----
    try:
        with open(IMG_A, "rb") as a, open(IMG_B, "rb") as b:
            r = s.post(
                f"{BASE}/api/analyze",
                files={
                    "returned_image": ("a.png", a, "image/png"),
                    "product_image": ("b.png", b, "image/png"),
                },
                data={"sku": "E2E-001", "amount": 99.5, "category": "3C数码", "supplier": "SUP-1",
                      "platform": "Amazon", "mode": "mock"},
                timeout=120,
            )
        ok = r.status_code == 200
        detail = f"HTTP {r.status_code} {r.text[:100]}"
        if ok:
            j = r.json()
            ok = all(k in j for k in ("similarity", "defect_boxes", "voice_audio_b64", "dossier",
                                      "case_id", "platform_evidence", "persisted", "priority_score"))
            detail = f"sim={j.get('similarity')} 框={len(j.get('defect_boxes', []))} " \
                     f"语音={bool(j.get('voice_audio_b64'))} 落库={j.get('persisted')} 举证项={len(j.get('platform_evidence', []))}"
        check("POST /api/analyze (已登录)", ok, detail)
    except FileNotFoundError:
        check("POST /api/analyze (已登录)", False, "测试图片缺失")

    r = s.post(f"{BASE}/api/cases", json={"sku": "E2E-MANUAL", "amount": 12.5, "category": "服饰",
                                          "supplier": "SUP-9", "platform": "Temu", "outcome": "赢"}, timeout=30)
    check("POST /api/cases (已登录)", r.status_code == 201, f"HTTP {r.status_code} {r.text[:80]}")

    r = s.get(f"{BASE}/api/insights?source=real", timeout=60)
    d = r.json()
    check("登录后 real 洞察", r.status_code == 200 and d.get("requires_login") is not True,
          f"案件 {d.get('total_cases')} / 胜诉率 {d.get('win_rate')}")

    r = s.get(f"{BASE}/api/cases?source=real", timeout=30)
    d = r.json()
    check("GET /api/cases (real 分页)", r.status_code == 200 and "items" in d,
          f"total={d.get('total')} 返回 {len(d.get('items', []))} 条")

    # ---- 7. 删除（real 可删 / demo 拒绝）----
    if d.get("items"):
        cid = d["items"][0].get("case_id")
        r = s.delete(f"{BASE}/api/cases/{cid}?source=real", timeout=30)
        check(f"DELETE /api/cases/{cid} (real)", r.status_code == 200, f"HTTP {r.status_code} {r.text[:60]}")
    r = s.delete(f"{BASE}/api/cases/RG-NOTEXIST?source=demo", timeout=30)
    check("DELETE demo 库被拒", r.status_code == 403, f"HTTP {r.status_code}")

    # ---- 8. PDF 导出 ----
    r = s.get(f"{BASE}/api/export_pdf?source=demo", timeout=120)
    check("GET /api/export_pdf", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"HTTP {r.status_code} {len(r.content)} bytes")

    # ---- 9. 安全 ----
    r = s.get(f"{BASE}/static/index.html", timeout=20)
    check("直连 .html 被拦截", r.status_code == 404, f"HTTP {r.status_code}")
    r = s.get(f"{BASE}/api/calibrate", timeout=20)
    check("GET /api/calibrate", r.status_code == 200, r.text[:60])
    r = s.get(f"{BASE}/metrics", timeout=20)
    check("GET /metrics 需鉴权", r.status_code == 200, f"HTTP {r.status_code}")

    # ---- 10. 非法输入 ----
    r = s.post(f"{BASE}/api/analyze", files={"returned_image": ("a.txt", b"hello", "text/plain"),
                                             "product_image": ("b.txt", b"world", "text/plain")}, timeout=30)
    check("非图片上传被拒", r.status_code == 400, f"HTTP {r.status_code} {r.text[:60]}")

    return report()


def report() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"结果：{passed}/{total} 通过")
    failed = [(n, d) for n, ok, d in results if not ok]
    if failed:
        print("\n未通过项：")
        for n, d in failed:
            print(f"  - {n} :: {d}")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
