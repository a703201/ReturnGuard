"""live 逐能力回退单测：网关渐进开通即生效；无 Key 整体回退 mock。

验证 A组「把假能力变真」的代码前提：每个模型独立可用/回退，不再因单点失败整体回退 mock。
不依赖外部网络——所有 models_router 能力函数（含 vl_similarity/embed/vl_chat/vl_detect_boxes）
均 monkeypatch 模拟网关行为，确保单测确定性、可在 CI 离线运行。
"""

import models_router
import pipeline


def _raise_sim(*_a, **_k):
    """模拟「视觉同款服务端未开通」：vl_similarity 直接抛异常。"""
    raise RuntimeError("gateway 未开通视觉同款")


def _sim_ok(*_a, **_k):
    """模拟「视觉同款服务端可用」：返回确定性同款结论。"""
    return {"similarity": 0.95, "same_item": True, "reason": "ok"}


def _rerank_ok(_query, _docs, model=None, **_k):
    """模拟「rerank 服务端可用」（P1-5 后单案优先级会调 qwen3-rerank）：返回相关性分。"""
    return [{"index": 0, "relevance_score": 0.8}]


def test_no_key_falls_back_to_mock(monkeypatch):
    monkeypatch.setattr(models_router, "API_KEY", "")
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["mode"] == "mock(fallback)"  # 无 Key 整体回退
    assert "error" in res


def test_per_capability_fallback_mixed(monkeypatch):
    # 模拟网关：视觉同款 + 图向量 + 视觉定位均不可用；瑕疵 / OCR / TTS / 文本 LLM 可用
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")

    def _raise(*_a, **_k):
        raise RuntimeError("gateway 未开通图向量")

    def _raise_boxes(*_a, **_k):
        raise RuntimeError("gateway 未开通视觉定位")

    monkeypatch.setattr(models_router, "vl_similarity", _raise_sim)  # 视觉同款服务端未开通
    monkeypatch.setattr(models_router, "embed_image", _raise)
    monkeypatch.setattr(models_router, "vl_detect_boxes", _raise_boxes)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt=None, **kw: "破损,缺件")
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None, **kw: "全新未拆封")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None, **kw: "一致性结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie", **kw: "BASE64AUDIO")
    monkeypatch.setattr(models_router, "rerank", _rerank_ok)

    res = pipeline.analyze_case("r.png", "p.png", "全新", "SKU-X", 10.0, mode="live")
    # 部分能力真实、部分回退 → 诚信标注 live(partial)（而非恒为 live）
    assert res["mode"] == "live(partial)"
    caps = res["capabilities"]
    assert caps["similarity"] is False  # 视觉同款 + 向量均回退
    assert caps["defects"] is True  # 瑕疵真实
    assert caps["ocr"] is True
    assert caps["tts"] is True
    assert caps["text"] is True  # 文本 LLM 真实
    assert "similarity" in res["degraded"] and "boxes" in res["degraded"]
    assert res["defect_tags"] == ["破损", "缺件"]  # 真实瑕疵标签
    assert "error" not in res


def test_all_capabilities_real(monkeypatch):
    # 模拟网关全开：各能力均真实
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "vl_similarity", _sim_ok)  # 视觉同款服务端可用
    monkeypatch.setattr(models_router, "embed_image", lambda url, **kw: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.95)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt=None, **kw: "功能故障")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None, **kw: [
            {"label": "功能故障", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "confidence": 0.9}
        ],
    )
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None, **kw: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None, **kw: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie", **kw: "BASE64AUDIO")
    monkeypatch.setattr(models_router, "rerank", _rerank_ok)

    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["mode"] == "live"
    assert all(res["capabilities"].values()), "全开时所有能力应为真实"
    assert res["similarity"] == 0.95


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def test_vl_detect_boxes_parsing(monkeypatch):
    """vl_detect_boxes 应稳健解析归一化 bbox JSON（含 <think>/markdown 噪声）。"""
    raw = (
        "```json\n"
        '{"boxes":[{"label":"外包装破损","bbox":[0.10,0.20,0.30,0.40],"confidence":0.92}]}'
        "\n```"
    )
    monkeypatch.setattr(
        models_router,
        "requests",
        type(
            "R",
            (),
            {
                "post": staticmethod(
                    lambda *a, **k: _FakeResp({"choices": [{"message": {"content": raw}}]})
                )
            },
        )(),
    )
    boxes = models_router.vl_detect_boxes("http://x/y.png")
    assert len(boxes) == 1
    b = boxes[0]
    assert b["label"] == "外包装破损"
    assert b["x"] == 0.10 and b["y"] == 0.20 and b["w"] == 0.30 and b["h"] == 0.40
    assert b["confidence"] == 0.92


def test_live_keypoint_boxes_real(monkeypatch):
    """网关开通 qwen3-vl-plus：红框为真实坐标，caps.boxes=True 且 defect_boxes_live=True。"""
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "vl_similarity", _sim_ok)
    monkeypatch.setattr(models_router, "embed_image", lambda url, **kw: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.9)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt=None, **kw: "外包装破损")
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None, **kw: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None, **kw: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie", **kw: "BASE64AUDIO")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None, **kw: [
            {"label": "外包装破损", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "confidence": 0.9}
        ],
    )
    monkeypatch.setattr(models_router, "rerank", _rerank_ok)
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["capabilities"]["boxes"] is True
    assert res["defect_boxes_live"] is True
    assert res["defect_boxes"][0]["label"] == "外包装破损"
    assert res["defect_boxes"][0]["x"] == 0.1


def test_live_keypoint_boxes_fallback(monkeypatch):
    """网关未开通视觉定位：红框回退为确定性示意框，caps.boxes=False、defect_boxes_live=False，但仍可见。"""
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "vl_similarity", _sim_ok)
    monkeypatch.setattr(models_router, "embed_image", lambda url, **kw: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.9)
    monkeypatch.setattr(
        models_router, "vl_chat", lambda url, prompt=None, **kw: "外包装破损"
    )  # 瑕疵标签真实
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None, **kw: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None, **kw: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie", **kw: "BASE64AUDIO")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None, **kw: (_ for _ in ()).throw(RuntimeError("未开通")),
    )
    monkeypatch.setattr(models_router, "rerank", _rerank_ok)
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["capabilities"]["boxes"] is False
    assert res["defect_boxes_live"] is False
    assert len(res["defect_boxes"]) >= 1, "回退示意框仍应可见"
    assert res["defect_boxes"][0]["label"] == "外包装破损"


def _mock_all_but_rerank(monkeypatch, rerank_stub):
    """把除 rerank 外的能力全部模拟为可用，rerank 用传入桩（用于 ⑤ 优先级专项测试）。"""
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "vl_similarity", _sim_ok)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt=None, **kw: "功能故障")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None, **kw: [
            {"label": "功能故障", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "confidence": 0.9}
        ],
    )
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None, **kw: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None, **kw: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie", **kw: "B64")
    monkeypatch.setattr(models_router, "rerank", rerank_stub)


def test_rerank_priority_integration(monkeypatch):
    """⑤ 优先级：rerank 可用时融合「rerank 相关性 + 本地公式」，caps.rerank=True。"""
    _mock_all_but_rerank(
        monkeypatch, lambda q, d, model=None, **kw: [{"index": 0, "relevance_score": 1.0}]
    )
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 200.0, mode="live")
    assert res["capabilities"]["rerank"] is True
    # 融合公式：0.5×本地 + 0.5×1.0 → 必然 >0.5 且 ≤1.0
    assert 0.5 < res["priority_score"] <= 1.0


def test_rerank_fallback_to_local_formula(monkeypatch):
    """⑤ 优先级：rerank 不可用时回退本地确定性公式，caps.rerank=False 且仍有优先级。"""
    _mock_all_but_rerank(
        monkeypatch,
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gateway 未开通 rerank")),
    )
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 200.0, mode="live")
    assert res["capabilities"]["rerank"] is False
    assert "rerank" in res["degraded"]
    assert 0 < res["priority_score"] <= 1.0


def test_live_insights_fallback_not_cached(monkeypatch):
    """可用性回归：live 洞察失败回退结果**不入缓存**，避免瞬时故障被"粘住"。

    背景：build_insights 的洞察缓存按 (mode, source, sig, 代际) 缓存。若把 live 失败回退
    （mock(fallback)）也写进缓存，一次网关/DNS 瞬时抖动就会让前端**持续**显示"AI 实算失败"，
    直到案件集或代际变化才恢复（无法自愈）。本用例断言：失败后再次调用应**重新尝试**（不被缓存短路）。
    """
    import models_router

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("gateway down (模拟瞬时故障)")

    monkeypatch.setattr(models_router, "build_insights_live", _boom)
    cases = [
        {
            "case_id": "RG-CACHE-1",
            "sku": "SKU-C",
            "amount": 10,
            "outcome": "赢",
            "defect_tags": ["功能故障"],
            "date": "2025-01-01",
        }
    ]
    a1 = pipeline.build_insights(cases, mode="live", source="demo")
    assert a1["mode"] == "mock(fallback)"
    a2 = pipeline.build_insights(cases, mode="live", source="demo")
    assert a2["mode"] == "mock(fallback)"
    assert calls["n"] == 2, "live 回退结果不应入缓存，第二次应重新真实尝试"
