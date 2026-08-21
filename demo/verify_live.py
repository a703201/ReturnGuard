#!/usr/bin/env python3
"""ReturnGuard · live 全链路冒烟测试（带 Key 才跑，无 Key 自动 SKIP）

验证 stage A 单案取证在 live 模式下的真实可用性：
  - 生成两张测试图 → 经 storage 图床得到公网 URL → live_analyze 跑通
  - 逐项报告 similarity / defects / ocr / tts 是否真实模型（capabilities）
  - 任一能力不可用则标注 (mock 回退)，整体不报错即视为链路就绪

运行：
  set MODEL_ROUTER_API_KEY=sk-xxx
  set PUBLIC_IMAGE_BASE=https://<你的公网>/uploads   # 或配置 RG_OSS_*
  python verify_live.py
"""

import base64
import os
import sys
import tempfile
import uuid

from models_router import live_analyze
from storage import backend_name, is_public_ready
from storage import upload as bed_upload

# 两张不同色的 1x1 PNG（base64），仅用于让视觉/向量模型有图可拉
_PNG_RED = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PNG_BLU = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _write_tmp(png: bytes, name: str) -> str:
    p = os.path.join(tempfile.gettempdir(), f"rg_live_{uuid.uuid4().hex[:8]}_{name}.png")
    with open(p, "wb") as f:
        f.write(png)
    return p


def main() -> int:
    if not os.environ.get("MODEL_ROUTER_API_KEY"):
        print("[verify_live] SKIP: 未配置 MODEL_ROUTER_API_KEY，无法跑 live 链路")
        return 0
    print(f"[verify_live] 图床后端={backend_name()} 公网就绪={is_public_ready()}")
    if not is_public_ready():
        print(
            "[verify_live] WARN: 未配置 PUBLIC_IMAGE_BASE / RG_OSS_*，"
            "视觉/向量/OCR 将不可用（live_analyze 会回退 mock）"
        )
    rp = _write_tmp(_PNG_RED, "ret.png")
    pp = _write_tmp(_PNG_BLU, "prod.png")
    ret_url = bed_upload(rp, os.path.basename(rp))
    prod_url = bed_upload(pp, os.path.basename(pp))
    print(f"[verify_live] ret_url={ret_url}\n[verify_live] prod_url={prod_url}")
    try:
        res = live_analyze(
            rp,
            pp,
            "全新未拆封",
            "SKU-LIVE-SMOKE",
            99.0,
            returned_url=ret_url,
            product_url=prod_url,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[verify_live] FAIL: live_analyze 抛错: {e}")
        return 1
    caps = res.get("capabilities", {})
    print("[verify_live] 能力逐项：")
    for k, v in caps.items():
        print(f"   - {k}: {'真实模型' if v else 'mock 回退'}")
    print(
        f"[verify_live] 相似度={res.get('similarity')} "
        f"瑕疵={res.get('defect_tags')} mode={res.get('mode')}"
    )
    print("[verify_live] PASS: live 链路调用成功（各能力按网关开通情况混合真实/回退）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
