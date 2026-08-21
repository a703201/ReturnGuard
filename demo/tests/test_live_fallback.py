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
    monkeypatch.setattr(models_router, "ocr", lambda url, prompt=None: "承诺")
    monkeypatch.setattr(models_router, "llm", lambda prompt, model=None: "结论")
    monkeypatch.setattr(models_router, "tts", lambda text, voice="Chelsie": "BASE64AUDIO")

    res = pipeline.analyze_case("r.png", "p.png", "", "SKU-X", 10.0, mode="live")
    assert res["mode"] == "live"
    assert all(res["capabilities"].values()), "全开时所有能力应为真实"
    assert res["similarity"] == 0.95
