# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard · AI 平台（Provider）注册表 —— 多厂商接口适配的单一来源。

为什么需要这一层
----------------
本服务对 AI 能力的使用只有 6 类（`CAPABILITIES`）：

    text（文本生成/归因） · vl（视觉理解/瑕疵识别） · ocr（图内文字提取）
    embed（图像/文本向量） · rerank（相关性重排） · tts（语音合成）

绝大多数厂商都提供 **OpenAI 兼容** 的 HTTP 接口，但「路径、鉴权头、模型标识、
能力覆盖」各不相同。把这些差异集中在本文件声明（配置即接口契约），
`models_router.py` 只按「能力」调用、不关心是哪家平台——这样新增一个平台
= 在本文件加一条声明，**不改任何调用代码**。

与 `MODEL_ROUTER_PROFILE` 的关系
--------------------------------
`MODEL_ROUTER_PROFILE`（兼容别名 `RG_AI_PROVIDER`）就是选择本文件里的 provider key。
历史三个 profile（tokenplan / official / dashscope）仍然是百炼系平台，声明保持不变，
因此老配置与既有测试继续有效。

能力缺口的处理原则（重要）
--------------------------
平台不提供某项能力时，**必须如实声明为不支持**，而不是给一个会 404 的模型名：
`models_router` 在调用前会检查并直接抛错，由既有「逐能力 try/except 回退」逻辑
把它标记为 `capabilities[cap] = False`（前端显示为「回退」），
`/api/providers` 也会把该能力的支持情况透出。宁可显示「该平台不支持语音」，
也不要让用户以为是模型坏了。

密钥与地址一律来自环境变量，本文件不保存任何凭据。
"""

from __future__ import annotations

import os
from typing import Any

# ===========================================================================
# 能力清单（与 models_router 的调用点一一对应）
# ===========================================================================
CAPABILITIES: tuple[str, ...] = ("text", "vl", "ocr", "embed", "rerank", "tts")

# 能力 → 人类可读名（用于前端/文档展示）
CAPABILITY_LABELS: dict[str, str] = {
    "text": "文本生成",
    "vl": "视觉理解",
    "ocr": "图内文字 OCR",
    "embed": "图像向量",
    "rerank": "相关性重排",
    "tts": "语音合成",
}

# ⚠️ 能力语义（声明模型前必须对齐，否则配了也用不了）：
#     text   —— 纯文本 chat/completions
#     vl     —— 带图 chat/completions（瑕疵识别 / 双图判同款 / 缺陷红框）
#     ocr    —— 带图 chat/completions，提示词要求"提取图中文字"；通常复用 vl 模型
#     embed  —— **图像**向量（退回件 vs 主图的相似度），请求体为
#               `{"model":…, "input": {"image": <dataURI>}}`（百炼视觉向量的扩展形状）。
#               文本嵌入模型（如 text-embedding-3-small / bge-m3）**不能**用于本能力，
#               因此未在那些平台上声明 embed——宁可显示"不支持"，也不给一个必然失败的配置。
#     rerank —— 专用 POST /rerank，体为 {model, query, documents}
#     tts    —— POST /audio/speech，体为 {model, input, voice}
#
# 每项能力的模型标识覆盖变量：平台控制台里模型名变化时，无需改代码。
_MODEL_ENV: dict[str, str] = {
    "text": "RG_MODEL_TEXT",
    "vl": "RG_MODEL_VL",
    "ocr": "RG_MODEL_OCR",
    "embed": "RG_MODEL_EMBED",
    "rerank": "RG_MODEL_RERANK",
    "tts": "RG_MODEL_TTS",
}

# 默认 provider（与历史行为一致：tokenplan）
DEFAULT_PROVIDER = "tokenplan"

# 当前 provider 的解析变量（MODEL_ROUTER_PROFILE 优先，保住历史配置）
_PROVIDER_ENVS = ("MODEL_ROUTER_PROFILE", "RG_AI_PROVIDER")

_UNSUPPORTED_HINT = (
    "该平台未提供此项能力的公开 HTTP 接口，本服务会如实标记为「回退」而非伪装成真实调用"
)


def _p(
    *,
    label: str,
    api_style: str,
    base_url: str,
    key_env: str,
    models: dict[str, str],
    base_url_env: str = "",
    auth: str = "bearer",
    key_required: bool = True,
    verified: bool = False,
    doc: str = "",
    note: str = "",
    supports: bool = True,
) -> dict[str, Any]:
    """构造一条 provider 声明（统一字段，避免各处缺键导致 KeyError）。"""
    unsupported = [c for c in CAPABILITIES if c not in models]
    return {
        "label": label,
        "api_style": api_style,  # openai / azure / native
        "base_url": base_url,
        "base_url_env": base_url_env,
        "key_env": key_env,
        "auth": auth,  # bearer / api-key / none
        "key_required": key_required,
        "models": dict(models),
        "unsupported": unsupported,
        "verified": verified,  # 是否在本仓实跑验证过（未验证=配置模板，模型名需按平台核对）
        "doc": doc,
        "note": note,
        "supported": supports,  # False = 原生协议非 OpenAI 兼容，本适配层不直接对接
    }


# ===========================================================================
# 平台注册表
# ---------------------------------------------------------------------------
# ⚠️ `verified=False` 的平台是**可用的配置模板**：base_url / 鉴权方式 / 能力矩阵已按
#    公开文档填写，但模型标识随平台版本变动，请按控制台实际可用项用 `RG_MODEL_*`
#    覆盖。`verified=True` 表示本仓已用真实 Key 跑通该平台的 live 链路。
# ===========================================================================
PROVIDERS: dict[str, dict[str, Any]] = {
    # ---------------- 阿里云百炼系（本项目长期使用，已实跑验证）----------------
    "tokenplan": _p(
        label="阿里云百炼 · Token Plan 网关",
        api_style="openai",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        base_url_env="MODEL_ROUTER_BASE_URL",
        key_env="MODEL_ROUTER_API_KEY",
        models={
            "text": "qwen3.7-max",
            "tts": "qwen-audio-3.0-tts-plus",
            "vl": "qwen/qwen3-vl-plus",
            "ocr": "qwen/qwen-vl-ocr",
            "embed": "qwen/tongyi-embedding-vision-plus",
            "rerank": "qwen3-rerank",
        },
        verified=True,
        note="文本 / TTS 使用无 qwen/ 前缀的旧命名；视觉系沿用 qwen/ 前缀。",
    ),
    "official": _p(
        label="阿里云百炼 · 官方 Model Router",
        api_style="openai",
        base_url="https://model-router.edu-aliyun.com/v1",
        base_url_env="MODEL_ROUTER_OFFICIAL_BASE_URL",
        key_env="MODEL_ROUTER_OFFICIAL_KEY",
        models={
            "text": "qwen/qwen3.7-max",
            "tts": "qwen/qwen3-tts-instruct-flash",
            "vl": "qwen/qwen3-vl-plus",
            "ocr": "qwen/qwen-vl-ocr",
            "embed": "qwen/tongyi-embedding-vision-plus",
            "rerank": "qwen/qwen3-rerank",
        },
        verified=True,
        note="该网关要求全部模型标识带 qwen/ 前缀，否则 404。",
    ),
    "dashscope": _p(
        label="阿里云百炼 · 国内站按量付费",
        api_style="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        base_url_env="DASHSCOPE_BASE_URL",
        key_env="DASHSCOPE_API_KEY",
        models={
            "text": "qwen3.7-max",
            "tts": "qwen-audio-3.0-tts-plus",
            "vl": "qwen3-vl-plus",
            "ocr": "qwen-vl-ocr",
            "embed": "tongyi-embedding-vision-plus",
            "rerank": "qwen3-rerank",
        },
        verified=True,
        note="模型标识不带 qwen/ 前缀；数据不出境，视觉三模型齐全。",
    ),
    # ---------------- 国际 / 国内通用平台（OpenAI 兼容）----------------
    "openai": _p(
        label="OpenAI",
        api_style="openai",
        base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        key_env="OPENAI_API_KEY",
        models={
            "text": "gpt-4o-mini",
            "vl": "gpt-4o-mini",
            "ocr": "gpt-4o-mini",
            "tts": "tts-1",
        },
        doc="https://platform.openai.com/docs/api-reference",
        note=f"无 rerank 端点；文本嵌入模型无法完成本服务的「图像向量」用途（{_UNSUPPORTED_HINT}）。",
    ),
    "deepseek": _p(
        label="DeepSeek",
        api_style="openai",
        base_url="https://api.deepseek.com/v1",
        base_url_env="DEEPSEEK_BASE_URL",
        key_env="DEEPSEEK_API_KEY",
        models={"text": "deepseek-chat"},
        doc="https://api-docs.deepseek.com/zh-cn/",
        note=f"仅提供文本对话，无视觉 / OCR / 向量 / 重排 / 语音接口（{_UNSUPPORTED_HINT}）。",
    ),
    "moonshot": _p(
        label="Moonshot AI（Kimi）",
        api_style="openai",
        base_url="https://api.moonshot.cn/v1",
        base_url_env="MOONSHOT_BASE_URL",
        key_env="MOONSHOT_API_KEY",
        models={
            "text": "moonshot-v1-8k",
            "vl": "moonshot-v1-8k-vision-preview",
            "ocr": "moonshot-v1-8k-vision-preview",
        },
        doc="https://platform.moonshot.cn/docs/api/chat",
        note=f"无图像向量 / 重排 / 语音端点（{_UNSUPPORTED_HINT}）。",
    ),
    "zhipu": _p(
        label="智谱 AI（GLM）",
        api_style="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        base_url_env="ZHIPU_BASE_URL",
        key_env="ZHIPU_API_KEY",
        models={
            "text": "glm-4-plus",
            "vl": "glm-4v-plus",
            "ocr": "glm-4v-plus",
            "rerank": "rerank",
        },
        doc="https://open.bigmodel.cn/dev/api",
        note="语音合成走独立接口（非 OpenAI 兼容），故声明为不支持；rerank 参数与百炼同形，失败会自动回退本地公式；嵌入仅为文本向量，不满足图像向量用途。",
    ),
    "siliconflow": _p(
        label="SiliconFlow（硅基流动）",
        api_style="openai",
        base_url="https://api.siliconflow.cn/v1",
        base_url_env="SILICONFLOW_BASE_URL",
        key_env="SILICONFLOW_API_KEY",
        models={
            "text": "Qwen/Qwen2.5-7B-Instruct",
            "vl": "Qwen/Qwen2.5-VL-7B-Instruct",
            "ocr": "Qwen/Qwen2.5-VL-7B-Instruct",
            "rerank": "BAAI/bge-reranker-v2-m3",
            "tts": "FunAudioLLM/CosyVoice2-0.5B",
        },
        doc="https://docs.siliconflow.cn/",
        note="模型名形如 org/model，需与平台模型广场一致；可用 RG_MODEL_* 覆盖。",
    ),
    "openrouter": _p(
        label="OpenRouter（多模型聚合）",
        api_style="openai",
        base_url="https://openrouter.ai/api/v1",
        base_url_env="OPENROUTER_BASE_URL",
        key_env="OPENROUTER_API_KEY",
        models={
            "text": "openai/gpt-4o-mini",
            "vl": "openai/gpt-4o-mini",
            "ocr": "openai/gpt-4o-mini",
        },
        doc="https://openrouter.ai/docs",
        note=f"聚合平台无图像向量 / 重排 / 语音端点（{_UNSUPPORTED_HINT}）；模型名需带厂商前缀。",
    ),
    "ollama": _p(
        label="Ollama（本机 / 内网自托管）",
        api_style="openai",
        base_url="http://127.0.0.1:11434/v1",
        base_url_env="OLLAMA_BASE_URL",
        key_env="OLLAMA_API_KEY",
        key_required=False,
        auth="none",
        models={
            "text": "qwen2.5:7b",
            "vl": "qwen2.5vl:7b",
            "ocr": "qwen2.5vl:7b",
        },
        doc="https://github.com/ollama/ollama/blob/main/docs/openai.md",
        note=f"本地推理，数据完全不出境；无图像向量 / 重排 / 语音端点（{_UNSUPPORTED_HINT}）。模型名含 `:` 标签，需与本机 `ollama list` 一致。",
    ),
    "azure_openai": _p(
        label="Azure OpenAI",
        api_style="azure",
        base_url="https://<your-resource>.openai.azure.com",
        base_url_env="AZURE_OPENAI_ENDPOINT",
        key_env="AZURE_OPENAI_API_KEY",
        auth="api-key",
        models={
            "text": "gpt-4o-mini",
            "vl": "gpt-4o-mini",
            "ocr": "gpt-4o-mini",
            "tts": "tts-1",
        },
        doc="https://learn.microsoft.com/azure/ai-services/openai/reference",
        note="URL 形状为 /openai/deployments/<部署名>/...?api-version=...，故模型字段填**部署名**；需设 AZURE_OPENAI_API_VERSION（默认 2024-10-21）。",
    ),
    # ---------------- 原生协议（非 OpenAI 兼容）----------------
    "anthropic": _p(
        label="Anthropic Claude（原生 Messages API）",
        api_style="native",
        base_url="https://api.anthropic.com/v1",
        base_url_env="ANTHROPIC_BASE_URL",
        key_env="ANTHROPIC_API_KEY",
        models={"text": "claude-3-5-sonnet-latest"},
        doc="https://docs.anthropic.com/",
        supports=False,
        note="原生 Messages 协议（x-api-key 头 + anthropic-version）与 OpenAI 形状不同，本适配层不直接对接；如需使用，请经兼容网关（如 one-api / LiteLLM）暴露 OpenAI 兼容端点后选 `custom`。",
    ),
    "gemini": _p(
        label="Google Gemini（原生 generateContent）",
        api_style="native",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        base_url_env="GEMINI_BASE_URL",
        key_env="GEMINI_API_KEY",
        models={"text": "gemini-1.5-flash"},
        doc="https://ai.google.dev/api",
        supports=False,
        note="原生 generateContent 协议与 OpenAI 形状不同，本适配层不直接对接；同上可经兼容网关接入后选 `custom`。",
    ),
    # ---------------- 任意 OpenAI 兼容自建端点 ----------------
    "custom": _p(
        label="自建 / 其他 OpenAI 兼容端点",
        api_style="openai",
        base_url="http://127.0.0.1:8000/v1",
        base_url_env="RG_CUSTOM_BASE_URL",
        key_env="RG_CUSTOM_API_KEY",
        key_required=False,
        models={
            "text": "",
            "vl": "",
            "ocr": "",
            "embed": "",
            "rerank": "",
            "tts": "",
        },
        note="通用兜底：把 base_url 指向任意 OpenAI 兼容服务（vLLM / TGI / one-api / LiteLLM / 自建网关），再用 RG_MODEL_* 声明各能力的模型名；留空的模型在运行时会被判为「未配置」并如实回退。",
    ),
}


# ===========================================================================
# 解析与查询
# ===========================================================================
def current_provider_name() -> str:
    """当前 provider key：`MODEL_ROUTER_PROFILE` 优先，其次 `RG_AI_PROVIDER`，未知回退默认。"""
    for env in _PROVIDER_ENVS:
        raw = (os.environ.get(env) or "").strip()
        if raw:
            return raw if raw in PROVIDERS else DEFAULT_PROVIDER
    return DEFAULT_PROVIDER


def resolve_provider(name: str | None) -> str:
    """把任意输入归一化为合法的 provider key（未知/空 → 默认 provider）。"""
    if name and name in PROVIDERS:
        return name
    return DEFAULT_PROVIDER


def get_provider(name: str | None = None) -> dict[str, Any]:
    """返回**已解析环境变量**的 provider 视图（base_url / api_key / models 均为最终值）。

    返回值在声明字段之外追加：
        resolved_base_url —— 环境变量覆盖后的基地址（去尾部斜杠）
        api_key           —— 密钥（可能为空字符串）
        models            —— 应用 `RG_MODEL_*` 覆盖后的模型映射
        supports_cap(cap) —— 该能力是否可用（平台支持 **且** 模型名非空）
    """
    key = resolve_provider(name)
    raw = PROVIDERS[key]
    base = raw["base_url"]
    if raw.get("base_url_env"):
        override = (os.environ.get(raw["base_url_env"]) or "").strip()
        if override:
            base = override
    models = dict(raw["models"])
    for cap, env in _MODEL_ENV.items():
        val = (os.environ.get(env) or "").strip()
        if val:
            models[cap] = val
    out: dict[str, Any] = dict(raw)
    out["key"] = key
    out["resolved_base_url"] = base.rstrip("/")
    out["api_key"] = (os.environ.get(raw["key_env"]) or "").strip()
    out["models"] = models
    return out


def supports(provider: dict[str, Any] | str, capability: str) -> bool:
    """该 provider 是否**真正可用**某能力：平台已声明 **且** 模型标识非空。"""
    p = get_provider(provider) if isinstance(provider, str) else provider
    if not p.get("supported", True):
        return False
    return bool(p["models"].get(capability))


def capability_matrix(provider: dict[str, Any] | str) -> dict[str, bool]:
    """能力 → 是否可用（供 /api/providers 与前端如实展示）。"""
    return {cap: supports(provider, cap) for cap in CAPABILITIES}


def model_for(capability: str, provider: dict[str, Any] | str | None = None) -> str:
    """取当前 provider 某能力的模型标识（未配置返回空串）。"""
    p = get_provider(provider) if not isinstance(provider, dict) else provider
    return p["models"].get(capability, "")


def auth_headers(provider: dict[str, Any] | str) -> dict[str, str]:
    """按平台的鉴权风格构造请求头（Bearer / api-key / 无鉴权）。"""
    p = get_provider(provider) if isinstance(provider, str) else provider
    headers = {"Content-Type": "application/json"}
    if p["auth"] == "bearer" and p["api_key"]:
        headers["Authorization"] = f"Bearer {p['api_key']}"
    elif p["auth"] == "api-key" and p["api_key"]:
        # Azure OpenAI 用 `api-key` 头而非 Authorization
        headers["api-key"] = p["api_key"]
    return headers


# 能力 → OpenAI 兼容路径片段
_PATH = {
    "chat": "chat/completions",
    "embed": "embeddings",
    "rerank": "rerank",
    "tts": "audio/speech",
}


def build_url(provider: dict[str, Any] | str, path: str, model: str = "") -> str:
    """构造某能力的请求 URL，屏蔽不同平台的 URL 形状差异。

    - `openai` 风格：`{base}/{path}`（chat/completions · embeddings · rerank · audio/speech）
    - `azure` 风格：`{base}/openai/deployments/{model}/{path}?api-version=...`（模型位填部署名）

    未知 path / 未知风格直接抛 ValueError——宁可启动即失败，也不要静默打错端点。
    """
    if path not in _PATH:
        raise ValueError(f"未知的接口路径类型：{path}")
    p = get_provider(provider) if isinstance(provider, str) else provider
    style = p["api_style"]
    segment = _PATH[path]
    if style == "openai":
        return f"{p['resolved_base_url']}/{segment}"
    if style == "azure":
        deployment = model or p["models"].get("text", "")
        version = (os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-10-21").strip()
        return (
            f"{p['resolved_base_url']}/openai/deployments/{deployment}"
            f"/{segment}?api-version={version}"
        )
    raise ValueError(f"平台 {p['label']} 的原生协议（{style}）不由本适配层处理")


def list_providers() -> list[dict[str, Any]]:
    """供 `/api/providers` 的公开目录。

    **刻意不返回**基地址与密钥（含"是否已配置密钥"这类运行态），避免匿名访客探测
    服务端内网拓扑与凭据状态；只说明「有哪些平台可选、各自支持哪些能力」。
    """
    current = current_provider_name()
    out: list[dict[str, Any]] = []
    for key, raw in PROVIDERS.items():
        out.append(
            {
                "key": key,
                "label": raw["label"],
                "api_style": raw["api_style"],
                "supported": raw.get("supported", True),
                "verified": raw.get("verified", False),
                "key_env": raw["key_env"],
                "key_required": raw.get("key_required", True),
                "capabilities": capability_matrix(raw),
                "doc": raw.get("doc", ""),
                "note": raw.get("note", ""),
                "is_current": key == current,
            }
        )
    return out


def current_provider_public() -> dict[str, Any]:
    """当前 provider 的**可公开**信息（供 /api/config 透出给前端）。

    含能力矩阵与模型映射（便于前端如实呈现「哪些走真实模型」），
    但不含密钥；基地址属于内部拓扑，同样不外发。
    """
    p = get_provider(current_provider_name())
    return {
        "key": p["key"],
        "label": p["label"],
        "api_style": p["api_style"],
        "key_env": p["key_env"],
        "key_configured": bool(p["api_key"]) or not p.get("key_required", True),
        "capabilities": capability_matrix(p),
        "models": {cap: p["models"].get(cap, "") for cap in CAPABILITIES},
    }
