# -*- coding: utf-8 -*-
"""录制用：本地直连 dashscope live，跑 A/B/C 三组单案取证。
- GROUP A（同款+瑕疵）：重试直到缺陷标签非「无明显瑕疵」为止（最多 MAX_A 次），
  保证录屏拿到"同款+真实瑕疵红框"的干净一拍。
- B（调包）/ C（同款+图文承诺）：各跑一次。
落盘 live_demo_capture.json，供录屏前自检 / 素材对齐。
走本地 127.0.0.1 视觉内联，无需公网、无 Cloudflare 524。
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(__file__))
UP = os.path.join(os.path.dirname(__file__), "uploads")
from models_router import live_analyze  # noqa: E402

MAX_A = 8

def run_a():
    rp, pp = os.path.join(UP, "live_mug_returned.png"), os.path.join(UP, "live_mug.png")
    for i in range(1, MAX_A + 1):
        t0 = time.time()
        r = live_analyze(rp, pp, "陶瓷马克杯·品质承诺卡", "MUG-LIVE-A", 99.0)
        tags = r.get("defect_tags") or ["无明显瑕疵"]
        ok = tags != ["无明显瑕疵"]
        print(f"[A try {i}] sim={r.get('similarity')} same={r.get('same_item')} "
              f"tags={tags} boxes_live={r.get('defect_boxes_live')} ({round(time.time()-t0,1)}s) "
              f"{'OK' if ok else 'retry'}")
        if ok and r.get("same_item"):
            return r
    return r  # 返回最后一次（仍可用）

def run_once(name, rp, pp, listing, sku, amt):
    t0 = time.time()
    r = live_analyze(rp, pp, listing, sku, amt)
    print(f"[{name}] sim={r.get('similarity')} same={r.get('same_item')} "
          f"tags={r.get('defect_tags')} boxes_live={r.get('defect_boxes_live')} ({round(time.time()-t0,1)}s)")
    return r

out = {
    "A": run_a(),
    "B": run_once("B", os.path.join(UP, "live_apple.png"), os.path.join(UP, "live_book.png"),
                  "新鲜苹果·A级果", "APPLE-LIVE-B", 39.0),
    "C": run_once("C", os.path.join(UP, "live_tshirt.png"), os.path.join(UP, "live_tshirt_listing.png"),
                  "纯棉T恤·品质承诺卡", "TSHIRT-LIVE-C", 59.0),
}
# 精简落盘
def slim(r):
    return {k: r.get(k) for k in ["mode", "similarity", "same_item", "defect_tags",
            "defect_description", "defect_boxes_live", "defect_boxes", "capabilities",
            "degraded", "consistency"]}
slim_out = {g: slim(r) for g, r in out.items()}
with open(os.path.join(os.path.dirname(__file__), "live_demo_capture.json"), "w", encoding="utf-8") as f:
    json.dump(slim_out, f, ensure_ascii=False, indent=2)
print("\nSAVED -> live_demo_capture.json")
