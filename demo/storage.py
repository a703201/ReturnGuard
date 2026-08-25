"""ReturnGuard · 图床（上传图公网可达，P3-17 收口）

live 模式下的视觉/图像向量/OCR 模型需要「服务端能公网回源拉取」上传的退货图。本模块把
"本地上传图如何变成公网可访问 URL" 抽象成可插拔后端，消除此前 live 模式拿不到图的硬伤：

- 七牛云对象存储（Qiniu，个人图床首选）：配置了 QINIU_ACCESS_KEY/SECRET/BUCKET/DOMAIN 时，
  上传即 PUT 到七牛并返回公网 URL（真实图床，跨网络可达）。SDK 延迟导入，无 qiniu 环境不必安装。
- 对象存储（OSS / S3 兼容）：配置了 RG_OSS_BUCKET/ENDPOINT/KEY/SECRET 时，上传即 PUT 到
  对象存储并返回公网 URL（真实图床，跨网络可达）。boto3 延迟导入，无对象存储环境不必安装。
- PUBLIC_IMAGE_BASE：仅配置该变量（如反代 / 内网 DNS 把本服务的 /uploads 暴露为公网）时，
  返回 PUBLIC_IMAGE_BASE + 文件名（由应用自身托管上传目录）。
- 兜底：返回应用相对路径 /uploads/<文件名>（仅同主机 demo 可用；live 需公网可达，否则
  live_analyze 会主动抛错并回退 mock，保证演示不中断）。

优先级：qiniu > oss > public_base > local。任一失败自动降级，保证上传主流程不中断。
select_backend() / is_public_ready() 让调用方在 live 前判断是否具备公网图能力。
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

# 必须在读取 QINIU_*/RG_OSS_*/PUBLIC_IMAGE_BASE 等环境变量前加载 .env，
# 否则若本模块在 models_router(其内调用 load_dotenv) 之前被 import，
# 模块级 os.environ.get 会捕获到空值且后续不再刷新（曾导致 running 服务误判图床为 local）。
# 测试环境跳过：pytest 在启动期就把自身注入 sys.modules（早于任何业务模块 import），
# 因此用 sys.modules.get("pytest") 判断最可靠；不能用 PYTEST_CURRENT_TEST——它只在测试
# "执行期"才写入环境，模块"收集期" import 时尚未存在，会导致真实 .env 被误加载泄漏进用例。
if sys.modules.get("pytest") is None and "PYTEST_CURRENT_TEST" not in os.environ:
    load_dotenv()

logger = logging.getLogger("returnguard.storage")

# ---- 七牛云（Qiniu）个人图床 ----
QINIU_ACCESS_KEY = os.environ.get("QINIU_ACCESS_KEY", "")
QINIU_SECRET_KEY = os.environ.get("QINIU_SECRET_KEY", "")
QINIU_BUCKET = os.environ.get("QINIU_BUCKET", "")
QINIU_DOMAIN = os.environ.get("QINIU_DOMAIN", "").rstrip("/")  # 公网域名，如 http://tuchuang.xxx.top
QINIU_KEY_PREFIX = os.environ.get("QINIU_KEY_PREFIX", "").strip("/")  # 存储键前缀（"文件夹"），如 ReturnGuard

# ---- OSS / S3 兼容对象存储 ----
OSS_BUCKET = os.environ.get("RG_OSS_BUCKET", "")
OSS_ENDPOINT = os.environ.get("RG_OSS_ENDPOINT", "")
OSS_KEY = os.environ.get("RG_OSS_KEY", "")
OSS_SECRET = os.environ.get("RG_OSS_SECRET", "")
OSS_REGION = os.environ.get("RG_OSS_REGION", "")
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "").rstrip("/")


def _use_qiniu() -> bool:
    return bool(QINIU_ACCESS_KEY and QINIU_SECRET_KEY and QINIU_BUCKET and QINIU_DOMAIN)


def _use_oss() -> bool:
    return bool(OSS_BUCKET and OSS_ENDPOINT and OSS_KEY and OSS_SECRET)


def _oss_public_base() -> str:
    # OSS 公网域名约定：<bucket>.<endpoint>
    return f"https://{OSS_BUCKET}.{OSS_ENDPOINT}".rstrip("/")


def _qiniu_public_base() -> str:
    return QINIU_DOMAIN


def backend_name() -> str:
    """当前生效的图床后端名，便于 /api/config 与日志透出。"""
    if _use_qiniu():
        return "qiniu"
    if _use_oss():
        return "oss"
    if PUBLIC_IMAGE_BASE:
        return "public_base"
    return "local"


def is_public_ready() -> bool:
    """live 模式能否拿到公网图：任一真实图床已配 或 PUBLIC_IMAGE_BASE 已配。"""
    return _use_qiniu() or _use_oss() or bool(PUBLIC_IMAGE_BASE)


def upload(local_path: str, filename: str) -> str:
    """把本地上传图变成公网可访问 URL（可能就地把文件同步到对象存储）。

    返回公网 URL 字符串：
        - 七牛云：<QINIU_DOMAIN>/<QINIU_KEY_PREFIX>/<filename>
        - 对象存储：https://<bucket>.<endpoint>/<filename>
        - PUBLIC_IMAGE_BASE：<base>/<filename>
        - 兜底：/uploads/<filename>
    任一真实图床失败不影响主流程：逐层降级到下一后端并记日志。
    """
    if _use_qiniu():
        try:
            return _upload_qiniu(local_path, filename)
        except Exception:  # 七牛异常降级，保证上传主流程不中断
            logger.exception("Qiniu 上传失败，降级到 OSS / PUBLIC_IMAGE_BASE / 本地路径")
    if _use_oss():
        try:
            return _upload_oss(local_path, filename)
        except Exception:  # 对象存储异常降级，保证上传主流程不中断
            logger.exception("OSS 回传失败，降级到 PUBLIC_IMAGE_BASE / 本地路径")
    if PUBLIC_IMAGE_BASE:
        return f"{PUBLIC_IMAGE_BASE}/{filename}"
    return f"/uploads/{filename}"


def _qiniu_key(filename: str) -> str:
    return f"{QINIU_KEY_PREFIX}/{filename}" if QINIU_KEY_PREFIX else filename


def _upload_qiniu(local_path: str, filename: str) -> str:
    """上传到七牛云对象存储（qiniu SDK 延迟导入，避免无 qiniu 环境也必须安装）。"""
    from qiniu import Auth, put_file  # noqa: PLC0415

    q = Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)
    key = _qiniu_key(filename)
    token = q.upload_token(QINIU_BUCKET, key, 3600)
    ret, info = put_file(token, key, local_path)
    if info is None or getattr(info, "status_code", None) != 200:
        raise RuntimeError(f"Qiniu 上传失败: {info}")
    return f"{_qiniu_public_base()}/{key}"


def _upload_oss(local_path: str, filename: str) -> str:
    """上传到 OSS / S3 兼容对象存储（boto3 延迟导入，避免无对象存储环境也必须安装）。"""
    import boto3  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{OSS_ENDPOINT}",
        aws_access_key_id=OSS_KEY,
        aws_secret_access_key=OSS_SECRET,
        region_name=OSS_REGION or None,
    )
    client.upload_file(local_path, OSS_BUCKET, filename)
    return f"{_oss_public_base()}/{filename}"
