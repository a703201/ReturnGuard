"""ReturnGuard · 图床（上传图公网可达，P3-17 收口）

live 模式下的视觉/图像向量/OCR 模型需要「服务端能公网回源拉取」上传的退货图。本模块把
"本地上传图如何变成公网可访问 URL" 抽象成可插拔后端，消除此前 live 模式拿不到图的硬伤：

- 对象存储（OSS / S3 兼容）：配置了 RG_OSS_BUCKET/ENDPOINT/KEY/SECRET 时，上传即 PUT 到
  对象存储并返回公网 URL（真实图床，跨网络可达）。boto3 延迟导入，无对象存储环境不必安装。
- PUBLIC_IMAGE_BASE：仅配置该变量（如反代 / 内网 DNS 把本服务的 /uploads 暴露为公网）时，
  返回 PUBLIC_IMAGE_BASE + 文件名（由应用自身托管上传目录）。
- 兜底：返回应用相对路径 /uploads/<文件名>（仅同主机 demo 可用；live 需公网可达，否则
  live_analyze 会主动抛错并回退 mock，保证演示不中断）。

select_backend() / is_public_ready() 让调用方在 live 前判断是否具备公网图能力。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("returnguard.storage")

OSS_BUCKET = os.environ.get("RG_OSS_BUCKET", "")
OSS_ENDPOINT = os.environ.get("RG_OSS_ENDPOINT", "")
OSS_KEY = os.environ.get("RG_OSS_KEY", "")
OSS_SECRET = os.environ.get("RG_OSS_SECRET", "")
OSS_REGION = os.environ.get("RG_OSS_REGION", "")
PUBLIC_IMAGE_BASE = os.environ.get("PUBLIC_IMAGE_BASE", "").rstrip("/")


def _use_oss() -> bool:
    return bool(OSS_BUCKET and OSS_ENDPOINT and OSS_KEY and OSS_SECRET)


def _oss_public_base() -> str:
    # OSS 公网域名约定：<bucket>.<endpoint>
    return f"https://{OSS_BUCKET}.{OSS_ENDPOINT}".rstrip("/")


def backend_name() -> str:
    """当前生效的图床后端名，便于 /api/config 与日志透出。"""
    if _use_oss():
        return "oss"
    if PUBLIC_IMAGE_BASE:
        return "public_base"
    return "local"


def is_public_ready() -> bool:
    """live 模式能否拿到公网图：对象存储已配 或 PUBLIC_IMAGE_BASE 已配。"""
    return _use_oss() or bool(PUBLIC_IMAGE_BASE)


def upload(local_path: str, filename: str) -> str:
    """把本地上传图变成公网可访问 URL（可能就地把文件同步到对象存储）。

    返回公网 URL 字符串：
        - 对象存储：https://<bucket>.<endpoint>/<filename>
        - PUBLIC_IMAGE_BASE：<base>/<filename>
        - 兜底：/uploads/<filename>
    对象存储失败不影响主流程：自动降级到 PUBLIC_IMAGE_BASE / 本地路径并记日志。
    """
    if _use_oss():
        try:
            return _upload_oss(local_path, filename)
        except Exception:  # 对象存储异常降级，保证上传主流程不中断
            logger.exception("OSS 回传失败，降级到 PUBLIC_IMAGE_BASE / 本地路径")
    if PUBLIC_IMAGE_BASE:
        return f"{PUBLIC_IMAGE_BASE}/{filename}"
    return f"/uploads/{filename}"


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
