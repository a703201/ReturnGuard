# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""API 层单测：用 FastAPI TestClient 打健康路径（不依赖外部模型 Key）。"""

import uuid

from db import get_case
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
        # 落库后在案件库中应能查到该单并带维度（直接按 case_id 取，避免依赖分页页序）。
        # P1-A：取证写入强制落 real 源（即便 source=demo），故按 real + 当前租户查询。
        saved = get_case("real", d["case_id"], tenant_id="demo")
        assert saved, "上传单案应进入 real 源案件库"
        assert saved["category"] == "3C数码"
        assert saved["supplier"] == "S3"
        assert saved["outcome"] == "待分析"
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


def test_real_source_isolated_and_empty(real_user_headers):
    """库级隔离（redesign 后版本）：全新真实租户的初始 real 视图为空，且不混入 demo 种子。

    redesign 后 demo/demo123 物理驻留 real 源（tenant_id='demo'，1206 条种子），
    因此隔离不变量不再是「real 无 demo SKU」，而是「任意新租户互不串台、初始为空」。
    """
    with TestClient(app) as c:
        # SEC-P0：real 源真实退货数据已要求登录，匿名一律 401
        anon = c.get("/api/cases", params={"source": "real"})
        assert anon.status_code == 401, "real 源真实数据不可匿名拉取"

        demo_skus = {
            x["sku"] for x in c.get("/api/cases", params={"source": "demo"}).json()["items"]
        }
        assert demo_skus, "demo 源应有种子数据"

        # 全新真实租户的初始 real 视图：应为空，且不包含任何 demo 种子 SKU（多租户隔离）
        my = c.get("/api/cases", params={"source": "real"}, headers=real_user_headers).json()
        my_skus = {x["sku"] for x in my["items"]}
        assert not my_skus, "全新真实租户初始 real 视图应为空"
        assert my_skus.isdisjoint(demo_skus), "新租户不应看到 demo 演示种子"

        # demo 源仍是种子数据，不受影响
        d2 = c.get("/api/insights", params={"mode": "mock", "source": "demo"}).json()
        assert d2["source"] == "demo" and d2["total_cases"] > 0


def test_manual_add_routes_to_source(real_user_headers, auth_headers):
    """手动录入落到当前租户，且与 demo 源 / demo 账户视图互不污染（多租户隔离实锤）。"""
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
        # 写入 real 源（需登录），归属当前真实租户
        r = c.post("/api/cases?source=real", json=payload, headers=real_user_headers)
        assert r.status_code == 201
        body = r.json()
        assert body["ok"] and body["source"] == "real"
        cid = body["case_id"]

        # 自己的 real 视图能查到该单（P1-① 排序后必现首页）
        my_cases = c.get("/api/cases", params={"source": "real"}, headers=real_user_headers).json()[
            "items"
        ]
        assert any(x.get("sku") == sku for x in my_cases), "real 源应含刚录入案件"

        # demo 源不应被污染
        demo_cases = c.get("/api/cases", params={"source": "demo"}).json()["items"]
        assert not any(x.get("sku") == sku for x in demo_cases), "demo 源不应出现 real 录入"

        # demo 账户（tenant='demo'）的 real 视图也不应看到本租户案件（跨租户隔离）
        demo_real = c.get("/api/cases", params={"source": "real"}, headers=auth_headers).json()[
            "items"
        ]
        assert not any(x.get("sku") == sku for x in demo_real), "跨租户不应串台"

        # 清理：删除 real 源该单（需登录且属本租户）
        del_r = c.delete(f"/api/cases/{cid}", params={"source": "real"}, headers=real_user_headers)
        assert del_r.status_code == 200 and del_r.json()["deleted"] == 1
        after = c.get("/api/cases", params={"source": "real"}, headers=real_user_headers).json()[
            "items"
        ]
        assert not any(x.get("sku") == sku for x in after), "删除后应不存在"
