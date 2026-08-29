"""ReturnGuard · 业务常量（单一来源，避免重复定义与阈值漂移）

双模式（mock/live）与双轨存储（SQLite/openGauss）共用本文件中的阈值与词表，
确保 pipeline（规则归因）与 models_router（真实模型）对「同款阈值」「严重程度」
的判断完全一致，杜绝两处各写一份导致的逻辑漂移。
"""

# 同款一致性阈值：相似度 ≥ 该值视为同一件商品（可调，用历史样本标定）
SAME_ITEM_THRESHOLD: float = 0.82

# 已判定 outcome 枚举：胜诉率分母只统计这些，避免「待分析」案件把胜诉率稀释成 0。
# 全局 win_rate 与各维度（platform_view / region_view / 交叉矩阵）共用此口径。
DECIDED_OUTCOMES: tuple[str, ...] = ("赢", "部分退款", "输")

# 缺陷词表（与方案功能②对齐）
DEFECT_POOL: list[str] = [
    "外包装破损",
    "商品缺件",
    "污渍划痕",
    "使用痕迹",
    "功能故障",
    "货不对板",
    "色差明显",
]

# 各缺陷的严重程度权重（用于优先级评分与排序，0~1）
SEVERITY: dict[str, float] = {
    "外包装破损": 0.3,
    "商品缺件": 0.5,
    "污渍划痕": 0.2,
    "使用痕迹": 0.6,
    "功能故障": 0.8,
    "货不对板": 0.7,
    "色差明显": 0.3,
    "无明显瑕疵": 0.0,
}

# ===========================================================================
# 销售地区归一化（单一来源：pipeline / convert_datasets / dataset_parse 共用）
# ===========================================================================
# 国家码（US / DE / …）或数据集里的国家全名（UCI Online Retail 用
# "United Kingdom" / "EIRE" / "Germany" 等）→ 宏观销售地区。
#
# 注意：pipeline._region_bucket 对未收录值返回「其他」，而「其他」在聚合阶段
# 会被丢弃（不进入 region_view / 退货成本）。因此接入新数据源时**必须**同步
# 补录本表，否则样本会静默流失且难以察觉。新增地区名后请跑一次：
#   python -c "import json,collections;print(collections.Counter(c['region'] for c in json.load(open('demo/cases.json',encoding='utf-8'))))"
MACRO_REGIONS: tuple[str, ...] = (
    "北美",
    "欧洲",
    "南美",
    "东亚",
    "东南亚",
    "大洋洲",
    "中东",
    "非洲",
)

REGION_MAP: dict[str, str] = {
    # ---- 北美 ----
    "US": "北美",
    "USA": "北美",
    "United States": "北美",
    "United States of America": "北美",
    "CA": "北美",
    "Canada": "北美",
    "MX": "北美",
    "Mexico": "北美",
    # ---- 欧洲（含 UCI 数据集的国家全名与历史写法）----
    "UK": "欧洲",
    "GB": "欧洲",
    "United Kingdom": "欧洲",
    "Great Britain": "欧洲",
    "Channel Islands": "欧洲",
    "European Community": "欧洲",
    "EIRE": "欧洲",
    "Ireland": "欧洲",
    "DE": "欧洲",
    "Germany": "欧洲",
    "FR": "欧洲",
    "France": "欧洲",
    "ES": "欧洲",
    "Spain": "欧洲",
    "IT": "欧洲",
    "Italy": "欧洲",
    "RU": "欧洲",
    "Russia": "欧洲",
    "NL": "欧洲",
    "Netherlands": "欧洲",
    "SE": "欧洲",
    "Sweden": "欧洲",
    "PL": "欧洲",
    "Poland": "欧洲",
    "PT": "欧洲",
    "Portugal": "欧洲",
    "AT": "欧洲",
    "Austria": "欧洲",
    "BE": "欧洲",
    "Belgium": "欧洲",
    "CH": "欧洲",
    "Switzerland": "欧洲",
    "CY": "欧洲",
    "Cyprus": "欧洲",
    "CZ": "欧洲",
    "Czech Republic": "欧洲",
    "Czechia": "欧洲",
    "DK": "欧洲",
    "Denmark": "欧洲",
    "EE": "欧洲",
    "Estonia": "欧洲",
    "FI": "欧洲",
    "Finland": "欧洲",
    "GR": "欧洲",
    "Greece": "欧洲",
    "HR": "欧洲",
    "Croatia": "欧洲",
    "HU": "欧洲",
    "Hungary": "欧洲",
    "IS": "欧洲",
    "Iceland": "欧洲",
    "LT": "欧洲",
    "Lithuania": "欧洲",
    "LV": "欧洲",
    "Latvia": "欧洲",
    "LU": "欧洲",
    "Luxembourg": "欧洲",
    "MT": "欧洲",
    "Malta": "欧洲",
    "NO": "欧洲",
    "Norway": "欧洲",
    "RO": "欧洲",
    "Romania": "欧洲",
    "SK": "欧洲",
    "Slovakia": "欧洲",
    "SI": "欧洲",
    "Slovenia": "欧洲",
    "BG": "欧洲",
    "Bulgaria": "欧洲",
    "TR": "欧洲",
    "Turkey": "欧洲",
    "UA": "欧洲",
    "Ukraine": "欧洲",
    # ---- 南美 ----
    "BR": "南美",
    "Brazil": "南美",
    "AR": "南美",
    "Argentina": "南美",
    "CL": "南美",
    "Chile": "南美",
    "CO": "南美",
    "Colombia": "南美",
    "PE": "南美",
    "Peru": "南美",
    "UY": "南美",
    "Uruguay": "南美",
    # ---- 东亚 ----
    "JP": "东亚",
    "Japan": "东亚",
    "KR": "东亚",
    "Korea": "东亚",
    "South Korea": "东亚",
    "CN": "东亚",
    "China": "东亚",
    "HK": "东亚",
    "Hong Kong": "东亚",
    "TW": "东亚",
    "Taiwan": "东亚",
    "MO": "东亚",
    "Macau": "东亚",
    # ---- 东南亚 ----
    "SG": "东南亚",
    "Singapore": "东南亚",
    "MY": "东南亚",
    "Malaysia": "东南亚",
    "TH": "东南亚",
    "Thailand": "东南亚",
    "VN": "东南亚",
    "Vietnam": "东南亚",
    "ID": "东南亚",
    "Indonesia": "东南亚",
    "PH": "东南亚",
    "Philippines": "东南亚",
    # ---- 大洋洲 ----
    "AU": "大洋洲",
    "Australia": "大洋洲",
    "NZ": "大洋洲",
    "New Zealand": "大洋洲",
    # ---- 中东 ----
    "IL": "中东",
    "Israel": "中东",
    "SA": "中东",
    "Saudi Arabia": "中东",
    "AE": "中东",
    "United Arab Emirates": "中东",
    "BH": "中东",
    "Bahrain": "中东",
    "LB": "中东",
    "Lebanon": "中东",
    "QA": "中东",
    "Qatar": "中东",
    "KW": "中东",
    "Kuwait": "中东",
    # ---- 非洲 ----
    "ZA": "非洲",
    "RSA": "非洲",
    "South Africa": "非洲",
    "NG": "非洲",
    "Nigeria": "非洲",
    "EG": "非洲",
    "Egypt": "非洲",
    # ---- 明确无地区信息：归一为「未知」，由聚合层显式丢弃（而非混入「其他」）----
    "Unspecified": "未知",
    "Unknown": "未知",
    "N/A": "未知",
}

# ===========================================================================
# 供应商质量分分级 / 黑名单（单一来源，杜绝分级与黑名单阈值漂移）
# ===========================================================================
# 质量分 = 100 × (0.5×胜诉率 + 0.5×(1−缺陷率))，取值 0~100。
# 分级按「上界（不含）」顺序匹配，落到第一个 score < bound 的档位；都不满足即顶级档。
SUPPLIER_LEVEL_THRESHOLDS: list[tuple[float, str]] = [
    (20.0, "高风险"),
    (30.0, "待改进"),
    (38.0, "合格"),
]
# 顶级档（质量分 ≥ 最后一档上界）
SUPPLIER_LEVEL_TOP: str = "优质"
# 进入黑名单（红黑榜黑榜 / 选品规避）的档位。
# 关键约束：黑名单必须按 level 判定而非另设一个分数阈值——历史上这里写死 score<50，
# 与「score≥38 即优质」的分级冲突，38~49 分的「优质」供应商会被同时拉黑。
BLACKLIST_LEVELS: tuple[str, ...] = ("高风险", "待改进")
