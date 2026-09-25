# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""多 AI 平台适配（providers）回归测试。

守住四类容易静默退化的问题：
  1. **注册表完整性**：每个平台声明必须有 label / base_url / key_env / models，且
     models 的键必须是已知能力（打错能力名会让该能力永远走不到）；
  2. **能力闸语义**：平台未声明的能力必须判为「不支持」并抛错（而不是返回空值被误当成功），
     这样上游才会如实标注 `capabilities[cap] = False`；
  3. **URL 形状**：OpenAI 兼容风格与 Azure 部署风格的拼接必须正确（打错端点=线上全回退）；
  4. **信息泄露收敛**：公开目录 `/api/providers` 不得回传基地址 / 密钥 / 密钥配置状态。

不依赖外网、不需要任何真实 Key。
"""

from __future__ import annotations

import providers as pv
from fastapi.testclient import TestClient
from main import app

# ---------------------------------------------------------------- 注册表完整性


def test_required_fields_present():
    """每个平台声明都必须具备必需字段，且能力键合法。"""
    required = {
        "label",
        "api_style",
        "base_url",
        "key_env",
        "auth",
        "key_required",
        "models",
        "unsupported",
        "verified",
        "supported",
    }
    for key, raw in pv.PROVIDERS.items():
        missing = required - set(raw)
        assert not missing, f"{key} 缺少字段：{sorted(missing)}"
        assert raw["label"], f"{key} 缺少展示名"
        assert raw["api_style"] in {"openai", "azure", "native"}, f"{key} api_style 非法"
        assert raw["auth"] in {"bearer", "api-key", "none"}, f"{key} auth 非法"
        bad = [c for c in raw["models"] if c not in pv.CAPABILITIES]
        assert not bad, f"{key} 声明了未知能力：{bad}"
        assert set(raw["unsupported"]) == set(pv.CAPABILITIES) - set(raw["models"]), (
            f"{key} 的 unsupported 与 models 声明不一致"
        )


def test_default_provider_exists():
    assert pv.DEFAULT_PROVIDER in pv.PROVIDERS
    assert pv.current_provider_name() in pv.PROVIDERS


def test_official_provider_models_are_qwen_prefixed():
    """official 平台的模型必须全部带 qwen/ 前缀（该网关硬要求，否则 404）。"""
    for cap, model in pv.PROVIDERS["official"]["models"].items():
        assert model.startswith("qwen/"), f"official.{cap}={model} 必须以 qwen/ 开头"


def test_covers_multiple_vendors():
    """至少覆盖多家不同厂商（不是同一家的多个 profile），否则「多平台适配」名不副实。"""
    vendors = {
        "阿里云百炼",
        "OpenAI",
        "DeepSeek",
        "Moonshot",
        "智谱",
        "SiliconFlow",
        "OpenRouter",
        "Ollama",
        "Azure",
    }
    labels = " ".join(p["label"] for p in pv.PROVIDERS.values())
    hit = [v for v in vendors if v in labels]
    assert len(hit) >= 6, f"覆盖的厂商过少：{hit}"


# ---------------------------------------------------------------- 能力矩阵与闸门


def test_capability_matrix_reflects_declarations():
    assert pv.capability_matrix("deepseek") == {
        "text": True,
        "vl": False,
        "ocr": False,
        "embed": False,
        "rerank": False,
        "tts": False,
    }
    # OpenAI 无 rerank 端点 —— 必须如实为 False（否则线上必然 404 后回退）
    assert pv.capability_matrix("openai")["rerank"] is False
    assert pv.supports("openai", "text") is True
    # OpenAI 的嵌入是**文本**向量，无法完成本服务的「图像向量」用途 → 不声明
    assert pv.capability_matrix("openai")["embed"] is False


def test_image_embedding_only_declared_where_supported():
    """`embed` 在本服务里是「图像向量」。只允许声明在真正支持图像向量输入的平台。"""
    allow = {"tokenplan", "official", "dashscope", "custom"}
    declared = {k for k, p in pv.PROVIDERS.items() if "embed" in p["models"]}
    assert declared <= allow, f"以下平台误声明了图像向量能力：{sorted(declared - allow)}"
    assert "embed" in pv.PROVIDERS["dashscope"]["models"], "百炼系应保留图像向量"


def test_native_protocol_providers_are_not_supported():
    """非 OpenAI 兼容的原生协议平台应显式声明为不支持（避免用户以为能用）。"""
    for key in ("anthropic", "gemini"):
        assert pv.PROVIDERS[key]["supported"] is False
        assert all(v is False for v in pv.capability_matrix(key).values()), key


def test_ollama_needs_no_key_and_supports_local_caps():
    p = pv.get_provider("ollama")
    assert p["key_required"] is False
    assert p["auth"] == "none"
    assert pv.supports("ollama", "text") and pv.supports("ollama", "vl")
    assert pv.supports("ollama", "rerank") is False


def test_models_router_gate_raises_for_unsupported_capability(monkeypatch):
    """能力闸：平台不支持时必须抛错（上游据此回退并标注），而不是静默返回空值。"""
    import models_router as mr

    monkeypatch.setattr(mr, "_PROFILE", pv.get_provider("deepseek"))
    try:
        mr._require_capability("vl")
    except RuntimeError as e:
        assert "不支持视觉理解" in str(e)
    else:  # pragma: no cover
        raise AssertionError("不支持的能力必须抛错")

    monkeypatch.setattr(mr, "_PROFILE", pv.get_provider("openai"))
    mr._require_capability("text")  # 支持的能力不应抛错


def test_custom_provider_is_empty_until_env_declares_models(monkeypatch):
    """custom 兜底平台默认无模型 → 全能力不可用；用 RG_MODEL_* 声明后即可用。"""
    assert all(v is False for v in pv.capability_matrix("custom").values())
    monkeypatch.setenv("RG_MODEL_TEXT", "my-local-model")
    assert pv.supports("custom", "text") is True
    assert pv.supports("custom", "tts") is False


# ---------------------------------------------------------------- URL 与鉴权


def test_build_url_openai_style():
    p = pv.get_provider("openai")
    assert pv.build_url(p, "chat") == "https://api.openai.com/v1/chat/completions"
    assert pv.build_url(p, "embed") == "https://api.openai.com/v1/embeddings"
    assert pv.build_url(p, "tts") == "https://api.openai.com/v1/audio/speech"


def test_build_url_azure_style_uses_deployment_and_api_version(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://demo.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    p = pv.get_provider("azure_openai")
    url = pv.build_url(p, "chat", "my-deployment")
    assert url == (
        "https://demo.openai.azure.com/openai/deployments/my-deployment"
        "/chat/completions?api-version=2024-10-21"
    )


def test_build_url_rejects_unknown_path_and_native_style():
    p = pv.get_provider("openai")
    try:
        pv.build_url(p, "does-not-exist")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("未知路径必须抛错")
    try:
        pv.build_url(pv.get_provider("gemini"), "chat")
    except ValueError as e:
        assert "原生协议" in str(e)
    else:  # pragma: no cover
        raise AssertionError("原生协议平台必须抛错")


def test_auth_headers_by_style(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-test")
    h_bearer = pv.auth_headers(pv.get_provider("openai"))
    assert h_bearer["Authorization"] == "Bearer sk-test"
    h_azure = pv.auth_headers(pv.get_provider("azure_openai"))
    assert h_azure["api-key"] == "az-test" and "Authorization" not in h_azure
    h_none = pv.auth_headers(pv.get_provider("ollama"))
    assert "Authorization" not in h_none and "api-key" not in h_none


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://my-proxy.example.com/v1/")
    assert pv.get_provider("openai")["resolved_base_url"] == "https://my-proxy.example.com/v1"


def test_unknown_provider_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_PROFILE", "not-a-provider")
    assert pv.current_provider_name() == pv.DEFAULT_PROVIDER


# ---------------------------------------------------------------- 接口与信息泄露


def test_api_config_exposes_provider_without_endpoint_leak():
    """前端需要能力矩阵与模型映射来如实呈现，但**不得**下发基地址/密钥。"""
    with TestClient(app) as c:
        d = c.get("/api/config").json()
    prov = d["provider"]
    assert prov["key"] and prov["label"] and prov["api_style"]
    assert set(prov["capabilities"]) == set(pv.CAPABILITIES)
    assert isinstance(prov["models"], dict)
    assert "model_router_endpoint" not in d, "不应回传内部网关地址"
    blob = str(d)
    assert "sk-" not in blob and "api_key" not in prov


def test_api_providers_catalog_is_public_safe():
    with TestClient(app) as c:
        r = c.get("/api/providers")
        assert r.status_code == 200, r.text
        items = r.json()["providers"]
    assert len(items) == len(pv.PROVIDERS)
    current = [i for i in items if i["is_current"]]
    assert len(current) == 1, "必须且只能有一个 is_current"
    for it in items:
        assert set(it["capabilities"]) == set(pv.CAPABILITIES)
        # 公开目录不得包含基地址 / 密钥状态 / 模型标识（避免探测服务端拓扑与凭据）
        for leaked in ("base_url", "resolved_base_url", "api_key", "key_set", "models"):
            assert leaked not in it, f"/api/providers 泄露了 {leaked}"


# ---------------------------------------------------------------- 与 models_router 的衔接


def test_models_router_consumes_registry():
    import models_router as mr

    assert mr._MODEL_ROUTER_PROFILES is pv.PROVIDERS, "注册表应作为单一来源被复用"
    assert mr.MODEL_ROUTER_PROFILE in pv.PROVIDERS
    assert mr.MODELS == pv.get_provider(mr.MODEL_ROUTER_PROFILE)["models"]
    # /api/config 透出的平台信息与 models_router 的实际选择必须一致（单一来源）
    assert mr.platform_info()["key"] == mr.MODEL_ROUTER_PROFILE
