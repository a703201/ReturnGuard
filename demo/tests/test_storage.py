"""图床 storage 单测：local / self（自托管隧道）/ public_base（自建反代）。"""

import importlib

import storage

_ENV_KEYS = (
    "PUBLIC_IMAGE_BASE",
    "RG_SELF_IMAGE_BASE",
    "IMAGE_BED",
    "QINIU_ACCESS_KEY",
    "QINIU_SECRET_KEY",
    "QINIU_BUCKET",
    "QINIU_DOMAIN",
    "QINIU_KEY_PREFIX",
)


def _reload(monkeypatch, envs: dict) -> None:
    for k in _ENV_KEYS:
        if k in envs:
            monkeypatch.setenv(k, envs[k])
        else:
            monkeypatch.delenv(k, raising=False)
    importlib.reload(storage)


def test_local_fallback(monkeypatch):
    _reload(monkeypatch, {})
    assert storage.backend_name() == "local"
    # 本地兜底改为签名短链（SEC-8），不再公开 /uploads/<file>
    url = storage.upload("/tmp/x.png", "a.png")
    assert url.startswith("/api/file/") and "f=a.png" in url
    assert storage.is_public_ready() is False


def _assert_unguessable_key(url: str, base: str, filename: str) -> None:
    """SEC-P0 回归：公网图床返回的 key 必须不可猜测（高熵随机，不沿用上传文件名）。"""
    assert url.startswith(base + "/")
    assert url.endswith(".png")
    key = url.rsplit("/", 1)[-1]
    assert key != filename, "对象 key 不应沿用上传文件名"
    # token_urlsafe(32) → 43 字符（不含扩展名），足以抵御遍历爆破
    assert len(key) >= 40, f"对象 key 熵过低（{len(key)} 字符），疑似沿用原名"


def test_public_base(monkeypatch, tmp_path):
    _reload(monkeypatch, {"PUBLIC_IMAGE_BASE": "https://img.example.com/uploads"})
    assert storage.backend_name() == "public_base"
    src = tmp_path / "x.png"
    src.write_bytes(b"x")
    _assert_unguessable_key(
        storage.upload(str(src), "a.png"), "https://img.example.com/uploads", "a.png"
    )
    assert storage.is_public_ready() is True


def test_self_backend(monkeypatch, tmp_path):
    _reload(monkeypatch, {"RG_SELF_IMAGE_BASE": "https://rg.example.com/api/img"})
    assert storage.backend_name() == "self"
    src = tmp_path / "x.png"
    src.write_bytes(b"x")
    url = storage.upload(str(src), "a.png")
    _assert_unguessable_key(url, "https://rg.example.com/api/img", "a.png")
    assert storage.is_public_ready() is True


def test_upload_fallback_on_copy_failure(monkeypatch, tmp_path):
    """public_base/self 复制失败时降级到 local 签名短链，不抛错。"""
    _reload(monkeypatch, {"PUBLIC_IMAGE_BASE": "https://img.example.com/uploads"})
    assert storage.backend_name() == "public_base"
    # 源文件不存在 → _copy_to_public_key 失败 → 自动降级 local
    url = storage.upload("/nonexistent/path/x.png", "a.png")
    assert url.startswith("/api/file/") and "f=a.png" in url


def test_qiniu_reserved_degrades_without_config(monkeypatch, tmp_path):
    """远端图床为**预留**后端：IMAGE_BED=qiniu 但配置不齐 → 安全降级 local，不影响上传。"""
    _reload(monkeypatch, {"IMAGE_BED": "qiniu", "QINIU_ACCESS_KEY": "ak"})
    assert storage.backend_name() == "local"
    src = tmp_path / "x.png"
    src.write_bytes(b"x")
    url = storage.upload(str(src), "a.png")
    assert url.startswith("/api/file/") and "f=a.png" in url
    assert storage.is_public_ready() is False


def test_qiniu_not_in_auto_chain(monkeypatch):
    """未显式 IMAGE_BED=qiniu 时，即使配齐 QINIU_* 也不启用远端（防误上传第三方云）。"""
    _reload(
        monkeypatch,
        {
            "QINIU_ACCESS_KEY": "ak",
            "QINIU_SECRET_KEY": "sk",
            "QINIU_BUCKET": "bucket",
            "QINIU_DOMAIN": "https://cdn.example.com",
        },
    )
    assert "qiniu" not in storage._backend_chain()
    assert storage.backend_name() == "local"
