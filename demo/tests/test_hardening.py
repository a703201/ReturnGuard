"""边界与健壮性加固回归测试（2.0.0 功能完善项）。

覆盖此轮新增的两类改动：
  1. **配额闸覆盖面**：SEC-13 的 live 配额闸此前只挂在 `/api/analyze` 上，
     `/api/insights?mode=live` 与 `/api/export_pdf?mode=live` 可绕开闸门消耗付费 Key；
     现统一在 `common._get_insights` 内收口。
  2. **入参边界**：分页上下界、字段长度、金额有限性、CSV 文本体积、标定样本量、
     PDF 导出限流；以及持久层的 `_clamp_values`（CSV/xlsx 导入的最后一道防线）。

另含 real 源连接串推导的隔离回归（此前 `REAL_DATABASE_URL` 默认等于 demo 库）。

不依赖外部模型 Key、不访问网络。
"""

from __future__ import annotations

import db
from fastapi.testclient import TestClient
from main import app


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n minimal"


# ---------------------------------------------------------------- 配额闸覆盖面


def test_live_insights_respects_quota(monkeypatch):
    """live 洞察同样受 SEC-13 配额约束：第 2 次请求应 429，而不是无限消耗 Key。"""
    monkeypatch.setenv("LIVE_QUOTA_GLOBAL_DAY", "1")
    with TestClient(app) as c:
        first = c.get("/api/insights", params={"mode": "live"})
        assert first.status_code == 200, first.text
        second = c.get("/api/insights", params={"mode": "live"})
        assert second.status_code == 429, "live 洞察应受配额闸约束"
        assert "配额" in second.json()["detail"]


def test_mock_insights_unaffected_by_quota(monkeypatch):
    """mock 模式不消耗付费额度，故不受 live 配额闸影响（否则演示会被误挡）。"""
    monkeypatch.setenv("LIVE_QUOTA_GLOBAL_DAY", "1")
    with TestClient(app) as c:
        c.get("/api/insights", params={"mode": "live"})
        r = c.get("/api/insights", params={"mode": "mock"})
        assert r.status_code == 200


def test_export_pdf_rate_limited(monkeypatch):
    """PDF 导出为 CPU 重的同步任务，需按 IP 限流。"""
    from routers import insights as insights_router

    monkeypatch.setattr(insights_router, "_EXPORT_PDF_LIMIT", 1)
    with TestClient(app) as c:
        assert c.get("/api/export_pdf", params={"mode": "mock"}).status_code == 200
        second = c.get("/api/export_pdf", params={"mode": "mock"})
        assert second.status_code == 429


# ---------------------------------------------------------------- 分页与字段边界


def test_cases_pagination_bounds():
    """page < 1 / page_size > 200 应被拒绝（422），而不是静默钳制或超量拉库。"""
    with TestClient(app) as c:
        assert c.get("/api/cases", params={"page": 0}).status_code == 422
        assert c.get("/api/cases", params={"page_size": 1000}).status_code == 422
        assert c.get("/api/cases", params={"page": 1, "page_size": 200}).status_code == 200


def test_manual_case_field_limits(auth_headers):
    """手动录入的超长 SKU / 负金额应在 schema 层被拒（422），不再等数据库报错。"""
    with TestClient(app) as c:
        too_long = c.post("/api/cases", json={"sku": "S" * 65}, headers=auth_headers)
        assert too_long.status_code == 422
        negative = c.post("/api/cases", json={"sku": "SKU-OK", "amount": -1}, headers=auth_headers)
        assert negative.status_code == 422
        bad_sim = c.post(
            "/api/cases", json={"sku": "SKU-OK", "similarity": 1.5}, headers=auth_headers
        )
        assert bad_sim.status_code == 422


def test_analyze_rejects_invalid_amount_and_long_sku(auth_headers):
    """取证接口的金额必须有限且非负；SKU 超列长直接 400。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        neg = c.post(
            "/api/analyze",
            files=files,
            data={"sku": "SKU-NEG", "amount": "-5", "mode": "mock"},
            headers=auth_headers,
        )
        assert neg.status_code == 400
        long_sku = c.post(
            "/api/analyze",
            files=files,
            data={"sku": "S" * 65, "amount": "10", "mode": "mock"},
            headers=auth_headers,
        )
        assert long_sku.status_code == 400


def test_import_csv_text_size_limited(monkeypatch, auth_headers):
    """表单直贴的大型 CSV 文本应被体积上限拒绝（此前只校验了上传文件大小）。"""
    from routers import import_ as import_router

    monkeypatch.setattr(import_router, "_MAX_CSV_TEXT_CHARS", 100)
    with TestClient(app) as c:
        r = c.post(
            "/api/import_csv",
            data={"csv_text": "sku,amount\n" + "x" * 500},
            headers=auth_headers,
        )
        assert r.status_code == 413


def test_calibrate_sample_limit(auth_headers):
    """标定样本量超上限应 422，避免用超大数组拖垮同步端点。"""
    with TestClient(app) as c:
        r = c.post(
            "/api/calibrate",
            json={"same_sims": [0.9] * 5001, "diff_sims": [0.1] * 5001},
            headers=auth_headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------- 持久层收敛


def test_clamp_values_truncates_and_sanitizes():
    """`_clamp_values` 截断超长字符串、归零非有限数值、归一 defect_tags。"""
    data = db._clamp_values(
        {
            "sku": "S" * 200,
            "sku_name": "N" * 500,
            "amount": float("nan"),
            "similarity": float("inf"),
            "defect_tags": "单标签",
        }
    )
    assert len(data["sku"]) == db._STR_LIMITS["sku"]
    assert len(data["sku_name"]) == db._STR_LIMITS["sku_name"]
    assert data["amount"] == 0.0 and data["similarity"] == 0.0
    assert data["defect_tags"] == ["单标签"]


def test_clamp_values_keeps_valid_data():
    """正常数据不应被改动（避免收敛逻辑产生副作用）。"""
    data = db._clamp_values(
        {
            "sku": "SKU-1",
            "sku_name": "纯棉 T 恤",
            "amount": 99.5,
            "similarity": 0.87,
            "defect_tags": ["污渍", "破损"],
        }
    )
    assert data["sku"] == "SKU-1" and data["amount"] == 99.5
    assert data["defect_tags"] == ["污渍", "破损"]


# ---------------------------------------------------------------- 数据源隔离


def test_real_url_derived_as_separate_database():
    """real 源连接串必须由 demo 串推导出**独立**库，杜绝默认同库（P0 隔离缺口）。"""
    assert db._derive_real_url(
        "postgresql+psycopg2://gaussdb:pw@localhost:5432/returnguard"
    ).endswith("/returnguard_real")
    assert db._derive_real_url("sqlite:///E:/x/cases.db").endswith("/cases_real.db")
    # 无法解析时原样返回（并已打 CRITICAL 日志），不抛异常影响启动
    assert db._derive_real_url("not-a-url") == "not-a-url"


def test_sources_are_isolated():
    """当前进程内 demo / real 必须指向不同后端（来自 conftest 的注入或推导）。"""
    assert db.SOURCES["demo"] != db.SOURCES["real"]
