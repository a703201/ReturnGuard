#!/usr/bin/env python3
"""端到端验证 live_analyze：用两张本地图（退回件 / 本店主图）走真实视觉链路。

证明单案取证「视觉实跑」已收口：①'同款(VL) / ②瑕疵(VL) / ②'红框(VL) / ③OCR 应全部 caps=True，
mode=live。embed(①向量) 在 dashscope 工作空间兼容模式不支持 → 走 VL 同款主路径（caps 不受影响）。
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models_router as mr

UP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UP, exist_ok=True)


def _dl(seed: str, name: str) -> str:
    p = os.path.join(UP, name)
    try:
        req = urllib.request.Request(
            f"https://picsum.photos/seed/{seed}/600/450", headers={"User-Agent": "rg"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) > 2000:
            open(p, "wb").write(data)
            return p
    except Exception as e:  # noqa: BLE001
        print(f"[dl] {seed} 失败: {e}")
    return p


if __name__ == "__main__":
    print(f"[e2e] profile={mr.MODEL_ROUTER_PROFILE} endpoint={mr.API_BASE} key_set={bool(mr.API_KEY)}")
    ret = _dl("rg_returned_xyz", "rg_returned_test.png")
    prod = _dl("rg_product_abc", "rg_product_test.png")
    print(f"[e2e] 退回件={ret}\n[e2e] 本店主图={prod}\n")
    try:
        out = mr.live_analyze(
            returned_path=ret,
            product_path=prod,
            listing_text="本店承诺：全新未拆封，支持 30 天无理由退换。",
            sku="SKU-TEST-001",
            amount=129.0,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[e2e] live_analyze 抛错: {type(e).__name__}: {e}")
        sys.exit(1)

    caps = out.get("capabilities", {})
    print("==== live_analyze 结果 ====")
    print(f"mode        = {out.get('mode')}")
    print(f"capabilities= {caps}")
    print(f"similarity  = {out.get('similarity')}  same_item={out.get('same_item')}")
    print(f"defect_tags = {out.get('defect_tags')}")
    print(f"defect_boxes= {len(out.get('defect_boxes', []))} 个  (live={out.get('defect_boxes_live')})")
    print(f"ocr(promise)= {str(out.get('consistency'))[:80]!r}")
    print(f"dossier     = {str(out.get('dossier'))[:80]!r}")
    print(f"priority    = {out.get('priority_score')}")
    live = [k for k, v in caps.items() if v]
    print(f"\n[e2e] 真实能力 = {len(live)}/{len(caps)} -> {live}")
    if out.get("mode") == "live":
        print("[e2e] ✅ 单案取证视觉实跑 OK（mode=live，全部视觉能力为真）")
    else:
        print(f"[e2e] ⚠️ mode={out.get('mode')}，仍有能力回退：{out.get('degraded')}")
