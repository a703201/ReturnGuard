"""平台适配举证包单测：规则引擎 + /api/platforms + analyze 关联 + insights 维度筛选。"""

from fastapi.testclient import TestClient
from main import app
from platforms import CAPABILITY_KEYS, PLATFORM_KEYS, get_platform_spec, list_platforms


def test_list_platforms_four():
    ps = list_platforms()
    assert len(ps) == 4
    assert [p["label"] for p in ps] == PLATFORM_KEYS


def test_spec_has_required_fields():
    for key in PLATFORM_KEYS:
        s = get_platform_spec(key)
        assert s, f"缺失平台规格: {key}"
        for f in (
            "return_window",
            "response_window",
            "shipping_payer",
            "burden_bias",
            "required_evidence",
            "common_loss_reasons",
            "special_clauses",
            "capability_map",
        ):
            assert f in s, f"{key} 缺字段 {f}"
        assert isinstance(s["required_evidence"], list) and s["required_evidence"]


def test_capability_map_uses_known_keys():
    for key in PLATFORM_KEYS:
        cap = get_platform_spec(key)["capability_map"]
        assert set(cap.keys()) <= set(CAPABILITY_KEYS), f"{key} 引用了未定义能力"


def test_api_platforms_endpoint():
    with TestClient(app) as c:
        r = c.get("/api/platforms")
        assert r.status_code == 200
        ps = r.json()["platforms"]
        assert len(ps) == 4
        assert ps[0]["label"] in PLATFORM_KEYS
        assert all("key" in p for p in ps), "每个平台规格都应带稳定 key 字段"


def test_analyze_attaches_platform_evidence():
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", b"\x89PNG\r\n\x1a\n x", "image/png"),
            "product_image": ("prod.png", b"\x89PNG\r\n\x1a\n y", "image/png"),
        }
        r = c.post(
            "/api/analyze",
            files=files,
            data={"sku": "SKU-PT", "amount": "120", "platform": "Amazon", "mode": "mock"},
        )
        assert r.status_code == 200
        d = r.json()
        assert d["platform"] == "Amazon"
        assert d["platform_evidence"], "应随单返回该平台必备举证材料清单"


def test_analyze_invalid_platform_400():
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", b"\x89PNG\r\n\x1a\n x", "image/png"),
            "product_image": ("prod.png", b"\x89PNG\r\n\x1a\n y", "image/png"),
        }
        r = c.post(
            "/api/analyze",
            files=files,
            data={"sku": "SKU-PT", "platform": "不存在的平台", "mode": "mock"},
        )
        assert r.status_code == 400


def test_insights_platform_filter():
    with TestClient(app) as c:
        r = c.get("/api/insights", params={"mode": "mock", "platform": "Amazon"})
        assert r.status_code == 200
        # 筛选后平台视图只含 Amazon，且其案件数 > 0（种子数据含 Amazon）
        pv = r.json()["platform_view"]
        assert pv and all(x["platform"] == "Amazon" for x in pv)
        assert pv[0]["cases"] > 0


def test_insights_invalid_platform_400():
    # S1：非法 platform 应 400，而非静默返回空看板
    with TestClient(app) as c:
        r = c.get("/api/insights", params={"mode": "mock", "platform": "不存在的平台"})
        assert r.status_code == 400


def test_insights_dispute_rate_is_proxy():
    # S2：avg_dispute_rate 须带代理指标说明，避免被误读为平台真实争议率
    with TestClient(app) as c:
        r = c.get("/api/insights", params={"mode": "mock"})
        assert r.status_code == 200
        d = r.json()
        assert "dispute_rate_note" in d and d["dispute_rate_note"]
        assert 0 <= d["avg_dispute_rate"] <= 1
