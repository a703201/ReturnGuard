#!/usr/bin/env python3
"""ReturnGuard · 视觉模型可用性探针（tokenplan profile，限流解除后跑）

对单案取证依赖的三个视觉能力逐一发起真实调用：
  ① embed_image   -> tongyi-embedding-vision-plus 图像向量（返回向量即开通）
  ② vl_chat       -> qwen3-vl-plus 瑕疵识别（返回文本即开通）
  ②' vl_detect_boxes -> qwen3-vl-plus 缺陷定位 bbox（返回有效 bbox 即开通）
  ③ ocr           -> qwen-vl-ocr listing 承诺提取（返回文本即开通）

用 storage 图床（七牛）得到公网 URL 喂给模型，逐能力报告 OK / FAIL+原因。
任一 FAIL 即说明该视觉模型在 Token Plan 网关未开通（会走 live 回退）。
"""
import os
import sys
import base64
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
# 只在本机跑（非 pytest），models_router/storage 会自行 load_dotenv
import models_router as mr
import storage
from prompts import DEFECT_RECOGNITION_PROMPT, DEFECT_BBOX_PROMPT, OCR_PROMISE_PROMPT

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _real_test_image() -> str:
    """下载一张真实尺寸的公网 HTTPS 图作视觉探测样本（1x1 会被模型解码器拒收）。
    离线时回退 1x1 PNG。返回本地文件路径（落在 demo/uploads，使 storage 自托管分支
    把副本也写到 demo/uploads，与本服务 /api/img 路由、e2e 占位服务同目录）。"""
    up = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(up, exist_ok=True)
    p = os.path.join(up, "rg_vis_real.png")
    try:
        req = urllib.request.Request(
            "https://picsum.photos/seed/returnguard/600/450",
            headers={"User-Agent": "rg-probe"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) > 2000:  # 真实图都远大于 1x1
            open(p, "wb").write(data)
            return p
    except Exception as e:  # noqa: BLE001
        print(f"[probe] 真图下载失败，回退 1x1: {e}")
    open(p, "wb").write(_PNG)
    return p


def _pub(path: str, name: str) -> str:
    return storage.upload(path, name)


def main() -> int:
    print(f"[probe] profile={mr.MODEL_ROUTER_PROFILE} endpoint={mr.API_BASE}")
    print(f"[probe] key_set={bool(mr.API_KEY)} 图床={storage.backend_name()} "
          f"公网就绪={storage.is_public_ready()}")
    if not mr.API_KEY:
        print("[probe] FAIL: 未配置 MODEL_ROUTER_API_KEY")
        return 1
    if not storage.is_public_ready():
        print("[probe] FAIL: 图床未就绪，无法喂公网图给视觉模型")
        return 1

    p = _real_test_image()
    url = _pub(p, "rg_vis_probe.png")
    print(f"[probe] 公网图 url={url}\n")

    results = {}

    # ① 向量
    try:
        v = mr.embed_image(url)
        results["①embed"] = f"OK 向量维度={len(v)}"
    except Exception as e:  # noqa: BLE001
        results["①embed"] = f"FAIL {type(e).__name__}: {str(e)[:160]}"

    # ② 瑕疵识别（传本地路径，由 _img_source 转 base64 内联，绕开隧道回源）
    try:
        t = mr.vl_chat(p, DEFECT_RECOGNITION_PROMPT)
        results["②vl_chat"] = f"OK 返回{len(t)}字: {t[:60]!r}"
    except Exception as e:  # noqa: BLE001
        results["②vl_chat"] = f"FAIL {type(e).__name__}: {str(e)[:160]}"

    # ②' bbox
    try:
        b = mr.vl_detect_boxes(p, DEFECT_BBOX_PROMPT)
        results["②'vl_boxes"] = f"OK bbox数={len(b)} -> {b[:1]}"
    except Exception as e:  # noqa: BLE001
        results["②'vl_boxes"] = f"FAIL {type(e).__name__}: {str(e)[:160]}"

    # ③ OCR
    try:
        o = mr.ocr(p, OCR_PROMISE_PROMPT)
        results["③ocr"] = f"OK 返回{len(o)}字: {o[:60]!r}"
    except Exception as e:  # noqa: BLE001
        results["③ocr"] = f"FAIL {type(e).__name__}: {str(e)[:160]}"

    # ①' VL 同款判定（新 ① 主路径：百炼兼容模式不支持视觉向量，改用 VL 直接判同款）
    try:
        vs = mr.vl_similarity(p, p)
        results["①'vl_sim"] = f"OK 相似度={vs['similarity']} 同款={vs['same_item']} 理由={vs['reason'][:40]!r}"
    except Exception as e:  # noqa: BLE001
        results["①'vl_sim"] = f"FAIL {type(e).__name__}: {str(e)[:160]}"

    print("==== 视觉模型逐项探测结果 ====")
    ok = 0
    for k, v in results.items():
        print(f"  {k}: {v}")
        if v.startswith("OK"):
            ok += 1
    print(f"\n[probe] 真实可用视觉能力 = {ok}/{len(results)}（embed/vl_chat/vl_boxes/ocr/vl_sim）")
    print("[probe] 未开通者将在 live_analyze 中走 mock 回退（前端如实标注）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
