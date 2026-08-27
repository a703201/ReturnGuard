"""安全单测：上传文件名穿越清洗、文件类型/大小校验（对应 CODE_REVIEW P1-1/3）。

另含安全复审三项回归（SEC-1 写接口鉴权 / SEC-2 AUTH_SECRET 加载 / SEC-3 代理客户端 IP）。
"""

import importlib
import os
import pathlib
import subprocess
import sys
import time
import types
import uuid

import pytest
from fastapi.testclient import TestClient
from urllib.parse import quote, urlparse, parse_qs

import auth as auth_mod
import main as main_mod
import storage as storage_mod
from main import UPLOAD_DIR, app

_DEMO_DIR = pathlib.Path(__file__).resolve().parent.parent  # demo/


def _read_env_secret() -> str | None:
    envf = _DEMO_DIR / ".env"
    if not envf.exists():
        return None
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("AUTH_SECRET=") and not line.startswith("AUTH_SECRET=请"):
            return line.split("=", 1)[1].strip()
    return None


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n x"


def test_path_traversal_sanitized(auth_headers):
    """恶意文件名 ../../evil.png 必须被清洗为 uploads/ 内的安全文件名，不能越界。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("../../evil.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"}, headers=auth_headers)
        assert r.status_code == 200
        saved = [f for f in os.listdir(UPLOAD_DIR) if "evil" in f]
        assert saved, "清洗后的 evil 文件应已落盘"
        assert all("/" not in f and "\\" not in f for f in saved)
        # 确证未写到 UPLOAD_DIR 之外
        assert not os.path.exists(os.path.join(UPLOAD_DIR, "..", "evil.png"))


def test_reject_non_image(auth_headers):
    with TestClient(app) as c:
        files = {
            "returned_image": ("x.txt", b"hello not an image", "text/plain"),
            "product_image": ("y.txt", b"hello", "text/plain"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"}, headers=auth_headers)
        assert r.status_code == 400


def test_reject_oversize(auth_headers):
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024)
    with TestClient(app) as c:
        files = {
            "returned_image": ("big.png", big, "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"}, headers=auth_headers)
        assert r.status_code == 413


# ===================== 安全复审回归 =====================

def test_write_endpoints_require_login():
    """SEC-1：所有数据写入接口匿名访问必须 401（不能无鉴权全开）。"""
    with TestClient(app) as c:
        # 取证沉淀
        r = c.post(
            "/api/analyze",
            files={
                "returned_image": ("a.png", _png(), "image/png"),
                "product_image": ("b.png", _png(), "image/png"),
            },
            data={"mode": "mock"},
        )
        assert r.status_code == 401, "匿名 /api/analyze 应被拒"
        # 案件录入
        r = c.post("/api/cases", json={"sku": "SKU-X", "category": "c", "supplier": "S1"})
        assert r.status_code == 401, "匿名 /api/cases 应被拒"
        # 阈值自标定（管理动作）
        r = c.post("/api/calibrate", json={"same_sims": [0.9], "diff_sims": [0.2]})
        assert r.status_code == 401, "匿名 /api/calibrate 应被拒"
        # 内部指标端点（P2：避免匿名暴露运行指标）
        r = c.get("/metrics")
        assert r.status_code == 401, "匿名 /metrics 应被拒"


def test_write_endpoints_allow_logged_in():
    """SEC-1：登录会话（demo/demo123）可正常写入，且令牌可跨「重启」复用。"""
    with TestClient(app) as c:
        # 启动期已预置 demo/demo123
        lr = c.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
        assert lr.status_code == 200, "demo 账号登录失败"
        tok = lr.json()["token"]
        hdr = {"Authorization": f"Bearer {tok}"}
        # 取证沉淀（mock）应成功
        r = c.post(
            "/api/analyze",
            files={
                "returned_image": ("a.png", _png(), "image/png"),
                "product_image": ("b.png", _png(), "image/png"),
            },
            data={"mode": "mock"},
            headers=hdr,
        )
        assert r.status_code == 200, "已登录 /api/analyze 应成功"
        # 案件录入应成功
        r = c.post(
            "/api/cases",
            json={"sku": "SKU-SEC1", "category": "c", "supplier": "S1"},
            headers=hdr,
        )
        assert r.status_code == 200, "已登录 /api/cases 应成功"
        # /metrics 登录后可访问
        r = c.get("/metrics", headers=hdr)
        assert r.status_code == 200, "已登录 /metrics 应可访问"


def test_auth_secret_loaded_from_dotenv():
    """SEC-2（真实锁）：auth 模块在 import 期必须自行 load_dotenv 并读取 .env 的 AUTH_SECRET。

    此前 auth 在 import 期读 AUTH_SECRET，但从不调用 load_dotenv，且 main 的 import auth 早于
    其它模块的 load_dotenv，导致 .env 配置被静默忽略、回退每进程随机密钥（重启令牌失效、多 worker 坏）。
    本测试用独立子进程（无 pytest 守卫）导入 auth，验证其确实从 demo/.env 读到了 AUTH_SECRET。
    仅当本地存在 demo/.env 时生效（CI 无 .env 则跳过，不破坏可复现性）。"""
    secret = _read_env_secret()
    if not secret:
        pytest.skip("本地无 demo/.env，跳过 .env 加载断言")
    # 关键：子进程会继承父进程的 PYTEST_CURRENT_TEST 环境变量，而 auth.py 用该变量判断
    # 「是否在测试中」以跳过 load_dotenv；这里必须把它从子进程环境里删掉，否则 .env 不会被加载。
    clean_env = dict(os.environ)
    clean_env.pop("PYTEST_CURRENT_TEST", None)
    out = subprocess.check_output(
        [sys.executable, "-c", "import sys;sys.path.insert(0, r'%s');import auth;print(auth._SECRET.hex())" % str(_DEMO_DIR)],
        cwd=str(_DEMO_DIR),
        env=clean_env,
        text=True,
    )
    assert out.strip() == secret, "SEC-2 回归：auth 未在 import 期从 .env 读取 AUTH_SECRET"


def test_auth_secret_survives_reload(monkeypatch):
    """SEC-2（属性锁）：配置固定 AUTH_SECRET 后，reload auth 两次（模拟重启/多 worker）令牌仍可验证。

    锁住「令牌签名密钥在重启/多 worker 间一致」这一安全属性。"""
    monkeypatch.setenv("AUTH_SECRET", "sec2_fixed_secret_32b_length_fixed_val_xx")
    importlib.reload(auth_mod)
    tok = auth_mod.issue_token("demo")
    importlib.reload(auth_mod)  # 再次「重启」
    assert auth_mod.verify_token(tok) == "demo", "SEC-2 回归：配置 AUTH_SECRET 后令牌跨重启失效"


def test_client_ip_respects_cloudflare_proxy(monkeypatch):
    """SEC-3：可信代理（127.0.0.1）下采纳 CF-Connecting-IP；非可信代理忽略伪造转发头。"""

    class _Req:
        client = types.SimpleNamespace(host="127.0.0.1")
        headers = {"CF-Connecting-IP": "203.0.113.5"}

    # 场景1：配置了可信代理 → 还原真实访客 IP
    monkeypatch.setattr(main_mod, "_AUTH_TRUSTED_PROXIES", ["127.0.0.1"])
    assert main_mod.get_client_ip(_Req()) == "203.0.113.5", "SEC-3：应采纳 CF-Connecting-IP"

    # 场景2：未配置可信代理（默认）→ 忽略伪造转发头，使用直连 IP
    monkeypatch.setattr(main_mod, "_AUTH_TRUSTED_PROXIES", [])
    assert main_mod.get_client_ip(_Req()) == "127.0.0.1", "SEC-3：未信代理时应忽略伪造 CF-IP"


# ===================== SEC-8 / SEC-9 收口回归 =====================


def test_uploads_no_longer_public_mount():
    """SEC-8：公开静态 /uploads 挂载已移除，匿名直接访问上传目录应 404（绝不公开可读）。"""
    with TestClient(app) as c:
        r = c.get("/uploads/" + uuid.uuid4().hex + ".png")
        assert r.status_code == 404, "公开 /uploads 挂载应已移除"


def test_signed_upload_url_gate():
    """SEC-8：上传图须经签名 + 未过期短链访问；伪造签名 / 过期 / 篡改均 404（不泄露是否存在）。"""
    fname = f"sec8_{uuid.uuid4().hex[:8]}.png"
    fpath = pathlib.Path(UPLOAD_DIR) / fname
    fpath.write_bytes(_png())
    try:
        url = storage_mod.sign_upload_url(fname)
        with TestClient(app) as c:
            # 有效签名 URL → 200
            assert c.get(url).status_code == 200, "有效签名 URL 应可取回文件"
            # 解析出 f / e 用于构造恶意 URL
            q = parse_qs(urlparse(url).query)
            f, e = q["f"][0], q["e"][0]
            # 伪造签名 → 404
            assert c.get(f"/api/file/{'0' * 32}?f={quote(f)}&e={e}").status_code == 404
            # 过期时间戳 → 404
            assert c.get(f"/api/file/{'0' * 32}?f={quote(f)}&e={int(time.time()) - 10}").status_code == 404
    finally:
        # Windows 文件锁：刚写完/读完的文件瞬时 unlink 可能报 PermissionError，
        # 重试若干次忽略瞬时锁，避免测试偶发 flaky。
        for _ in range(5):
            try:
                fpath.unlink(missing_ok=True)
                break
            except OSError:
                time.sleep(0.05)


def test_csp_nonce_injected():
    """SEC-9：首页 CSP 含 per-request nonce，且内联 <script> 被注入相同 nonce（阻断未授权内联脚本执行）。"""
    import re

    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        csp = r.headers["Content-Security-Policy"]
        m = re.search(r"nonce-([A-Za-z0-9_-]+)", csp)
        assert m, "CSP 应含 nonce"
        nonce = m.group(1)
        assert f'<script nonce="{nonce}">' in r.text, "内联 <script> 应被注入相同 nonce"
        # script-src 不得再放行 'unsafe-inline'（XSS 主防线）
        assert "script-src 'self' 'nonce-" in csp


