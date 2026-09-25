# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard · 音频占位工具（P2-4 去重）

生成正弦占位 WAV 的 base64 字符串，作为 mock / TTS 回退时的可播放音频。

原 `_gen_wav` 在 pipeline.py 与 models_router.py 各有一份逐字副本，现下沉为单一来源，
两处统一引用，避免「改一处忘另一处」的口径分叉（与 imghash.py 同思路：跨模块共用的
纯函数放底层小模块，依赖方向 pipeline → models_router 不反向 import）。
"""

from __future__ import annotations

import base64
import io
import math
import struct
import wave


def gen_wav(text: str = "", sr: int = 16000, dur: float = 1.2) -> str:
    """生成一段占位 WAV（正弦音）的 base64 字符串。

    text 参数保留以兼容既有调用签名（未来可按文本调节音高/内容），当前实现不依赖文本。
    用于无真实语音时的可播放占位音频。
    """
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
