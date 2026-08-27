"""API 层单测：用 FastAPI TestClient 打健康路径（不依赖外部模型 Key）。"""

import uuid

import pytest
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


def test_analyze_mock(auth_headers):
    with TestClient(app) as c:
        files = {
            "returned_image": ("ret.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post(
            "/api/analyze",
            files=files,
            data={"sku": "SKU-T1", "amount": "120", "mode": "mock"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        d = r.json()
        assert "similarity" in d and "defect_boxes" in d
        # P3-5 + SEC-8：退回图用签名短链访问，不再内联 base64、不再公开 /uploads/
        assert d["returned_image_url"].startswith("/api/file/"), "退回图应回传签名短链 URL"


def test_analyze_persists_dimensions(auth_headers):
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
            headers=auth_headers,
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


def test_metrics_endpoint(auth_headers):
    """P2-9：基础运行指标端点可用（需登录/管理员密钥，见安全复审 P2 收敛）。"""
    with TestClient(app) as c:
        r = c.get("/metrics", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        for k in (
            "uptime_seconds",
            "requests",
            "avg_latency_ms",
            "errors_5xx",
            "analyze_count",
            "insights_count",
        ):
            assert k in d, f"metrics 缺少字段 {k}"


def test_real_source_isolated_and_empty():
    """库级隔离：real 源与 demo 种子物理隔离。

    说明：demo/real 为独立库文件/实例，real 的初始数据来自录入/导入（含 C组多租户 public 基准）。
    由于同一进程内全量测试的执行顺序不保证（部分测试会向 real 写入），这里断言的是
    「物理隔离」这一不变量：real 源绝不混入 demo 种子 SKU。
    """
    with TestClient(app) as c:
        r = c.get("/api/insights", params={"mode": "mock", "source": "real"})
        assert r.status_code == 200
        d = r.json()
        assert d["source"] == "real"
        # 物理隔离：demo 种子库的 SKU 绝不应出现在 real 源
        demo_skus = {x["sku"] for x in c.get("/api/cases", params={"source": "demo"}).json()}
        real_skus = {x["sku"] for x in c.get("/api/cases", params={"source": "real"}).json()}
        assert demo_skus and real_skus.isdisjoint(demo_skus), "real 源不应混入 demo 种子数据"
        # demo 源仍是种子数据，不受影响
        d2 = c.get("/api/insights", params={"mode": "mock", "source": "demo"}).json()
        assert d2["source"] == "demo" and d2["total_cases"] > 0


def test_manual_add_routes_to_source(auth_headers):
    """手动录入落到指定 source，且 demo/real 互不污染（库级隔离实锤）。"""
    with TestClient(app) as c:
        sku = "SKU-ISOLATE-" + uuid.uuid4().hex[:6]
        payload = {
            "sku": sku,
            "category": "3C数码",
            "supplier": "S9",
            "platform": "Amazon",
            "amount": 199,
            "outcome": "赢",
            "similarity": 0.95,
            "same_item": True,
            "defect_tags": ["无明显瑕疵"],
        }
        # 写入 real 源（需登录）
        r = c.post("/api/cases?source=real", json=payload, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["source"] == "real"
        cid = body["case_id"]

        # real 源能查到该单（按当前登录租户隔离，须带会话读取）
        real_cases = c.get("/api/cases", params={"source": "real"}, headers=auth_headers).json()
        assert any(x.get("sku") == sku for x in real_cases), "real 源应含刚录入案件"

        # demo 源不应被污染
        demo_cases = c.get("/api/cases", params={"source": "demo"}).json()
        assert not any(x.get("sku") == sku for x in demo_cases), "demo 源不应出现 real 录入"

        # 清理：删除 real 源该单（需登录）
        del_r = c.delete(f"/api/cases/{cid}", params={"source": "real"}, headers=auth_headers)
        assert del_r.status_code == 200 and del_r.json()["deleted"] == 1
        after = c.get("/api/cases", params={"source": "real"}, headers=auth_headers).json()
        assert not any(x.get("sku") == sku for x in after), "删除后应不存在"
