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
from datetime import datetime, timedelta

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


# 缺陷类型 -> 根因桶映射（用于归因与整改建议）
_DEFECT_BUCKET = {
    "外包装破损": "物流与包装",
    "污渍划痕": "物流与包装",
    "商品缺件": "供应商履约",
    "功能故障": "供应商质量",
    "货不对板": "Listing与图文",
    "色差明显": "Listing与图文",
    "使用痕迹": "非质量(倾向买家)",
    "无明显瑕疵": "非质量(倾向买家)",
}
_BUCKET_ADVICE = {
    "物流与包装": "对易碎/高值品升级加厚纸箱+气泡膜，做跌落测试，并评估物流商分拣质量",
    "供应商履约": "到货全检+装箱清单逐项核对，必要时更换供应商",
    "供应商质量": "批次抽检老化测试，建立供应商质量分淘汰机制",
    "Listing与图文": "核对实物与listing图文，去掉过度承诺，补充实拍与色差说明",
    "非质量(倾向买家)": "保留同款一致性证据，主张买家责任，提升举证完整度",
}
_DEFECT_SEV = {"外包装破损": 0.3, "商品缺件": 0.5, "污渍划痕": 0.2, "使用痕迹": 0.6,
               "功能故障": 0.8, "货不对板": 0.7, "色差明显": 0.3, "无明显瑕疵": 0.0}


def _dominant_defect(defects):
    real = [d for d in defects if d != "无明显瑕疵"]
    if not real:
        return "无明显瑕疵"
    return max(real, key=lambda d: _DEFECT_SEV.get(d, 0.2))


def _parse_date(c):
    try:
        return datetime.strptime(c.get("date", ""), "%Y-%m-%d")
    except Exception:
        return None


def _aggregate(cases):
    """多维聚合（确定性，mock/live 通用底层）。"""
    if not cases:
        return {"total_cases": 0, "total_refund": 0.0, "win_rate": 0.0,
                "avg_dispute_rate": 0.0, "outcome_dist": {},
                "sku_ranking": [], "defect_distribution": {},
                "category_heatmap": [], "supplier_scorecard": [],
                "platform_view": [], "root_cause_dist": {}, "anomaly_alerts": [],
                "sourcing_advice": [], "recommendations": ["暂无案件数据，请先提交退货取证。"],
                "report": "暂无足够案件数据生成洞察报告。"}
    total = len(cases)
    total_refund = sum(float(c.get("amount", 0) or 0) for c in cases)
    outcome_dist = Counter(c.get("outcome", "未知") for c in cases)
    wins = outcome_dist.get("赢", 0)
    win_rate = round(wins / total, 3)

    cat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "sim": 0.0,
                               "defects": Counter(), "won": 0})
    sup = defaultdict(lambda: {"cases": 0, "refund": 0.0, "defects": Counter(),
                              "won": 0, "name": "未知", "real": 0})
    plat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    sku = defaultdict(lambda: {"cases": 0, "refund": 0.0, "sim": 0.0,
                               "defects": Counter(), "won": 0, "cat": "未分类",
                               "supplier": "未知", "dates": []})
    defect_all = Counter()
    root_all = Counter()
    sim_sum = 0.0

    for c in cases:
        s = c.get("sku", "未知")
        d = sku[s]
        amt = float(c.get("amount", 0) or 0)
        sim = float(c.get("similarity", 0) or 0)
        d["cases"] += 1
        d["refund"] += amt
        d["sim"] += sim
        d["cat"] = c.get("category", d["cat"])
        d["supplier"] = c.get("supplier", d["supplier"])
        if c.get("outcome") == "赢":
            d["won"] += 1
        dt = c.get("defect_tags", []) or ["无明显瑕疵"]
        for t in dt:
            d["defects"][t] += 1
            defect_all[t] += 1
        dom = _dominant_defect(dt)
        root_all[_DEFECT_BUCKET.get(dom, "其他")] += 1
        if c.get("date"):
            d["dates"].append(c["date"])
        cc = cat[c.get("category", "未分类")]
        cc["cases"] += 1
        cc["refund"] += amt
        cc["sim"] += sim
        for t in dt:
            cc["defects"][t] += 1
        if c.get("outcome") == "赢":
            cc["won"] += 1
        ss = sup[c.get("supplier", "未知")]
        ss["cases"] += 1
        ss["refund"] += amt
        ss["name"] = c.get("supplier_name", ss["name"])
        for t in dt:
            ss["defects"][t] += 1
        if any(t != "无明显瑕疵" for t in dt):
            ss["real"] += 1
        if c.get("outcome") == "赢":
            ss["won"] += 1
        pp = plat[c.get("platform", "未知")]
        pp["cases"] += 1
        pp["refund"] += amt
        if c.get("outcome") == "赢":
            pp["won"] += 1
        sim_sum += sim

    avg_dispute = round(1 - sim_sum / total, 3) if total else 0.0

    category_heatmap = []
    for k, v in cat.items():
        top = v["defects"].most_common(1)[0][0] if v["defects"] else "-"
        category_heatmap.append({
            "category": k, "cases": v["cases"],
            "refund": round(v["refund"], 2),
            "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
            "dispute_rate": round(1 - v["sim"] / v["cases"], 3) if v["cases"] else 0,
            "top_defect": top,
        })
    category_heatmap.sort(key=lambda x: -x["refund"])

    supplier_scorecard = []
    for k, v in sup.items():
        defect_rate = round(v["real"] / v["cases"], 3) if v["cases"] else 0
        wr = round(v["won"] / v["cases"], 3) if v["cases"] else 0
        score = round(100 * (0.5 * wr + 0.5 * (1 - defect_rate)), 1)
        level = ("高风险" if score < 20 else "待改进" if score < 30
                 else "合格" if score < 38 else "优质")
        supplier_scorecard.append({
            "supplier": k, "name": v["name"], "cases": v["cases"],
            "defect_rate": defect_rate, "win_rate": wr,
            "refund": round(v["refund"], 2), "quality_score": score, "level": level,
        })
    supplier_scorecard.sort(key=lambda x: x["quality_score"])

    platform_view = []
    for k, v in plat.items():
        platform_view.append({
            "platform": k, "cases": v["cases"],
            "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
            "refund": round(v["refund"], 2),
        })
    platform_view.sort(key=lambda x: -x["cases"])

    max_date = None
    for s, v in sku.items():
        for dt in v["dates"]:
            try:
                dd = datetime.strptime(dt, "%Y-%m-%d")
                if max_date is None or dd > max_date:
                    max_date = dd
            except Exception:
                pass

    sku_ranking = []
    anomaly_alerts = []
    for s, v in sku.items():
        wr = round(v["won"] / v["cases"], 3) if v["cases"] else 0
        top = v["defects"].most_common(1)[0][0] if v["defects"] else "-"
        sku_ranking.append({
            "sku": s, "category": v["cat"], "supplier": v["supplier"],
            "cases": v["cases"], "refund": round(v["refund"], 2),
            "avg_similarity": round(v["sim"] / v["cases"], 3) if v["cases"] else 0,
            "dispute_rate": round(1 - v["sim"] / v["cases"], 3) if v["cases"] else 0,
            "win_rate": wr, "top_defect": top, "anomaly": False,
        })
        if max_date and len(v["dates"]) >= 6:
            recent = sum(1 for dt in v["dates"]
                         if (max_date - datetime.strptime(dt, "%Y-%m-%d")).days <= 30)
            prior = sum(1 for dt in v["dates"]
                        if 30 < (max_date - datetime.strptime(dt, "%Y-%m-%d")).days <= 60)
            if recent >= 4 and prior > 0 and recent >= 1.8 * prior:
                pct = round((recent - prior) / prior * 100)
                anomaly_alerts.append({
                    "sku": s, "category": v["cat"], "recent": recent,
                    "prior": prior, "pct": pct,
                    "reason": f"近30天纠纷 {recent} 笔，较前期({prior}笔)环比 +{pct}%，疑似集中爆发",
                })
                for r in sku_ranking:
                    if r["sku"] == s:
                        r["anomaly"] = True
    sku_ranking.sort(key=lambda x: -x["refund"])

    return {
        "total_cases": total,
        "total_refund": round(total_refund, 2),
        "win_rate": win_rate,
        "avg_dispute_rate": avg_dispute,
        "outcome_dist": dict(outcome_dist),
        "sku_ranking": sku_ranking,
        "defect_distribution": dict(defect_all),
        "category_heatmap": category_heatmap,
        "supplier_scorecard": supplier_scorecard,
        "platform_view": platform_view,
        "root_cause_dist": dict(root_all),
        "anomaly_alerts": anomaly_alerts,
        "sourcing_advice": [],
        "recommendations": [],
        "report": "",
    }


def _mock_attribution(agg):
    """基于结构化统计的确定性叙事归因（mock 模式，数据可溯源）。"""
    rc = agg.get("root_cause_dist", {})
    ranked = sorted(rc.items(), key=lambda x: -x[1])
    if ranked:
        top_b, top_n = ranked[0]
        total = sum(rc.values()) or 1
        pct = round(top_n / total * 100)
        root_cause = (f"退货根因以「{top_b}」为主（占 {pct}%）。"
                      + ("结合品类与供应商分布，建议优先治理该环节。" if pct >= 35
                         else "各环节分布较分散，建议综合治理包装、供应商与 listing。"))
    else:
        root_cause = "暂无足够缺陷数据用于根因归因。"

    advice = []
    blacks = [s for s in agg.get("supplier_scorecard", []) if s["quality_score"] < 50]
    if blacks:
        names = "、".join(f"{b['supplier']}({b['name']},质量分{b['quality_score']})"
                          for b in blacks[:3])
        advice.append(f"供应商红黑榜：规避高风险供应商 {names}，其退货缺陷率显著偏高。")
    bad_cats = [c for c in agg.get("category_heatmap", []) if c["win_rate"] < 0.30]
    if bad_cats:
        advice.append("选品避坑：" + "、".join(f"{c['category']}(胜诉率{c['win_rate']*100:.0f}%)"
                        for c in bad_cats) + " 纠纷胜诉率低，上新前需重点核验质量与图文一致性。")
    for b, _ in ranked[:1]:
        if b in _BUCKET_ADVICE:
            advice.append(f"根因治理（{b}）：{_BUCKET_ADVICE[b]}。")
    alerts = agg.get("anomaly_alerts", [])
    if alerts:
        advice.append(f"异常预警：{alerts[0]['sku']} 等 {len(alerts)} 个 SKU 近期纠纷集中爆发，"
                      "建议立即排查批次/物流/供应商，暂停相关推广。")

    sku_insights = []
    for r in agg.get("sku_ranking", [])[:3]:
        dom = r["top_defect"]
        bucket = _DEFECT_BUCKET.get(dom, "综合质量与履约")
        sku_insights.append({
            "sku": r["sku"],
            "finding": f"共 {r['cases']} 笔纠纷、退款约 ¥{r['refund']}，"
                       f"胜诉率 {r['win_rate']*100:.0f}%，高发问题：{dom}"
                       + ("（⚠ 近期异常）" if r.get("anomaly") else ""),
            "action": _BUCKET_ADVICE.get(bucket, "复核供应商质量与包装方案"),
        })

    report = (f"本期共沉淀 {agg['total_cases']} 笔退货案件，累计退款约 ¥{agg['total_refund']}，"
              f"综合胜诉率 {agg['win_rate']*100:.0f}%。"
              + (f"根因集中于「{ranked[0][0]}」。" if ranked else "")
              + (f"已识别 {len(agg.get('anomaly_alerts', []))} 个异常 SKU、"
                 f"{len(blacks)} 个高风险供应商。" if (agg.get('anomaly_alerts') or blacks) else "")
              + "建议将退货负面信号反哺选品与品控，从源头降低退货结构占比。")

    agg["root_cause"] = root_cause
    agg["sourcing_advice"] = advice
    agg["recommendations"] = advice
    agg["sku_insights"] = sku_insights
    agg["report"] = report
    return agg


def build_insights(cases, mode="mock"):
    """群体洞察：mock=确定性规则归因；live=接大模型做聚类/根因/建议（失败回退 mock）。"""
    agg = _aggregate(cases)
    if mode == "live":
        try:
            from models_router import build_insights_live
            llm = build_insights_live(agg)
            agg.update({
                "root_cause": llm.get("root_cause", agg.get("root_cause", "")),
                "sku_insights": llm.get("sku_insights", agg.get("sku_insights", [])),
                "recommendations": llm.get("recommendations", agg.get("recommendations", [])),
                "report": llm.get("report", agg.get("report", "")),
                "mode": "live",
            })
            return agg
        except Exception as e:  # 失败回退，保证演示不中断
            agg["mode"] = "mock(fallback)"
            agg["error"] = str(e)
    agg = _mock_attribution(agg)
    agg["mode"] = agg.get("mode", "mock")
    return agg
