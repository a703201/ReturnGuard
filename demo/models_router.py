"""Model Router 实时调用（live 模式）。需要：
- 环境变量 MODEL_ROUTER_API_KEY
- 环境变量 PUBLIC_IMAGE_BASE：上传图片可公网访问的基础 URL
  （生产用对象存储，如阿里云 OSS；本地演示无法被 Model Router 回源，故 live 需可公网地址）
"""
import os
import json
import math
import base64
import re
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


def _extract_json(raw):
    """从模型返回里稳健地抽取 JSON（兼容 deepseek-r1 的 <think> 包裹 / 多余文本）。"""
    if not raw:
        return {}
    s = raw.strip()
    # 去掉 <think>...</think>
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)
    # 找第一个 { 到最后一个 }
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    block = s[start:end + 1]
    try:
        return json.loads(block)
    except Exception:
        return {}


def llm_json(prompt, model="qwen/qwen3-max"):
    r = requests.post(f"{API_BASE}/chat/completions", headers=_headers(),
                      json={"model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False}, timeout=120)
    r.raise_for_status()
    return _extract_json(r.json()["choices"][0]["message"]["content"])


def build_insights_live(aggregated):
    """用大模型对聚合统计做缺陷聚类 + 根因归因 + 选品/品控建议（方案阶段B 核心）。

    aggregated 来自 pipeline._aggregate，含 sku_ranking / defect_distribution / total_cases。
    返回 {root_cause, sku_insights[], recommendations[], report}。
    """
    if not API_KEY:
        raise RuntimeError("未配置 MODEL_ROUTER_API_KEY")
    ctx = {
        "total_cases": aggregated.get("total_cases"),
        "sku_ranking": aggregated.get("sku_ranking"),
        "defect_distribution": aggregated.get("defect_distribution"),
    }
    prompt = (
        "你是一名资深的跨境电商品控与选品分析师。下面是一位跨境卖家退货案件的聚合统计（JSON）：\n"
        f"{json.dumps(ctx, ensure_ascii=False)}\n\n"
        "请完成四件事，并以 JSON 返回（不要任何解释文本，只返回 JSON）：\n"
        "1) root_cause：字符串，归纳退货高发的根因（如包装防护不足 / 供应商质量不稳定 / listing 过度承诺 / 物流暴力分拣等），并给出数据依据。\n"
        "2) sku_insights：数组，取退款金额最高的前 3 个 SKU，每个元素为 {\"sku\":..,\"finding\":..,\"action\":..}，finding 指出该 SKU 的核心问题，action 给可执行整改动作。\n"
        "3) recommendations：数组，3-5 条可执行的选品 / 品控 / listing 改写建议，面向卖家管理者。\n"
        "4) report：字符串，一段《选品 / 品控洞察报告》正文（中文，约 150 字），总结现状与下一步。\n"
    )
    out = llm_json(prompt, model="qwen/qwen3-max")
    if not out:
        raise RuntimeError("洞察 LLM 未返回有效 JSON")
    return {
        "root_cause": out.get("root_cause", ""),
        "sku_insights": out.get("sku_insights", []),
        "recommendations": out.get("recommendations", []),
        "report": out.get("report", ""),
    }
