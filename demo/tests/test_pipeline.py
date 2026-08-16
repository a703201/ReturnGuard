"""pipeline 层单测：mock 确定性、结果结构、聚合洞察字段。"""

import os
import tempfile

from db import init_db, load_cases
from pipeline import analyze_case, build_insights


def _png(name: str) -> str:
    p = os.path.join(tempfile.gettempdir(), name)
    with open(p, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n minimal")
    return p


def test_mock_deterministic():
    a, b = _png("rg_a.png"), _png("rg_b.png")
    r1 = analyze_case(a, b, "", "SKU-X", 100, "mock")
    r2 = analyze_case(a, b, "", "SKU-X", 100, "mock")
    assert r1["similarity"] == r2["similarity"]
    assert r1["defect_tags"] == r2["defect_tags"]
    assert 0.0 <= r1["similarity"] <= 1.0


def test_analyze_result_shape():
    a, b = _png("rg_a.png"), _png("rg_b.png")
    r = analyze_case(a, b, "", "SKU-X", 100, "mock")
    for k in ("similarity", "same_item", "defect_tags", "priority_score", "defect_boxes", "mode"):
        assert k in r
    assert r["mode"] == "mock"
    assert isinstance(r["defect_boxes"], list)


def test_insights_fields():
    init_db()
    cases = load_cases()
    ins = build_insights(cases, "mock")
    assert ins["total_cases"] > 0
    assert "platform_supplier_matrix" in ins
    assert (
        isinstance(ins["platform_supplier_matrix"], list)
        and len(ins["platform_supplier_matrix"]) > 0
    )
    assert ins["win_rate"] >= 0
    assert ins.get("recommendations"), "应给出选品/品控建议"
