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
    """单张退货图上的缺陷示意框（归一化坐标 0~1，前端按比例绘制）。"""

    label: str
    x: float
    y: float
    w: float
    h: float


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
    returned_image_b64: str = ""
    case_id: str = ""
    mode: str = "mock"
    error: str | None = None


class InsightsResponse(BaseModel):
    """GET /api/insights 的响应（群体洞察看板）。

    显式声明核心标量字段以保证类型；其余聚合字段（category_heatmap /
    supplier_scorecard / platform_view / platform_supplier_matrix / sku_ranking /
    anomaly_alerts / recommendations 等）通过 extra="allow" 透传，兼容现有前端。
    """

    model_config = ConfigDict(extra="allow")

    total_cases: int = 0
    total_refund: float = 0.0
    win_rate: float = 0.0
    avg_dispute_rate: float = 0.0
    outcome_dist: dict[str, int] = {}
