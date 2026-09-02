# -*- coding: utf-8 -*-
"""A/B/C 全量复测（P3-18 双图对比缺陷识别后），直连 live_analyze，输出统一结果集。"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(__file__))
UP = os.path.join(os.path.dirname(__file__), "uploads")
from models_router import live_analyze  # noqa: E402

CASES = {
    "A": (os.path.join(UP, "live_mug_returned.png"), os.path.join(UP, "live_mug.png"),
          "陶瓷马克杯·品质承诺卡", "MUG-LIVE-A", 99.0, "同款+瑕疵(咖啡渍+划痕)"),
    "B": (os.path.join(UP, "live_apple.png"), os.path.join(UP, "live_book.png"),
          "新鲜苹果·A级果", "APPLE-LIVE-B", 39.0, "调包(苹果 vs 书)"),
    "C": (os.path.join(UP, "live_tshirt.png"), os.path.join(UP, "live_tshirt_listing.png"),
          "纯棉T恤·品质承诺卡", "TSHIRT-LIVE-C", 59.0, "同款+图文承诺(OCR)"),
}

results = {}
for g, (rp, pp, listing, sku, amt, desc) in CASES.items():
    t0 = time.time()
    try:
        r = live_analyze(rp, pp, listing, sku, amt)
        results[g] = {
            "desc": desc, "elapsed_s": round(time.time() - t0, 1),
            "mode": r.get("mode"),
            "similarity": r.get("similarity"),
            "same_item": r.get("same_item"),
            "defect_tags": r.get("defect_tags"),
            "defect_boxes_live": r.get("defect_boxes_live"),
            "defect_boxes": r.get("defect_boxes"),
            "capabilities": r.get("capabilities"),
            "degraded": r.get("degraded"),
            "consistency": r.get("consistency"),
            "promise_ocr": r.get("promise") if "promise" in r else None,
        }
        print(f"=== GROUP {g} ({desc}) {results[g]['elapsed_s']}s ===")
        print("  sim:", r.get("similarity"), "same:", r.get("same_item"),
              "tags:", r.get("defect_tags"), "boxes_live:", r.get("defect_boxes_live"))
    except Exception as e:
        results[g] = {"desc": desc, "error": str(e), "elapsed_s": round(time.time() - t0, 1)}
        print(f"=== GROUP {g} ERROR: {e}")

with open(os.path.join(os.path.dirname(__file__), "live_abc_final.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSAVED -> live_abc_final.json")
