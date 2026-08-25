"""ReturnGuard · 提示词集中管理（live 模式）

把 models_router 里散落的内联 prompt 统一抽到这里，按「方案功能编号 + 编排层级」组织，
便于评审、调参与录屏讲解。所有函数返回可直接喂给大模型（chat/completions 的 user 消息）的字符串。

约定：
- 视觉 / OCR 类：模型走多模态，prompt 作为文本指令随图一起发送。
- 文本类：单条 user 消息即完整 prompt（含角色设定与输出格式）。
- 所有「只返回 JSON」的接口都要求纯 JSON、禁止解释文本，配合 models_router._extract_json 稳健解析。
"""

from __future__ import annotations

import json
from typing import Any

# ===================== ① 同款一致性比对（图像向量）=====================
# 该能力走 embeddings 接口，无自然语言 prompt（输入为图片 URL）。


# ===================== ② 瑕疵视觉识别（多模态）=====================
DEFECT_RECOGNITION_PROMPT = (
    "你是一名严苛的跨境电商质检员，正在核查一笔退货商品的外观。"
    "请仔细观察图片，只关注与「买家退货原因」相关的视觉瑕疵，"
    "优先从以下类别中判定：外包装破损、缺件/少配件、污渍/水渍、使用痕迹、"
    "功能故障、颜色不符、材质不符、仿冒/假货、吊牌/标签缺失。"
    "用逗号分隔的简短中文标签列出你确认存在的瑕疵（每个标签不超过 6 个字）。"
    "不要输出任何解释、序号或英文。若图片中无明显瑕疵，只输出：无明显瑕疵。"
)


# ===================== ③ listing 承诺提取（OCR / 多模态）=====================
OCR_PROMISE_PROMPT = (
    "请提取图片中本店对该商品的「销售承诺/卖点文字」，例如：全新未拆封、"
    "支持 30 天无理由退换、原装正品、防水防摔等。"
    "只输出承诺相关的关键短句，用逗号分隔；若图中无文字承诺，只输出：无明确承诺。"
)


# ===================== ④ 文本生成 / 推理 =====================
# 4a. 货不对板一致性核验
def consistency_prompt(similarity: float, defects: list[str], promise: str) -> str:
    defect_str = "、".join(defects) if defects else "无明显瑕疵"
    return (
        "你是一名跨境退货一致性核验员，职责是客观描述退回件与卖家承诺之间的差异程度，"
        "不做责任判定或纠纷裁决。请基于下列事实给出一致性评估。\n"
        "事实：\n"
        f"- 退回件与本店主图相似度：{similarity:.2f}（越接近 1 越可能是同一件）\n"
        f"- 肉眼可见瑕疵：{defect_str}\n"
        f"- 本店承诺/商品描述：{promise or '（未提供）'}\n\n"
        "请先给一句话结论（严格使用格式：「一致性：高/中/低。」），"
        "随后用一句话说明最关键的客观依据。不要罗列、不要解释模型原理、不做责任归属判断。"
    )


# 4b. 结构化举证卷宗
def dossier_prompt(sku: str, similarity: float, defects: list[str], consistency: str) -> str:
    defect_str = "、".join(defects) if defects else "无明显瑕疵"
    return (
        "你是一名专业的跨境卖家维权助理。请为下面这笔退货生成一段「举证卷宗」正文，"
        "用于向平台申诉或内部归档。要求事实清楚、用词克制、不夸大。\n"
        f"案件要素：\n- SKU：{sku}\n- 相似度：{similarity:.2f}\n"
        f"- 瑕疵：{defect_str}\n- 一致性结论：{consistency}\n\n"
        "卷宗请包含四小节（用换行分隔，不要序号标题符号喧宾夺主）：\n"
        "事实摘要 / 相似度结论 / 瑕疵清单 / 建议动作。控制在 200 字以内。"
    )


# 4c. 母语口头陈述（TTS 前置文本）
def voice_prompt(similarity: float, defects: list[str]) -> str:
    defect_str = "、".join(defects) if defects else "无明显瑕疵"
    return (
        "你正在帮助一位中国跨境卖家，就一笔退货向平台用母语做一段口头举证陈述。"
        "请用第一人称、口语化、有说服力但实事求是，面向平台仲裁人员。\n"
        f"要点：退回件相似度 {similarity:.2f}，主要问题：{defect_str}。\n"
        "请生成一段 60 字以内的中文陈述，不要称呼、不要标点堆砌，可直接朗读。"
    )


# ===================== ⑤ 案件优先级重排（rerank）=====================
# 该能力走 rerank 结构化接口（query + documents），无自由文本 prompt。


# ===================== ⑥ 母语语音合成（TTS）=====================
# 输入为上面 voice_prompt 生成的文本，无独立 prompt。


# ===================== 群体洞察（阶段B）LLM 归因 =====================
INSIGHTS_SYSTEM_PERSONA = (
    "你是一名资深的跨境电商品控与选品分析师，服务对象是中小跨境卖家管理者。"
    "你只基于提供的数据说话，不编造数字，不夸大；建议必须可执行、可落地。\n"
    "重要边界：你的职责是「数据驱动的选品避坑与品控改进建议」，不做纠纷裁决、"
    "不给法律意见、不判定责任归属（如「买家责任」「卖家全责」等）。"
    "胜诉率（win_rate）仅作为参考指标反映历史纠纷结果分布，不代表选品成功率或未来预期。"
)


def build_insights_prompt(aggregated: dict[str, Any]) -> str:
    """把聚合统计组装成一段结构化 JSON 输出 prompt。

    返回的 prompt 要求模型以纯 JSON 返回五部分：
    root_cause / sku_insights / recommendations / sourcing_advice / report。
    上下文在 pipeline._aggregate 已算好的基础上，额外带入退款额、胜率、
    品类热力、供应商红黑榜、异常预警、地区/季节等维度，让 LLM 归因更有依据。

    sourcing_advice 与 recommendations 的区别（避免前端/用户混淆）：
    - recommendations 偏「选品 / 品控 / 策略建议」（方向性）；
    - sourcing_advice 偏「卖家管理者下一步就要执行的具体动作」（待办清单，
      强调谁 + 做什么 + 量化目标/期限），直接喂给 ⑧「下一步怎么做」卡片。
    """
    ctx = {
        "total_cases": aggregated.get("total_cases"),
        "total_refund": aggregated.get("total_refund"),
        "win_rate": aggregated.get("win_rate"),
        "sku_ranking": aggregated.get("sku_ranking"),
        "defect_distribution": aggregated.get("defect_distribution"),
        "category_heatmap": aggregated.get("category_heatmap"),
        "supplier_scorecard": aggregated.get("supplier_scorecard"),
        "anomaly_alerts": aggregated.get("anomaly_alerts"),
        "region_view": aggregated.get("region_view"),
        "season_view": aggregated.get("season_view"),
    }
    ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    return (
        f"{INSIGHTS_SYSTEM_PERSONA}\n\n"
        "下面是一位跨境卖家退货案件的聚合统计（JSON）：\n"
        f"{ctx_json}\n\n"
        "请完成五件事，并以**纯 JSON**返回（不要任何解释文本、不要 markdown 围栏，只返回可解析的 JSON 对象）：\n"
        "1) root_cause：字符串。归纳退货高发的根因（如包装防护不足 / 供应商质量不稳定 / "
        "listing 过度承诺 / 物流暴力分拣等），并给出对应的数据依据（引用上面 JSON 中的具体数字）。\n"
        "   注意：根因归因限于「供应链与运营环节」的质量/履约/包装/图文层面，不涉及买家行为揣测或责任判定。\n"
        "2) sku_insights：数组，取退款金额最高的前 3 个 SKU。每个元素为 "
        '{"sku": 字符串, "finding": 字符串（该 SKU 核心问题，含数据）, "action": 字符串（可执行整改动作）}。\n'
        "3) recommendations：数组，3-5 条可执行的选品 / 品控 / listing 改写**策略建议**，面向卖家管理者，"
        "每条一句话、可落地（偏方向性）。引用胜诉率时仅作为「历史纠纷结果分布参考」，不当作选品成功率预测。\n"
        "4) sourcing_advice：数组，3-5 条**下一步的具体执行动作**（喂给「下一步怎么做」卡片）。"
        "与 recommendations 的区别：这里是「马上要做的待办清单」，每条强调「谁 + 做什么 + 量化目标/期限」，"
        "例如「对 S3、S6 两家高风险供应商启动备用供应链引入，2 周内完成比价」。每条一句话。\n"
        "5) report：字符串，一段《选品 / 品控洞察报告》正文（中文，150-220 字），"
        "总结现状、点明根因、给出下一步，语言正式但不浮夸。"
        "聚焦「数据驱动的选品避坑与品控改进」，不涉及纠纷裁决或责任判定。\n"
    )
