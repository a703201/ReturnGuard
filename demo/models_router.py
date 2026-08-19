"""ReturnGuard · 模型能力层（live 模式，经阿里云百炼 Token Plan 专属网关调用）

本文件把「方案文档」里规划的模型能力封装成可调用函数，供 pipeline 在 live 模式下调取。
当前网关（Token Plan，OpenAI 兼容协议）开通能力以「文本推理 / 图像生成 / TTS 语音」为主：

    能力                  模型（新网关命名，无 qwen/ 前缀）          本文件函数
    ──────────────────  ──────────────────────────────────────    ──────────────
    ④ 文本生成 / 聚类归因  qwen3.7-max（也可 qwen3.6-flash 等）       llm / llm_json / build_insights_live
    ⑥ 母语语音陈述        qwen-audio-3.0-tts-plus                   tts

以下能力当前网关的「团队版模型列表」未开通（保持原模型名占位，调用会报错并由
pipeline 自动回退 mock，保证演示不中断）：
    ① 同款一致性比对（图像向量）    tongyi-embedding-vision-plus → embed_image + cosine
    ② 瑕疵视觉识别（多模态理解）    qwen3-vl-plus               → vl_chat
    ③ listing 承诺提取（OCR）       qwen-vl-ocr                 → ocr
    ⑤ 案件优先级排序（重排）        qwen3-rerank                → rerank
若网关后续开通视觉/向量能力，只需把对应函数里的 model 改成网关下发的模型名即可。

运行前提（live 模式必须）：
    - demo/.env 或环境变量 MODEL_ROUTER_API_KEY：Token Plan 专属 API Key
      注意：必须与专属基地址配套使用；用 dashscope.aliyuncs.com 通用地址无法抵扣套餐额度。
    - 环境变量 PUBLIC_IMAGE_BASE：上传图片可公网访问的基础 URL（视觉能力需要时再配）
"""

import base64
import json
import logging
import math
import os
import re

import requests
from constants import SAME_ITEM_THRESHOLD, SEVERITY
from dotenv import load_dotenv

logger = logging.getLogger("returnguard.models_router")

# ---- 阿里云百炼 Token Plan 专属网关（OpenAI 兼容协议）----
# 密钥 / 基地址优先从 demo/.env 读取（.env 不入 git，见根与 demo 两层 .gitignore），
# 也支持外部环境变量覆盖（如 docker compose 注入）。
load_dotenv()  # 读取 demo/.env（本地敏感配置：API Key、网关地址等）

API_BASE = os.environ.get(
    "MODEL_ROUTER_BASE_URL",
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
).rstrip("/")
API_KEY = os.environ.get("MODEL_ROUTER_API_KEY", "")
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "")


def _headers():
    """构造请求头：Bearer 鉴权 + JSON 内容类型。"""
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


# ===================== ① 同款一致性比对（图像向量）=====================
def embed_image(image_url):
    """调用 tongyi-embedding-vision-plus，把一张商品图转成向量。
    返回：浮点数列表（向量）。用于后续余弦相似度判断是否同一件。
    注意：当前 Token Plan 网关团队版模型列表未开通图像向量，调用会报错；
    由 pipeline 的 live 回退机制降级到 mock（确定性哈希），演示不中断。"""
    r = requests.post(
        f"{API_BASE}/embeddings",
        headers=_headers(),
        json={"model": "qwen/tongyi-embedding-vision-plus", "input": {"image": image_url}},
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
    r = requests.post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": "qwen/qwen3-vl-plus",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ===================== ③ listing 承诺提取（OCR）=====================
def ocr(image_url):
    """调用 qwen-vl-ocr，从本店主图/详情图里提取文字承诺（如「全新未拆/30天退换」）。
    方案功能③用它做「退回件实际状态 vs 本店承诺」的货不对板核验。
    注意：当前网关未开通 OCR 视觉模型，调用会报错并回退 mock。"""
    r = requests.post(
        f"{API_BASE}/chat/completions",
        headers=_headers(),
        json={
            "model": "qwen/qwen-vl-ocr",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": image_url}}],
                }
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ===================== ④ 文本生成 / 推理（大模型）=====================
def llm(prompt, model="qwen3.7-max"):
    """调用 qwen3.7-max 做文本生成（举证卷宗、母语陈述、一致性判断）。
    新网关命名无 qwen/ 前缀；可选 qwen3.6-flash / deepseek-v4-flash 等更快模型。返回模型文本。"""
    r = requests.post(
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


def llm_json(prompt, model="qwen3.7-max"):
    """调用大模型并直接返回结构化 JSON（用于洞察聚类/归因）。
    qwen3.6+ 等模型会把思考放进 reasoning_content、content 可能为空，
    此时回退读取 reasoning_content 再抽取。"""
    r = requests.post(
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
def rerank(query, documents, model="qwen3-rerank"):
    """调用 qwen3-rerank，按「追回价值」对多笔待处理案件重排，把高金额/高胜算排前。
    注：当前网关未开通重排模型，pipeline 会退化为本地公式计算（见 pipeline.analyze_case）。"""
    r = requests.post(
        f"{API_BASE}/rerank",
        headers=_headers(),
        json={"model": model, "query": query, "documents": documents},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("results", [])


# ===================== ⑥ 母语语音陈述（TTS）=====================
def tts(text, voice="Chelsie"):
    """调用 qwen-audio-3.0-tts-plus 生成语音（base64 编码的音频）。
    新网关命名 qwen-audio-3.0-tts-plus（OpenAI 兼容 /audio/speech 路径，若网关路径不同需调整）。"""
    r = requests.post(
        f"{API_BASE}/audio/speech",
        headers=_headers(),
        json={"model": "qwen-audio-3.0-tts-plus", "input": text, "voice": voice},
        timeout=60,
    )
    r.raise_for_status()
    return base64.b64encode(r.content).decode("ascii")


# ===================== 单案取证（阶段A）实时编排 =====================
def live_analyze(
    returned_path: str, product_path: str, listing_text: str, sku: str, amount: float
) -> dict:
    """方案「阶段A·个案举证」：把上传的退回图+本店主图送进多个模型，输出一单取证结果。
    三路并行取证 → 一致性核验 → 卷宗+语音 → 优先级评分。
    无 Key / 无公网图 时主动抛错，由 pipeline 回退到 mock，保证演示不中断。"""
    if not API_KEY:
        raise RuntimeError("未配置 MODEL_ROUTER_API_KEY")
    if not PUBLIC_IMAGE_BASE:
        raise RuntimeError("未配置 PUBLIC_IMAGE_BASE（live 模式需可公网访问的图片地址）")

    # 组装两张图的公网 URL（Model Router 在服务端回源拉取）
    ret_url = PUBLIC_IMAGE_BASE.rstrip("/") + "/" + os.path.basename(returned_path)
    prod_url = PUBLIC_IMAGE_BASE.rstrip("/") + "/" + os.path.basename(product_path)

    # ① 同款一致性：两张图向量 → 余弦相似度
    va = embed_image(ret_url)
    vb = embed_image(prod_url)
    sim = cosine(va, vb)
    same = sim >= SAME_ITEM_THRESHOLD  # 阈值来自 constants，与 mock 一致（可调，用历史样本标定）

    # ② 瑕疵识别：让 VL 模型列出视觉瑕疵标签
    raw = vl_chat(
        ret_url, "列出该退货商品的视觉瑕疵，若无则说'无明显瑕疵'，用逗号分隔的简短中文标签。"
    )
    defects = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()] or ["无明显瑕疵"]

    # ③ + ④ 一致性核验与卷宗：OCR 提取承诺，LLM 判断货不对板并生成报告/陈述
    promise = ocr(prod_url)
    consistency = llm(
        f"退回件相似度{sim}，瑕疵：{defects}。本店承诺：{promise or listing_text}。判断是否货不对板，一句话。"
    )
    dossier = llm(
        f"生成结构化举证报告：SKU {sku}，相似度 {sim}，瑕疵 {defects}，一致性 {consistency}。"
    )
    voice_text = llm(
        f"用中文写一段 60 字内的母语退货举证口头陈述，基于：相似度 {sim}，问题 {defects}。"
    )
    audio = tts(voice_text)  # ⑥ 母语语音

    # ⑤ 优先级评分（此处用确定性公式，rerank 大规模多案时替换）
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
        "mode": "live",
    }


# ===================== 群体洞察（阶段B）LLM 归因 =====================
def build_insights_live(aggregated: dict) -> dict:
    """方案「阶段B·群体洞察」：用大模型对聚合统计做缺陷聚类 + 根因归因 + 选品/品控建议。
    输入 aggregated 来自 pipeline._aggregate（sku_ranking / defect_distribution / total_cases 等）。
    返回 {root_cause, sku_insights[], recommendations[], report}。
    注意：本函数只负责「推理」，所有数值统计由 pipeline 算好再喂进来，保证可溯源。
    """
    if not API_KEY:
        raise RuntimeError("未配置 MODEL_ROUTER_API_KEY")
    ctx = {
        "total_cases": aggregated.get("total_cases"),
        "sku_ranking": aggregated.get("sku_ranking"),
        "defect_distribution": aggregated.get("defect_distribution"),
    }
    prompt = (
        "你是一名资深的跨境电商品控与选品分析师。下面是一位跨境卖家退货案件的聚合统计（JSON）：\n"
        f"{json.dumps(ctx, ensure_ascii=False)}\n\n"
        "请完成四件事，并以 JSON 返回（不要任何解释文本，只返回 JSON）：\n"
        "1) root_cause：字符串，归纳退货高发的根因（如包装防护不足 / 供应商质量不稳定 / listing 过度承诺 / 物流暴力分拣等），并给出数据依据。\n"
        '2) sku_insights：数组，取退款金额最高的前 3 个 SKU，每个元素为 {"sku":..,"finding":..,"action":..}，finding 指出该 SKU 的核心问题，action 给可执行整改动作。\n'
        "3) recommendations：数组，3-5 条可执行的选品 / 品控 / listing 改写建议，面向卖家管理者。\n"
        "4) report：字符串，一段《选品 / 品控洞察报告》正文（中文，约 150 字），总结现状与下一步。\n"
    )
    out = llm_json(prompt, model="qwen3.7-max")
    if not out:
        raise RuntimeError("洞察 LLM 未返回有效 JSON")
    return {
        "root_cause": out.get("root_cause", ""),
        "sku_insights": out.get("sku_insights", []),
        "recommendations": out.get("recommendations", []),
        "report": out.get("report", ""),
    }
