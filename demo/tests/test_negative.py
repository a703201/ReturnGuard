"""负向 / 一致性测试（P3-3）：非法输入拦截、鉴权、幂等、确定性、XSS 防御纵深。

运行：DATABASE_URL=sqlite:///./_ci_cases.db REAL_DATABASE_URL=sqlite:///./_ci_cases_real.db python -m pytest tests/test_negative.py -q
"""

import json
import uuid

import main  # 用于 monkeypatch 代理信任列表
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


def test_analyze_bad_file_type_rejected(auth_headers):
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.txt", b"not an image", "text/plain"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"}, headers=auth_headers)
        assert r.status_code == 400


def test_import_csv_missing_sku_skipped():
    """CSV 缺 sku 的行必须跳过并计入 skipped，不落库、不崩。"""
    from importer import import_csv_text

    text = "sku,金额,结果\n,100,赢\nSKU-X,200,输\n"
    res = import_csv_text(text, "real")
    # 第一行缺 sku → skipped=1；第二行有 sku → imported=1
    assert res["imported"] == 1 and res["skipped"] == 1
    assert any("缺 sku" in e for e in res["errors"])


def test_import_csv_empty_rejected(auth_headers):
    with TestClient(app) as c:
        r = c.post("/api/import_csv", data={"csv_text": "   "}, headers=auth_headers)
        assert r.status_code == 400


# ---------------- 一致性：相同输入 → 相同输出（mock 确定性） ----------------


def test_mock_analyze_deterministic(auth_headers):
    """同一对图片 + 同一 SKU，两次 mock 取证应得到完全相同的相似度与缺陷标签（确定性、可复现）。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        data = {"sku": "SKU-DET", "amount": "120", "mode": "mock"}
        r1 = c.post("/api/analyze", files=dict(files), data=data, headers=auth_headers).json()
        r2 = c.post("/api/analyze", files=dict(files), data=data, headers=auth_headers).json()
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


def test_xss_payload_stored_not_executed(auth_headers):
    """恶意 SKU（含 <script>）可被正常录入（后端 JSON 安全转义，无注入执行）；
    前端已用 esc() 转义渲染；此处验证接口不崩且原样（安全）存返。"""
    with TestClient(app) as c:
        payload = "<script>alert(1)</script>"
        r = c.post(
            "/api/cases",
            json={"sku": payload, "category": "3C数码", "supplier": "S3"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        # 取回列表，确认后端未做危险处理（JSON 本身是安全载体）
        lst = c.get("/api/cases", params={"slim": "1"}).json()
        assert any(x.get("sku") == payload for x in lst)


# ---------------- 鉴权：写接口在设 Key 后必须校验 ----------------


def test_calibrate_requires_admin_key(monkeypatch):
    """安全复审 SEC-1：/api/calibrate 这类会改写全局判定阈值的管理动作，必须管理员密钥。

    设了 ADMIN_API_KEY 后，匿名（无密钥）→ 401；带 X-Admin-Key → 通过（样本不足则不落盘）。
    避免任何人匿名覆写胜诉率判定逻辑。"""
    monkeypatch.setattr(main, "_ADMIN_KEY", "admin-secret")
    with TestClient(app) as c:
        # 匿名（无 ADMIN_KEY）→ 401
        r1 = c.post("/api/calibrate", json={"same_sims": [0.9], "diff_sims": [0.2]})
        assert r1.status_code == 401
        # 带 ADMIN_KEY → 通过（样本不足 → saved=False，不落盘、不污染既有标定）
        r2 = c.post(
            "/api/calibrate",
            json={"same_sims": [], "diff_sims": []},
            headers={"X-Admin-Key": "admin-secret"},
        )
        assert r2.status_code == 200 and r2.json()["saved"] is False


# ---------------- 防御纵深：代理感知 IP / 去枚举 ----------------


class _StubRequest:
    """最小请求桩，用于直接验证 get_client_ip 的代理感知逻辑。"""

    class _Addr:
        def __init__(self, host):
            self.host = host

    def __init__(self, direct, xff="", xri=""):
        self.client = self._Addr(direct) if direct else None
        self.headers = {}
        if xff:
            self.headers["X-Forwarded-For"] = xff
        if xri:
            self.headers["X-Real-IP"] = xri


def test_get_client_ip_proxy_aware(monkeypatch):
    """仅当直连属于可信代理时才采纳 X-Forwarded-For / X-Real-IP；否则用直连 IP（防伪造绕过限流）。"""
    monkeypatch.setattr(main, "_AUTH_TRUSTED_PROXIES", ["127.0.0.1/32"])
    assert main.get_client_ip(_StubRequest("127.0.0.1", xff="9.9.9.9, 10.0.0.1")) == "9.9.9.9"
    assert main.get_client_ip(_StubRequest("127.0.0.1", xri="8.8.8.8")) == "8.8.8.8"
    # 未配置可信代理 → 忽略转发头
    monkeypatch.setattr(main, "_AUTH_TRUSTED_PROXIES", [])
    assert main.get_client_ip(_StubRequest("127.0.0.1", xff="9.9.9.9")) == "127.0.0.1"
    # 直连不在可信列表 → 不采纳
    monkeypatch.setattr(main, "_AUTH_TRUSTED_PROXIES", ["10.0.0.0/8"])
    assert main.get_client_ip(_StubRequest("127.0.0.1", xff="9.9.9.9")) == "127.0.0.1"


def test_duplicate_register_generic(monkeypatch):
    """重名注册返回泛化 400，不泄露'用户名已存在'（消除用户名枚举）。"""
    monkeypatch.setattr(main, "_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(main, "_REGISTRATION_INVITE_CODE", "")
    with TestClient(app) as c:
        u = "dup_" + uuid.uuid4().hex[:6]
        assert c.post("/api/auth/register", json={"username": u, "password": "secret123"}).status_code == 200
        r2 = c.post("/api/auth/register", json={"username": u, "password": "secret123"})
        assert r2.status_code == 400
        assert "用户名已存在" not in r2.json().get("detail", "")
