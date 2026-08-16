"""ReturnGuard · 平台适配举证包（交付物 A 的数据源）

本模块是「平台适配举证包」的唯一事实来源：把 Amazon / AliExpress / Temu / SHEIN
四大主流跨境平台的退货/纠纷举证规则结构化沉淀，并映射到 ReturnGuard 既有的取证能力。

设计原则（守住「只取证不裁决」）：
    - 这里只描述**平台政策的客观事实**（退货窗口、举证责任偏向、必备材料、常见失分点），
      绝不替商家下"一定能赢/输"的结论性判决。
    - capability_map 说明 ReturnGuard 的哪项能力可以**支撑**对应举证环节，是工具说明而非裁决。

对外暴露：
    - PLATFORM_KEYS：平台标识列表（与案件库 platform 字段一致）
    - get_platform_spec(key)：取单个平台规格
    - list_platforms()：取全部平台规格（供 /api/platforms 与文档生成器复用）
"""

from __future__ import annotations

from typing import Any

# 平台标识 = 案件库 platform 字段存储值，前后端/数据集统一使用这四个
PLATFORM_KEYS: list[str] = ["Amazon", "AliExpress", "Temu", "SHEIN"]

# 规则对照表在文档/前端展示时的属性顺序
ATTRIBUTES: list[tuple[str, str]] = [
    ("return_window", "退货窗口"),
    ("response_window", "卖家响应时限"),
    ("shipping_payer", "运费承担"),
    ("burden_bias", "举证责任偏向"),
    ("required_evidence", "必备举证材料"),
    ("common_loss_reasons", "常见失分 / 败诉原因"),
    ("special_clauses", "平台特殊条款"),
]

# ReturnGuard 既有取证能力的稳定键（capability_map 引用，便于文档/前端一致渲染）
CAPABILITY_KEYS: list[str] = [
    "关键帧红框标注",
    "SKU 同款比对",
    "瑕疵聚类归因",
    "胜诉率参考",
    "取证卷宗",
]

EVIDENCE_SPECS: dict[str, dict[str, Any]] = {
    "Amazon": {
        "label": "Amazon",
        "return_window": "自营 30 天；FBA 由 Amazon 处理退货与退款",
        "response_window": "A-to-z 索赔须在 72 小时内响应，否则自动判负并扣款",
        "shipping_payer": "A-to-z 下买家先垫付，裁决后由责任方承担；使用 Buy Shipping 准时发货可获保护",
        "burden_bias": "偏向买家（A-to-z 保障对买家极友好，卖家须主动举证）",
        "required_evidence": [
            "有效物流追踪号（平台认可承运商，如 ePacket / DHL Global Mail）",
            "妥投证明 POD（签收 / 签名确认截图）",
            "商品状况照片 / 视频（含瑕疵特写）",
            "Buyer-Seller Messaging 内的沟通记录",
            "正品采购发票（应对假货投诉）",
            "商品合规认证（CE / FCC 等，如适用）",
        ],
        "common_loss_reasons": [
            "72 小时内未响应 A-to-z → 自动判负并扣款",
            "缺妥投证明 POD，无法证明已送达",
            "假货投诉无采购发票佐证",
            "实物与 listing 描述不符（货不对板）",
            "FBA 仍可能因错发 / 过期 / 侵权判卖家责",
        ],
        "special_clauses": [
            "ODR 订单缺陷率目标 <1%（建议 ≤0.8%）",
            "裁决后 30 天内可凭新证据申诉（成功率 <15%）",
            "AI 自动裁决试点中，处理周期目标缩至 5 天",
            "禁止诱导线下退款（Anti-Incentives，扣绩效分、可能冻店）",
        ],
        "capability_map": {
            "关键帧红框标注": "退货图红框标注瑕疵/污损，证明退回时真实状态，反驳「无损」主张",
            "SKU 同款比对": "相似度证明退回件与售出货品为同一件，反驳调包/发错货指控",
            "瑕疵聚类归因": "定位高频缺陷品类，反哺选品与供应商整改，降低 ODR",
            "胜诉率参考": "同类目/供应商历史胜诉率，评估举证投入产出",
            "取证卷宗": "一键归档追踪号/POD/沟通/照片，生成可提交的 A-to-z 举证材料",
        },
    },
    "AliExpress": {
        "label": "AliExpress",
        "return_window": "确认收货后 15 天内可开纠纷（保护期通常 60 天，部分 90 天免退）",
        "response_window": "纠纷协商期卖家 5 天响应；清晰证据案件 2025 起 48 小时内裁定",
        "shipping_payer": "未收到 / 严重不符由卖家承担；低值（<$5）可免退仅退款",
        "burden_bias": "偏向买家（escrow 放款前须买家确认，举证清晰则高胜率）",
        "required_evidence": [
            "瑕疵照片 / 视频（电子类建议视频）",
            "商品与 listing 图文差异截图",
            "物流追踪页截图（未收到时）",
            "与卖家的沟通记录",
            "完整证据包（照片+视频可显著提升胜率）",
        ],
        "common_loss_reasons": [
            "未提供 / 证据不足 → 纠纷关闭、放款给卖家（买家败诉）",
            "过早点击「确认收货」放弃保护",
            "提前关闭纠纷无法重开",
            "描述与实物差异但无图文对比证据",
        ],
        "special_clauses": [
            "2025 起清晰证据案件 48 小时内裁定",
            "<$5 低值订单自动免退仅退款",
            "Free Returns 计划：部分商品 90 天免运费退",
            "务必确认收货前满意再确认，勿私下和解",
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注瑕疵部位，直观证明「与描述不符」",
            "SKU 同款比对": "证明发出商品与订单一致，反驳「错发/调包」",
            "瑕疵聚类归因": "识别高频不符品类，优化 listing 图文一致性",
            "胜诉率参考": "类目胜诉率辅助判断申诉优先级",
            "取证卷宗": "归档图文证据与沟通，形成可提交纠纷的证据链",
        },
    },
    "Temu": {
        "label": "Temu",
        "return_window": "无理由退货签收后 30 天内；质量问题凭证据可延至 90 天",
        "response_window": "收到退货申请 24 小时内确认（2025 新规逾期默认同意）；争议 48 小时内上传凭证",
        "shipping_payer": "质量问题卖家/平台承担；非质量买家承担，手续费 5–15%（最低 $2）",
        "burden_bias": "平台主导仲裁（AI 辅助判责，卖家须自证无过错）",
        "required_evidence": [
            "发货前商品完好证明（带时间戳照片 / 视频）",
            "发货单 / 物流轨迹",
            "质检报告（质量争议）",
            "与买家沟通截图",
            "高价值品建议开箱视频",
        ],
        "common_loss_reasons": [
            "描述误导（材质虚标）→ 全额退款 + 商品下架",
            "证据不足 → 判卖家责、扣保证金",
            "逾期未响应 → 默认同意退货 / 自动判负",
            "非质量退货未保持原状被拒收",
        ],
        "special_clauses": [
            "2025-07 上线争议仲裁系统，86% 案件 7 工作日内裁定",
            "AI 判责准确率 87%，争议 >$50 触发人工复核",
            "默认支持 7 天无理由，卖家不可拒绝",
            "全托管模式退货由平台主导",
        ],
        "capability_map": {
            "关键帧红框标注": "对比发货前/退货后红框，证明商品状态变化非卖家责",
            "SKU 同款比对": "证明所发即所售，反驳「发错货」指控",
            "瑕疵聚类归因": "定位质量争议高发品类，推动供应商整改",
            "胜诉率参考": "供应商维度胜诉率，识别高风险供货方",
            "取证卷宗": "归档发货前证据链，提交平台仲裁自证",
        },
    },
    "SHEIN": {
        "label": "SHEIN",
        "return_window": "收货后 30 天无忧退货；欧盟仓须遵守 14 天无理由",
        "response_window": "争议由 SHEIN 客服裁决，供应商须在 48 小时内提供证据链",
        "shipping_payer": "质量 / 发错货卖家承担（平台发预付标签）；个人偏好买家承担",
        "burden_bias": "平台裁判，供应商须提供生产 / 质检证据自证",
        "required_evidence": [
            "发货前质检照片（易损部位特写）",
            "生产记录 / 质检单（LOT 批次）",
            "物流追踪（≥17 位单号）+ 签收记录",
            "与买家沟通记录",
            "批次留样（建议保存 3 个月）",
        ],
        "common_loss_reasons": [
            "无法证明发货前质量 → 判卖家责",
            "图文 / 实物不一致被判定误导",
            "恶意退货（买家损坏后退回）无发货前照片反驳",
            "退货率 >8% 触发供应商约谈，>1% 品质投诉暂停上新",
        ],
        "special_clauses": [
            "退货地须标注 'China' 而非 'Hong Kong'，否则视为虚假发货罚款",
            "EPR / CE / REACH 合规前置（违规扣保证金 ¥50,000）",
            "批次留样 3 个月 + LOT 追溯降低举证难度",
            "纠纷率红线 3%，>5% 扣分（12 分/月暂停销售）",
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注发货前完好/退货后差异，反驳恶意退货",
            "SKU 同款比对": "证明所发商品与订单一致，反驳错发",
            "瑕疵聚类归因": "定位品质投诉高发品类，指导留样与质检重点",
            "胜诉率参考": "供应商质量分辅助遴选合规工厂",
            "取证卷宗": "归档生产/质检/LOT 证据，满足 SHEIN 48h 举证时效",
        },
    },
}


def get_platform_spec(key: str) -> dict[str, Any] | None:
    """按平台标识取规格；不存在返回 None。"""
    return EVIDENCE_SPECS.get(key)


def list_platforms() -> list[dict[str, Any]]:
    """返回全部平台规格（列表，按 PLATFORM_KEYS 顺序）。"""
    return [EVIDENCE_SPECS[k] for k in PLATFORM_KEYS if k in EVIDENCE_SPECS]


def is_valid_platform(key: str) -> bool:
    """判断是否为受支持的平台标识。"""
    return key in EVIDENCE_SPECS
