"""ReturnGuard · 取证 + 洞察流水线（pipeline.py）

本文件是整个产品的「业务逻辑层」，分两大阶段，对应方案文档的 6 大功能：

【阶段A · 个案举证】—— 把每一笔退货变成结构化证据（数据采集管道）
    功能① 同款一致性比对  → analyze_case：相似度（live 走模型路由，mock 走确定性哈希）
    功能② 瑕疵视觉识别    → analyze_case：瑕疵标签
    功能③ listing 承诺核验 → analyze_case：货不对板一致性判断
    功能④ 证据卷宗+语音   → analyze_case：生成举证报告 + 母语语音 + 关键帧说明
    功能⑤ 案件优先级排序  → analyze_case：priority_score（live 可用 rerank 重排）

【阶段B · 群体洞察】—— 沉淀后的案件反哺选品/品控（这是 AI 市场洞察赛道的核心交付物）
    功能⑥ 退货群体洞察    → build_insights：多维聚合 + 根因归因 + 供应商红黑榜 + 异常预警 + 选品建议

双模式设计：
    - mock 模式：不依赖任何 Key，用确定性规则/合成数据，立即可演示，结果可复现。
    - live 模式：调用 models_router 走真实模型；失败时自动回退 mock，保证演示不中断。
"""

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

# ---- 缺陷词表（与方案功能②对齐）----
DEFECT_POOL = ["外包装破损", "商品缺件", "污渍划痕", "使用痕迹", "功能故障", "货不对板", "色差明显"]
# 各缺陷的严重程度权重（用于优先级评分与排序，0~1）
SEVERITY = {"外包装破损": 0.3, "商品缺件": 0.5, "污渍划痕": 0.2, "使用痕迹": 0.6,
            "功能故障": 0.8, "货不对板": 0.7, "色差明显": 0.3, "无明显瑕疵": 0.0}


# ===================== 工具函数 =====================
def _hash_seed(*paths):
    """用文件名生成稳定随机种子（mock 模式专用），保证同一张图每次结果一致、可复现。"""
    h = hashlib.md5("|".join(str(p) for p in paths).encode("utf-8")).hexdigest()
    return int(h, 16)


def _mock_similarity(returned_path, product_path):
    """mock 相似度：由两张图文件名算出的确定性值（0.55~0.98），仅用于免 Key 演示。
    注意：这不是模型真实能力，真实相似度在 live 模式由图向量余弦得到。"""
    s = _hash_seed(returned_path, product_path)
    return round(0.55 + (s % 1000) / 1000 * 0.43, 3)


def _gen_wav(text, sr=16000, dur=1.2):
    """生成一段占位 WAV（正弦音），mock 模式下充当 TTS 产物。
    真实语音由 models_router.tts 生成；此处仅保证前端有可播放音频。"""
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


# ===================== 阶段A · 个案举证（功能①②③④⑤）=====================
def _mock(returned_path, product_path, listing_text, sku, amount):
    """mock 模式的单案取证：用确定性规则模拟一单结果（无需模型）。
    字段含义与 live 模式一致，便于前端/洞察层无缝切换。"""
    sim = _mock_similarity(returned_path, product_path)
    # 用文件名种子决定瑕疵数量与种类（确定性）
    random.seed(_hash_seed(returned_path))
    n_def = random.randint(0, 3)
    defects = random.sample(DEFECT_POOL, n_def) if n_def > 0 else ["无明显瑕疵"]
    same = sim >= 0.82  # 阈值：≥0.82 视为同一件商品

    # 功能③ 一致性判断：同款且无瑕疵→倾向于买家责任；否则存在货不对板/质量瑕疵
    if same and defects == ["无明显瑕疵"]:
        consistency = "一致（疑似非质量原因，倾向买家责任）"
    else:
        consistency = "存在差异（货不对板 / 运输或质量瑕疵）"

    # 功能⑤ 优先级评分：相似度越低、缺陷越重、金额越高 → 越该先处理
    sev_score = max([SEVERITY.get(d, 0.2) for d in defects])
    priority = round(min(1.0, 0.4 + (1 - sim) * 0.3 + sev_score * 0.3 + (0.2 if amount > 50 else 0)), 3)

    # 功能④ 举证卷宗 + 母语陈述（mock 文本）
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
    # 缺陷区域示意框（mock 确定性占位；live 接通后由视觉模型返回真实 bbox）
    # 归一化坐标(0~1)，前端按比例绘制红框；演示数据仅作"示意"，不替代真实检测。
    defect_boxes = []
    rng = random.Random(_hash_seed(returned_path, "boxes"))
    for d in defects:
        if d == "无明显瑕疵":
            continue
        bx = round(rng.random() * 0.6, 3)
        by = round(rng.random() * 0.55, 3)
        bw = round(0.20 + rng.random() * 0.22, 3)
        bh = round(0.20 + rng.random() * 0.22, 3)
        defect_boxes.append({"label": d, "x": bx, "y": by, "w": bw, "h": bh})

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
        "defect_boxes": defect_boxes,
        "mode": "mock",
    }


def analyze_case(returned_path, product_path, listing_text, sku, amount, mode="mock"):
    """阶段A 统一入口：对一笔退货做取证，返回结构化结果（功能①②③④⑤）。
    - mode="mock"：确定性规则，免 Key 立即可演示。
    - mode="live"：调用 models_router.live_analyze 走真实模型；任何异常都回退 mock 并标注，
      确保现场演示不会因网络/额度问题而卡死。
    """
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


# ===================== 案件持久化（数据沉淀）=====================
# 持久化已迁移到 db.py（SQLAlchemy 仓储层，SQLite / openGauss 双轨）。
# 这里只做 re-export，保持 main.py 的 import 路径不变。
from db import load_cases, save_case


# ===================== 阶段B · 群体洞察（功能⑥）=====================
# 缺陷类型 → 根因桶（用于归因与整改建议，对应方案「根因归因」）
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
_DEFECT_SEV = SEVERITY  # 复用严重程度权重


def _dominant_defect(defects):
    """取一笔案件的主缺陷（忽略「无明显瑕疵」），用于根因归因。"""
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
    """多维聚合（确定性，mock/live 通用底层）：把案件库汇总成可洞察的指标。
    输出涵盖：KPI、品类热力、缺陷分布、根因分布、供应商质量分、平台胜诉、SKU 预警等。"""
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

    # 三个维度的累加器：品类 / 供应商 / 平台
    cat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "sim": 0.0,
                               "defects": Counter(), "won": 0})
    sup = defaultdict(lambda: {"cases": 0, "refund": 0.0, "defects": Counter(),
                              "won": 0, "name": "未知", "real": 0})
    plat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    # 平台 × 供应商 交叉累加器（供应商维度扩展：跨平台横向对比供货方质量）
    matrix = defaultdict(lambda: defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0}))
    # SKU 维度（含日期，用于近期异常预警）
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
        # 主缺陷归入根因桶，用于根因分布
        dom = _dominant_defect(dt)
        root_all[_DEFECT_BUCKET.get(dom, "其他")] += 1
        if c.get("date"):
            d["dates"].append(c["date"])

        # 品类维度
        cc = cat[c.get("category", "未分类")]
        cc["cases"] += 1
        cc["refund"] += amt
        cc["sim"] += sim
        for t in dt:
            cc["defects"][t] += 1
        if c.get("outcome") == "赢":
            cc["won"] += 1

        # 供应商维度（real=含真实缺陷的案件数，用于缺陷率）
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

        # 平台维度
        pp = plat[c.get("platform", "未知")]
        pp["cases"] += 1
        pp["refund"] += amt
        if c.get("outcome") == "赢":
            pp["won"] += 1
        sim_sum += sim

        # 平台 × 供应商 交叉
        mm = matrix[c.get("platform", "未知")][c.get("supplier", "未知")]
        mm["cases"] += 1
        mm["refund"] += amt
        if c.get("outcome") == "赢":
            mm["won"] += 1

    avg_dispute = round(1 - sim_sum / total, 3) if total else 0.0

    # —— ① 品类退货热力 ——
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

    # —— ③ 供应商红黑榜（质量分）——
    # 质量分 = 100 × (0.5×胜诉率 + 0.5×(1−有真实缺陷案件占比))
    # 注：跳过"未知"供应商——没记录供货方无从"换供"，且会污染红黑榜可读性。
    supplier_scorecard = []
    for k, v in sup.items():
        if not k or k == "未知":   # 跳过缺失/未知供应商，避免污染红黑榜可读性
            continue
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

    # —— ④ 平台胜诉对比 ——
    platform_view = []
    for k, v in plat.items():
        platform_view.append({
            "platform": k, "cases": v["cases"],
            "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
            "refund": round(v["refund"], 2),
        })
    platform_view.sort(key=lambda x: -x["cases"])

    # 最近日期（用于 SKU 近期异常预警）
    max_date = None
    for s, v in sku.items():
        for dt in v["dates"]:
            try:
                dd = datetime.strptime(dt, "%Y-%m-%d")
                if max_date is None or dd > max_date:
                    max_date = dd
            except Exception:
                pass

    # —— ⑥ SKU 纠纷明细 + ⑤ 异常预警（近30天环比）——
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
        # 异常判定：案件≥6 笔且近30天数量≥前期的1.8倍，视为集中爆发
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

    # —— 平台 × 供应商 交叉视图 ——
    platform_supplier_matrix = []
    for p, sup_map in matrix.items():
        for s, v in sup_map.items():
            if not s or s == "未知":
                continue
            platform_supplier_matrix.append({
                "platform": p, "supplier": s, "cases": v["cases"],
                "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
                "refund": round(v["refund"], 2),
            })

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
        "platform_supplier_matrix": platform_supplier_matrix,
        "root_cause_dist": dict(root_all),
        "anomaly_alerts": anomaly_alerts,
        "sourcing_advice": [],
        "recommendations": [],
        "report": "",
    }


def _mock_attribution(agg):
    """基于结构化统计的确定性叙事归因（mock 模式，数据可溯源，无需模型）。
    生成：根因结论、供应商红黑榜提示、选品避坑建议、SKU 整改、洞察报告正文。"""
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
    """阶段B 统一入口：群体洞察（功能⑥）。
    - mock：确定性规则归因，结果可复现，适合录屏演示。
    - live：调用 models_router.build_insights_live 做 LLM 聚类/归因/建议；失败回退 mock。
    兼容键：total_cases / sku_ranking / defect_distribution 始终保留，前端无需分支。"""
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
