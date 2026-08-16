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
        assert d["returned_image_b64"], "退回图应回传 base64 供红框预览"
