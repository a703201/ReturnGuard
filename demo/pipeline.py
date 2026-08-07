"""ReturnGuard 取证 + 洞察流水线（mock / live 双模式）"""
import os
import json
import math
import base64
import io
import wave
import struct
import random
import hashlib
from collections import Counter, defaultdict

DEFECT_POOL = ["外包装破损", "商品缺件", "污渍划痕", "使用痕迹", "功能故障", "货不对板", "色差明显"]
SEVERITY = {"外包装破损": 0.3, "商品缺件": 0.5, "污渍划痕": 0.2, "使用痕迹": 0.6,
            "功能故障": 0.8, "货不对板": 0.7, "色差明显": 0.3, "无明显瑕疵": 0.0}


def _hash_seed(*paths):
    h = hashlib.md5("|".join(str(p) for p in paths).encode("utf-8")).hexdigest()
    return int(h, 16)


def _mock_similarity(returned_path, product_path):
    s = _hash_seed(returned_path, product_path)
    return round(0.55 + (s % 1000) / 1000 * 0.43, 3)  # 0.55 ~ 0.98


def _gen_wav(text, sr=16000, dur=1.2):
    """生成一段占位 WAV（正弦音），mock 模式下充当 TTS 产物。"""
    n = int(sr * dur)
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    for i in range(n):
        val = int(12000 * math.sin(2 * math.pi * 440 * i / sr) * (1 - i / n))
        w.writeframes(struct.pack("<h", val))
    w.close()
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _mock(returned_path, product_path, listing_text, sku, amount):
    sim = _mock_similarity(returned_path, product_path)
    random.seed(_hash_seed(returned_path))
    n_def = random.randint(0, 3)
    defects = random.sample(DEFECT_POOL, n_def) if n_def > 0 else ["无明显瑕疵"]
    same = sim >= 0.82
    if same and defects == ["无明显瑕疵"]:
        consistency = "一致（疑似非质量原因，倾向买家责任）"
    else:
        consistency = "存在差异（货不对板 / 运输或质量瑕疵）"
    sev_score = max([SEVERITY.get(d, 0.2) for d in defects])
    priority = round(min(1.0, 0.4 + (1 - sim) * 0.3 + sev_score * 0.3 + (0.2 if amount > 50 else 0)), 3)
    dossier = (
        f"《ReturnGuard 举证报告》\nSKU：{sku}\n"
        f"同款一致性相似度：{sim}（{'同一件商品' if same else '疑似调包 / 非同款'}）\n"
        f"瑕疵识别：{', '.join(defects)}\n"
        f"与 listing 承诺一致性：{consistency}\n"
        f"处置建议：{'提交客观证据，主张买家责任' if same else '据实举证商品状态，争取合理退款'}。"
    )
    voice_text = (
        f"您好，这是关于订单 {sku} 的退货举证。系统比对显示退回商品与本店商品相似度为 {sim}，"
        f"{'为同一件商品' if same else '存在明显差异'}；主要问题为{', '.join(defects)}。"
        f"请核查后公正裁决，谢谢。"
    )
    return {
        "similarity": sim,
        "same_item": same,
        "defect_tags": defects,
        "defect_description": "；".join(defects),
        "consistency": consistency,
        "dossier": dossier,
        "voice_text": voice_text,
        "voice_audio_b64": _gen_wav(voice_text),
        "priority_score": priority,
        "mode": "mock",
    }


def analyze_case(returned_path, product_path, listing_text, sku, amount, mode="mock"):
    if mode == "live":
        try:
            from models_router import live_analyze
            return live_analyze(returned_path, product_path, listing_text, sku, amount)
        except Exception as e:  # 失败回退 mock，保证演示不中断
            res = _mock(returned_path, product_path, listing_text, sku, amount)
            res["mode"] = "mock(fallback)"
            res["error"] = str(e)
            return res
    return _mock(returned_path, product_path, listing_text, sku, amount)


def load_cases(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_case(path, case):
    cases = load_cases(path)
    cases.append(case)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)


def build_insights(cases):
    if not cases:
        return {"total_cases": 0, "sku_ranking": [], "defect_distribution": {},
                "top_problem_skus": [], "recommendations": ["暂无案件数据，请先提交退货取证。"]}
    sku_data = defaultdict(lambda: {"cases": 0, "refund": 0.0, "sim_sum": 0.0,
                                    "defects": Counter(), "won": 0})
    defect_all = Counter()
    for c in cases:
        s = c.get("sku", "未知")
        d = sku_data[s]
        d["cases"] += 1
        d["refund"] += float(c.get("amount", 0) or 0)
        d["sim_sum"] += float(c.get("similarity", 0) or 0)
        for dt in c.get("defect_tags", []):
            d["defects"][dt] += 1
            defect_all[dt] += 1
    ranking = []
    for s, d in sku_data.items():
        avg_sim = d["sim_sum"] / d["cases"]
        ranking.append({
            "sku": s, "cases": d["cases"], "avg_similarity": round(avg_sim, 3),
            "dispute_rate": round(1 - avg_sim, 3), "refund": round(d["refund"], 2),
            "top_defect": d["defects"].most_common(1)[0][0] if d["defects"] else "-",
        })
    ranking.sort(key=lambda x: -x["refund"])
    top = ranking[:3]
    recs = []
    for r in top:
        recs.append(
            f"SKU {r['sku']} 退货纠纷 {r['cases']} 笔、退款约 ¥{r['refund']}，"
            f"高发问题：{r['top_defect']}，建议复核供应商或加固包装 / 改写 listing 承诺。"
        )
    return {"total_cases": len(cases), "sku_ranking": ranking,
            "defect_distribution": dict(defect_all),
            "top_problem_skus": [r["sku"] for r in top], "recommendations": recs}
