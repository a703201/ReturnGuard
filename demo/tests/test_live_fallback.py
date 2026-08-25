"""live 逐能力回退单测：网关渐进开通即生效；无 Key 整体回退 mock。

验证 A组「把假能力变真」的代码前提：每个模型独立可用/回退，不再因单点失败整体回退 mock。
不依赖外部网络——所有 models_router 能力函数均 monkeypatch 模拟网关行为。
"""

import models_router
import pipeline


def test_no_key_falls_back_to_mock(monkeypatch):
    monkeypatch.setattr(models_router, "API_KEY", "")
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["mode"] == "mock(fallback)"  # 无 Key 整体回退
    assert "error" in res


def test_per_capability_fallback_mixed(monkeypatch):
    # 模拟网关：图向量不可用；瑕疵 / OCR / TTS 可用
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")

    def _raise(*_a, **_k):
        raise RuntimeError("gateway 未开通图向量")

    monkeypatch.setattr(models_router, "embed_image", _raise)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt: "破损,缺件")
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None: "全新未拆封")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None: "一致性结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie": "BASE64AUDIO")

    res = pipeline.analyze_case("r.png", "p.png", "全新", "SKU-X", 10.0, mode="live")
    assert res["mode"] == "live"
    caps = res["capabilities"]
    assert caps["similarity"] is False  # 向量回退
    assert caps["defects"] is True  # 瑕疵真实
    assert caps["ocr"] is True
    assert caps["tts"] is True
    assert res["defect_tags"] == ["破损", "缺件"]  # 真实瑕疵标签
    assert "error" not in res


def test_all_capabilities_real(monkeypatch):
    # 模拟网关全开：各能力均真实
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "embed_image", lambda url: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.95)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt: "功能故障")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None: [
            {"label": "功能故障", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "confidence": 0.9}
        ],
    )
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie": "BASE64AUDIO")

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
        type("R", (), {"post": staticmethod(lambda *a, **k: _FakeResp({"choices": [{"message": {"content": raw}}]}))})(),
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
    monkeypatch.setattr(models_router, "embed_image", lambda url: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.9)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt: "外包装破损")
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie": "BASE64AUDIO")
    monkeypatch.setattr(
        models_router,
        "vl_detect_boxes",
        lambda url, prompt=None: [
            {"label": "外包装破损", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "confidence": 0.9}
        ],
    )
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["capabilities"]["boxes"] is True
    assert res["defect_boxes_live"] is True
    assert res["defect_boxes"][0]["label"] == "外包装破损"
    assert res["defect_boxes"][0]["x"] == 0.1


def test_live_keypoint_boxes_fallback(monkeypatch):
    """网关未开通视觉定位：红框回退为确定性示意框，caps.boxes=False、defect_boxes_live=False，但仍可见。"""
    monkeypatch.setattr(models_router, "API_KEY", "test-key")
    monkeypatch.setattr(models_router, "PUBLIC_IMAGE_BASE", "https://img.example.com/uploads")
    monkeypatch.setattr(models_router, "embed_image", lambda url: [0.1] * 8)
    monkeypatch.setattr(models_router, "cosine", lambda a, b: 0.9)
    monkeypatch.setattr(models_router, "vl_chat", lambda url, prompt: "外包装破损")  # 瑕疵标签真实
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie": "BASE64AUDIO")
    monkeypatch.setattr(models_router, "vl_detect_boxes", lambda url, prompt=None: (_ for _ in ()).throw(RuntimeError("未开通")))
    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["capabilities"]["boxes"] is False
    assert res["defect_boxes_live"] is False
    assert len(res["defect_boxes"]) >= 1, "回退示意框仍应可见"
    assert res["defect_boxes"][0]["label"] == "外包装破损"
