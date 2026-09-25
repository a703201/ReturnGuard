# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard · 上传图存储（可插拔后端：默认本地自持，远端图床接口预留）

上传的退货图默认**落本机磁盘**，不经第三方对象存储；同时保留一套**可插拔的后端注册表**，
把「自托管公开通道」与「远端对象存储（预留）」统一到同一 upload() 入口，便于按部署环境
零代码切换。

后端一览（`IMAGE_BED` 环境变量可显式指定；未指定时按下列**自动优先级**）：
    - local（默认兜底）：落在 ``demo/uploads/``，经 HMAC 签名短链 ``/api/file/{sig}?f=..&e=..``
      短期可读。**演示即用此/自托管通道，不依赖任何第三方云服务。**
    - self：配 ``RG_SELF_IMAGE_BASE``（如反向代理 / CDN 域名 + ``/api/img``），把本地图
      复制为 256-bit 不可猜测 key 后经 ``/api/img/{key}`` 暴露，供 live 视觉模型回源。
    - public_base：已有自建反代把 uploads 目录暴露为公网时，配 ``PUBLIC_IMAGE_BASE``。
    - qiniu（**远端预留，默认关闭**）：七牛云对象存储。仅当显式设 ``IMAGE_BED=qiniu`` 且
      配齐 ``QINIU_ACCESS_KEY/SECRET_KEY/BUCKET/DOMAIN`` 时启用；qiniu SDK 为**可选依赖**，
      未安装则自动降级到下一后端（不影响上传主流程）。**默认不启用，保留接口做后续准备。**

自动优先级（未显式指定 IMAGE_BED 时）：self > public_base > local。
qiniu 不进入自动链——必须显式开启，避免误上传到第三方云。

live 模式的视觉/图像向量/OCR 是否受影响：
    视觉调用优先走 **base64 内联本地文件**（见 models_router._img_source），不经公网图，
    因此默认 local 模式也能让单案视觉真跑通；公网图 URL 只是可选的回源增强通道。

任一后端失败自动降级到下一档并记日志，保证上传主流程不中断。
backend_name() / is_public_ready() 让调用方判断当前生效后端与是否具备公网图能力。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import shutil
import sys
import time
from urllib.parse import quote as _urlquote

from dotenv import load_dotenv

# 必须在读取 RG_SELF_IMAGE_BASE / PUBLIC_IMAGE_BASE 等环境变量前加载 .env，
# 否则若本模块在 models_router(其内调用 load_dotenv) 之前被 import，
# 模块级 os.environ.get 会捕获到空值且后续不再刷新（曾导致 running 服务误判图床为 local）。
# 测试环境跳过：pytest 在启动期就把自身注入 sys.modules（早于任何业务模块 import），
# 因此用 sys.modules.get("pytest") 判断最可靠；不能用 PYTEST_CURRENT_TEST——它只在测试
# "执行期"才写入环境，模块"收集期" import 时尚未存在，会导致真实 .env 被误加载泄漏进用例。
if sys.modules.get("pytest") is None and "PYTEST_CURRENT_TEST" not in os.environ:
    load_dotenv()

# 上传图签名 URL 复用令牌签名密钥（SEC-8）：本地回退从公开 /uploads/<file> 改为
# 签名 + 短期过期的 /api/file/{sig}?f=..&e=..，杜绝 PII 被匿名长期拉取。
# 动态引用 auth._SECRET（而非捕获到导入期值），避免 auth 被 reload 后密钥漂移导致验签失败。
import auth  # noqa: E402

logger = logging.getLogger("returnguard.storage")

# ---- 后端配置（均从环境变量读取，缺省即不启用对应后端）----
# 显式指定生效后端：local / self / public_base / qiniu。留空=自动优先级。
IMAGE_BED = os.environ.get("IMAGE_BED", "").strip().lower()
# self：经本服务隧道暴露上传图，供视觉网关回源；退货图不出境。
SELF_IMAGE_BASE = os.environ.get("RG_SELF_IMAGE_BASE", "").rstrip("/")
# public_base：自建反代 / 内网 DNS 把本服务的上传目录暴露为公网时配置。
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "").rstrip("/")
# qiniu（远端预留）：仅在 IMAGE_BED=qiniu 时启用，且需四项齐备，否则降级。
QINIU_ACCESS_KEY = os.environ.get("QINIU_ACCESS_KEY", "").strip()
QINIU_SECRET_KEY = os.environ.get("QINIU_SECRET_KEY", "").strip()
QINIU_BUCKET = os.environ.get("QINIU_BUCKET", "").strip()
QINIU_DOMAIN = os.environ.get("QINIU_DOMAIN", "").strip().rstrip("/")
QINIU_KEY_PREFIX = os.environ.get("QINIU_KEY_PREFIX", "ReturnGuard").strip().strip("/")

# qiniu SDK 懒加载状态（未安装/导入失败时只提示一次，随后静默降级）
_QINIU_IMPORT_TRIED = False
_qiniu_mod = None


def _qiniu_available() -> bool:
    """qiniu 远端后端是否「配置齐备且 SDK 可用」。首次调用时懒加载 SDK。"""
    global _QINIU_IMPORT_TRIED, _qiniu_mod
    if not (QINIU_ACCESS_KEY and QINIU_SECRET_KEY and QINIU_BUCKET and QINIU_DOMAIN):
        return False
    if not _QINIU_IMPORT_TRIED:
        _QINIU_IMPORT_TRIED = True
        try:
            import qiniu  # type: ignore[import-untyped]  # 可选依赖

            _qiniu_mod = qiniu
        except Exception:  # noqa: BLE001
            _qiniu_mod = None
            logger.info(
                "IMAGE_BED=qiniu 但未安装 qiniu SDK，远端图床降级（pip install qiniu 后生效）"
            )
    return _qiniu_mod is not None


def _backend_chain() -> list[str]:
    """返回本次 upload() 的尝试顺序（后端名）。

    - 显式 ``IMAGE_BED``：以其为首选，随后追加 local 兜底（qiniu 未就绪时自动跳过）。
    - 未指定：self > public_base > local（qiniu 预留后端不进入自动链）。
    """
    if IMAGE_BED == "qiniu":
        return ["qiniu", "local"] if _qiniu_available() else ["local"]
    if IMAGE_BED in ("self", "public_base", "local"):
        return [IMAGE_BED, "local"] if IMAGE_BED != "local" else ["local"]
    if IMAGE_BED:
        logger.warning("未知 IMAGE_BED=%s，按自动优先级处理", IMAGE_BED)
    chain: list[str] = []
    if SELF_IMAGE_BASE:
        chain.append("self")
    if PUBLIC_IMAGE_BASE:
        chain.append("public_base")
    chain.append("local")
    return chain


def backend_name() -> str:
    """当前生效的存储后端名（/api/config 与启动日志透出）。

    取值：qiniu（远端预留·显式开启）/ self（自托管隧道）/ public_base（自建反代）/ local（纯本地签名短链）。
    """
    return _backend_chain()[0]


def is_public_ready() -> bool:
    """上传图是否具备**公网可达**地址（live 视觉回源的可选增强项，非必需）。

    local 仅为签名短链（本机放行），不算公网就绪；self / public_base / qiniu 计入。
    """
    return any(b in ("self", "public_base", "qiniu") for b in _backend_chain())


def upload(local_path: str, filename: str) -> str:
    """把本地上传图变成「可经 HTTP 拿到」的 URL，按后端链依次尝试，全失败回退本地签名短链。

    返回：
        - qiniu        ：<QINIU_DOMAIN>/<prefix>/<256bit key>（远端预留，显式开启）
        - self         ：<RG_SELF_IMAGE_BASE>/<256bit key>
        - public_base  ：<PUBLIC_IMAGE_BASE>/<256bit key>
        - local（兜底） ：/api/file/<sig>?f=..&e=.. 签名短链（SEC-8）
    """
    # SEC-P0: 暴露给外部的 URL 必须不可猜测。此前直接沿用上传文件名
    # （形如 <8位hex>_ret_<原名>.png），随机空间仅 32 bit，可被遍历爆破，
    # 而退货图属于买家 PII、且 URL 无校验。对外键统一用 256 bit 随机串。
    public_key = _public_object_key(filename)
    for backend in _backend_chain():
        if backend == "local":
            break  # local 是兜底，循环后再统一走签名短链
        url = _serve_via(backend, local_path, public_key)
        if url:
            return url
    return sign_upload_url(filename)  # 本地兜底：签名短链（SEC-8）


def _serve_via(backend: str, local_path: str, public_key: str) -> str | None:
    """按后端名尝试产出公网 URL，成功返回 URL，失败返回 None（调用方继续降级）。"""
    if backend == "self":
        if SELF_IMAGE_BASE and _copy_to_public_key(local_path, public_key):
            return f"{SELF_IMAGE_BASE}/{public_key}"
    elif backend == "public_base":
        if PUBLIC_IMAGE_BASE and _copy_to_public_key(local_path, public_key):
            return f"{PUBLIC_IMAGE_BASE}/{public_key}"
    elif backend == "qiniu":
        return _qiniu_upload(local_path, public_key)
    return None


def _qiniu_upload(local_path: str, public_key: str) -> str | None:
    """远端预留后端：上传到七牛云对象存储并返回公网 URL（失败返回 None 以降级）。

    仅当 IMAGE_BED=qiniu 且配置齐备、SDK 可用时被调用；默认不启用。
    """
    if _qiniu_mod is None:
        return None
    try:
        from qiniu import Auth, put_file  # type: ignore[import-untyped]

        key = f"{QINIU_KEY_PREFIX}/{public_key}" if QINIU_KEY_PREFIX else public_key
        token = Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY).upload_token(QINIU_BUCKET, key, 3600)
        info, err = put_file(token, key, local_path)
        if err is not None or info is None:
            logger.warning("七牛上传失败，降级下一后端：%s", err)
            return None
        return f"{QINIU_DOMAIN}/{info['key']}"
    except Exception:  # noqa: BLE001
        logger.exception("七牛上传异常，降级下一后端")
        return None


def _copy_to_public_key(local_path: str, public_key: str) -> bool:
    """把上传图复制成同目录下的不可猜测文件名，成功返回 True（失败已记日志）。"""
    try:
        dst = os.path.join(os.path.dirname(os.path.abspath(local_path)), public_key)
        shutil.copy2(local_path, dst)
        return True
    except Exception:
        logger.exception("本地图复制失败，降级到下一后端")
        return False


def _public_object_key(filename: str) -> str:
    """为对外暴露的图生成不可猜测的对象 key（保留扩展名，便于 CDN 正确设置 Content-Type）。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        ext = ".png"
    return f"{secrets.token_urlsafe(32)}{ext}"


def sign_upload_url(filename: str, ttl: int | None = None) -> str:
    """生成本地上传图的签名短链（SEC-8）：HMAC(filename|exp, AUTH_SECRET) + TTL。

    替代原公开静态 /uploads/<file>：URL 带 ?f=<文件名>&e=<过期时间戳>，sig 为 HMAC 前缀；
    服务端 /api/file/{sig} 校验签名与过期，失败/过期/越界均 404（不泄露是否存在）。"""
    ttl = int(os.environ.get("UPLOAD_URL_TTL", "3600")) if ttl is None else ttl
    exp = int(time.time()) + ttl
    payload = f"{filename}|{exp}"
    sig = hmac.new(auth._SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"/api/file/{sig}?f={_urlquote(filename)}&e={exp}"
