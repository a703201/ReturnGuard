# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""图片内容确定性哈希（pipeline / models_router 共用的单一实现）

为什么单独成模块：
    依赖方向是 ``pipeline → models_router``（洞察与取证编排调用模型网关），
    所以 models_router **不能反向 import** pipeline，否则成环。早期两边各写一份
    "确定性哈希"，结果实现分叉：pipeline 用**文件内容**（``_content_seed``），
    models_router 用**文件路径**（``md5(f"{returned_path}|{product_path}")``），
    而上传文件名带随机 rid 前缀 —— 同一张图两次上传回退结果就不同，且与 mock
    路径口径不一致，注释却声称"与 pipeline 同口径"（见审查 P0-3）。

    故把"按**文件内容**取种子"下沉为唯一实现，两个模块共同引用，杜绝再次分叉。

不变量：
    * 同一份文件内容 → 恒定种子（可复现，演示与测试可校验）
    * 路径变化不影响结果（修复随机 rid 导致的漂移）
    * 读取失败不抛异常（取证链路上的兜底逻辑不应因 IO 失败中断）
"""

from __future__ import annotations

import hashlib

_CHUNK = 65536


def content_seed(*paths) -> int:
    """用图片**内容**（而非路径）生成稳定随机种子。

    Args:
        *paths: 一个或多个图片路径（本地文件）；也接受任意可 ``open`` 的字节源路径。
            额外传入字符串（如 ``"boxes"``）可为同一张图派生互相独立的种子流。

    Returns:
        int: 由内容 MD5 派生的正整数种子。

    Note:
        读取失败（文件不存在 / 传入的是 URL 而非本地路径）时退化为路径字符串
        哈希，行为与旧实现一致，保证兜底链路永不中断。
    """
    h = hashlib.md5()
    for p in paths:
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(_CHUNK), b""):
                    h.update(chunk)
        except Exception:  # noqa: BLE001 - 兜底：读不到就退化为路径哈希
            h.update(str(p).encode("utf-8"))
    return int(h.hexdigest(), 16)
