"""ReturnGuard · 平台适配举证包（交付物 A 的数据源）

本模块是「平台适配举证包」的唯一事实来源：把 Amazon / AliExpress / Temu / SHEIN /
eBay / Shopee / Lazada / Walmart / TikTok Shop 九大主流及新兴跨境平台的退货/纠纷
举证规则结构化沉淀，并映射到 ReturnGuard 既有的取证能力。

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

# 平台标识 = 案件库 platform 字段存储值，前后端/数据集统一使用
PLATFORM_KEYS: list[str] = [
    "Amazon", "AliExpress", "Temu", "SHEIN",
    "eBay", "Shopee", "Lazada", "Walmart", "TikTok Shop",
]

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
    "eBay": {
        "label": "eBay",
        "return_window": "交付/预计交付后 30 天（以较长者为准）；卖家自设退货政策须 ≥ MBG 标准",
        "response_window": "3 个工作日内响应买家请求；收到退货后 2 个工作日内退款（逾期 eBay 自动代退）",
        "shipping_payer": '"Not as described" 卖家承担退回运费；买家 remorse 按卖家退货政策执行',
        "burden_bias": "偏向买家（MBG 即使卖家不提供退货也强制退款；假货无需退回即退款）",
        "required_evidence": [
            "商品与 listing 描述一致的图文对比（反驳 SNAD — Significantly Not As Described）",
            "发货前商品状况照片/视频（证明发出时完好）",
            "有效物流追踪号 + 妥投证明 POD",
            "正品采购发票/授权书（应对假货/仿冒投诉）",
            "买卖双方沟通记录（eBay Messages 截图）",
        ],
        "common_loss_reasons": [
            "3 个工作日内未响应 → eBay 自动接受退货",
            "收到退货后超 2 天未退款 → eBay 自动代退并扣款",
            '无法证明"与描述一致" → SNAD 判买家胜',
            "假货投诉无采购凭证 → 直接判负 + 可能账号限制",
            "退货政策低于 MBG 最低标准 → 政策违规",
        ],
        "special_clauses": [
            "MBG 覆盖几乎所有品类（车辆/房产/数字内容/工业设备除外），自动生效、无额外费用",
            "14 天退货政策仅限特定品类（珠宝/收藏品/相机/医疗器械）",
            "TRS（Top Rated Seller）可享部分退款折扣 + 额外保护",
            "禁止诱导线下退款（违反可能降权/冻结）",
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注 SNAD 争议点（与 listing 描述差异），支持 MBG 申诉",
            "SKU 同款比对": 'MBG 下证明"收到的即发出的"，反驳调包假货',
            "瑕疵聚类归因": "定位 SNAD 高发品类，优化 listing 准确性",
            "胜诉率参考": "MBG 历史裁决趋势 + 卖家 Defect Rate 变化",
            "取证卷宗": "归档 MBG 所需全套证据（追踪/POD/发票/沟通），3 日响应窗口内可用",
        },
    },
    "Shopee": {
        "label": "Shopee",
        "return_window": "Mall 店铺 = 15 天（送达起）；Non-Mall（Marketplace/Preferred）= 7 天；In-Transit RR 可在途中拦截",
        "response_window": "质询 48h 内响应；Dispute 申诉 Online=3 天、Offline=1 个月；warranty case 14 天内提供解决方案",
        "shipping_payer": "SSL（Shopee Supported Logistics）丢件 Shopee 自动补偿卖家；非 SSL 卖家自理承运商索赔；质量争议卖家承担退货运费",
        "burden_bias": "平台裁决为主，卖家可在裁决后 2 天内 Dispute 并附证据申诉（但成功率有限）",
        "required_evidence": [
            "发货前商品完好照片/视频（含时间戳、防伪标签）",
            "物流追踪号 + 承运商交接证明（非 SSL 尤其重要）",
            "商品与 listing 图文差异对比截图",
            "与买家的站内沟通记录",
            "批次留样 / 生产质检单（Mall 店铺建议保留 3 个月）",
        ],
        "common_loss_reasons": [
            "48h 内未响应质询 → 平台直接批准买家请求",
            "非 SSL 物流无法提供有效追踪 → 丢件判卖家责且无法获补偿",
            '无发货前照片 → "损坏/瑕疵" 类争议难以反驳',
            "买家滥用退货（可疑账户被 watch list 限制，但普通卖家难触发此机制）",
            '电子产品拆封/使用痕迹 → 不符合「原封/可转售」条件',
        ],
        "special_clauses": [
            "Shopee Guarantee Period 内资金由平台托管（escrow 模式）",
            "Return on the Spot: COD 单当场验货退货（2025-07 新增）",
            '2025-08 起"I want to return in original/sealed condition"设免费退货额度（Platinum 3 次/月，普通 2 次/月）',
            "Counterfeit 理由仅限 Mall/FBS/Preferred+ 卖家使用",
            "东南亚六国本地化规则差异大（新加坡/马来西亚/菲律宾/泰国/印尼/越南各自有变体）",
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注瑕疵/缺件/破损，支撑 Dispute 申诉证据包",
            "SKU 同款比对": "SSL 物流下证明包裹完整性；非 SSL 佐证承运商责任",
            "瑕疵聚类归因": "按 Mall/Non-Mall 分层定位缺陷热点，指导质检投入",
            "胜诉率参考": "Dispute 胜诉率 + Shopee 裁决倾向分析",
            "取证卷宗": "归档 SSL 追踪/非 SSL 承运商证据 + 2 日 Dispute 窗口材料",
        },
    },
    "Lazada": {
        "label": "Lazada",
        "return_window": "LazMall / Choice 订单 = 30 天；Marketplace / LazGlobal = 15 天；RedMart = 7 天",
        "response_window": "2 个工作日内响应退款申请（逾期系统自动批准）；LazMall 退款处理 3-5 个工作日",
        "shipping_payer": "非质量问题买家承担；质量问题/错发卖家承担；LazMall Guaranteed Return 未按时处理赔 LazCash",
        "burden_bias": "LazMall Guaranteed Return 强保障买家；平台仲裁 + LazCash 补偿机制",
        "required_evidence": [
            "发货前商品完好照片（原始包装/标签完整）",
            "物流追踪 + 签收证明（尤其 LazGlobal 跨境订单）",
            "商品与 listing 描述一致性证据",
            "生产批次 / LOT 追溯信息（LazMall 品牌/授权卖家建议备）",
            "开箱视频（高价值品必备）",
        ],
        "common_loss_reasons": [
            "2 日内未响应 → 系统自动批准退款",
            "LazMall Guaranteed Return 超时（>3 工作日）→ 赔偿买家 LazCash（从卖家扣除）",
            "退货商品状态不符（已使用/缺配件/包装破损）→ 可拒收但需举证",
            "跨境订单退货至香港/当地仓 → 处理周期长（2-4 周），期间资金冻结",
            "错发产品每件罚款 $5（Lazada 新措施）",
        ],
        "special_clauses": [
            "LazMall 三重保证：Guaranteed Stock / Guaranteed Return / Guaranteed Delivery",
            "LazCash 补偿机制（15 天内领取，1 年有效期）",
            "东南亚六国本地化退货中心（印尼/泰国设跨境中心处理退货）",
            "Choice 计划卖家享更高曝光 + 退货优惠",
            '"无理由退款"标记仅在部分商品显示，非全品类支持',
        ],
        "capability_map": {
            "关键帧红框标注": "红框对比发出 vs 退回状态，LazMall Guaranteed Return 举证",
            "SKU 同款比对": "跨境订单证明发出-退回一致性（防调包）",
            "瑕疵聚类归因": "LazMall vs Marketplace 分层缺陷分析，品牌保护",
            "胜诉率参考": "LazMall Guaranteed Return 赔付率 + 退款时效",
            "取证卷宗": "归档 LazMall Claim Form + 退货凭证 + LOT 追溯",
        },
    },
    "Walmart": {
        "label": "Walmart",
        "return_window": "标准品 30 天（多数品类）；部分品类 90 天（无线电话/大型家电等例外更短）；旺季（10/1–12/31 购买）延长至次年 1 月 31 日",
        "response_window": "收到退货后 **48 小时**内确认并退款（逾期 Walmart 自动代退，计入 ODR 缺陷率）",
        "shipping_payer": "Walmart 过失（运输破损/丢失/错发）承担退货运费；否则卖家承担（含 return processing fee）；Keep It 规则可免退回",
        "burden_bias": "偏向买家（ODR<1% 红线极严；Walmart 可代表卖家拒绝/批准退货；Keep It 规则买家保留商品仍获退款）",
        "required_evidence": [
            "有效物流追踪码（17 位以上，Walmart 要求）",
            "退货签收入库记录 / 仓库扫描证明",
            "商品状况照片（退回时的实际状态 vs 发出时）",
            "采购发票 / 品牌授权（应对假货/知识产权投诉）",
            "Dispute 申诉材料（若对退货判定有异议）",
        ],
        "common_loss_reasons": [
            "超 48 小时未退款 → Walmart 自动代退 + ODR 扣分",
            "ODR >1% 连续两月 → 商品下架 / 店铺冻结",
            "无有效追踪码 → 丢失件判卖家责",
            "退回商品不可售状态（已使用/损坏）→ Keep It 场景下卖家损失商品 + 退款",
            "手动修改退款金额 → 触发财务审计",
        ],
        "special_clauses": [
            "ODR（Order Defect Rate）红线 <1%（建议 ≤0.8%）",
            "WFS（Walmart Fulfillment Services）：平台代管退货全流程，费用 $5.99/件",
            "Keep It Rule：按品类设置价格区间，买家保留商品仍获退款（防退回损耗）",
            "Free & Easy Returns 全渠道计划（线上/门店 ~5000 家店均可退）",
            '2026 年"一键通全球"：美国站卖家一键拓展加拿大/墨西哥/智利',
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注退回商品实际状况，支撑 Dispute 或 ODR 申诉",
            "SKU 同款比对": "WFS vs Seller Fulfilled 均适用：证明退回件即原商品",
            "瑕疵聚类归因": "按 WFS vs Seller Fulfilled 分层，ODR 驱动整改",
            "胜诉率参考": "ODR 趋势 + Dispute 成功率 + Keep It 规则命中率",
            "取证卷宗": "归档追踪码(17位)/签收/Dispute 材料，48h 退款窗口内就绪",
        },
    },
    "TikTok Shop": {
        "label": "TikTok Shop",
        "return_window": "标准 30 天（交付起）；质量问题/损坏 90 天 Money-Back Guarantee；节假日可延长（如 2025 黑五至 2026/2/10）",
        "response_window": "退货审核 ≤$100 为 2 日、>$100 为 4 日；取消请求 24h 内响应；纠纷升级 2-4 日（按金额）",
        "shipping_payer": "多数商品免费退货（55K 投递点 UPS/USPS/FedEx/Walgreens）；质量问题平台可能报销退货运费；商家可设自主退款不退货规则",
        "burden_bias": "平台主导（TikTok Shop 客服最终裁决；商家可申诉但需按标准仲裁流程；店铺停用时 TikTok 代处理全部退款）",
        "required_evidence": [
            "发货前商品完好照片/视频（原包装/标签/序列号）",
            "物流追踪号 + 签收证明",
            "商品与直播/短视频展示一致性证据（TikTok 特有：内容 vs 实物）",
            "与买家的站内沟通记录",
            "退货商品状态比对（退回时 vs 发出时，证明是否被调包/使用过）",
        ],
        "common_loss_reasons": [
            "2-4 日内未审核 → 系统自动批准退货/退款",
            "买家退回错误商品 → 商家需在 2-4 日内拒付并说明原因（否则默认通过）",
            "直播/短视频展示与实物严重不符 → 'Not as described' 高发区",
            "SFCR（商责取消率）过高 → 限流/降权",
            "退货商品已被使用/损坏 → 可反转退款但需强证据",
        ],
        "special_clauses": [
            "Money-Back Guarantee：90 天质量保障（即使标准退货窗已关闭）",
            "TikTok Shop Balance：虚拟余额即时退款（分钟级到账，替代传统支付 3-10 天）",
            "FBT（Fulfillment by TikTok）：平台仓发订单退货由 TikTok 代处理",
            "55K 线下投递点 + QR Code 免标签退货",
            "直播电商特有风险：主播口头承诺与 listing 不一致易引发纠纷",
            "禁止将交易引导至 TikTok 之外（违规处罚包括限流/关店）",
        ],
        "capability_map": {
            "关键帧红框标注": "红框标注直播展示 vs 实物差异（TikTok 特有高频纠纷源）",
            "SKU 同款比对": "直播电商高价值场景：证明实物与直播展示品一致",
            "瑕疵聚类归因": "直播话术 vs 实物偏差聚类，反哺主播培训",
            "胜诉率参考": "纠纷升级裁决率 + SFCR 趋势 + 90 天保障利用率",
            "取证卷宗": "归档直播截图/发货证据/沟通记录，2-4 日审核窗口内可用",
        },
    },
}


def get_platform_spec(key: str) -> dict[str, Any] | None:
    """按平台标识取规格；不存在返回 None。"""
    return EVIDENCE_SPECS.get(key)


def list_platforms() -> list[dict[str, Any]]:
    """返回全部平台规格（列表，按 PLATFORM_KEYS 顺序）。

    返回的是 EVIDENCE_SPECS 的浅拷贝并补 `key` 字段（原标识），
    便于前端/文档用稳定 key 关联（避免依赖 label==key 的脆弱耦合），
    且不污染源常量 EVIDENCE_SPECS。
    """
    out = []
    for k in PLATFORM_KEYS:
        if k in EVIDENCE_SPECS:
            spec = dict(EVIDENCE_SPECS[k])  # 浅拷贝，避免改到模块级常量
            spec["key"] = k
            out.append(spec)
    return out


def is_valid_platform(key: str) -> bool:
    """判断是否为受支持的平台标识。"""
    return key in EVIDENCE_SPECS
