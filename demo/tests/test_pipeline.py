"""pipeline 层单测：mock 确定性、结果结构、聚合洞察字段、上传单案去污染（P1-1）。"""

import os
import tempfile

from db import init_db, load_cases
from pipeline import analyze_case, build_insights, invalidate_insights_cache


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


def test_aggregate_excludes_pending_from_winrate():
    """P1-1：『待分析』单案不污染聚合——胜诉率只按已判定案件算，且缺失维度不入噪声桶。"""
    invalidate_insights_cache()
    cases = []
    for _ in range(5):
        cases.append({"outcome": "赢", "category": "3C数码", "supplier": "S1",
                      "platform": "Amazon", "similarity": 0.9, "amount": 100,
                      "defect_tags": ["无明显瑕疵"], "sku": "A"})
    for _ in range(5):
        cases.append({"outcome": "输", "category": "3C数码", "supplier": "S1",
                      "platform": "Amazon", "similarity": 0.9, "amount": 100,
                      "defect_tags": ["无明显瑕疵"], "sku": "A"})
    # 5 笔待分析且缺失品类/供应商/平台维度
    for _ in range(5):
        cases.append({"outcome": "待分析", "category": "", "supplier": "",
                      "platform": "", "similarity": 0.9, "amount": 100,
                      "defect_tags": ["无明显瑕疵"], "sku": "B"})
    ins = build_insights(cases, "mock")
    assert ins["total_cases"] == 15
    assert abs(ins["win_rate"] - 0.5) < 1e-6, "胜诉率应只按 10 笔已判定(5赢5输)=0.5"
    assert ins["outcome_dist"].get("待分析") == 5, "待分析应单独分组"
    assert all(x["category"] != "未分类" for x in ins["category_heatmap"]), "不应出现未分类噪声桶"
    assert all(x["supplier"] != "未知" for x in ins["supplier_scorecard"]), "不应出现未知供应商"
    assert all(x["platform"] != "未知" for x in ins["platform_view"]), "不应出现未知平台"
