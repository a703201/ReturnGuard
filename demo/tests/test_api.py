"""API 层单测：用 FastAPI TestClient 打健康路径（不依赖外部模型 Key）。"""

from fastapi.testclient import TestClient
from main import app


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n minimal"


def test_health():
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_insights_mock():
    with TestClient(app) as c:
        r = c.get("/api/insights", params={"mode": "mock"})
        assert r.status_code == 200
        d = r.json()
        assert d["total_cases"] > 0
        assert d["win_rate"] >= 0


def test_analyze_mock():
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post(
            "/api/analyze", files=files, data={"sku": "SKU-T1", "amount": "120", "mode": "mock"}
        )
        assert r.status_code == 200
        d = r.json()
        assert "similarity" in d and "defect_boxes" in d
        # P3-5：退回图用 URL 访问，不再内联整图 base64
        assert d["returned_image_url"].startswith("/uploads/"), "退回图应回传可访问 URL"


def test_analyze_persists_dimensions():
    """P1-1 / P3-3：上传带 category+supplier 的单案应干净落库，且 outcome 标记为『待分析』，
    不污染已判定案件的胜诉率分母。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post(
            "/api/analyze",
            files=files,
            data={
                "sku": "SKU-T2",
                "amount": "120",
                "category": "3C数码",
                "supplier": "S3",
                "mode": "mock",
            },
        )
        assert r.status_code == 200
        d = r.json()
        assert d["outcome"] == "待分析"
        # 落库后在案件库中应能查到该单并带维度
        cases = c.get("/api/cases").json()
        mine = [x for x in cases if x.get("sku") == "SKU-T2"]
        assert mine, "上传单案应进入案件库"
        saved = mine[0]
        assert saved["category"] == "3C数码"
        assert saved["supplier"] == "S3"
        assert saved["outcome"] == "待分析"


def test_config_exposes_threshold():
    """P2-4：前端/生成器共享的常量应从单一来源 /api/config 暴露（同款阈值）。"""
    with TestClient(app) as c:
        r = c.get("/api/config")
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d.get("same_item_threshold"), (int, float))
        assert 0 < d["same_item_threshold"] <= 1


def test_metrics_endpoint():
    """P2-9：基础运行指标端点可用，返回 uptime / 请求量 / 错误数等。"""
    with TestClient(app) as c:
        r = c.get("/metrics")
        assert r.status_code == 200
        d = r.json()
        for k in ("uptime_seconds", "requests", "avg_latency_ms", "errors_5xx",
                  "analyze_count", "insights_count"):
            assert k in d, f"metrics 缺少字段 {k}"
