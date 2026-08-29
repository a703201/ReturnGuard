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
        "QINIU_ACCESS_KEY",
        "QINIU_SECRET_KEY",
        "QINIU_BUCKET",
        "QINIU_DOMAIN",
        "QINIU_KEY_PREFIX",
    ):
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


def test_public_base(monkeypatch):
    _reload(monkeypatch, {"PUBLIC_IMAGE_BASE": "https://img.example.com/uploads"})
    assert storage.backend_name() == "public_base"
    _assert_unguessable_key(
        storage.upload("/tmp/x.png", "a.png"), "https://img.example.com/uploads", "a.png"
    )
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
    _assert_unguessable_key(
        storage.upload("/tmp/x.png", "a.png"), "https://img.example.com/uploads", "a.png"
    )


def test_qiniu_backend_mocked(monkeypatch):
    # 用假 qiniu 模块避免真实网络/依赖；验证后端选择 + URL 拼装 + 优先级
    import sys
    import types

    class _Info:
        status_code = 200

    class _Auth:
        def __init__(self, ak, sk):
            pass

        def upload_token(self, bucket, key, expires):
            return "fake-token"

    def _put_file(token, key, local_path, **kw):
        return {"key": key}, _Info()

    fake = types.ModuleType("qiniu")
    fake.Auth = _Auth
    fake.put_file = _put_file
    sys.modules["qiniu"] = fake

    try:
        _reload(
            monkeypatch,
            {
                "QINIU_ACCESS_KEY": "ak",
                "QINIU_SECRET_KEY": "sk",
                "QINIU_BUCKET": "mybucket",
                "QINIU_DOMAIN": "http://tuchuang.a703201sworld.top",
                "QINIU_KEY_PREFIX": "ReturnGuard",
            },
        )
        assert storage.backend_name() == "qiniu"
        assert storage.is_public_ready() is True
        url = storage.upload("/tmp/x.png", "abc.png")
        # SEC-P0：key 不可猜测（不再沿用 abc.png）；前缀与域名仍正确拼接
        assert url.startswith("http://tuchuang.a703201sworld.top/ReturnGuard/")
        assert url.endswith(".png")
        assert url.rsplit("/", 1)[-1] != "abc.png"
    finally:
        sys.modules.pop("qiniu", None)


def test_qiniu_over_oss_priority(monkeypatch):
    # 七牛与 OSS 同时配置时，七牛优先（用户个人图床）
    import sys
    import types

    class _Info:
        status_code = 200

    class _Auth:
        def __init__(self, ak, sk):
            pass

        def upload_token(self, bucket, key, expires):
            return "fake-token"

    def _put_file(token, key, local_path, **kw):
        return {"key": key}, _Info()

    fake = types.ModuleType("qiniu")
    fake.Auth = _Auth
    fake.put_file = _put_file
    sys.modules["qiniu"] = fake

    try:
        _reload(
            monkeypatch,
            {
                "QINIU_ACCESS_KEY": "ak",
                "QINIU_SECRET_KEY": "sk",
                "QINIU_BUCKET": "mybucket",
                "QINIU_DOMAIN": "http://tuchuang.a703201sworld.top",
                "QINIU_KEY_PREFIX": "ReturnGuard",
                "RG_OSS_BUCKET": "ossbucket",
                "RG_OSS_ENDPOINT": "oss-cn.example.com",
                "RG_OSS_KEY": "ak2",
                "RG_OSS_SECRET": "sk2",
            },
        )
        assert storage.backend_name() == "qiniu"
    finally:
        sys.modules.pop("qiniu", None)
