#!/usr/bin/env python3
"""
Model Router API 关键能力验证脚本（仅依赖标准库）
验证三项：
  1) 文本对话（连通性 sanity）
  2) TTS -> ASR 语音闭环（验证 /v1/audio/speech + /v1/audio/transcriptions）
  3) 图向量比对（生成两张图 -> tongyi-embedding-vision-plus 嵌入 -> 余弦相似度）

用法：
  set MODEL_ROUTER_API_KEY=sk-xxx   (Windows: set, Linux/Mac: export)
  python verify_api.py
"""

import json
import math
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = "https://model-router.edu-aliyun.com/v1"
KEY = os.environ.get("MODEL_ROUTER_API_KEY")


def _request(method, path, payload=None, extra_headers=None, as_bytes=False):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {KEY}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read()
        return r.status, (raw if as_bytes else raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa
        return -1, f"{type(e).__name__}: {e}"


def jprint(label, status, body, clip=600):
    s = body if isinstance(body, str) else f"<{len(body)} bytes binary>"
    print(f"[{label}] HTTP {status}")
    print("   " + s[:clip].replace("\n", " "))
    print()


def test_chat():
    print("=== TEST 1: chat completion (sanity) ===")
    st, bd = _request(
        "POST",
        "/chat/completions",
        {
            "model": "qwen/qwen3.6-flash",
            "messages": [{"role": "user", "content": "用一句话介绍跨境退货取证。"}],
            "stream": False,
        },
    )
    jprint("chat", st, bd)
    return st == 200


def test_tts_asr():
    print("=== TEST 2: TTS -> ASR round trip ===")
    text = "您好，这里是跨境退货取证系统，请上传退回商品照片。"
    # 1) TTS 合成语音
    st, bd = _request(
        "POST",
        "/audio/speech",
        {
            "model": "qwen/qwen3-tts-instruct-flash",
            "input": text,
            "voice": "Chelsie",
            "response_format": "wav",
        },
        as_bytes=True,
    )
    if st != 200 or not isinstance(bd, (bytes, bytearray)):
        jprint("tts", st, bd if isinstance(bd, str) else f"<audio {len(bd)}B>")
        print("   TTS FAILED -> cannot run ASR round trip\n")
        return False
    wav_path = "asr_test.wav"
    with open(wav_path, "wb") as f:
        f.write(bd)
    print(f"[tts] HTTP {st} -> saved {wav_path} ({len(bd)} bytes)")

    # 2) ASR 转写（multipart/form-data）
    boundary = "----wb" + uuid.uuid4().hex[:16]
    with open(wav_path, "rb") as f:
        fdata = f.read()
    body = b""
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nqwen/qwen3-asr-flash\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="asr_test.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    body += fdata
    body += f"\r\n--{boundary}--\r\n".encode()
    st, bd = _request(
        "POST",
        "/audio/transcriptions",
        None,
        extra_headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        as_bytes=True,
    )
    s = bd.decode("utf-8", "replace") if isinstance(bd, (bytes, bytearray)) else bd
    jprint("asr", st, s)
    ok = st == 200 and any(ch in s for ch in ["退货", "取证", "商品", "照片", "跨境"])
    print(f"   ASR round-trip {'PASS' if ok else 'CHECK'}: expected substring from '{text}'\n")
    return ok


def test_image_vectors():
    print("=== TEST 3: image embedding + similarity ===")

    # 1) 生成两张不同图（同步模型 wan2.7-image）
    def gen(prompt):
        st, bd = _request(
            "POST",
            "/images/generations",
            {
                "model": "qwen/wan2.7-image",
                "prompt": prompt,
                "n": 1,
                "size": "512*512",
            },
        )
        try:
            d = json.loads(bd) if isinstance(bd, str) else {}
            item = (d.get("data") or [{}])[0]
            return st, (item.get("url") or item.get("b64_json"))
        except Exception:  # noqa
            return st, None

    st1, url1 = gen("一只在厨房台面上运行的便携式榨汁杯，白色背景产品图")
    st2, url2 = gen("一双放在木质桌面的蓝色运动鞋，侧光")
    if not url1 or not url2:
        jprint("img-gen A", st1, str(url1)[:200])
        jprint("img-gen B", st2, str(url2)[:200])
        print("   image generation FAILED -> cannot embed\n")
        return False
    print(f"[img-gen] A HTTP {st1} url?{bool(url1)} | B HTTP {st2} url?{bool(url2)}")

    # 2) 嵌入两张图
    def embed(url):
        st, bd = _request(
            "POST",
            "/embeddings",
            {
                "model": "qwen/tongyi-embedding-vision-plus",
                "input": {"image": url},
            },
        )
        try:
            d = json.loads(bd) if isinstance(bd, str) else {}
            return st, (d.get("data") or [{}])[0].get("embedding")
        except Exception:  # noqa
            return st, None

    st_e1, v1 = embed(url1)
    st_e2, v2 = embed(url2)
    if not v1 or not v2:
        jprint("embed A", st_e1, str(v1)[:200])
        jprint("embed B", st_e2, str(v2)[:200])
        print("   embedding FAILED\n")
        return False

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    sim = cos(v1, v2)
    print(f"[embed] dim={len(v1)} | cross-similarity(不同图)={sim:.4f}")
    print(f"   image-vector pipeline {'PASS' if len(v1) > 0 else 'FAIL'}\n")
    return len(v1) > 0


if __name__ == "__main__":
    if not KEY:
        print("ERROR: 请先设置环境变量 MODEL_ROUTER_API_KEY=sk-xxx")
        sys.exit(2)
    print(f"BASE={BASE}\n")
    r1 = test_chat()
    r2 = test_tts_asr()
    r3 = test_image_vectors()
    print("=" * 40)
    print(f"SUMMARY  chat={r1}  tts+asr={r2}  image-vectors={r3}")
