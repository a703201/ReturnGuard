"""ReturnGuard · 模型能力层（live 模式，经阿里云百炼网关调用，支持 Token Plan 测试网关 / 赛事指定 Model Router 双 profile 一键切换）

本文件把「方案文档」里规划的模型能力封装成可调用函数，供 pipeline 在 live 模式下调取。
切换网关只需改 MODEL_ROUTER_PROFILE（tokenplan / official），详见下方「双 profile」配置块。
各能力的模型标识随 profile 固化在 _MODEL_ROUTER_PROFILES[...]["models"]，统一由 MODELS[...] 下发。

    profile      能力(④文本/⑥TTS)            其余(①向量/②VL/③OCR/⑤rerank)
    ──────────  ──────────────────────────  ──────────────────────────────────
    tokenplan    qwen3.7-max / qwen-audio-3.0-tts-plus    qwen/qwen3-vl-plus 等（视觉未开通→回退）
    official     qwen/qwen3.7-max / qwen/qwen3-tts-instruct-flash   qwen/qwen3-vl-plus 等（赛事指定）
    dashscope    qwen3.7-max / qwen-audio-3.0-tts-plus    qwen3-vl-plus 等（自购·视觉齐全·数据不出境）

⚠️ 两个网关「模型命名」不同：Token Plan 文本/TTS 为无 qwen/ 前缀旧名；赛事指定 Model Router
（model-router.edu-aliyun.com）全部模型必须带 qwen/ 前缀（见 ModelRouter_API.docx）。切换 profile
时 base_url + key + 模型标识三者一并切换，避免 404/模型不存在。

Token Plan 当前开通以「文本推理 / TTS 语音」为主；视觉/向量/rerank 在团队版模型列表未开通，
调用会报错并由 pipeline 自动回退 mock（保持原模型名占位），保证演示不中断——网关渐进开通即生效。

dashscope（阿里云百炼国内站按量付费）是「自购 token」通道：视觉/向量/OCR 模型齐全、数据不出境、
合规首选。设 MODEL_ROUTER_PROFILE=dashscope + DASHSCOPE_API_KEY 即可让单案视觉真跑通，
模型标识不带 qwen/ 前缀（与 Token Plan / 官方 Model Router 命名不同）。退回演示仍走 mock 回退。

运行前提（live 模式必须）：
    - demo/.env 或环境变量 MODEL_ROUTER_API_KEY：Token Plan 专属 API Key
      注意：必须与专属基地址配套使用；用 dashscope.aliyuncs.com 通用地址无法抵扣套餐额度。
    - 环境变量 PUBLIC_IMAGE_BASE：上传图片可公网访问的基础 URL（视觉能力需要时再配）
"""

import base64
import contextvars
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import struct
import sys
import time
import wave

import requests
from calibration import get_active_threshold
from constants import SEVERITY
from dotenv import load_dotenv
from prompts import (
    DEFECT_BBOX_PROMPT,
    DEFECT_RECOGNITION_PROMPT,
    OCR_PROMISE_PROMPT,
    SIMILARITY_PROMPT,
    build_insights_prompt,
    consistency_prompt,
    dossier_prompt,
    voice_prompt,
)

logger = logging.getLogger("returnguard.models_router")

# ---- 阿里云百炼网关（双 profile 一键切换，OpenAI 兼容协议）----
# 密钥 / 基地址优先从 demo/.env 读取（.env 不入 git，见根与 demo 两层 .gitignore），
# 也支持外部环境变量覆盖（如 docker compose 注入）。
# 读取 demo/.env（本地敏感配置：API Key、网关地址等）。
# 测试环境跳过：pytest 在启动期就把自身注入 sys.modules（早于任何业务模块 import），
# 因此用 sys.modules.get("pytest") 判断最可靠；不能用 PYTEST_CURRENT_TEST——它只在测试
# "执行期"才写入环境，模块"收集期" import 时尚未存在，会导致真实 .env 被误加载、七牛密钥等
# 泄漏进用例、造成图床后端等非确定性行为。
if sys.modules.get("pytest") is None and "PYTEST_CURRENT_TEST" not in os.environ:
    load_dotenv()

# 双 profile：tokenplan=本地测试（Token Plan 专属网关）/ official=赛事指定「阿里云百炼 Model Router」。
# 切换只需改 MODEL_ROUTER_PROFILE 一个变量，避免 base_url 与 key 错配；各 profile 的
# base_url 有默认值，仅 official 的 key（MODEL_ROUTER_OFFICIAL_KEY=组委会发放）需单独配置。
#
# ⚠️ 关键差异：两个网关的「模型标识命名」不同！
#   - Token Plan 网关：文本/TTS 用「无 qwen/ 前缀」旧命名（qwen3.7-max / qwen-audio-3.0-tts-plus），
#     视觉/OCR/向量沿用 qwen/ 前缀。
#   - 赛事指定 Model Router（model-router.edu-aliyun.com）：全部模型「必须带 qwen/ 前缀」
#     （如 qwen/qwen3.7-max、qwen/qwen3-tts-instruct-flash、qwen/qwen3-rerank）。
#   因此 base_url 切换的同时，模型标识也必须随 profile 切换，否则会 404/模型不存在。
#   下方 models 字典把每个能力的模型标识按 profile 固化，统一由 MODELS[...] 下发，杜绝错配。
_MODEL_ROUTER_PROFILES = {
    "tokenplan": {
        "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "key_env": "MODEL_ROUTER_API_KEY",
        "models": {
            "text": "qwen3.7-max",
            "tts": "qwen-audio-3.0-tts-plus",
            "vl": "qwen/qwen3-vl-plus",
            "ocr": "qwen/qwen-vl-ocr",
            "embed": "qwen/tongyi-embedding-vision-plus",
            "rerank": "qwen3-rerank",
        },
    },
    "official": {
        "base_url": "https://model-router.edu-aliyun.com/v1",
        "key_env": "MODEL_ROUTER_OFFICIAL_KEY",
        "models": {
            "text": "qwen/qwen3.7-max",
            "tts": "qwen/qwen3-tts-instruct-flash",
            "vl": "qwen/qwen3-vl-plus",
            "ocr": "qwen/qwen-vl-ocr",
            "embed": "qwen/tongyi-embedding-vision-plus",
            "rerank": "qwen/qwen3-rerank",
        },
    },
    # dashscope：阿里云百炼国内站「按量付费」自购通道（视觉模型齐全、数据不出境、合规首选）。
    # 模型标识不带 qwen/ 前缀（与 Token Plan / 官方 Model Router 的命名不同），base_url 用百炼
    # 通用兼容端点。自购 key 走这里即可让单案视觉（①向量/②VL/②'红框/③OCR）真跑通，
    # 代码其余逻辑无需改动——拿到 key 后设 MODEL_ROUTER_PROFILE=dashscope + DASHSCOPE_API_KEY 即可。
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY",
        "models": {
            "text": "qwen3.7-max",
            "tts": "qwen-audio-3.0-tts-plus",
            "vl": "qwen3-vl-plus",
            "ocr": "qwen-vl-ocr",
            "embed": "tongyi-embedding-vision-plus",
            "rerank": "qwen3-rerank",
        },
    },
}
MODEL_ROUTER_PROFILE = os.environ.get("MODEL_ROUTER_PROFILE", "tokenplan")
_PROFILE = _MODEL_ROUTER_PROFILES.get(MODEL_ROUTER_PROFILE, _MODEL_ROUTER_PROFILES["tokenplan"])
# 当前 profile 的模型标识字典（随 profile 切换，杜绝 base_url/base_key/模型名错配）。
MODELS = _PROFILE["models"]
# base_url 解析规则（每个 profile 用各自独立的覆盖变量，杜绝 .env 里某个 profile 的 base_url
# 把其他 profile 的端点错配——此前 tokenplan 的 MODEL_ROUTER_BASE_URL 曾把 official/dashscope
# 端点污染成 Token Plan 地址，导致"切了 profile 仍打旧网关"）：
#   - tokenplan ：允许 MODEL_ROUTER_BASE_URL 覆盖；否则取 Token Plan 专属默认
#   - official  ：固定赛事指定端点，可用 MODEL_ROUTER_OFFICIAL_BASE_URL 覆盖（一般不改）
#   - dashscope ：固定百炼国内站端点，可用 DASHSCOPE_BASE_URL 覆盖
_PROFILE_BASE_ENV = {
    "tokenplan": "MODEL_ROUTER_BASE_URL",
    "official": "MODEL_ROUTER_OFFICIAL_BASE_URL",
    "dashscope": "DASHSCOPE_BASE_URL",
}
_base_env = _PROFILE_BASE_ENV.get(MODEL_ROUTER_PROFILE, "")
_override = os.environ.get(_base_env, "") if _base_env else ""
API_BASE = _override.rstrip("/") if _override else _PROFILE["base_url"]
API_KEY = os.environ.get(_PROFILE["key_env"], "")
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "")
# 默认文本推理模型：随 profile 取对应命名（official=qwen/qwen3.7-max，tokenplan=qwen3.7-max）；
# 可用 MODEL_ROUTER_TEXT_MODEL 覆盖（演示求快可切 kimi-k2.6 / deepseek-v4-pro / qwen3.6-flash 等，
# 但 official profile 下覆盖值也必须带 qwen/ 前缀才生效，对比结论见 compare_models.py）。
TEXT_MODEL = os.environ.get("MODEL_ROUTER_TEXT_MODEL", MODELS["text"])
# 赛事指定 Model Router 的全部模型必须带 qwen/ 前缀；若 .env 遗留 tokenplan 风格的无前缀命名
# （如 qwen3.7-max），在 official profile 下自动补齐前缀，避免 404/模型不存在，保证一键切换可用。
if MODEL_ROUTER_PROFILE == "official" and not TEXT_MODEL.startswith("qwen/"):
    TEXT_MODEL = f"qwen/{TEXT_MODEL}"

logger.info(
    "模型网关已加载 profile=%s endpoint=%s key_set=%s",
    MODEL_ROUTER_PROFILE,
    API_BASE,
    bool(API_KEY),
)

# ===================== live 链路总超时预算（A22）=====================
# 并发安全：用 contextvars 隔离每个请求的 deadline，避免并发请求互相串扰。
# 每次外部 HTTP 调用经 _post() → _guard() 检查是否超总预算；超限抛 TimeoutError，
# 由 live_analyze 逐能力 except 回退 mock，或 pipeline.build_insights 整体回退 mock(fallback)。
LLM_HTTP_TIMEOUT = float(os.environ.get("LLM_HTTP_TIMEOUT", "60"))
LLM_TOTAL_BUDGET = float(os.environ.get("LLM_TOTAL_BUDGET", "120"))
_LLM_DEADLINE = contextvars.ContextVar("rg_llm_deadline", default=0.0)


def _enter_budget(budget: float) -> None:
    """进入一次 live 调用前设定总预算（秒）。budget<=0 表示不限。"""
    _LLM_DEADLINE.set(time.monotonic() + budget if budget > 0 else 0.0)


def _guard() -> None:
    """外部调用前检查总预算，超限抛 TimeoutError 触发 mock 回退。"""
    d = _LLM_DEADLINE.get()
    if d and time.monotonic() > d:
        raise TimeoutError("live 链路超过总预算，回退 mock")


def _post(url: str, **kw):
    """requests.post 统一封装：强制总预算检查 + 默认超时，避免单/多次调用无界阻塞工作线程。"""
    _guard()
    kw.setdefault("timeout", LLM_HTTP_TIMEOUT)
    return requests.post(url, **kw)


def _headers():
    """构造请求头：Bearer 鉴权 + JSON 内容类型。"""
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


# 视觉输入归一化：把「本地路径 / 公网 URL / data URI」统一成送给视觉网关的值。
# 关键决策（P3-17 收口后的视觉实跑修复）：优先把本地上传图转成 base64 data URI 内联，
# 彻底绕开「网关需回源拉取我们隧道图」这一最脆弱环节（cloudflared 进程一旦停，隧道 530，
# 网关报 Failed to download multimodal content）。内联字节同样只流经阿里云国内站，数据不出境。
_IMG_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
}


def _img_source(src: str | None) -> str | None:
    """把图像来源归一化为视觉调用可用的输入。

    - data:image/...  → 原样（已内联）
    - http(s)://...   → 原样（网关可回源拉取，如七牛公网 https；隧道 http 此前被拒）
    - 本地文件路径     → 读文件转 base64 data URI（最稳，无需公网可达）
    - 其它/读取失败    → 原样返回（交由后续调用自然失败并回退）
    """
    if not src:
        return src
    if src.startswith("data:image/"):
        return src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    try:
        with open(src, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(src)[1].lower().lstrip(".")
        mime = _IMG_MIME.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    except Exception:  # noqa: BLE001
        logger.warning("本地图转 base64 失败，保持原值: %s", src)
        return src


def _image_size(path: str) -> tuple[int, int] | None:
    """读图片像素尺寸（PNG/JPEG），无需第三方库。用于把模型可能返回的像素坐标 bbox 归一化。"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            import struct as _st
            w, h = _st.unpack(">II", head[16:24])
            return (w, h)
        if head[:2] == b"\xff\xd8":  # JPEG：扫描 SOF  marker
            with open(path, "rb") as f:
                data = f.read()
            i = 2
            n = len(data)
            while i < n - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                m = data[i + 1]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                         0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return (w, h)
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                i += 2 + seg
    except Exception:  # noqa: BLE001
        return None
    return None


# ===================== ① 同款一致性比对（图像向量）=====================
def embed_image(image_url):
    """调用 tongyi-embedding-vision-plus，把一张商品图转成向量。
    返回：浮点数列表（向量）。用于后续余弦相似度判断是否同一件。
    注意：当前 Token Plan 网关团队版模型列表未开通图像向量，调用会报错；
    由 pipeline 的 live 回退机制降级到 mock（确定性哈希），演示不中断。"""
    src = _img_source(image_url)
    r = _post(
        f"{API_BASE}/embeddings",
        headers=_headers(),
        json={"model": MODELS["embed"], "input": {"image": src}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def cosine(a, b):
    """计算两个向量的余弦相似度，值域约 [0, 1]，越接近 1 越相似。
    业务含义：退回件 vs 本店主图的相似度，高=同一件、低=疑似调包/非同款。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return round(dot / (na * nb), 3)


# ===================== ② 瑕疵视觉识别（多模态理解）=====================
def vl_chat(image_url, prompt):
    """调用 qwen3-vl-plus，对图片提问题并返回文字回答。
    方案功能②用它做「破损/缺件/污渍/使用痕迹」等瑕疵标签识别。
    注意：当前网关未开通多模态理解，调用会报错并回退 mock。"""
    src = _img_source(image_url)
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": MODELS["vl"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": src}},
                    ],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def vl_detect_boxes(image_url, prompt=DEFECT_BBOX_PROMPT, img_size=None):
    """调用 qwen3-vl-plus 做缺陷定位，返回归一化 bbox 列表（坐标 0~1，xywh）。

    返回：[{label, x, y, w, h, confidence}, ...]。用于「关键帧红框标注」真实坐标。
    网关开通多模态理解即真实；未开通/解析失败由 live_analyze 回退确定性示意框，
    保证演示不中断且如实标注（不替代平台裁决）。

    img_size=(w,h)：当模型返回像素坐标（任一值>1）时，用其归一化到 0~1；
    不传则遇到像素坐标按无法归一化跳过（由回退机制补全示意框）。"""
    src = _img_source(image_url)
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": MODELS["vl"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": src}},
                    ],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    raw = msg.get("content") or msg.get("reasoning_content") or ""
    data = _extract_json(raw)
    items = data.get("boxes") or data.get("defects") or []
    boxes: list[dict] = []
    iw, ih = (img_size or (None, None))
    for item in items:
        if not isinstance(item, dict):
            continue
        lab = str(item.get("label", "")).strip()
        coords = item.get("bbox") or item.get("box") or []
        if not lab or len(coords) < 4:
            continue
        try:
            a = [float(c) for c in coords[:4]]
        except Exception:
            continue
        # 归一化 0~1；若为像素坐标（任一值>1）且已知图尺寸，则归一化；否则跳过
        if not all(0 <= v <= 1 for v in a):
            if iw and ih:
                a = [a[0] / iw, a[1] / ih, a[2] / iw, a[3] / ih]
            else:
                continue
            if not all(0 <= v <= 1 for v in a):
                continue
        x, y, w, h = a
        conf = float(item.get("confidence", 0.0) or 0.0)
        boxes.append(
            {
                "label": lab,
                "x": round(x, 3),
                "y": round(y, 3),
                "w": round(w, 3),
                "h": round(h, 3),
                "confidence": round(conf, 2),
            }
        )
    return boxes


# ===================== ①' 同款一致性（VL 直接判同款）=====================
def vl_similarity(returned_url, product_url, prompt=SIMILARITY_PROMPT):
    """用多模态模型「同时看退回件 + 本店主图」直接判同款，返回相似度 0~1 + 理由。

    用途：百炼工作空间 OpenAI 兼容模式**不支持**视觉向量模型
    （tongyi-embedding-vision-plus → "Unsupported model ... for OpenAI compatibility mode"），
    故 ① 同款一致性改用 VL 直接判定，比向量更贴合业务（同款/调包判定）。
    返回 {similarity, same_item, reason}。调用失败抛异常，由 live_analyze 回退向量/哈希。"""
    r_src = _img_source(returned_url)
    p_src = _img_source(product_url)
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": MODELS["vl"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": r_src}},
                        {"type": "image_url", "image_url": {"url": p_src}},
                    ],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    raw = msg.get("content") or msg.get("reasoning_content") or ""
    data = _extract_json(raw)
    sim = float(data.get("similarity", 0.0) or 0.0)
    sim = max(0.0, min(1.0, sim))
    same = bool(data.get("same_item", sim >= get_active_threshold()))
    return {
        "similarity": round(sim, 3),
        "same_item": same,
        "reason": str(data.get("reason", ""))[:200],
    }


# ===================== ③ listing 承诺提取（OCR）=====================
def ocr(image_url, prompt=OCR_PROMISE_PROMPT):
    """调用 qwen-vl-ocr，从本店主图/详情图里提取文字承诺（如「全新未拆/30天退换」）。
    方案功能③用它做「退回件实际状态 vs 本店承诺」的货不对板核验。
    注意：当前网关未开通 OCR 视觉模型，调用会报错并回退 mock。"""
    src = _img_source(image_url)
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": MODELS["ocr"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": src}},
                    ],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ===================== ④ 文本生成 / 推理（大模型）=====================
def llm(prompt, model=TEXT_MODEL):
    """调用默认文本模型（MODEL_ROUTER_TEXT_MODEL，默认 qwen3.7-max）做文本生成。
    可选 kimi-k2.6 / deepseek-v4-pro / qwen3.6-flash 等更快模型。返回模型文本。"""
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _extract_json(raw):
    """从模型返回里稳健地抽取 JSON 对象。

    兼容：
      - markdown 代码围栏（```json ... ```）
      - deepseek / qwen3.6+ 的 <think>...</think> 思考链
      - JSON 前后的解释文本 / 多余尾巴
      - 输出被截断、或夹带两个以上 JSON 对象（取首个可解析的对象）
    返回：解析后的 dict；抽不到则返回 {}。"""
    if not raw:
        return {}
    s = raw.strip()
    s = re.sub(r"```(?:json)?\s*", "", s, flags=re.S)  # 去掉 ```json 围栏
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)  # 去掉思考链
    starts = [m.start() for m in re.finditer(r"\{", s)]
    if not starts:
        return {}
    ends = [m.start() for m in re.finditer(r"\}", s)]
    if not ends:
        return {}
    # 优先最长候选（首个 { → 最后一个 }），解析失败再逐步缩短，
    # 处理截断 / 夹带多段 JSON 的情况
    for si in starts:
        for ei in reversed(ends):
            if ei <= si:
                break
            try:
                return json.loads(s[si : ei + 1])
            except Exception:
                continue
    return {}


def llm_json(prompt, model=TEXT_MODEL):
    """调用大模型并直接返回结构化 JSON（用于洞察聚类/归因）。
    qwen3.6+ 等模型会把思考放进 reasoning_content、content 可能为空，
    此时回退读取 reasoning_content 再抽取。"""
    r = _post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    raw = msg.get("content") or msg.get("reasoning_content") or ""
    return _extract_json(raw)


# ===================== ⑤ 案件优先级排序（重排）=====================
def rerank(query, documents, model=None):
    """调用 qwen3-rerank，按「追回价值」对多笔待处理案件重排，把高金额/高胜算排前。
    注：当前网关未开通重排模型，pipeline 会退化为本地公式计算（见 pipeline.analyze_case）。"""
    if model is None:
        model = MODELS["rerank"]
    r = _post(
        f"{API_BASE}/rerank",
        headers=_headers(),
        json={"model": model, "query": query, "documents": documents},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("results", [])


# ===================== ⑥ 母语语音陈述（TTS）=====================
def tts(text, voice="Chelsie"):
    """调用 TTS 模型生成语音（base64 编码的音频）。
    profile 自适应：official=qwen/qwen3-tts-instruct-flash（voice 用 Chelsie/Ethan/Serena），
    tokenplan=qwen-audio-3.0-tts-plus。OpenAI 兼容 /audio/speech 路径。"""
    r = _post(
        f"{API_BASE}/audio/speech",
        headers=_headers(),
        json={"model": MODELS["tts"], "input": text, "voice": voice},
        timeout=60,
    )
    r.raise_for_status()
    return base64.b64encode(r.content).decode("ascii")


# ===================== live 模式逐能力回退（网关渐进开通即生效）=====================
def _fallback_similarity(returned_path: str, product_path: str) -> float:
    """live 图向量不可用时，用与 pipeline 同口径的确定性哈希相似度兜底（仅演示，非模型真实能力）。
    放本模块内避免反向 import pipeline 造成循环依赖。"""
    h = hashlib.md5(f"{returned_path}|{product_path}".encode()).hexdigest()
    return round(0.55 + (int(h, 16) % 1000) / 1000 * 0.43, 3)


def _fallback_defects(returned_path: str) -> list[str]:
    """live 瑕疵视觉不可用时，确定性哈希兜底标签（仅演示）。"""
    h = int(hashlib.md5(str(returned_path).encode("utf-8")).hexdigest(), 16)
    rng = random.Random(h)
    pool = ["外包装破损", "商品缺件", "污渍划痕", "使用痕迹", "功能故障", "货不对板", "色差明显"]
    n = rng.randint(0, 3)
    return rng.sample(pool, n) if n > 0 else ["无明显瑕疵"]


def _fallback_defect_boxes(returned_path: str, defects: list[str]) -> list[dict]:
    """live 缺陷定位（bbox）不可用时，确定性示意框（仅演示，不替代真实检测坐标）。

    与 pipeline._mock 的示意框口径一致：按缺陷标签生成归一化 [x,y,w,h] + 演示置信度；
    live 路径下会如实通过 capabilities["boxes"]=False 向前端标注「示意回退」。"""
    out: list[dict] = []
    h = int(hashlib.md5(f"{returned_path}|boxes".encode()).hexdigest(), 16)
    rng = random.Random(h)
    for d in defects:
        if d == "无明显瑕疵":
            continue
        bx = round(rng.random() * 0.6, 3)
        by = round(rng.random() * 0.55, 3)
        bw = round(0.20 + rng.random() * 0.22, 3)
        bh = round(0.20 + rng.random() * 0.22, 3)
        conf = round(0.75 + rng.random() * 0.23, 2)
        out.append({"label": d, "x": bx, "y": by, "w": bw, "h": bh, "confidence": conf})
    return out


def _gen_wav(text: str, sr: int = 16000, dur: float = 1.2) -> str:
    """占位 WAV（正弦音），TTS 不可用时充当可播放音频（与 pipeline._gen_wav 同口径）。"""
    n = int(sr * dur)
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    for i in range(n):
        val = int(12000 * math.sin(2 * math.pi * 440 * i / sr) * (1 - i / n))
        w.writeframes(struct.pack("<h", val))
    w.close()
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ===================== 单案取证（阶段A）实时编排 =====================
def _honest_mode(caps: dict) -> str:
    """按 capabilities 的真实降级程度给出 mode 标注，杜绝"全回退仍标 live"。

    - 全部能力均回退 → "mock(fallback)"（与阶段B 群体洞察的回退标注口径一致）
    - 部分回退       → "live(partial)"（前端可提示"本轮部分能力回退"）
    - 全部真实       → "live"
    """
    if not caps:
        return "mock(fallback)"
    live_keys = [k for k, v in caps.items() if v]
    if not live_keys:
        return "mock(fallback)"
    if len(live_keys) < len(caps):
        return "live(partial)"
    return "live"


def live_analyze(
    returned_path: str,
    product_path: str,
    listing_text: str,
    sku: str,
    amount: float,
    returned_url: str | None = None,
    product_url: str | None = None,
) -> dict:
    """方案「阶段A·个案举证」live 编排：并行取证 → 一致性核验 → 卷宗+语音 → 优先级评分。

    **逐能力回退**：任一模型调用失败（网关未开通/超时/额度）仅该能力回退 mock，其余真实能力仍生效，
    从而网关「渐进开通」哪些模型，哪些就实时变真（A1/A3 变真的代码前提）。
    无 Key / 无公网图 时整体抛错，由 pipeline 回退到 mock，保证演示不中断。

    returned_url / product_url：上传图的公网 URL（由 storage 层给出，图床落地 P3-17）；
    缺省时按 PUBLIC_IMAGE_BASE + 文件名拼装（保持旧行为）。
    """
    if not API_KEY:
        raise RuntimeError(f"未配置 {_PROFILE['key_env']}（profile={MODEL_ROUTER_PROFILE}）")
    # 视觉输入：优先本地文件内联 base64（无需公网可达，最稳），回退公网 URL。
    # 不再强制 PUBLIC_IMAGE_BASE——只要调用方能给出本地图路径，视觉即可真跑（P3-17 视觉实跑修复）。
    ret_src = _img_source(returned_path) or _img_source(returned_url)
    prod_src = _img_source(product_path) or _img_source(product_url)
    # 向量回退仍需 URL（embeddings 端点吃 {"image": url}）；没有则后续自然失败并降级哈希
    ret_url = returned_url or (
        f"{PUBLIC_IMAGE_BASE}/{os.path.basename(returned_path)}" if PUBLIC_IMAGE_BASE else None
    )
    prod_url = product_url or (
        f"{PUBLIC_IMAGE_BASE}/{os.path.basename(product_path)}" if PUBLIC_IMAGE_BASE else None
    )
    if not ret_src or not prod_src:
        raise RuntimeError("live 模式需本地图路径或可公网访问的图片地址（视觉输入缺失）")

    _enter_budget(LLM_TOTAL_BUDGET)
    caps: dict[str, bool] = {}

    # ① 同款一致性：优先 VL 直接判同款（真实视觉；百炼工作空间兼容模式不支持视觉向量模型），
    # 失败再回退视觉向量 embed（tokenplan/official 可能支持，吃 URL），最后回退确定性哈希
    try:
        vs = vl_similarity(ret_src, prod_src)
        sim = vs["similarity"]
        caps["similarity"] = True
    except Exception as e:
        logger.warning("live VL 同款判定失败，尝试向量: %s", e)
        try:
            va = embed_image(ret_url or ret_src)
            vb = embed_image(prod_url or prod_src)
            sim = cosine(va, vb)
            caps["similarity"] = True
        except Exception as e2:
            logger.warning("live 图向量也失败，回退 mock 相似度: %s", e2)
            sim = _fallback_similarity(returned_path, product_path)
            caps["similarity"] = False
    # 阈值用自标定值（calibration.get_active_threshold），网关开通视觉后即按真实分离点判定
    same = sim >= get_active_threshold()

    # ② 瑕疵识别（网关开通 qwen3-vl-plus 即真实；真实 bbox 待视觉模型支持，live 不返回示意框）
    try:
        raw = vl_chat(ret_src, DEFECT_RECOGNITION_PROMPT)
        defects = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()] or [
            "无明显瑕疵"
        ]
        caps["defects"] = True
    except Exception as e:
        logger.warning("live 瑕疵识别失败，回退 mock: %s", e)
        defects = _fallback_defects(returned_path)
        caps["defects"] = False

    # ②' 缺陷定位（关键帧红框）：网关开通 qwen3-vl-plus 即返回真实归一化 bbox；
    # 未开通 / 解析失败 → 确定性示意框（不替代真实检测），并标记 boxes=False 让前端如实标注「回退」
    try:
        boxes = vl_detect_boxes(ret_src, DEFECT_BBOX_PROMPT, img_size=_image_size(returned_path))
        if not boxes:
            raise ValueError("VL 未返回任何有效 bbox")
        caps["boxes"] = True
    except Exception as e:
        logger.warning("live 缺陷定位失败，回退示意框: %s", e)
        boxes = _fallback_defect_boxes(returned_path, defects)
        caps["boxes"] = False

    # ③ + ④ 一致性核验与卷宗（OCR + LLM；网关开通 qwen-vl-ocr 即真实承诺提取）
    try:
        promise = ocr(prod_src)
        caps["ocr"] = True
    except Exception as e:
        logger.warning("live OCR 失败，回退 listing_text: %s", e)
        promise = listing_text
        caps["ocr"] = False
    consistency = llm(consistency_prompt(sim, defects, promise or listing_text))
    dossier = llm(dossier_prompt(sku, sim, defects, consistency))
    voice_text = llm(voice_prompt(sim, defects))

    # ⑥ 母语语音（网关开通 TTS 即真实）
    try:
        audio = tts(voice_text)
        caps["tts"] = True
    except Exception as e:
        logger.warning("live TTS 失败，回退占位音频: %s", e)
        audio = _gen_wav(voice_text)
        caps["tts"] = False

    # ⑤ 优先级评分（rerank 大规模多案时替换；单案用确定性公式，网关开通 qwen3-rerank 时可用）
    sev_score = max([SEVERITY.get(d, 0.2) for d in defects])
    priority = round(
        min(1.0, 0.4 + (1 - sim) * 0.3 + sev_score * 0.3 + (0.2 if amount > 50 else 0)), 3
    )

    return {
        "similarity": sim,
        "same_item": same,
        "defect_tags": defects,
        "defect_description": ", ".join(defects),
        "consistency": consistency,
        "dossier": dossier,
        "voice_text": voice_text,
        "voice_audio_b64": audio,
        "priority_score": priority,
        "defect_boxes": boxes,  # live 真实 bbox（网关开通 qwen3-vl-plus）或确定性示意框（回退）
        "defect_boxes_live": caps.get("boxes", False),  # True=真实视觉坐标，False=示意回退
        # 诚信标注：此前无论 capabilities 是否全部回退都恒返回 "live"，与阶段B 群体洞察的
        # "mock(fallback)" 口径自相矛盾——演示时拔掉网线即可复现"标称 AI 实算、实为确定性
        # 哈希"。现按真实降级程度标注：全回退 → mock(fallback)，部分回退 → live(partial)。
        "mode": _honest_mode(caps),
        "capabilities": caps,  # 透出哪些能力是真实模型、哪些是回退，便于演示说明
        "degraded": [k for k, v in caps.items() if not v],  # 本轮实际降级的能力清单
    }


# ===================== 群体洞察（阶段B）LLM 归因 =====================
def build_insights_live(aggregated: dict) -> dict:
    """方案「阶段B·群体洞察」：用大模型对聚合统计做缺陷聚类 + 根因归因 + 选品/品控建议。
    输入 aggregated 来自 pipeline._aggregate（sku_ranking / defect_distribution / total_cases 等）。
    返回 {root_cause, sku_insights[], recommendations[], sourcing_advice[], report}。
    注意：本函数只负责「推理」，所有数值统计由 pipeline 算好再喂进来，保证可溯源。
    """
    if not API_KEY:
        raise RuntimeError(f"未配置 {_PROFILE['key_env']}（profile={MODEL_ROUTER_PROFILE}）")
    _enter_budget(LLM_TOTAL_BUDGET)
    prompt = build_insights_prompt(aggregated)
    out = llm_json(prompt, model=TEXT_MODEL)
    if not out:
        raise RuntimeError("洞察 LLM 未返回有效 JSON")
    return {
        "root_cause": out.get("root_cause", ""),
        "sku_insights": out.get("sku_insights", []),
        "recommendations": out.get("recommendations", []),
        "sourcing_advice": out.get("sourcing_advice", []),
        "report": out.get("report", ""),
    }
