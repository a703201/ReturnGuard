"""图床 storage 单测：本地 / PUBLIC_IMAGE_BASE / OSS 降级（无 boto3 时降级不报错）。"""

import importlib

import storage


def _reload(monkeypatch, envs: dict) -> None:
    for k in (
        "PUBLIC_IMAGE_BASE",
        "RG_OSS_BUCKET",
        "RG_OSS_ENDPOINT",
        "RG_OSS_KEY",
        "RG_OSS_SECRET",
        "RG_OSS_REGION",
    ):
        if k in envs:
            monkeypatch.setenv(k, envs[k])
        else:
            monkeypatch.delenv(k, raising=False)
    importlib.reload(storage)


def test_local_fallback(monkeypatch):
    _reload(monkeypatch, {})
    assert storage.backend_name() == "local"
    assert storage.upload("/tmp/x.png", "a.png") == "/uploads/a.png"
    assert storage.is_public_ready() is False


def test_public_base(monkeypatch):
    _reload(monkeypatch, {"PUBLIC_IMAGE_BASE": "https://img.example.com/uploads"})
    assert storage.backend_name() == "public_base"
    assert storage.upload("/tmp/x.png", "a.png") == "https://img.example.com/uploads/a.png"
    assert storage.is_public_ready() is True


def test_oss_fallback_without_boto3(monkeypatch):
    # 配了 OSS 但环境无 boto3（或上传失败）→ 降级到 public_base，不抛错
    _reload(
        monkeypatch,
        {
            "RG_OSS_BUCKET": "mybucket",
            "RG_OSS_ENDPOINT": "oss-cn.example.com",
            "RG_OSS_KEY": "ak",
            "RG_OSS_SECRET": "sk",
            "PUBLIC_IMAGE_BASE": "https://img.example.com/uploads",
        },
    )
    assert storage.backend_name() == "oss"
    url = storage.upload("/tmp/x.png", "a.png")
    assert url == "https://img.example.com/uploads/a.png"
