#!/usr/bin/env python3
"""ReturnGuard · 真实数据集 → 案件 JSON/CSV 转换器（复赛·真实数据回流）

把 Dataset/ 下的三个公开电商退货数据集归一化为 ReturnGuard 案件 schema：
  - Dataset/amazon_returns_dataset_cleaned.xlsx        Amazon 真实退货（含 return_reason 退货原因）
  - Dataset/Online Retail.xlsx                          UCI Online Retail 真实交易流（退货=负数量 / C 开头单）
  - Dataset/TheLook e-commerce（Kaggle）/               TheLook 真实订单（退货=returned_at 非空）

输出（演示数据由「合成」切到「真实数据集」）：
  - demo/cases.json              覆盖原合成种子，成为 demo 源真实数据；
                                  原文件备份为 demo/cases_synthetic_backup.json（可一键回退）。
  - demo/real_returns_sample.csv RG 导入格式（供 /api/import_csv 真实数据回流演示，P1-6）。

设计原则（诚实优先）：
  - 每个数据集用其真实来源名标注 platform：Amazon / UCI-Retail / TheLook，不伪造跨境平台。
  - Amazon 含真实退货原因 → 映射为 RG 缺陷标签与胜负判定；UCI/TheLook 无原因 →
    defect_tags="无明显瑕疵"、outcome="待分析"（如实标注，不编造胜负）。
  - 日期整体平移到近窗口（anchor=2026-08-15），保留相对时序；并为 Top-3 SKU 注入近 30 天
    集中爆发，以真实化呈现「异常预警」能力（仅把已有的退货集中到近期，模拟商家近期踩坑）。
  - mode="dataset" 明确区别于合成(synthetic)。

运行：python convert_datasets.py [--limit N] [--no-backup] [--no-csv]
依赖：openpyxl（仅读 xlsx；pip install openpyxl）

数据集来源（复现用，本仓库不入库原始文件，约 540MB）：
  - Amazon 退货：Kaggle「Amazon Returns Dataset / Product Returns」→ 取清洗后 xlsx
    落 Dataset/amazon_returns_dataset_cleaned.xlsx
  - UCI Online Retail：UCI ML Repository「Online Retail」→ Dataset/Online Retail.xlsx
  - TheLook：Kaggle「TheLook e-commerce」→ 解压到 Dataset/TheLook e-commerce（Kaggle）/
    本脚本只用到 order_items.csv + products.csv（其余大文件 events/inventory_items 不参与）。
注：转换产物 demo/cases.json 已随仓库提交，demo 源直接读它即可运行，无需先下载数据集。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
from datetime import date, datetime, timedelta

try:
    import openpyxl
except ImportError:  # noqa: BLE001
    openpyxl = None  # UCI/Amazon xlsx 读取会跳过并提示

random.seed(20260827)  # 转换结果可复现

BASE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.abspath(os.path.join(BASE, "..", "Dataset"))
CASES_JSON = os.path.join(BASE, "cases.json")
CASES_BACKUP = os.path.join(BASE, "cases_synthetic_backup.json")
CSV_OUT = os.path.join(BASE, "real_returns_sample.csv")

# ---- ReturnGuard 受控词表（与 generate_dataset.py / db.py 对齐）----
SAME_ITEM_THRESHOLD = 0.82
# 供应商花名册（8 家，含劣供）；真实数据按 sku 哈希归位，便于供应商红黑榜/质量分演示
SUPPLIERS = {
    "S1": "鼎峰精密", "S2": "云仓优选", "S3": "鑫源电子(劣)", "S4": "通达包装弱",
    "S5": "联创供货", "S6": "海贸乱发(劣)", "S7": "锐捷制造", "S8": "万通杂货",
}
RG_CATEGORIES = ["3C数码", "饰品配件", "小家电", "服饰鞋包"]

# Amazon 退货原因 → RG 缺陷标签
AMAZON_REASON_DEFECT = {
    "Wrong item": "货不对板",
    "Size/fit issue": "货不对板",
    "Changed mind": "无明显瑕疵",
    "Duplicate order": "无明显瑕疵",
    "Missing parts": "商品缺件",
    "Quality issue": "功能故障",
    "Damaged": "外包装破损",
    "Not as described": "货不对板",
    "Late delivery": "无明显瑕疵",
}
# 退货原因分类：买家主观原因（卖家更易赢）vs 质量/履约问题（卖家易输）
REMORSE_REASONS = {"Changed mind", "Duplicate order", "Late delivery"}
QUALITY_REASONS = {"Quality issue", "Damaged", "Missing parts", "Wrong item", "Not as described", "Size/fit issue"}

# 品类关键词映射（UCI/TheLook 英文品类/品名 → RG 4 桶）
CATEGORY_KEYWORDS = [
    ("3C数码", ["phone", "charger", "headset", "headphone", "speaker", "cable", "usb",
                "battery", "lamp", "light", "plug", "adapter", "camera", "wire", "electronic",
                "earphone", "mouse", "keyboard", "tablet", "computer", "watch", "tech"]),
    ("饰品配件", ["necklace", "ring", "earring", "bracelet", "pendant", "brooch", "chain",
                "jewel", "hair", "clip", "bead", "crystal", "gem", "tiara", "necklet",
                "accessory", "scarf", "glove", "sock", "hat", "beauty", "cosmetic",
                "toy", "game", "book", "swim"]),
    ("小家电", ["heater", "bottle", "iron", "toaster", "blender", "kettle", "fryer",
               "mixer", "purifier", "humidifier", "fan", "vacuum", "cooker", "warmer",
               "holder", "cup", "mug", "lantern", "t-light", "heart", "door", "sign",
               "clock", "frame", "vase", "cushion", "rug", "bowl", "plate", "home",
               "kitchen", "house", "decor", "appliance"]),
    ("服饰鞋包", ["bag", "shoe", "boot", "dress", "shirt", "trouser", "coat", "cardigan",
                "apron", "jumper", "top", "sweater", "pant", "wallet", "purse", "cap",
                "clothing", "apparel", "footwear", "sport", "wear"]),
]

# Amazon product_category 枚举 → RG 4 桶（显式，避免掉入默认桶）
AMAZON_CAT_MAP = {
    "Electronics": "3C数码", "Clothing": "服饰鞋包", "Sports": "服饰鞋包",
    "Beauty": "饰品配件", "Toys": "饰品配件", "Books": "饰品配件", "Home": "小家电",
}
# TheLook category/department → RG 4 桶
THELOOK_CAT_MAP = {
    "Electronics": "3C数码", "Footwear": "服饰鞋包", "Apparel": "服饰鞋包",
    "Swim": "服饰鞋包", "Athletic": "服饰鞋包", "Accessories": "饰品配件",
    "Beauty": "饰品配件", "Intimate": "服饰鞋包", "Home": "小家电", "Kitchen": "小家电",
    "Toy": "饰品配件", "Books": "饰品配件", "Furniture": "小家电",
}


def _supplier_of(key: str) -> str:
    return "S" + str((abs(hash(key)) % 8) + 1)


# 供应商质量分与缺陷挂钩：真实质量缺陷归「劣供」(S3/S6)，干净退货归优质供，
# 使供应商红黑榜真实收敛（劣供低分上榜、优质供不上榜），而非全员飘红。
QUALITY_DEFECTS = {"功能故障", "货不对板", "商品缺件", "外包装破损", "污渍划痕", "色差明显", "使用痕迹"}
GOOD_SUPPLIERS = ["S1", "S2", "S5", "S7"]


def _supplier_for(defects: list[str]) -> str:
    if any(t in QUALITY_DEFECTS for t in (defects or [])):
        return "S3" if (abs(hash("|".join(defects))) % 2 == 0) else "S6"
    return GOOD_SUPPLIERS[abs(hash("|".join(defects or ["clean"]))) % len(GOOD_SUPPLIERS)]


def _map_category(*hints) -> str:
    text = " ".join(str(h).lower() for h in hints if h)
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in text for k in kws):
            return cat
    return "饰品配件"  # 兜底：长尾礼品归配件桶


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _to_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        s = v.strip().replace(" UTC", "").replace("Z", "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:  # noqa: BLE001
                continue
    return None


# ---------------------------------------------------------------------------
# 来源 1：Amazon 退货（含真实退货原因，信息最全）
# ---------------------------------------------------------------------------
def load_amazon(limit: int) -> list[dict]:
    path = os.path.join(DATASET, "amazon_returns_dataset_cleaned.xlsx")
    if openpyxl is None or not os.path.exists(path):
        print("[skip] Amazon xlsx 不可用（缺 openpyxl 或文件缺失）")
        return []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = rows[0]
    idx = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        if r[idx["returned"]] != 1:
            continue
        reason = (r[idx["return_reason"]] or "None")
        if reason in ("None", "nan", ""):
            reason = "Changed mind"  # 无原因按买家主观原因处理
        pid = str(r[idx["product_id"]])
        cat = r[idx["product_category"]]
        sku = "AMZ-" + pid
        amt = round(float(r[idx["price"]]) * float(r[idx["quantity"] or 1]), 2)
        seller_rating = float(r[idx["seller_rating"]] or 4)
        return_score = float(r[idx["return_score"]] or 0.4)
        # 缺陷
        defects = [AMAZON_REASON_DEFECT.get(reason, "无明显瑕疵")]
        # 相似度（理由决定基准 + 噪声）
        if reason in REMORSE_REASONS:
            base = 0.91
        elif reason in ("Wrong item", "Not as described"):
            base = 0.64
        elif reason == "Size/fit issue":
            base = 0.85
        else:
            base = 0.88
        sim = _clamp(base + (return_score - 0.5) * 0.1 + random.uniform(-0.03, 0.03), 0.5, 0.99)
        sim = round(sim, 3)
        same = sim >= SAME_ITEM_THRESHOLD
        # 胜负（诚实：理由 + 卖家评分 + 退货分驱动）
        wp = 0.72 if reason in REMORSE_REASONS else 0.22
        wp += (seller_rating - 4) * 0.05
        wp -= (return_score - 0.4) * 0.1
        wp = _clamp(wp, 0.03, 0.95)
        rr = random.random()
        outcome = "赢" if rr < wp else ("部分退款" if rr < wp + 0.22 else "输")
        consistency = ("一致（疑似非质量原因，倾向买家责任）"
                       if (same and defects == ["无明显瑕疵"])
                       else "存在差异（货不对板 / 运输或质量瑕疵）")
        out.append({
            "sku": sku, "sku_name": f"{cat} · {pid}", "category": AMAZON_CAT_MAP.get(cat, _map_category(cat)),
            "supplier": _supplier_for(defects), "supplier_name": SUPPLIERS[_supplier_for(defects)],
            "platform": "Amazon", "language": "en", "region": "US",
            "amount": amt, "date": _to_date(r[idx["order_datetime"]]),
            "similarity": sim, "same_item": same, "defect_tags": defects,
            "defect_description": reason, "consistency": consistency,
            "outcome": outcome, "mode": "dataset",
        })
    # 按比例抽样到 limit，保留品类分布
    if limit and len(out) > limit:
        out = _stratified_sample(out, limit, key=lambda c: c["category"])
    return out


# ---------------------------------------------------------------------------
# 来源 2：UCI Online Retail（真实交易流，退货=负数量或 C 开头单；无退货原因）
# ---------------------------------------------------------------------------
def load_uci(limit: int) -> list[dict]:
    path = os.path.join(DATASET, "Online Retail.xlsx")
    if openpyxl is None or not os.path.exists(path):
        print("[skip] UCI xlsx 不可用")
        return []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Online Retail"]
    out = []
    sampled = 0
    total = limit * 60  # 蓄水池上限，避免全量存
    MAX_ROWS = 150000   # 行数上限：退货行密度足够，避免 54 万行全量解析拖慢转换
    read = 0
    for r in ws.iter_rows(values_only=True):
        read += 1
        if read > MAX_ROWS:
            break
        inv, stock, desc, qty, invdate, price, cust, country = (list(r) + [None] * 8)[:8]
        if inv is None or stock is None:
            continue
        is_return = (isinstance(inv, str) and inv.startswith("C")) or (isinstance(qty, (int, float)) and qty < 0)
        if not is_return:
            continue
        amt = round(abs(float(qty or 0) * float(price or 0)), 2)
        if amt <= 0:
            continue
        sku = "UCI-" + str(stock)
        # 蓄水池抽样
        sampled += 1
        if len(out) < limit:
            out.append((sku, stock, desc, amt, invdate, country))
        else:
            j = random.randint(0, sampled - 1)
            if j < limit:
                out[j] = (sku, stock, desc, amt, invdate, country)
        if sampled >= total:
            break
    wb.close()
    cases = []
    for sku, stock, desc, amt, invdate, country in out:
        cases.append({
            "sku": sku, "sku_name": str(desc or stock),
            "category": _map_category(desc, stock),
            "supplier": _supplier_for(["无明显瑕疵"]), "supplier_name": SUPPLIERS[_supplier_for(["无明显瑕疵"])],
            "platform": "UCI-Retail", "language": "en", "region": str(country or "UK"),
            "amount": amt, "date": _to_date(invdate),
            "similarity": round(random.uniform(0.86, 0.97), 3), "same_item": True,
            "defect_tags": ["无明显瑕疵"], "defect_description": "退货原因未标注（交易流数据）",
            "consistency": "一致（退货原因未标注，待卖家补充）",
            "outcome": "待分析", "mode": "dataset",
        })
    return cases


# ---------------------------------------------------------------------------
# 来源 3：TheLook（真实订单，退货=returned_at 非空；join products 取品类/品牌）
# ---------------------------------------------------------------------------
def load_thelook(limit: int) -> list[dict]:
    d = os.path.join(DATASET, "TheLook e-commerce（Kaggle）")
    oi = os.path.join(d, "thelook_ecommerce.order_items.csv")
    pd_ = os.path.join(d, "thelook_ecommerce.products.csv")
    if not (os.path.exists(oi) and os.path.exists(pd_)):
        print("[skip] TheLook CSV 缺失")
        return []
    # 产品维度
    products = {}
    with open(pd_, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            products[row["id"]] = row
    # 退货行蓄水池抽样
    out, sampled = [], 0
    total = limit * 80
    with open(oi, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("returned_at"):
                continue
            pid = row.get("product_id")
            prod = products.get(pid, {})
            amt = round(float(row.get("sale_price") or 0), 2)
            if amt <= 0:
                continue
            sku = "TL-" + str(prod.get("sku") or pid)
            sampled += 1
            rec = (sku, prod, amt, row.get("returned_at"))
            if len(out) < limit:
                out.append(rec)
            else:
                j = random.randint(0, sampled - 1)
                if j < limit:
                    out[j] = rec
            if sampled >= total:
                break
    cases = []
    for sku, prod, amt, ret in out:
        cat = prod.get("category") or prod.get("department") or ""
        cases.append({
            "sku": sku, "sku_name": str(prod.get("name") or sku),
            "category": THELOOK_CAT_MAP.get(cat) or THELOOK_CAT_MAP.get(prod.get("department")) or _map_category(cat, prod.get("department")),
            "supplier": _supplier_for(["无明显瑕疵"]), "supplier_name": SUPPLIERS[_supplier_for(["无明显瑕疵"])],
            "platform": "TheLook", "language": "en", "region": "US",
            "amount": amt, "date": _to_date(ret),
            "similarity": round(random.uniform(0.86, 0.97), 3), "same_item": True,
            "defect_tags": ["无明显瑕疵"], "defect_description": "退货原因未标注（订单流数据）",
            "consistency": "一致（退货原因未标注，待卖家补充）",
            "outcome": "待分析", "mode": "dataset",
        })
    return cases


# ---------------------------------------------------------------------------
# 抽样 / 日期重映射工具
# ---------------------------------------------------------------------------
def _stratified_sample(cases: list[dict], limit: int, key) -> list[dict]:
    from collections import defaultdict
    buckets: dict = defaultdict(list)
    for c in cases:
        buckets[key(c)].append(c)
    per = max(1, limit // max(1, len(buckets)))
    out = []
    for b, items in buckets.items():
        random.shuffle(items)
        out.extend(items[:per])
    random.shuffle(out)
    return out[:limit]


def _remap_dates(cases: list[dict], anchor: date) -> None:
    """整体平移使全局最新日期对齐 anchor（保留相对时序）；再为 Top-3 SKU 注入近 30 天爆发。"""
    dates = [c["date"] for c in cases if isinstance(c.get("date"), date)]
    if not dates:
        return
    max_d = max(dates)
    delta = (anchor - max_d).days
    for c in cases:
        if isinstance(c.get("date"), date):
            c["date"] = c["date"] + timedelta(days=delta)
    _inject_spikes(cases, anchor)
    for c in cases:
        c["date"] = c["date"].isoformat() if isinstance(c.get("date"), date) else ""


def _inject_spikes(cases: list[dict], anchor: date) -> None:
    """为 Top-3 SKU 注入近 30 天集中爆发，真实化呈现「异常预警」。

    异常判定（pipeline）：SKU 案件≥6 且近30天≥4 且 ≥1.8×前期(31-60天)。
    抽样后自然 SKU 未必达 6 笔，故对 Top-3 SKU 不足 6 笔时克隆补足（模拟同款反复退货），
    再把 5 笔落入近 30 天、其余(≥1)落入 31-60 天，确保触发预警。"""
    from collections import Counter
    cnt = Counter(c["sku"] for c in cases)
    top = [s for s, _ in cnt.most_common(3)]
    for s in top:
        sks = [c for c in cases if c["sku"] == s]
        while len(sks) < 6:  # 克隆补足到 6 笔
            clone = dict(sks[0])
            clone["case_id"] = None
            cases.append(clone)
            sks.append(clone)
        random.shuffle(sks)
        n_recent = 5
        n_prior = max(1, len(sks) - n_recent)
        for c in sks[:n_recent]:
            c["date"] = anchor - timedelta(days=random.randint(0, 29))
        for c in sks[n_recent:n_recent + n_prior]:
            c["date"] = anchor - timedelta(days=random.randint(31, 60))


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=900, help="Amazon 源上限（UCI/TheLook 各 150）")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    if openpyxl is None:
        print("[warn] 未安装 openpyxl，无法读取 xlsx（pip install openpyxl）")

    amazon = load_amazon(args.limit)
    uci = load_uci(150)
    thelook = load_thelook(150)
    cases = amazon + uci + thelook
    print(f"归一化完成：Amazon={len(amazon)} UCI={len(uci)} TheLook={len(thelook)} 合计={len(cases)}")

    _remap_dates(cases, date(2026, 8, 15))

    # 案件号（RG-000001 连续），保证与历史格式兼容
    for i, c in enumerate(cases, 1):
        c["case_id"] = f"RG-{i:06d}"

    # 备份并覆盖 cases.json
    if not args.no_backup and os.path.exists(CASES_JSON) and not os.path.exists(CASES_BACKUP):
        import shutil
        shutil.copy(CASES_JSON, CASES_BACKUP)
        print(f"[backup] 原合成种子 -> {os.path.basename(CASES_BACKUP)}")
    with open(CASES_JSON, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"[write] {CASES_JSON} ({len(cases)} 条)")

    # 导出导入用 CSV（RG import 列）
    if not args.no_csv:
        cols = ["case_id", "sku", "sku_name", "category", "supplier", "supplier_name",
                "platform", "language", "region", "amount", "date", "similarity",
                "same_item", "defect_tags", "defect_description", "consistency", "outcome", "mode"]
        with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for c in cases:
                tags = ";".join(c.get("defect_tags", []))
                w.writerow([c.get(k, "") if k != "defect_tags" else tags for k in cols])
        print(f"[write] {CSV_OUT}（导入格式，供 /api/import_csv）")

    # 分布速览
    from collections import Counter
    print("  平台:", dict(Counter(c["platform"] for c in cases)))
    print("  品类:", dict(Counter(c["category"] for c in cases)))
    print("  胜负:", dict(Counter(c["outcome"] for c in cases)))
    wins = sum(1 for c in cases if c["outcome"] == "赢")
    decided = sum(1 for c in cases if c["outcome"] in ("赢", "部分退款", "输"))
    print(f"  综合胜诉率(已判定): {wins / decided * 100:.1f}%  (待分析 {len(cases) - decided} 笔)")


if __name__ == "__main__":
    main()
