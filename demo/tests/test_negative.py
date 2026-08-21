"""负向 / 一致性测试（P3-3）：非法输入拦截、鉴权、幂等、确定性、XSS 防御纵深。

运行：DATABASE_URL=sqlite:///./_ci_cases.db REAL_DATABASE_URL=sqlite:///./_ci_cases_real.db python -m pytest tests/test_negative.py -q
"""

import json

from fastapi.testclient import TestClient
from main import app


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n minimal"


# ---------------- 负向：非法输入必须被 4xx 拦截（不静默返回空看板） ----------------


def test_invalid_mode_rejected():
    with TestClient(app) as c:
        assert c.get("/api/insights", params={"mode": "evil"}).status_code == 400


def test_invalid_platform_rejected():
    with TestClient(app) as c:
        assert (
            c.get("/api/insights", params={"mode": "mock", "platform": "淘宝"}).status_code == 400
        )


def test_invalid_season_rejected():
    with TestClient(app) as c:
        assert (
            c.get("/api/insights", params={"mode": "mock", "season": "monsoon"}).status_code == 400
        )


def test_blank_category_rejected():
    with TestClient(app) as c:
        assert c.get("/api/insights", params={"mode": "mock", "category": "   "}).status_code == 400


def test_analyze_bad_file_type_rejected():
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.txt", b"not an image", "text/plain"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"})
        assert r.status_code == 400


def test_import_csv_missing_sku_skipped():
    """CSV 缺 sku 的行必须跳过并计入 skipped，不落库、不崩。"""
    from importer import import_csv_text

    text = "sku,金额,结果\n,100,赢\nSKU-X,200,输\n"
    res = import_csv_text(text, "real")
    # 第一行缺 sku → skipped=1；第二行有 sku → imported=1
    assert res["imported"] == 1 and res["skipped"] == 1
    assert any("缺 sku" in e for e in res["errors"])


def test_import_csv_empty_rejected():
    with TestClient(app) as c:
        r = c.post("/api/import_csv", data={"csv_text": "   "})
        assert r.status_code == 400


# ---------------- 一致性：相同输入 → 相同输出（mock 确定性） ----------------


def test_mock_analyze_deterministic():
    """同一对图片 + 同一 SKU，两次 mock 取证应得到完全相同的相似度与缺陷标签（确定性、可复现）。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        data = {"sku": "SKU-DET", "amount": "120", "mode": "mock"}
        r1 = c.post("/api/analyze", files=dict(files), data=data).json()
        r2 = c.post("/api/analyze", files=dict(files), data=data).json()
        assert r1["similarity"] == r2["similarity"]
        assert r1["defect_tags"] == r2["defect_tags"]
        assert r1["same_item"] == r2["same_item"]


def test_insights_deterministic():
    """同一过滤条件下两次洞察聚合结果一致（含 B组 time_series/forecast/sourcing_checklist）。"""
    with TestClient(app) as c:
        a = c.get("/api/insights", params={"mode": "mock", "category": "3C数码"}).json()
        b = c.get("/api/insights", params={"mode": "mock", "category": "3C数码"}).json()
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        # B组新增字段在一致性响应中稳定存在
        assert {"time_series", "forecast", "sourcing_checklist", "forecast_alerts"} <= set(a)


# ---------------- 防御纵深：安全响应头（P1-3） ----------------


def test_security_headers_present():
    with TestClient(app) as c:
        h = c.get("/").headers
        assert "Content-Security-Policy" in h
        assert h.get("X-Content-Type-Options") == "nosniff"
        assert h.get("Referrer-Policy") == "no-referrer"


def test_xss_payload_stored_not_executed():
    """恶意 SKU（含 <script>）可被正常录入（后端 JSON 安全转义，无注入执行）；
    前端已用 esc() 转义渲染；此处验证接口不崩且原样（安全）存返。"""
    with TestClient(app) as c:
        payload = "<script>alert(1)</script>"
        r = c.post(
            "/api/cases",
            json={"sku": payload, "category": "3C数码", "supplier": "S3"},
        )
        assert r.status_code == 200
        # 取回列表，确认后端未做危险处理（JSON 本身是安全载体）
        lst = c.get("/api/cases", params={"slim": "1"}).json()
        assert any(x.get("sku") == payload for x in lst)


# ---------------- 鉴权：写接口在设 Key 后必须校验 ----------------


def test_write_requires_api_key_when_set(monkeypatch):
    monkeypatch.setattr("main._API_KEY", "secret-key")
    with TestClient(app) as c:
        # 无 Key → 401
        r1 = c.post("/api/cases", json={"sku": "SKU-AUTH", "category": "饰品配件"})
        assert r1.status_code == 401
        # 带 Key → 通过
        r2 = c.post(
            "/api/cases",
            json={"sku": "SKU-AUTH2", "category": "饰品配件"},
            headers={"X-API-Key": "secret-key"},
        )
        assert r2.status_code == 200
