"""Model Router 实时调用（live 模式）。需要：
- 环境变量 MODEL_ROUTER_API_KEY
- 环境变量 PUBLIC_IMAGE_BASE：上传图片可公网访问的基础 URL
  （生产用对象存储，如阿里云 OSS；本地演示无法被 Model Router 回源，故 live 需可公网地址）
"""
import os
import math
import base64
import requests

API_BASE = "https://model-router.edu-aliyun.com/v1"
API_KEY = os.environ.get("MODEL_ROUTER_API_KEY", "")
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "")


def _headers():
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def embed_image(image_url):
    r = requests.post(f"{API_BASE}/embeddings", headers=_headers(),
                      json={"model": "qwen/tongyi-embedding-vision-plus",
                            "input": {"image": image_url}}, timeout=60)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return round(dot / (na * nb), 3)


def vl_chat(image_url, prompt):
    r = requests.post(f"{API_BASE}/chat/completions", headers=_headers(),
                      json={"model": "qwen/qwen3-vl-plus",
                            "messages": [{"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": image_url}}]}]},
                      timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ocr(image_url):
    r = requests.post(f"{API_BASE}/chat/completions", headers=_headers(),
                      json={"model": "qwen/qwen-vl-ocr",
                            "messages": [{"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": image_url}}]}]},
                      timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def llm(prompt):
    r = requests.post(f"{API_BASE}/chat/completions", headers=_headers(),
                      json={"model": "qwen/qwen3-max",
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False}, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def tts(text, voice="Chelsie"):
    r = requests.post(f"{API_BASE}/audio/speech", headers=_headers(),
                      json={"model": "qwen/qwen3-tts-instruct-flash",
                            "input": text, "voice": voice}, timeout=60)
    r.raise_for_status()
    return base64.b64encode(r.content).decode("ascii")


def live_analyze(returned_path, product_path, listing_text, sku, amount):
    if not API_KEY:
        raise RuntimeError("未配置 MODEL_ROUTER_API_KEY")
    if not PUBLIC_IMAGE_BASE:
        raise RuntimeError("未配置 PUBLIC_IMAGE_BASE（live 模式需可公网访问的图片地址）")
    ret_url = PUBLIC_IMAGE_BASE.rstrip("/") + "/" + os.path.basename(returned_path)
    prod_url = PUBLIC_IMAGE_BASE.rstrip("/") + "/" + os.path.basename(product_path)

    va = embed_image(ret_url)
    vb = embed_image(prod_url)
    sim = cosine(va, vb)
    same = sim >= 0.82

    raw = vl_chat(ret_url, "列出该退货商品的视觉瑕疵，若无则说'无明显瑕疵'，用逗号分隔的简短中文标签。")
    defects = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()] or ["无明显瑕疵"]

    promise = ocr(prod_url)
    consistency = llm(f"退回件相似度{sim}，瑕疵：{defects}。本店承诺：{promise or listing_text}。判断是否货不对板，一句话。")
    dossier = llm(f"生成结构化举证报告：SKU {sku}，相似度 {sim}，瑕疵 {defects}，一致性 {consistency}。")
    voice_text = llm(f"用中文写一段 60 字内的母语退货举证口头陈述，基于：相似度 {sim}，问题 {defects}。")
    audio = tts(voice_text)

    sev = {"外包装破损": 0.3, "商品缺件": 0.5, "污渍划痕": 0.2, "使用痕迹": 0.6,
           "功能故障": 0.8, "货不对板": 0.7, "色差明显": 0.3, "无明显瑕疵": 0.0}
    sev_score = max([sev.get(d, 0.2) for d in defects])
    priority = round(min(1.0, 0.4 + (1 - sim) * 0.3 + sev_score * 0.3 + (0.2 if amount > 50 else 0)), 3)

    return {"similarity": sim, "same_item": same, "defect_tags": defects,
            "defect_description": ", ".join(defects), "consistency": consistency,
            "dossier": dossier, "voice_text": voice_text, "voice_audio_b64": audio,
            "priority_score": priority, "mode": "live"}
