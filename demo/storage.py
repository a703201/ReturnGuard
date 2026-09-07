"""ReturnGuard · 上传图存储（本地自持，P3-17 收口 → 去云端化）

上传的退货图一律**落本机磁盘**，不外传任何第三方对象存储（此前支持七牛云 / OSS，
已按「不用云端、降低资源消耗与依赖体积」的决策整体移除相关 SDK 依赖与代码分支）。

对外仍保留两个可选的自托管通道（均为**自己这台机器**，不引入第三方云服务）：

- local（默认）：落在 ``demo/uploads/``，经 HMAC 签名短链 ``/api/file/{sig}?f=..&e=..``
  短期可读，且签名短链本身就在本机放行。
- self：配 ``RG_SELF_IMAGE_BASE``（如 Cloudflare Tunnel 域名 + ``/api/img``），把本地图
  复制为 256-bit 不可猜测 key 后经 ``/api/img/{key}`` 暴露，供 live 视觉模型回源。
- public_base：已有自建反代把 uploads 目录暴露为公网时，配 ``PUBLIC_IMAGE_BASE``。

live 模式的视觉/图像向量/OCR 是否受影响：
    视觉调用优先走 **base64 内联本地文件**（见 models_router._img_source），不经公网图，
    因此默认 local 模式也能让单案视觉真跑通；公网图 URL 只是可选的回源增强通道。

优先级：self > public_base > local。任一失败自动降级，保证上传主流程不中断。
backend_name() / is_public_ready() 让调用方判断是否具备公网图能力。
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

# ---- 自托管（可选，非第三方云）----
# 经本服务隧道暴露上传图，供视觉网关回源；退货图不出境，文件随 UPLOAD_DIR 到期清理。
# 例：RG_SELF_IMAGE_BASE=https://rg.a703201sworld.top/api/img
SELF_IMAGE_BASE = os.environ.get("RG_SELF_IMAGE_BASE", "").rstrip("/")
# 自建反代 / 内网 DNS 把本服务的上传目录暴露为公网时配置。
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "").rstrip("/")


def backend_name() -> str:
    """当前生效的存储后端名，便于 /api/config 与日志透出。

    取值：self（自托管隧道）/ public_base（自建反代）/ local（纯本地签名短链）。
    """
    if SELF_IMAGE_BASE:
        return "self"
    if PUBLIC_IMAGE_BASE:
        return "public_base"
    return "local"


def is_public_ready() -> bool:
    """上传图是否具备公网可达地址（live 视觉回源的可选增强项，非必需）。"""
    return bool(SELF_IMAGE_BASE) or bool(PUBLIC_IMAGE_BASE)


def upload(local_path: str, filename: str) -> str:
    """把本地上传图变成「可经 HTTP 拿到」的 URL，全程不依赖任何第三方云对象存储。

    返回：
        - self        ：<RG_SELF_IMAGE_BASE>/<256bit key>
        - public_base ：<PUBLIC_IMAGE_BASE>/<256bit key>
        - local（兜底）：/api/file/<sig>?f=..&e=.. 签名短链（SEC-8）
    任一环节失败降级到下一档并记日志，保证上传主流程不中断。
    """
    # SEC-P0: 暴露给外部的 URL 必须不可猜测。此前直接沿用上传文件名
    # （形如 <8位hex>_ret_<原名>.png），随机空间仅 32 bit，可被遍历爆破，
    # 而退货图属于买家 PII、且 URL 无校验。对外键统一用 256 bit 随机串。
    public_key = _public_object_key(filename)
    if SELF_IMAGE_BASE:
        # 自托管：把本地上传图复制为不可猜测 key，经 /api/img/{key} 暴露给视觉网关回源。
        # 文件仍留在本机 UPLOAD_DIR，随 24h 清理策略回收，不占用额外存储配额。
        if _copy_to_public_key(local_path, public_key):
            return f"{SELF_IMAGE_BASE}/{public_key}"
    if PUBLIC_IMAGE_BASE:
        if _copy_to_public_key(local_path, public_key):
            return f"{PUBLIC_IMAGE_BASE}/{public_key}"
    return sign_upload_url(filename)  # 本地兜底：签名短链（SEC-8）


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
