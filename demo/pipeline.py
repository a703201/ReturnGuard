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
import wave
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

from calibration import get_active_threshold
from constants import (
    BLACKLIST_LEVELS,
    DECIDED_OUTCOMES,
    DEFECT_POOL,
    REGION_MAP,
    SEVERITY,
    SUPPLIER_LEVEL_THRESHOLDS,
    SUPPLIER_LEVEL_TOP,
)

# re-export：保留历史内部引用名 _REGION_MAP（数据本体已迁到 constants 单一来源）
_REGION_MAP = REGION_MAP

logger = logging.getLogger("returnguard.pipeline")

# 洞察聚合缓存（_ins_cache / _ins_lock / _ins_cache_put / invalidate_insights_cache）
# 已下沉到独立 cache.py，解耦 db ⇄ pipeline 循环依赖（A21）。本模块仅复用，不再自持状态。
from cache import (  # noqa: E402, F401
    _ins_cache,
    _ins_cache_put,
    _ins_lock,
    invalidate_insights_cache,
)

# 案件持久化已迁移到 db.py（SQLAlchemy 仓储层，统一 openGauss，离线回退 SQLite）。
# 这里做 re-export，保持 main.py 的 import 路径不变。
from db import get_generation, load_cases, save_case  # noqa: E402, F401

# ---- 缺陷词表/严重程度已迁至 constants.py（见文件头说明），此处仅保留业务映射 ----


# ===================== 工具函数 =====================
def _content_seed(*paths) -> int:
    """用图片**内容**（而非路径，路径含随机 rid 前缀）生成稳定随机种子，
    保证同一张图每次取证结果一致、可复现（修复 mock 相似度因随机文件名而漂移的隐患）。"""
    h = hashlib.md5()
    for p in paths:
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except Exception:  # noqa: BLE001
            h.update(str(p).encode("utf-8"))
    return int(h.hexdigest(), 16)


def _mock_similarity(returned_path: str, product_path: str) -> float:
    """mock 相似度：由两张图内容算出的确定性值（0.55~0.98），仅用于免 Key 演示。
    注意：这不是模型真实能力，真实相似度在 live 模式由图向量余弦得到。"""
    s = _content_seed(returned_path, product_path)
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
    # 用图片内容种子决定瑕疵数量与种类（确定性，避免随机文件名导致结果漂移）
    random.seed(_content_seed(returned_path))
    n_def = random.randint(0, 3)
    defects = random.sample(DEFECT_POOL, n_def) if n_def > 0 else ["无明显瑕疵"]
    same = sim >= get_active_threshold()  # 阈值：≥阈值 视为同一件商品（标定值或默认 0.82）

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
    rng = random.Random(_content_seed(returned_path, "boxes"))
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
    returned_url: str | None = None,
    product_url: str | None = None,
) -> dict:
    """阶段A 统一入口：对一笔退货做取证，返回结构化结果（功能①②③④⑤）。
    - mode="mock"：确定性规则，免 Key 立即可演示。
    - mode="live"：调用 models_router.live_analyze 走真实模型；任何异常都回退 mock 并标注，
      确保现场演示不会因网络/额度问题而卡死。
    - returned_url / product_url：上传图公网 URL（由 storage 图床层给出），透传给 live_analyze
      供视觉/向量/OCR 模型服务端回源。
    """
    if mode == "live":
        try:
            from models_router import live_analyze

            return live_analyze(
                returned_path,
                product_path,
                listing_text,
                sku,
                amount,
                returned_url=returned_url,
                product_url=product_url,
            )
        except Exception as e:  # 失败回退 mock，保证演示不中断
            logger.exception("live 取证失败，回退 mock: %s", e)
            res = _mock(returned_path, product_path, listing_text, sku, amount)
            res["mode"] = "mock(fallback)"
            res["error"] = str(e)
            return res
    return _mock(returned_path, product_path, listing_text, sku, amount)


# ===================== 案件持久化（数据沉淀）=====================
# 持久化已迁移到 db.py（SQLAlchemy 仓储层，统一 openGauss，离线回退 SQLite）。
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
    "北美": 0.16,
    "欧洲": 0.18,
    "南美": 0.15,
    "东亚": 0.13,
    "东南亚": 0.12,
    "大洋洲": 0.17,
    "中东": 0.15,
    "非洲": 0.16,
    "": 0.14,
    "未知": 0.14,
    "其他": 0.14,
}
# 国家代码 / 国家全名 → 宏观销售地区，见 constants.REGION_MAP（单一来源）。
# 已在此处 re-export，保持历史 import 路径与内部引用不变。


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


def _supplier_level(score: float) -> str:
    """质量分 → 档位（阈值取自 constants，与黑名单判定共用同一套，杜绝漂移）。"""
    for bound, level in SUPPLIER_LEVEL_THRESHOLDS:
        if score < bound:
            return level
    return SUPPLIER_LEVEL_TOP


def _build_supplier_scorecard(sup: dict) -> list[dict]:
    out: list[dict] = []
    for k, v in sup.items():
        if not k or k == "未知":  # 跳过缺失/未知供应商，避免污染红黑榜可读性
            continue
        defect_rate = round(v["real"] / v["cases"], 3) if v["cases"] else 0
        wr = round(v["won"] / v["cases"], 3) if v["cases"] else 0
        score = round(100 * (0.5 * wr + 0.5 * (1 - defect_rate)), 1)
        level = _supplier_level(score)
        # 缺陷构成：剔除"无明显瑕疵"占位，保留真实缺陷分布（前端画构成条）
        defect_dist = {dk: dv for dk, dv in v["defects"].items() if dk != "无明显瑕疵"}
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
    # win_rate 分母用 decided（已判定）而非 cases：与全局 win_rate 同口径，
    # 否则「待分析」案件会把平台胜诉率稀释成接近 0，出现所有平台都远低于大盘的假象。
    out: list[dict] = []
    for k, v in plat.items():
        out.append(
            {
                "platform": k,
                "cases": v["cases"],
                "decided": v["decided"],
                "win_rate": round(v["won"] / v["decided"], 3) if v["decided"] else 0,
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
                    "decided": v["decided"],
                    "win_rate": round(v["won"] / v["decided"], 3) if v["decided"] else 0,
                    "refund": round(v["refund"], 2),
                }
            )
    return out


def _build_region_view(region: dict) -> list[dict]:
    """地区维度聚合（方向2 维度扩展）：按销售地区统计纠纷量、退款、胜诉率。

    decided 字段供前端区分「胜诉率 0%」与「尚无已判定案件」——跨境数据源里
    整批无退货原因的案件（outcome=待分析）会全部落在同一地区，若按 cases 做分母
    会显示成红色 0%，实际只是还没判定。
    """
    out: list[dict] = []
    for k, v in region.items():
        out.append(
            {
                "region": k,
                "cases": v["cases"],
                "decided": v["decided"],
                "refund": round(v["refund"], 2),
                "win_rate": round(v["won"] / v["decided"], 3) if v["decided"] else 0,
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


# ===================== 时间序列 + 预测预警（B组）=====================
def _build_time_series(ts: dict) -> list[dict]:
    """按自然月汇总案件数与退款，返回升序时间序列（缺日期的案件不计入）。"""
    out: list[dict] = []
    for k, v in ts.items():
        out.append({"month": k, "cases": v["cases"], "refund": round(v["refund"], 2)})
    out.sort(key=lambda x: x["month"])
    return out


def _next_month(y: int, m: int, k: int) -> tuple[int, int]:
    """由 (年, 月) 向后推 k 个月，返回新的 (年, 月)。"""
    total = (y * 12 + (m - 1)) + k
    return total // 12, total % 12 + 1


def _forecast_monthly(series: list[dict], horizon: int = 3) -> dict:
    """B组：对月度案件量做线性最小二乘外推，预测未来 horizon 个月并给出趋势结论。

    方法：以月序为自变量做 OLS 拟合 slope/intercept，预测点 = intercept + slope·(n-1+k)；
    单件退款按历史均值外推；趋势由 slope 相对均值占比判定（up/down/flat），避免弱噪声误报。
    样本不足（<3 个月）返回 available=False，前端据此提示「暂无足够时间维度数据」。
    纯确定性计算，无需模型、可复现，适合录屏演示。
    """
    n = len(series)
    if n < 3:
        return {
            "available": False,
            "points": [],
            "trend": "flat",
            "slope": 0.0,
            "recent_avg": 0.0,
            "next_month_cases": 0,
            "next_month_refund": 0.0,
        }
    xs = list(range(n))
    ys = [p["cases"] for p in series]
    ybar = sum(ys) / n
    xbar = (n - 1) / 2
    sxx = sum((x - xbar) ** 2 for x in xs) or 1
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    # 历史单件退款均值，用于外推预测退款
    total_refund = sum(p["refund"] for p in series)
    total_cases = sum(ys) or 1
    avg_refund_per_case = total_refund / total_cases

    y, m = int(series[-1]["month"][:4]), int(series[-1]["month"][5:7])
    points: list[dict] = []
    for k in range(1, horizon + 1):
        ny, nm = _next_month(y, m, k)
        pred_cases = max(0, round(intercept + slope * (n - 1 + k)))
        points.append(
            {
                "month": f"{ny:04d}-{nm:02d}",
                "cases": pred_cases,
                "refund": round(pred_cases * avg_refund_per_case, 2),
            }
        )
    # 趋势判定：slope 占均值比例，弱趋势视为 flat（防噪声误报）
    rel = abs(slope) / ybar if ybar else 0.0
    trend = "flat" if rel < 0.05 else ("up" if slope > 0 else "down")
    recent_avg = round(mean(ys[-3:]), 1) if n >= 3 else ybar
    return {
        "available": True,
        "points": points,
        "trend": trend,
        "slope": round(slope, 3),
        "recent_avg": recent_avg,
        "next_month_cases": points[0]["cases"],
        "next_month_refund": points[0]["refund"],
    }


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
        outcome_dist[oc if oc in DECIDED_OUTCOMES else "待分析"] += 1
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
    # decided=已判定案件数（胜诉率分母，与全局 win_rate 同口径，剔除「待分析」）
    plat = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0, "decided": 0})
    # 平台 × 供应商 交叉累加器（供应商维度扩展：跨平台横向对比供货方质量）
    matrix = defaultdict(
        lambda: defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0, "decided": 0})
    )
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
    region = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0, "decided": 0})
    season = defaultdict(lambda: {"cases": 0, "refund": 0.0, "won": 0})
    # 时间序列累加器（B组：时间序列 + 预测预警）：按自然月 'YYYY-MM' 累加案件数与退款
    ts = defaultdict(lambda: {"cases": 0, "refund": 0.0})
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
            if c.get("outcome") in DECIDED_OUTCOMES:
                pp["decided"] += 1

        # 平台 × 供应商 交叉：两端都需有效才入交叉矩阵
        p_val = c.get("platform")
        s_val = c.get("supplier")
        if p_val and p_val != "未知" and s_val and s_val != "未知":
            mm = matrix[p_val][s_val]
            mm["cases"] += 1
            mm["refund"] += amt
            if c.get("outcome") == "赢":
                mm["won"] += 1
            if c.get("outcome") in DECIDED_OUTCOMES:
                mm["decided"] += 1

        # 地区维度（方向2 维度扩展）：归一化宏观地区，缺失/未知/其他不污染地区对比
        reg_val = _region_bucket(c.get("region"))
        if reg_val and reg_val not in ("未知", "其他"):
            rr = region[reg_val]
            rr["cases"] += 1
            rr["refund"] += amt
            if c.get("outcome") == "赢":
                rr["won"] += 1
            if c.get("outcome") in DECIDED_OUTCOMES:
                rr["decided"] += 1
        # 季节维度（由日期推导）
        seas_val = _season_of(c.get("date"))
        if seas_val:
            ss = season[seas_val]
            ss["cases"] += 1
            ss["refund"] += amt
            if c.get("outcome") == "赢":
                ss["won"] += 1
        # 时间序列维度（B组）：按自然月累加，供趋势线与预测
        cd = c.get("date") or ""
        if len(cd) >= 7 and cd[4] == "-":
            mm = ts[cd[:7]]
            mm["cases"] += 1
            mm["refund"] += amt
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

    # 供应商红黑榜 + 黑名单自动生成（方向2）：按档位入黑名单，带可解释理由。
    # 注意：这里按 level 判定而非另设分数阈值——历史写法为 quality_score < 50，
    # 与「score≥38 即优质」的分级冲突，38~49 分的「优质」供应商会被同时拉黑。
    supplier_scorecard = _build_supplier_scorecard(sup)

    def _pct(x: float) -> str:
        return f"{round(x * 100)}%"

    supplier_blacklist = [
        {
            "supplier": s["supplier"],
            "name": s["name"],
            "quality_score": s["quality_score"],
            "level": s["level"],
            "defect_rate": s["defect_rate"],
            "win_rate": s["win_rate"],
            "reason": f"质量分 {s['quality_score']}（{s['level']}）：缺陷率 {_pct(s['defect_rate'])}、"
            f"维权胜诉率 {_pct(s['win_rate'])}",
        }
        for s in supplier_scorecard
        if s["level"] in BLACKLIST_LEVELS
    ]

    # 退货成本估算：物流成本（按地区比例）+ 退款 = 退货总成本
    logistics_cost = round(logistics_all, 2)
    total_return_cost = round(total_refund + logistics_cost, 2)

    # 时间序列 + 预测预警（B组）：月度序列 + 线性外推 + 上行预警
    time_series = _build_time_series(ts)
    forecast = _forecast_monthly(time_series)
    forecast_alerts: list[dict] = []
    if forecast.get("available") and forecast.get("trend") == "up":
        recent_avg = forecast.get("recent_avg", 0) or 0
        predicted = forecast.get("next_month_cases", 0)
        if recent_avg >= 4 and predicted > recent_avg * 1.15:
            pct_up = round((predicted - recent_avg) / recent_avg * 100)
            forecast_alerts.append(
                {
                    "month": forecast["points"][0]["month"],
                    "predicted": predicted,
                    "recent_avg": recent_avg,
                    "pct": pct_up,
                    "reason": (
                        f"退货量预测上行：{forecast['points'][0]['month']} 预计 {predicted} 笔，"
                        f"较近3月均值({recent_avg}笔)环比 +{pct_up}%，"
                        "建议提前做品控抽检与备货/物流前置"
                    ),
                }
            )

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
        # B组：时间序列 + 预测预警
        "time_series": time_series,
        "forecast": forecast,
        "forecast_alerts": forecast_alerts,
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


def _build_sourcing_loop(agg: dict) -> list[dict]:
    """B组·选品避坑闭环：把洞察的"负面信号"收敛成一份**可执行**清单（结构化、可导出、可落地）。

    闭环逻辑：退货证据 → 洞察（供应商黑榜 / 品类低胜诉 / SKU 异常 / 退货量上行） →
    反哺选品与品控的"动作项"，每条带 {动作, 对象, 理由, 严重度}，让卖家拿到就能做决策，
    而不是一堆描述性结论。severity 加权排序（高→中→低），前端按严重度渲染色块。
    """
    SEV_W = {"高": 0, "中": 1, "低": 2}
    items: list[dict] = []

    # ① 供应商黑名单 → 规避动作
    for b in agg.get("supplier_blacklist", []):
        items.append(
            {
                "action": "规避供应商",
                "target": f"{b.get('supplier', '')}({b.get('name', '')})",
                "reason": b.get("reason", ""),
                "severity": "高",
            }
        )

    # ② 低胜诉率品类 → 上新前必核验
    for c in agg.get("category_heatmap", []):
        if c.get("win_rate", 1) < 0.30:
            items.append(
                {
                    "action": "上新前必核验",
                    "target": c.get("category", ""),
                    "reason": (
                        f"该品类纠纷胜诉率仅 {round(c.get('win_rate', 0) * 100)}%、"
                        f"高发缺陷「{c.get('top_defect', '-')}」，上新前重点核验质量与图文一致性"
                    ),
                    "severity": "中",
                }
            )

    # ③ SKU 异常爆发 → 暂停推广排查
    for a in agg.get("anomaly_alerts", []):
        items.append(
            {
                "action": "暂停推广·排查批次",
                "target": a.get("sku", ""),
                "reason": a.get("reason", ""),
                "severity": "高",
            }
        )

    # ④ 退货量上行预测 → 前置品控/备货
    for fa in agg.get("forecast_alerts", []):
        items.append(
            {
                "action": "前置品控·备货物流",
                "target": "退货量整体",
                "reason": fa.get("reason", ""),
                "severity": "中",
            }
        )

    items.sort(key=lambda x: SEV_W.get(x["severity"], 1))
    return items


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
    # 案件 id 指纹（缺失 id 归一为 "" 以避免 None 不可排序）；唯一标识被聚合批次。
    # 用 sha1 而非内置 hash()：避免 PYTHONHASHSEED 随机化导致缓存键跨进程不一致，且抗碰撞（P1-缓存指纹）。
    sig = hashlib.sha1(
        ",".join(sorted((c.get("case_id") or "") for c in cases)).encode("utf-8")
    ).hexdigest()
    key = (mode, source, sig, get_generation(source))
    with _ins_lock:
        if key in _ins_cache:
            _ins_cache.move_to_end(key)  # 命中即刷新 LRU 序
            return _ins_cache[key]
    agg = _aggregate(cases)
    if not cases:
        _ins_cache_put(key, agg)
        return agg
    if mode == "live":
        try:
            from models_router import build_insights_live

            llm = build_insights_live(agg)
            # ⑧ 下一步怎么做：优先用 LLM 专属的 sourcing_advice，缺失时回退到 LLM 的
            # recommendations（保证 live 模式下 ⑧ 始终有内容，与 mock 字段结构一致）。
            live_advice = llm.get("sourcing_advice") or llm.get("recommendations") or []
            agg.update(
                {
                    "root_cause": llm.get("root_cause", agg.get("root_cause", "")),
                    "sku_insights": llm.get("sku_insights", agg.get("sku_insights", [])),
                    "recommendations": llm.get("recommendations", agg.get("recommendations", [])),
                    "sourcing_advice": live_advice,
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
    # B组·选品避坑闭环：无论 mock/live，均把负面信号收敛成可执行清单（结构化、可落地）
    agg["sourcing_checklist"] = _build_sourcing_loop(agg)
    agg["mode"] = agg.get("mode", "mock")
    _ins_cache_put(key, agg)
    return agg
