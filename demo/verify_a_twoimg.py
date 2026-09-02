# -*- coding: utf-8 -*-
"""GROUP A 复测：双图对比缺陷识别（P3-18 修复后）。
直接 import models_router.live_analyze，验证「同款+瑕疵」能否被 live 视觉链路真实检出。
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(__file__))
UP = os.path.join(os.path.dirname(__file__), "uploads")

from models_router import live_analyze  # noqa: E402

t0 = time.time()
r = live_analyze(
    os.path.join(UP, "live_mug_returned.png"),  # 退回件（带污渍/划痕）
    os.path.join(UP, "live_mug.png"),            # 本店主图
    "陶瓷马克杯·品质承诺卡", "MUG-LIVE-A", 99.0,
)
keys = ["mode", "similarity", "same_item", "defect_tags", "defect_description",
        "defect_boxes_live", "capabilities", "degraded", "consistency"]
out = {k: r.get(k) for k in keys}
out["elapsed_s"] = round(time.time() - t0, 1)
out["defect_boxes"] = r.get("defect_boxes")
print(json.dumps(out, ensure_ascii=False, indent=2))

with open(os.path.join(os.path.dirname(__file__), "live_a_twoimg.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("SAVED -> live_a_twoimg.json")
