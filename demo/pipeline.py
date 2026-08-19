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

工程化（大厂对标）：常量/阈值抽到 constants.py 单一来源；_aggregate 拆为单遍累加 +
各维度 builder 纯函数便于单测；回退路径记日志；公共函数补类型注解。
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
import random
import struct
import threading
import wave
from collections import Counter, defaultdict
from datetime import datetime

from constants import DEFECT_POOL, SAME_ITEM_THRESHOLD, SEVERITY

logger = logging.getLogger("returnguard.pipeline")

# 案件持久化已迁移到 db.py（SQLAlchemy 仓储层，SQLite / openGauss 双轨）。
# 这里做 re-export，保持 main.py 的 import 路径不变。
from db import get_generation, load_cases, save_case  # noqa: E402, F401

# 洞察聚合缓存：按 (mode, source, 案件集合指纹, 代际) 缓存，save_case 时代际自增即失效。
# 说明：缓存为进程内、单 worker 场景（demo 默认）；uvicorn 线程池并发下用 _ins_lock 保证线程安全；
# 多 worker（多进程）部署仍需 Redis 等共享缓存（跨进程不可共享本进程 dict）。
_ins_cache: dict = {}
_ins_lock = threading.Lock()


def invalidate_insights_cache() -> None:
    """使洞察聚合缓存失效（由 db.save_case / delete_case 在写库后调用）。"""
    with _ins_lock:
        _ins_cache.clear()

# ---- 缺陷词表/严重程度已迁至 constants.py（见文件头说明），此处仅保留业务映射 ----


# ===================== 工具函数 =====================
def _hash_seed(*paths) -> int:
    """用文件名生成稳定随机种子（mock 模式专用），保证同一张图每次结果一致、可复现。"""
    h = hashlib.md5("|".join(str(p) for p in paths).encode("utf-8")).hexdigest()
    return int(h, 16)


def _mock_similarity(returned_path: str, product_path: str) -> float:
    """mock 相似度：由两张图文件名算出的确定性值（0.55~0.98），仅用于免 Key 演示。
    注意：这不是模型真实能力，真实相似度在 live 模式由图向量余弦得到。"""
    s = _hash_seed(returned_path, product_path)
    return round(0.55 + (s % 1000) / 1000 * 0.43, 3)


def _gen_wav(text: str, sr: int = 16000, dur: float = 1.2) -> str:
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
def _mock(
    returned_path: str, product_path: str, listing_text: str, sku: str, amount: float
) -> dict:
    """mock 模式的单案取证：用确定性规则模拟一单结果（无需模型）。
    字段含义与 live 模式一致，便于前端/洞察层无缝切换。"""
    sim = _mock_similarity(returned_path, product_path)
    # 用文件名种子决定瑕疵数量与种类（确定性）
    random.seed(_hash_seed(returned_path))
    n_def = random.randint(0, 3)
    defects = random.sample(DEFECT_POOL, n_def) if n_def > 0 else ["无明显瑕疵"]
    same = sim >= SAME_ITEM_THRESHOLD  # 阈值：≥阈值 视为同一件商品

    # 功能③ 一致性判断：同款且无瑕疵→倾向于买家责任；否则存在货不对板/质量瑕疵
    if same and defects == ["无明显瑕疵"]:
        consistency = "一致（疑似非质量原因，倾向买家责任）"
    else:
        consistency = "存在差异（货不对板 / 运输或质量瑕疵）"

    # 功能⑤ 优先级评分：相似度越低、缺陷越重、金额越高 → 越该先处理
    sev_score = max([SEVERITY.get(d, 0.2) for d in defects])
    priority = round(
        min(1.0, 0.4 + (1 - sim) * 0.3 + sev_score * 0.3 + (0.2 if amount > 50 else 0)), 3
    )

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
    defect_boxes: list[dict] = []
    rng = random.Random(_hash_seed(returned_path, "boxes"))
    for d in defects:
        if d == "无明显瑕疵":
            continue
        bx = round(rng.random() * 0.6, 3)
        by = round(rng.random() * 0.55, 3)
        bw = round(0.20 + rng.random() * 0.22, 3)
        bh = round(0.20 + rng.random() * 0.22, 3)
        # 示意置信度（确定性，0.75~0.98）：让红框更接近真实检测的呈现；
        # 仅作演示，不替代真实视觉模型的检测分数（P1-3 仍走 esc 防 XSS）
        conf = round(0.75 + rng.random() * 0.23, 2)
        defect_boxes.append({"label": d, "x": bx, "y": by, "w": bw, "h": bh, "confidence": conf})

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


def analyze_case(
    returned_path: str,
    product_path: str,
    listing_text: str,
    sku: str,
    amount: float,
    mode: str = "mock",
) -> dict:
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
            logger.exception("live 取证失败，回退 mock: %s", e)
            res = _mock(returned_path, product_path, listing_text, sku, amount)
            res["mode"] = "mock(fallback)"
            res["error"] = str(e)
            return res
    return _mock(returned_path, product_path, listing_text, sku, amount)


# ===================== 案件持久化（数据沉淀）=====================
# 持久化已迁移到 db.py（SQLAlchemy 仓储层，SQLite / openGauss 双轨）。
# 这里只做 re-export，保持 main.py 的 import 路径不变。

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

# 地区退货物流成本占比（估算用，单一来源）：退货成本 = 退款 + 物流；物流按宏观地区粗略比例估算
# 注意：demo 种子用国家码（US/UK/DE/…），real 种子用中文宏观地区（北美/欧洲/东南亚），
# 二者口径不一；_region_bucket 统一归一到宏观地区，保证 region_view / 物流成本跨源一致。
_REGION_SHIP_RATIO = {
    "北美": 0.16, "欧洲": 0.18, "南美": 0.15, "东亚": 0.13,
    "东南亚": 0.12, "大洋洲": 0.17, "": 0.14, "未知": 0.14, "其他": 0.14,
}
# 国家代码 → 宏观销售地区（仅兜底映射；已是中文宏观地区则透传）
_REGION_MAP = {
    "US": "北美", "CA": "北美", "MX": "北美",
    "UK": "欧洲", "DE": "欧洲", "FR": "欧洲", "ES": "欧洲", "IT": "欧洲",
    "RU": "欧洲", "NL": "欧洲", "SE": "欧洲", "PL": "欧洲", "PT": "欧洲",
    "BR": "南美", "AR": "南美", "CL": "南美",
    "JP": "东亚", "KR": "东亚", "CN": "东亚",
    "SG": "东南亚", "MY": "东南亚", "TH": "东南亚", "VN": "东南亚",
    "ID": "东南亚", "PH": "东南亚",
    "AU": "大洋洲", "NZ": "大洋洲",
}


def _region_bucket(code: str | None) -> str:
    """归一化地区口径：已是中文宏观地区（北美/欧洲/…）直接沿用；国家码映射为宏观地区；其余归「其他」。"""
    if not code:
        return ""
    if code in _REGION_SHIP_RATIO:  # 已是宏观地区名
        return code
    return _REGION_MAP.get(code, "其他")


def _dominant_defect(defects) -> str:
    """取一笔案件的主缺陷（忽略「无明显瑕疵」），用于根因归因。"""
    real = [d for d in defects if d != "无明显瑕疵"]
    if not real:
        return "无明显瑕疵"
    return max(real, key=lambda d: SEVERITY.get(d, 0.2))


def _parse_date(c: dict):
    try:
        return datetime.strptime(c.get("date", ""), "%Y-%m-%d")
    except Exception:
        return None


def _season_of(date_str: str | None) -> str:
    """由案件日期推导季节（12-2 冬 / 3-5 春 / 6-8 夏 / 9-11 秋）；无日期返回空串。"""
    if not date_str:
        return ""
    try:
        m = datetime.strptime(date_str, "%Y-%m-%d").month
    except Exception:
        return ""
    if m in (3, 4, 5):
        return "春"
    if m in (6, 7, 8):
        return "夏"
    if m in (9, 10, 11):
        return "秋"
    return "冬"


# ---- 各维度 builder：输入累加器，输出看板列表（纯函数，便于单测）----
def _build_category_heatmap(cat: dict) -> list[dict]:
    out: list[dict] = []
    for k, v in cat.items():
        top = v["defects"].most_common(1)[0][0] if v["defects"] else "-"
        out.append(
            {
                "category": k,
                "cases": v["cases"],
                "refund": round(v["refund"], 2),
                "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
                "dispute_rate": round(1 - v["sim"] / v["cases"], 3) if v["cases"] else 0,
                "top_defect": top,
            }
        )
    out.sort(key=lambda x: -x["refund"])
    return out


def _build_supplier_scorecard(sup: dict) -> list[dict]:
    out: list[dict] = []
    for k, v in sup.items():
        if not k or k == "未知":  # 跳过缺失/未知供应商，避免污染红黑榜可读性
            continue
        defect_rate = round(v["real"] / v["cases"], 3) if v["cases"] else 0
        wr = round(v["won"] / v["cases"], 3) if v["cases"] else 0
        score = round(100 * (0.5 * wr + 0.5 * (1 - defect_rate)), 1)
        level = (
            "高风险" if score < 20 else "待改进" if score < 30 else "合格" if score < 38 else "优质"
        )
        # 缺陷构成：剔除"无明显瑕疵"占位，保留真实缺陷分布（前端画构成条）
        defect_dist = {
            dk: dv for dk, dv in v["defects"].items() if dk != "无明显瑕疵"
        }
        out.append(
            {
                "supplier": k,
                "name": v["name"],
                "cases": v["cases"],
                "defect_rate": defect_rate,
                "win_rate": wr,
                "refund": round(v["refund"], 2),
                "avg_refund": round(v["refund"] / v["cases"], 2) if v["cases"] else 0,
                "sku_count": len(v["skus"]),
                "platform_count": len(v["platforms"]),
                "avg_similarity": round(v["sim"] / v["cases"], 3) if v["cases"] else 0,
                "defect_dist": defect_dist,
                "quality_score": score,
                "level": level,
            }
        )
    out.sort(key=lambda x: x["quality_score"])
    return out


def _build_platform_view(plat: dict) -> list[dict]:
    out: list[dict] = []
    for k, v in plat.items():
        out.append(
            {
                "platform": k,
                "cases": v["cases"],
                "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
                "refund": round(v["refund"], 2),
            }
        )
    out.sort(key=lambda x: -x["cases"])
    return out


def _build_matrix(matrix: dict) -> list[dict]:
    out: list[dict] = []
    for p, sup_map in matrix.items():
        for s, v in sup_map.items():
            if not s or s == "未知":
                continue
            out.append(
                {
                    "platform": p,
                    "supplier": s,
                    "cases": v["cases"],
                    "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
                    "refund": round(v["refund"], 2),
                }
            )
    return out


def _build_region_view(region: dict) -> list[dict]:
    """地区维度聚合（方向2 维度扩展）：按销售地区统计纠纷量、退款、胜诉率。"""
    out: list[dict] = []
    for k, v in region.items():
        out.append(
            {
                "region": k,
                "cases": v["cases"],
                "refund": round(v["refund"], 2),
                "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
            }
        )
    out.sort(key=lambda x: -x["cases"])
    return out


def _build_season_view(season: dict) -> list[dict]:
    """季节维度聚合（方向2 维度扩展）：按季节统计纠纷量、退款、胜诉率。"""
    order = {"春": 0, "夏": 1, "秋": 2, "冬": 3}
    out: list[dict] = []
    for k, v in season.items():
        out.append(
            {
                "season": k,
                "cases": v["cases"],
                "refund": round(v["refund"], 2),
                "win_rate": round(v["won"] / v["cases"], 3) if v["cases"] else 0,
            }
        )
    out.sort(key=lambda x: order.get(x["season"], 9))
    return out


def _build_sku_ranking(sku: dict, max_date) -> tuple[list[dict], list[dict]]:
    ranking: list[dict] = []
    alerts: list[dict] = []
    for s, v in sku.items():
        wr = round(v["won"] / v["cases"], 3) if v["cases"] else 0
        top = v["defects"].most_common(1)[0][0] if v["defects"] else "-"
        ranking.append(
            {
                "sku": s,
                "category": v["cat"],
                "supplier": v["supplier"],
                "cases": v["cases"],
                "refund": round(v["refund"], 2),
                "avg_similarity": round(v["sim"] / v["cases"], 3) if v["cases"] else 0,
                "dispute_rate": round(1 - v["sim"] / v["cases"], 3) if v["cases"] else 0,
                "win_rate": wr,
                "top_defect": top,
                "anomaly": False,
            }
        )
        # 异常判定：案件≥6 笔且近30天数量≥前期的1.8倍，视为集中爆发
        if max_date and len(v["dates"]) >= 6:
            recent = sum(
                1 for dt in v["dates"] if (max_date - datetime.strptime(dt, "%Y-%m-%d")).days <= 30
            )
            prior = sum(
                1
                for dt in v["dates"]
                if 30 < (max_date - datetime.strptime(dt, "%Y-%m-%d")).days <= 60
            )
            if recent >= 4 and prior > 0 and recent >= 1.8 * prior:
                pct = round((recent - prior) / prior * 100)
                alerts.append(
                    {
                        "sku": s,
                        "category": v["cat"],
                        "recent": recent,
                        "prior": prior,
                        "pct": pct,
                        "reason": f"近30天纠纷 {recent} 笔，较前期({prior}笔)环比 +{pct}%，疑似集中爆发",
                    }
                )
                for r in ranking:
                    if r["sku"] == s:
                        r["anomaly"] = True
    ranking.sort(key=lambda x: -x["refund"])
    return ranking, alerts


def _empty_aggregate() -> dict:
    return {
        "total_cases": 0,
        "total_refund": 0.0,
        "win_rate": 0.0,
        "avg_dispute_rate": 0.0,
        "outcome_dist": {},
        "sku_ranking": [],
        "defect_distribution": {},
        "category_heatmap": [],
        "supplier_scorecard": [],
        "platform_view": [],
        "root_cause_dist": {},
        "anomaly_alerts": [],
        "sourcing_advice": [],
        "recommendations": ["暂无案件数据，请先提交退货取证。"],
        "report": "暂无足够案件数据生成洞察报告。",
    }


def _aggregate(cases: list[dict]) -> dict:
    """多维聚合（确定性，mock/live 通用底层）：把案件库汇总成可洞察的指标。
    输出涵盖：KPI、品类热力、缺陷分布、根因分布、供应商质量分、平台胜诉、SKU 预警等。

    实现：先单遍累加各维度计数器，再交由各 builder 纯函数产出看板列表（便于单测）。"""
    if not cases:
        return _empty_aggregate()

    total = len(cases)
    total_refund = sum(float(c.get("amount", 0) or 0) for c in cases)
    # outcome 分布：已判定案件按真实结果，未判定（单案上传、无法判定输赢）单独归入「待分析」，
    # 不混入「未知」噪声桶；胜诉率只按已判定案件计算，避免上传单案稀释 KPI。
    outcome_dist = Counter()
    for c in cases:
        oc = c.get("outcome")
        outcome_dist[oc if oc in ("赢", "部分退款", "输") else "待分析"] += 1
    wins = outcome_dist.get("赢", 0)
    decided = total - outcome_dist.get("待分析", 0)
    win_rate = round(wins / decided, 3) if decided else 0.0

    # 三个维度的累加器：品类 / 供应商 / 平台
    cat = defaultdict(
        lambda: {"cases": 0, "refund": 0.0, "sim": 0.0, "defects": Counter(), "won": 0}
    )
    sup = defaultdict(
        lambda: {
            "cases": 0,
            "refund": 0.0,
            "defects": Counter(),
            "won": 0,
            "name": "未知",
            "real": 0,
            "skus": set(),
            "platforms": set(),
            "sim": 0.0,
        }
    )
    plat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    # 平台 × 供应商 交叉累加器（供应商维度扩展：跨平台横向对比供货方质量）
    matrix = defaultdict(lambda: defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0}))
    # SKU 维度（含日期，用于近期异常预警）
    sku = defaultdict(
        lambda: {
            "cases": 0,
            "refund": 0.0,
            "sim": 0.0,
            "defects": Counter(),
            "won": 0,
            "cat": "未分类",
            "supplier": "未知",
            "dates": [],
        }
    )
    defect_all = Counter()
    root_all = Counter()
    # 全量相似度累加（每案都计），用于代理争议率分母，避免只统计"有平台"案件导致虚高
    sim_all = 0.0
    # 地区 / 季节 维度累加器（方向2 维度扩展）
    region = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    season = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    # 退货成本估算累加：物流成本按地区比例粗略估算（退款 + 物流 = 退货总成本）
    logistics_all = 0.0

    for c in cases:
        s = c.get("sku", "未知")
        d = sku[s]
        amt = float(c.get("amount", 0) or 0)
        sim = float(c.get("similarity", 0) or 0)
        sim_all += sim
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

        # 品类维度：缺失品类的单案（如上传时未选）不计入「未分类」噪声桶
        cat_val = c.get("category")
        if cat_val:
            cc = cat[cat_val]
            cc["cases"] += 1
            cc["refund"] += amt
            cc["sim"] += sim
            for t in dt:
                cc["defects"][t] += 1
            if c.get("outcome") == "赢":
                cc["won"] += 1

        # 供应商维度（real=含真实缺陷的案件数，用于缺陷率）：缺失/未知供应商不污染红黑榜
        sup_val = c.get("supplier")
        if sup_val and sup_val != "未知":
            ss = sup[sup_val]
            ss["cases"] += 1
            ss["refund"] += amt
            ss["name"] = c.get("supplier_name", ss["name"])
            ss["skus"].add(c.get("sku", "未知"))
            ss["platforms"].add(c.get("platform", "未知"))
            ss["sim"] += sim
            for t in dt:
                ss["defects"][t] += 1
            if any(t != "无明显瑕疵" for t in dt):
                ss["real"] += 1
            if c.get("outcome") == "赢":
                ss["won"] += 1

        # 平台维度：缺失/未知平台不污染平台对比
        plat_val = c.get("platform")
        if plat_val and plat_val != "未知":
            pp = plat[plat_val]
            pp["cases"] += 1
            pp["refund"] += amt
            if c.get("outcome") == "赢":
                pp["won"] += 1

        # 平台 × 供应商 交叉：两端都需有效才入交叉矩阵
        p_val = c.get("platform")
        s_val = c.get("supplier")
        if p_val and p_val != "未知" and s_val and s_val != "未知":
            mm = matrix[p_val][s_val]
            mm["cases"] += 1
            mm["refund"] += amt
            if c.get("outcome") == "赢":
                mm["won"] += 1

        # 地区维度（方向2 维度扩展）：归一化宏观地区，缺失/未知/其他不污染地区对比
        reg_val = _region_bucket(c.get("region"))
        if reg_val and reg_val not in ("未知", "其他"):
            rr = region[reg_val]
            rr["cases"] += 1
            rr["refund"] += amt
            if c.get("outcome") == "赢":
                rr["won"] += 1
        # 季节维度（由日期推导）
        seas_val = _season_of(c.get("date"))
        if seas_val:
            ss = season[seas_val]
            ss["cases"] += 1
            ss["refund"] += amt
            if c.get("outcome") == "赢":
                ss["won"] += 1
        # 退货成本估算：物流成本按归一化宏观地区比例累加（退款 + 物流 = 总成本）
        logistics_all += amt * _REGION_SHIP_RATIO.get(_region_bucket(c.get("region")) or "", 0.14)

    # 代理指标（非平台真实争议笔数）：以"退货图与本店主图的相似度"推得。
    # avg_dispute = 1 - 平均相似度，越接近 1 表示"货不对板/调包"嫌疑越强。
    # 前端务必标注为代理指标，不可当作平台标记的争议率。
    avg_dispute = round(1 - sim_all / total, 3) if total else 0.0
    dispute_rate_note = (
        "代理指标：由退货图与本店主图的平均相似度（1−相似度）推算，"
        "反映'货不对板/调包'嫌疑强度，并非平台标记的争议笔数。"
    )

    # 最近日期（用于 SKU 近期异常预警）
    max_date = None
    for _s, v in sku.items():
        for dt in v["dates"]:
            try:
                dd = datetime.strptime(dt, "%Y-%m-%d")
                if max_date is None or dd > max_date:
                    max_date = dd
            except Exception:
                pass

    sku_ranking, anomaly_alerts = _build_sku_ranking(sku, max_date)

    # 供应商红黑榜 + 黑名单自动生成（方向2）：质量分<50 自动入黑名单，带可解释理由
    supplier_scorecard = _build_supplier_scorecard(sup)
    pct_local = lambda x: f"{round(x * 100)}%"
    supplier_blacklist = [
        {
            "supplier": s["supplier"],
            "name": s["name"],
            "quality_score": s["quality_score"],
            "level": s["level"],
            "defect_rate": s["defect_rate"],
            "win_rate": s["win_rate"],
            "reason": f"质量分 {s['quality_score']}（{s['level']}）：缺陷率 {pct_local(s['defect_rate'])}、"
                      f"维权胜诉率 {pct_local(s['win_rate'])}",
        }
        for s in supplier_scorecard
        if s["quality_score"] < 50
    ]

    # 退货成本估算：物流成本（按地区比例）+ 退款 = 退货总成本
    logistics_cost = round(logistics_all, 2)
    total_return_cost = round(total_refund + logistics_cost, 2)

    return {
        "total_cases": total,
        "total_refund": round(total_refund, 2),
        "win_rate": win_rate,
        "avg_dispute_rate": avg_dispute,
        "dispute_rate_note": dispute_rate_note,
        "outcome_dist": dict(outcome_dist),
        "sku_ranking": sku_ranking,
        "defect_distribution": dict(defect_all),
        "category_heatmap": _build_category_heatmap(cat),
        "supplier_scorecard": supplier_scorecard,
        "platform_view": _build_platform_view(plat),
        "platform_supplier_matrix": _build_matrix(matrix),
        "root_cause_dist": dict(root_all),
        "anomaly_alerts": anomaly_alerts,
        # 方向2 维度扩展：地区/季节交叉 + 退货成本 + 供应商黑名单
        "region_view": _build_region_view(region),
        "season_view": _build_season_view(season),
        "supplier_blacklist": supplier_blacklist,
        "logistics_cost": logistics_cost,
        "total_return_cost": total_return_cost,
        "sourcing_advice": [],
        "recommendations": [],
        "report": "",
    }


def _mock_attribution(agg: dict) -> dict:
    """基于结构化统计的确定性叙事归因（mock 模式，数据可溯源，无需模型）。
    生成：根因结论、供应商红黑榜提示、选品避坑建议、SKU 整改、洞察报告正文。"""
    rc = agg.get("root_cause_dist", {})
    ranked = sorted(rc.items(), key=lambda x: -x[1])
    if ranked:
        top_b, top_n = ranked[0]
        total = sum(rc.values()) or 1
        pct = round(top_n / total * 100)
        root_cause = f"退货根因以「{top_b}」为主（占 {pct}%）。" + (
            "结合品类与供应商分布，建议优先治理该环节。"
            if pct >= 35
            else "各环节分布较分散，建议综合治理包装、供应商与 listing。"
        )
    else:
        root_cause = "暂无足够缺陷数据用于根因归因。"

    advice: list[str] = []
    blacks = agg.get("supplier_blacklist", [])
    if blacks:
        names = "、".join(
            f"{b['supplier']}({b['name']},质量分{b['quality_score']})" for b in blacks[:3]
        )
        advice.append(f"供应商红黑榜：规避高风险供应商 {names}，其退货缺陷率显著偏高。")
    bad_cats = [c for c in agg.get("category_heatmap", []) if c["win_rate"] < 0.30]
    if bad_cats:
        advice.append(
            "选品避坑："
            + "、".join(f"{c['category']}(胜诉率{c['win_rate'] * 100:.0f}%)" for c in bad_cats)
            + " 纠纷胜诉率低，上新前需重点核验质量与图文一致性。"
        )
    for b, _ in ranked[:1]:
        if b in _BUCKET_ADVICE:
            advice.append(f"根因治理（{b}）：{_BUCKET_ADVICE[b]}。")
    alerts = agg.get("anomaly_alerts", [])
    if alerts:
        advice.append(
            f"异常预警：{alerts[0]['sku']} 等 {len(alerts)} 个 SKU 近期纠纷集中爆发，"
            "建议立即排查批次/物流/供应商，暂停相关推广。"
        )

    sku_insights: list[dict] = []
    for r in agg.get("sku_ranking", [])[:3]:
        dom = r["top_defect"]
        bucket = _DEFECT_BUCKET.get(dom, "综合质量与履约")
        sku_insights.append(
            {
                "sku": r["sku"],
                "finding": f"共 {r['cases']} 笔纠纷、退款约 ¥{r['refund']}，"
                f"胜诉率 {r['win_rate'] * 100:.0f}%，高发问题：{dom}"
                + ("（⚠ 近期异常）" if r.get("anomaly") else ""),
                "action": _BUCKET_ADVICE.get(bucket, "复核供应商质量与包装方案"),
            }
        )

    report = (
        f"本期共沉淀 {agg['total_cases']} 笔退货案件，累计退款约 ¥{agg['total_refund']}，"
        f"综合胜诉率 {agg['win_rate'] * 100:.0f}%，"
        f"预估退货总成本约 ¥{agg.get('total_return_cost', agg['total_refund'])}"
        f"（含物流 ¥{agg.get('logistics_cost', 0)}）。"
        + (f"根因集中于「{ranked[0][0]}」。" if ranked else "")
        + (
            f"已识别 {len(agg.get('anomaly_alerts', []))} 个异常 SKU、"
            f"{len(blacks)} 个高风险供应商。"
            if (agg.get("anomaly_alerts") or blacks)
            else ""
        )
        + "建议将退货负面信号反哺选品与品控，从源头降低退货结构占比。"
    )

    agg["root_cause"] = root_cause
    agg["sourcing_advice"] = advice
    # 避免空数据下 recommendations 被覆盖成空列表（回归保护）：有建议才覆盖，否则保留默认提示
    agg["recommendations"] = (
        advice if advice else agg.get("recommendations", ["暂无足够案件数据生成洞察建议。"])
    )
    agg["sku_insights"] = sku_insights
    agg["report"] = report
    return agg


def build_insights(cases: list[dict], mode: str = "mock", source: str = "demo") -> dict:
    """阶段B 统一入口：群体洞察（功能⑥）。
    - mock：确定性规则归因，结果可复现，适合录屏演示。
    - live：调用 models_router.build_insights_live 做 LLM 聚类/归因/建议；失败回退 mock。

    缓存：按 (mode, source, 案件集合指纹, 代际) 缓存聚合结果，save_case 时对应 source
    代际自增即失效，避免每次 /api/insights 都全量重算（P2-5）。空数据提前返回，避免
    recommendations 回归（P3-1）。source 用于隔离 demo/real 两源的缓存，互不串扰。

    注意：调用方会在外部按 category/platform 预过滤 cases，若仅以 len(cases) 作缓存键，
    不同筛选命中相同条数会冲突（复现：A 5笔 / B 5笔 返回同一结果）。故键必须唯一标识
    "被聚合的那一批案件"——用案件 id 集合指纹（配合代际防陈旧），确保下钻结果互不污染。
    """
    # 案件 id 指纹（缺失 id 归一为 "" 以避免 None 不可排序）；唯一标识被聚合批次
    sig = hash(tuple(sorted((c.get("case_id") or "") for c in cases)))
    key = (mode, source, sig, get_generation(source))
    with _ins_lock:
        if key in _ins_cache:
            return _ins_cache[key]
    agg = _aggregate(cases)
    if not cases:
        with _ins_lock:
            _ins_cache[key] = agg
        return agg
    if mode == "live":
        try:
            from models_router import build_insights_live

            llm = build_insights_live(agg)
            agg.update(
                {
                    "root_cause": llm.get("root_cause", agg.get("root_cause", "")),
                    "sku_insights": llm.get("sku_insights", agg.get("sku_insights", [])),
                    "recommendations": llm.get("recommendations", agg.get("recommendations", [])),
                    "report": llm.get("report", agg.get("report", "")),
                    "mode": "live",
                }
            )
        except Exception as e:  # 失败回退，保证演示不中断
            logger.exception("live 洞察失败，回退 mock: %s", e)
            agg["mode"] = "mock(fallback)"
            agg["error"] = str(e)
            agg = _mock_attribution(agg)  # 仅 live 失败回退时才用 mock 归因（避免覆盖 LLM 结果）
    else:
        agg = _mock_attribution(agg)  # mock 模式：确定性规则归因
    agg["mode"] = agg.get("mode", "mock")
    with _ins_lock:
        _ins_cache[key] = agg
    return agg
