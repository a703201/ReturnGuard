"""ReturnGuard · 接口契约（Pydantic 请求/响应模型）

给 FastAPI 端点挂上 response_model，收益：
    1) 自动校验与序列化，前端拿到稳定结构；
    2) OpenAPI 文档自动生成（/docs 可见字段与类型）；
    3) 后端返回裸 dict 时的「隐性契约」变成显式、可类型检查。

设计：聚合洞察字段多且部分为动态派生，InsightsResponse 用 extra="allow"
保留未显式声明但前端依赖的字段（platform_supplier_matrix 等），不破坏现有前端。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DefectBox(BaseModel):
    """单张退货图上的缺陷示意框（归一化坐标 0~1，前端按比例绘制）。

    confidence 为示意置信度（mock 由确定性哈希生成，live 接通视觉模型后为真实分数），
    用于让「关键帧红框」更接近真实检测呈现；无论真假都标注为「演示示意」，不替代平台裁决。
    """

    label: str
    x: float
    y: float
    w: float
    h: float
    confidence: float = 0.0


class AnalyzeResult(BaseModel):
    """POST /api/analyze 的响应（单案取证结果）。"""

    model_config = ConfigDict(extra="allow")

    similarity: float
    same_item: bool
    defect_tags: list[str] = []
    defect_description: str | None = None
    consistency: str | None = None
    dossier: str | None = None
    voice_text: str | None = None
    voice_audio_b64: str | None = None
    priority_score: float
    defect_boxes: list[DefectBox] = []
    # 红框是否来自真实视觉模型：True=live 真实坐标框，False=live 回退示意框 / mock 演示框。
    # 前端据此区分红框(真实)与琥珀色示意框(回退)，如实呈现、不替代平台裁决。
    defect_boxes_live: bool = False
    # 退回图访问地址（/uploads/<文件名>），前端据此加载做红框标注；
    # 用 URL 替代整图 base64，避免 10MB 图塞进 JSON 撑大响应（P3-5）。
    returned_image_url: str = ""
    case_id: str = ""
    platform: str = ""
    platform_evidence: list[str] = []
    mode: str = "mock"
    error: str | None = None
    # live 模式逐能力真实/回退标记（similarity/defects/ocr/tts），便于演示说明哪些走了真实模型
    capabilities: dict[str, bool] = {}


class InsightsResponse(BaseModel):
    """GET /api/insights 的响应（群体洞察看板）。

    显式声明全部核心聚合字段（类型化契约，便于 OpenAPI 文档与前端的强类型消费）；
    另保留 extra="allow" 作为受控逃生口，兼容未来新增的派生字段，避免破环前端。
    """

    model_config = ConfigDict(extra="allow")

    total_cases: int = 0
    total_refund: float = 0.0
    win_rate: float = 0.0
    avg_dispute_rate: float = 0.0
    # 代理指标说明：avg_dispute_rate 实为由"退货图与本店主图相似度"推算的代理值，
    # 并非平台标记的争议笔数。前端须据实呈现，避免误导为真实争议率。
    dispute_rate_note: str = ""
    outcome_dist: dict[str, int] = {}
    # —— 以下聚合维度显式声明，构成稳定契约 ——
    category_heatmap: list[dict] = []
    supplier_scorecard: list[dict] = []
    platform_view: list[dict] = []
    platform_supplier_matrix: list[dict] = []
    sku_ranking: list[dict] = []
    anomaly_alerts: list[dict] = []
    root_cause_dist: dict[str, int] = {}
    root_cause: str = ""
    sourcing_advice: list[str] = []
    recommendations: list[str] = []
    report: str = ""
    sku_insights: list[dict] = []
    # —— 维度扩展（方向2）：地区 / 季节交叉 + 退货成本估算 + 供应商黑名单自动生成 ——
    region_view: list[dict] = []
    season_view: list[dict] = []
    supplier_blacklist: list[dict] = []
    logistics_cost: float = 0.0
    total_return_cost: float = 0.0
    mode: str = "mock"
    error: str | None = None


class ManualCase(BaseModel):
    """POST /api/cases 的请求体（网页「数据录入」手动添加的实际退货案件）。

    字段与 Case 表对齐；均带默认值，未填字段落库为缺省值（聚合时按 P1-1 规则跳过噪声桶）。
    缺陷标签以字符串数组传入；缺省给「无明显瑕疵」占位，避免聚合索引报错。
    """

    sku: str
    sku_name: str = ""
    category: str = ""
    supplier: str = ""
    supplier_name: str = ""
    platform: str = ""
    language: str = "zh"
    region: str = ""
    amount: float = 0.0
    date: str = ""
    similarity: float = 0.0
    same_item: bool = True
    defect_tags: list[str] = []
    defect_description: str = ""
    consistency: str = ""
    outcome: str = ""
    mode: str = "manual"
    listing_text: str = ""
    priority_score: float = 0.0
    returned_image: str = ""
    product_image: str = ""
