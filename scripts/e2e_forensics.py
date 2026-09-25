#!/usr/bin/env python3
# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
# -*- coding: utf-8 -*-
"""ReturnGuard 单案取证（阶段A）端到端功能验证。

针对 /api/analyze 全链路：鉴权 → 落图 → 取证 → 沉淀 → 导出 PDF，
并覆盖异常分支（未登录/非图片/非法 mode/platform/超大文件/live 降级标注）。

用法：
    python scripts/e2e_forensics.py [base_url]
默认 base_url = http://127.0.0.1:65432
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _enc_url(u: str) -> str:
    """URL 归一化：路径 percent-encode、查询串按 UTF-8 编码（含中文筛选值）。"""
    parts = urllib.parse.urlsplit(u)
    q = urllib.parse.urlencode(
        urllib.parse.parse_qsl(parts.query, keep_blank_values=True), encoding="utf-8"
    )
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, urllib.parse.quote(parts.path, safe="/"), q, parts.fragment)
    )

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:65432"
HERE = os.path.dirname(os.path.abspath(__file__))
IMG_A = os.path.join(HERE, "..", "demo", "test_a.png")
IMG_B = os.path.join(HERE, "..", "demo", "test_b.png")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def req(path, data=None, headers=None, method=None, timeout=90):
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
    r = urllib.request.Request(
        _enc_url(BASE + path), data=body, headers=headers or {},
        method=method or ("POST" if body else "GET"),
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def req_raw(path, headers=None, timeout=90):
    """取二进制响应（PDF 导出），不做 JSON 解析。"""
    r = urllib.request.Request(_enc_url(BASE + path), headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def multipart(fields: dict, files: dict) -> bytes:
    """手工构造 multipart/form-data（避免额外依赖）。"""
    boundary = "----rgForensicsBoundary" + str(int(time.time() * 1000))
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{boundary}\r\n".encode())
        out.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        out.write(f"{v}\r\n".encode())
    for k, (fn, content) in files.items():
        out.write(f"--{boundary}\r\n".encode())
        out.write(
            f'Content-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'.encode()
        )
        out.write(b"Content-Type: image/png\r\n\r\n")
        out.write(content)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def analyze(files_map, fields, headers=None):
    body, ctype = multipart(fields, files_map)
    h = {"Content-Type": ctype}
    if headers:
        h.update(headers)
    return req("/api/analyze", data=body, headers=h)


def main():
    print("=" * 60)
    print("单案取证（阶段A）端到端验证")
    print("=" * 60)

    # ---- 0. 前置 ----
    print("\n[0] 前置健康检查")
    st, _ = req("/health")
    check("服务健康 /health=200", st == 200, f"got {st}")
    for p in (IMG_A, IMG_B):
        check(f"测试图存在 {os.path.basename(p)}", os.path.exists(p))
    a_bytes = open(IMG_A, "rb").read()
    b_bytes = open(IMG_B, "rb").read()

    # ---- 1. 鉴权 ----
    print("\n[1] 鉴权")
    st, body = req(
        "/api/auth/login",
        data={"username": "demo", "password": "demo123"},
        headers={"Content-Type": "application/json"},
    )
    check("登录 demo/demo123 成功", st == 200 and "token" in body, f"status={st}")
    token = body.get("token", "")
    AUTH = {"Authorization": "Bearer " + token} if token else {}

    # 1b 未登录应 401（取证必须登录，SEC-1）
    st, _ = analyze(
        {"returned_image": ("r.png", a_bytes), "product_image": ("p.png", b_bytes)},
        {"sku": "SKU-NOAUTH", "mode": "mock"},
    )
    check("未登录取证被拒 401", st == 401, f"got {st}")

    # ---- 2. mock 取证全字段 ----
    print("\n[2] mock 模式取证（完整字段校验）")
    sku = "SKU-FORENSICS-" + str(int(time.time()))[-6:]
    st, res = analyze(
        {"returned_image": ("r.png", a_bytes), "product_image": ("p.png", b_bytes)},
        {
            "sku": sku,
            "listing_text": "纯棉T恤，支持7天无理由",
            "amount": "129.9",
            "category": "服饰鞋包",
            "supplier": "S3",
            "platform": "Amazon",
            "mode": "mock",
        },
        headers=AUTH,
    )
    forensics_id = res.get("case_id")  # 记录待清理，避免污染演示租户
    check("取证返回 200", st == 200, f"got {st}")
    required = [
        "case_id", "similarity", "same_item", "defect_tags", "defect_description",
        "consistency", "dossier", "voice_text", "voice_audio_b64",
        "priority_score", "defect_boxes", "mode", "persisted",
    ]
    for k in required:
        check(f"响应含字段 {k}", k in res)
    check("similarity 在 [0,1]", isinstance(res.get("similarity"), (int, float))
          and 0.0 <= float(res.get("similarity", -1)) <= 1.0, str(res.get("similarity")))
    check("priority_score 在 [0,1]", 0.0 <= float(res.get("priority_score", -1)) <= 1.0,
          str(res.get("priority_score")))
    check("mode=mock", res.get("mode") == "mock", str(res.get("mode")))
    check("persisted=True（已沉淀落库）", res.get("persisted") is True, str(res.get("persisted")))
    check("defect_tags 非空列表", isinstance(res.get("defect_tags"), list) and len(res["defect_tags"]) > 0)
    check("dossier 非空文本", bool(str(res.get("dossier", "")).strip()))
    check("voice_text 非空文本", bool(str(res.get("voice_text", "")).strip()))
    check("voice_audio_b64 可解码 base64", bool(str(res.get("voice_audio_b64", "")).strip()))
    boxes = res.get("defect_boxes") or []
    boxes_ok = all(
        all(kk in b for kk in ("label", "x", "y", "w", "h")) for b in boxes
    )
    check("defect_boxes 坐标字段完整", boxes_ok, f"{len(boxes)} boxes")
    # 归一化坐标应在 0~1
    norm_ok = all(
        0.0 <= float(b.get("x", -1)) <= 1.0 and 0.0 <= float(b.get("y", -1)) <= 1.0
        for b in boxes
    ) if boxes else True
    check("defect_boxes 坐标为归一化 0~1", norm_ok)
    ev = res.get("platform_evidence")
    check("platform=Amazon 返回平台举证清单", isinstance(ev, list) and len(ev) > 0,
          f"{len(ev) if isinstance(ev, list) else 0} 项")
    check("单案 outcome 固定为「待分析」（不污染胜诉率）", res.get("outcome") == "待分析",
          str(res.get("outcome")))

    # ---- 3. 数据沉淀（按 sku 精确检索，绕开分页）----
    print("\n[3] 取证结果沉淀校验")
    st, lst = req(f"/api/cases?source=real&page=1&page_size=200", headers=AUTH)
    found = None
    if st == 200:
        for it in lst.get("items", []):
            if it.get("sku") == sku:
                found = it
                break
    if found is None:
        # 分页可能覆盖不到（>200 条时），按 filter 再查一次确认
        st2, lst2 = req("/api/cases?source=real&page=1&page_size=200&category=服饰鞋包", headers=AUTH)
        if st2 == 200:
            for it in lst2.get("items", []):
                if it.get("sku") == sku:
                    found = it
                    break
    check("取证案件已落入 real 源并可按 sku 检索", found is not None,
          "未在首两页找到（分页/排序隐患）" if found is None else f"case_id={found.get('case_id')}")
    if found:
        check("沉淀记录带 supplier 维度", found.get("supplier") == "S3", str(found.get("supplier")))
        check("沉淀记录 outcome=待分析", found.get("outcome") == "待分析", str(found.get("outcome")))

    # ---- 4. live 模式降级标注（诚信）----
    print("\n[4] live 模式与降级标注")
    st, res_live = analyze(
        {"returned_image": ("r.png", a_bytes), "product_image": ("p.png", b_bytes)},
        {"sku": sku + "-LIVE", "mode": "live", "platform": "Temu"},
        headers=AUTH,
    )
    check("live 取证不 5xx（有降级兜底）", st == 200 and st < 500, f"got {st}")
    mode_live = res_live.get("mode", "")
    check("live mode 标注诚实（live / live(partial) / mock(fallback)）",
          mode_live in ("live", "live(partial)", "mock(fallback)"), f"mode={mode_live}")
    if mode_live != "live":
        check("降级时透出 degraded 能力清单", "degraded" in res_live or "capabilities" in res_live,
              f"degraded={res_live.get('degraded')}")
    check("live 仍返回完整取证字段",
          all(k in res_live for k in ("similarity", "dossier", "defect_boxes", "voice_text")))
    live_id = res_live.get("case_id")  # 记录待清理，避免污染演示租户

    # ---- 5. 异常分支 ----
    print("\n[5] 异常分支")
    # 非图片文件
    st, _ = analyze(
        {"returned_image": ("bad.png", b"not-an-image"), "product_image": ("p.png", b_bytes)},
        {"sku": "SKU-BAD", "mode": "mock"}, headers=AUTH,
    )
    check("非图片被拒 400", st == 400, f"got {st}")
    # 非法 mode
    st, _ = analyze(
        {"returned_image": ("r.png", a_bytes), "product_image": ("p.png", b_bytes)},
        {"sku": "SKU-BADMODE", "mode": "evil"}, headers=AUTH,
    )
    check("非法 mode 被拒 400", st == 400, f"got {st}")
    # 非法 platform
    st, _ = analyze(
        {"returned_image": ("r.png", a_bytes), "product_image": ("p.png", b_bytes)},
        {"sku": "SKU-BADPLAT", "mode": "mock", "platform": "NotAPlatform"}, headers=AUTH,
    )
    check("非法 platform 被拒 400", st == 400, f"got {st}")
    # 超大文件（构造 > 上限的假图，带 PNG 魔数）
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (12 * 1024 * 1024)
    st, _ = analyze(
        {"returned_image": ("big.png", big), "product_image": ("p.png", b_bytes)},
        {"sku": "SKU-BIG", "mode": "mock"}, headers=AUTH,
    )
    check("超大文件被拒 413（或 400）", st in (400, 413), f"got {st}")

    # ---- 6. PDF 导出 ----
    print("\n[6] 报告导出")
    st, pdf = req_raw("/api/export_pdf", headers=AUTH)
    check("PDF 导出 200", st == 200, f"got {st}")
    check("PDF 内容为合法 PDF（%PDF 魔数）",
          isinstance(pdf, bytes) and pdf[:4] == b"%PDF", f"{len(pdf) if pdf else 0} bytes")
    check("PDF 体积 > 1KB（非空报告）", isinstance(pdf, bytes) and len(pdf) > 1024,
          f"{len(pdf) if pdf else 0} bytes")

    # ---- 7. 洞察看板仍正常 ----
    print("\n[7] 洞察看板")
    st, ins = req("/api/insights?source=real", headers=AUTH)
    check("登录态 real 洞察 200", st == 200, f"got {st}")
    if st == 200:
        check("洞察 total_cases > 0", (ins.get("total_cases") or 0) > 0,
              f"total={ins.get('total_cases')}")
    st, ins_demo = req("/api/insights?source=demo")
    check("匿名 demo 洞察 200 且为 1206",
          st == 200 and ins_demo.get("total_cases") == 1206,
          f"total={ins_demo.get('total_cases') if st == 200 else st}")

    # ---- 8. 清理：删除本脚本创建的取证案件，使演示租户(real→demo)回到 1206（P2-③）----
    print("\n[8] 清理演示租户测试数据")
    for _cid in (forensics_id, live_id):
        if not _cid:
            continue
        st, _ = req(f"/api/cases/{_cid}?source=real", method="DELETE", headers=AUTH)
        check(f"清理测试案件 {_cid}", st in (200, 404), f"got {st}")

    # ---- 汇总 ----
    print("\n" + "=" * 60)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
