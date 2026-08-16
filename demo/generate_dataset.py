"""ReturnGuard · 多维合成退货数据集生成器
生成贴近真实结构的跨境退货/纠纷案件（确定性、可复现），用于驱动「退货情报站」洞察层。
字段：case_id, sku, sku_name, category, supplier, platform, language, region,
      amount, date, similarity, same_item, defect_tags, defect_description,
      consistency, outcome, mode
说明：全部为模拟数据，仅用于演示洞察能力；接入真实取证流水后可直接替换。
"""

import json
import os
import random
from datetime import datetime, timedelta

random.seed(42)
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "cases.json")

TODAY = datetime(2026, 8, 15)
DAY0 = TODAY - timedelta(days=120)

# 品类 -> 缺陷倾向权重（与 pipeline.DEFECT_POOL 对齐）
CATEGORY_DEFECTS = {
    "3C数码": {
        "功能故障": 0.40,
        "外包装破损": 0.25,
        "货不对板": 0.15,
        "使用痕迹": 0.10,
        "无明显瑕疵": 0.10,
    },
    "饰品配件": {
        "商品缺件": 0.30,
        "货不对板": 0.25,
        "色差明显": 0.20,
        "污渍划痕": 0.10,
        "无明显瑕疵": 0.15,
    },
    "小家电": {
        "功能故障": 0.35,
        "外包装破损": 0.25,
        "使用痕迹": 0.15,
        "货不对板": 0.10,
        "无明显瑕疵": 0.15,
    },
    "服饰鞋包": {
        "色差明显": 0.30,
        "污渍划痕": 0.25,
        "外包装破损": 0.20,
        "货不对板": 0.10,
        "无明显瑕疵": 0.15,
    },
}

# 供应商画像：quality 越低越易出真实缺陷；bias 为偏好的缺陷类型
SUPPLIERS = {
    "S1": {"quality": 0.92, "bias": None, "name": "鼎峰精密"},
    "S2": {"quality": 0.80, "bias": None, "name": "云仓优选"},
    "S3": {"quality": 0.45, "bias": "功能故障", "name": "鑫源电子(劣)"},
    "S4": {"quality": 0.62, "bias": "外包装破损", "name": "通达包装弱"},
    "S5": {"quality": 0.78, "bias": None, "name": "联创供货"},
    "S6": {"quality": 0.50, "bias": "货不对板", "name": "海贸乱发(劣)"},
    "S7": {"quality": 0.85, "bias": None, "name": "锐捷制造"},
    "S8": {"quality": 0.68, "bias": "商品缺件", "name": "万通杂货"},
}

PLATFORMS = {
    "AliExpress": {
        "win": 0.28,
        "langs": ["ru", "es", "pt", "en"],
        "regions": ["RU", "ES", "BR", "US"],
    },
    "Amazon": {"win": 0.42, "langs": ["en", "de", "fr"], "regions": ["US", "UK", "DE", "FR"]},
    "PayPal": {"win": 0.30, "langs": ["en", "es"], "regions": ["US", "ES", "MX"]},
    "TikTok Shop": {"win": 0.38, "langs": ["en", "pt"], "regions": ["US", "BR", "UK"]},
}

SKU_POOL = {
    "3C数码": ["无线蓝牙耳机", "移动电源", "手机壳", "快充数据线", "蓝牙音箱", "智能手环"],
    "饰品配件": ["925银项链", "珍珠耳钉", "合金手链", "钛钢戒指", "水晶吊坠", "发饰胸针"],
    "小家电": ["迷你加湿器", "电动牙刷", "便携榨汁杯", "卷发棒", "暖风机", "电热水壶"],
    "服饰鞋包": ["运动卫帽卫衣", "真皮短钱包", "帆布休闲鞋", "牛仔直筒裤", "双肩背包", "针织开衫"],
}

PLATFORM_LIST = list(PLATFORMS.keys())
SUP_KEYS = list(SUPPLIERS.keys())
CATS = list(CATEGORY_DEFECTS.keys())


def weighted_defect(category, supplier):
    weights = dict(CATEGORY_DEFECTS[category])
    sup = SUPPLIERS[supplier]
    # 优质供应商更易出现“无明显瑕疵”(非质量退货，卖家可赢)；劣质供应商反之
    target_none = max(0.04, min(0.55, (sup["quality"] - 0.4) * 0.75))
    weights["无明显瑕疵"] = target_none
    # 供应商偏好缺陷
    if sup["bias"]:
        weights[sup["bias"]] = weights.get(sup["bias"], 0) + 0.30
    # 归一化
    tot = sum(weights.values())
    items = list(weights.items())
    pick = random.choices([k for k, _ in items], weights=[v / tot for _, v in items])[0]
    # 决定是否追加第二个缺陷（真实缺陷更易叠加）
    tags = [pick]
    if pick != "无明显瑕疵" and random.random() < 0.30:
        others = [d for d in CATEGORY_DEFECTS[category] if d != pick and d != "无明显瑕疵"]
        if others:
            tags.append(random.choice(others))
    return tags


def sample_similarity(defects):
    if "无明显瑕疵" in defects:
        return round(0.90 + random.random() * 0.08, 3)
    if "货不对板" in defects:
        return round(0.62 + random.random() * 0.20, 3)
    return round(0.80 + random.random() * 0.16, 3)


def sample_outcome(defects, similarity, platform):
    wp = PLATFORMS[platform]["win"]
    if "无明显瑕疵" in defects:
        wp += 0.22
    if "功能故障" in defects:
        wp -= 0.18
    if "货不对板" in defects:
        wp -= 0.12
    if "使用痕迹" in defects:
        wp -= 0.06
    if similarity >= 0.90:
        wp += 0.08
    if similarity < 0.82:
        wp -= 0.05
    wp = max(0.05, min(0.95, wp))
    r = random.random()
    if r < wp:
        return "赢"
    if r < wp + 0.22:
        return "部分退款"
    return "输"


def sample_date(spike):
    if spike and random.random() < 0.65:
        # 问题 SKU：近期（近 30 天）集中爆发
        return TODAY - timedelta(days=random.randint(0, 29))
    return DAY0 + timedelta(days=random.randint(0, 119))


def gen():
    cases = []
    cid = 0
    # 标记少数“问题 SKU”做异常预警演示
    problem_skus = set()
    for _ci, cat in enumerate(CATS):
        skus = SKU_POOL[cat]
        for si, name in enumerate(skus):
            sku = f"SKU-{cat[:1]}{si + 1:02d}"
            supplier = random.choice(SUP_KEYS)
            is_problem = si % 3 == 2  # 每类第 3、6 个为问题 SKU
            if is_problem:
                problem_skus.add(sku)
                supplier = random.choice([k for k in SUP_KEYS if SUPPLIERS[k]["quality"] < 0.7])
            n = random.randint(14, 24)
            if is_problem:
                n = random.randint(34, 52)
            for _ in range(n):
                cid += 1
                platform = random.choice(PLATFORM_LIST)
                pf = PLATFORMS[platform]
                defects = weighted_defect(cat, supplier)
                sim = sample_similarity(defects)
                outcome = sample_outcome(defects, sim, platform)
                amount = round(random.uniform(39, 320), 2)
                date = sample_date(is_problem)
                same = sim >= 0.82
                cons = (
                    "一致（疑似非质量原因，倾向买家责任）"
                    if (same and defects == ["无明显瑕疵"])
                    else "存在差异（货不对板 / 运输或质量瑕疵）"
                )
                cases.append(
                    {
                        "case_id": f"RG-{cid:06d}",
                        "sku": sku,
                        "sku_name": name,
                        "category": cat,
                        "supplier": supplier,
                        "supplier_name": SUPPLIERS[supplier]["name"],
                        "platform": platform,
                        "language": random.choice(pf["langs"]),
                        "region": random.choice(pf["regions"]),
                        "amount": amount,
                        "date": date.strftime("%Y-%m-%d"),
                        "similarity": sim,
                        "same_item": same,
                        "defect_tags": defects,
                        "defect_description": "；".join(defects),
                        "consistency": cons,
                        "outcome": outcome,
                        "mode": "synthetic",
                    }
                )
    return cases


if __name__ == "__main__":
    data = gen()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已生成 {len(data)} 条案件 -> {OUT}")
    # 快速校验分布
    from collections import Counter

    print("品类:", dict(Counter(c["category"] for c in data)))
    print("平台:", dict(Counter(c["platform"] for c in data)))
    print("结果:", dict(Counter(c["outcome"] for c in data)))
    wins = sum(1 for c in data if c["outcome"] == "赢")
    print(f"综合胜诉率: {wins / len(data) * 100:.1f}%")
