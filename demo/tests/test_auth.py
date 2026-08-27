"""账户体系 + 多租户隔离测试（C组）。

运行需隔离数据库（与现有测试同约定）：
  DATABASE_URL=sqlite:///./_ci_cases.db REAL_DATABASE_URL=sqlite:///./_ci_cases_real.db AUTH_DATABASE_URL=sqlite:///./_ci_users.db python -m pytest tests/test_auth.py -q
"""

import uuid

import auth  # 用于重置懒引擎，确保用户库隔离
import main  # 用于 monkeypatch 限流/封禁/注册开关等模块级状态
import shared_state  # SEC-12：共享状态（限流/封禁）落库，测试需 reset
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture()
def client(monkeypatch):
    """让 auth 引擎使用本次运行隔离的用户库（懒创建 + 每次重置为 None）。"""
    monkeypatch.setattr(auth, "_auth_engine", None)
    with TestClient(app) as c:
        yield c


def _reg(c, prefix="t_") -> tuple[str, str]:
    u = prefix + uuid.uuid4().hex[:6]
    r = c.post(
        "/api/auth/register", json={"username": u, "password": "secret123", "tenant_name": u}
    )
    assert r.status_code == 200
    return u, r.json()["token"]


def test_register_login_me(client):
    u, tok = _reg(client)
    # 登录成功
    r = client.post("/api/auth/login", json={"username": u, "password": "secret123"})
    assert r.status_code == 200 and r.json()["token"]
    # 密码错误 → 401
    assert (
        client.post("/api/auth/login", json={"username": u, "password": "wrong"}).status_code == 401
    )
    # /me：携带令牌返回租户；匿名 401
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok})
    assert me.status_code == 200 and me.json()["tenant"] == u
    assert client.get("/api/auth/me").status_code == 401


def test_duplicate_register_rejected(client):
    u, _ = _reg(client)
    r = client.post("/api/auth/register", json={"username": u, "password": "secret123"})
    assert r.status_code == 400


def test_weak_password_rejected(client):
    r = client.post(
        "/api/auth/register", json={"username": "u_" + uuid.uuid4().hex[:6], "password": "123"}
    )
    assert r.status_code == 400


def test_tenant_isolation(client):
    """多租户：私有数据严格隔离，public 基准对所有人可见（含匿名）。"""
    ua, ta = _reg(client, prefix="acme")
    ub, tb = _reg(client, prefix="beta")
    # 匿名 → public 基准
    client.post("/api/cases?source=real", json={"sku": "SKU-PUB", "category": "饰品配件"})
    client.post(
        "/api/cases?source=real",
        json={"sku": "SKU-" + ua, "category": "3C数码"},
        headers={"Authorization": "Bearer " + ta},
    )
    client.post(
        "/api/cases?source=real",
        json={"sku": "SKU-" + ub, "category": "小家电"},
        headers={"Authorization": "Bearer " + tb},
    )

    def skus(h=None):
        hdrs = {"Authorization": "Bearer " + h} if h else {}
        return sorted(
            x["sku"] for x in client.get("/api/cases?source=real&slim=1", headers=hdrs).json()
        )

    a, b, anon = skus(ta), skus(tb), skus()
    # 各自能看到自己的私有数据
    assert "SKU-" + ua in a
    assert "SKU-" + ub in b
    # 私有数据不跨租户泄露
    assert "SKU-" + ub not in a
    assert "SKU-" + ua not in b
    # public 基准对所有人可见（含匿名），私有数据对匿名不可见
    assert "SKU-PUB" in a and "SKU-PUB" in b and "SKU-PUB" in anon
    assert "SKU-" + ua not in anon


def test_cross_tenant_delete_blocked(client):
    """跨租户删除被隔离：A 删不掉 B 的案件。"""
    ua, ta = _reg(client, prefix="delA")
    ub, tb = _reg(client, prefix="delB")
    client.post(
        "/api/cases?source=real",
        json={"sku": "SKU-DEL-" + ub, "category": "小家电"},
        headers={"Authorization": "Bearer " + tb},
    )
    bid = [
        x["case_id"]
        for x in client.get(
            "/api/cases?source=real&slim=1", headers={"Authorization": "Bearer " + tb}
        ).json()
        if x["sku"] == "SKU-DEL-" + ub
    ][0]
    r = client.delete(
        "/api/cases/" + bid + "?source=real", headers={"Authorization": "Bearer " + ta}
    )
    assert r.status_code == 200 and r.json()["deleted"] == 0


# ---------------- 防 spam / 防攻击：限流、封禁、登出吊销、邀请码、注册开关 ----------------


def _reset_auth_state(monkeypatch):
    """清空共享状态（限流/封禁落库，SEC-12），并隔离用户库，保证测试互不干扰。"""
    shared_state.reset_state()
    monkeypatch.setattr(auth, "_auth_engine", None)
    monkeypatch.setattr(auth, "_version_cache", {})


def test_register_rate_limited(client, monkeypatch):
    """同 IP 注册超过上限即被 429 拦截（防批量建租户 spam）。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_AUTH_REGISTER_LIMIT", 2)
    ok = 0
    for i in range(4):
        r = client.post(
            "/api/auth/register",
            json={"username": f"rl_{i}_{uuid.uuid4().hex[:4]}", "password": "secret123"},
        )
        if r.status_code == 200:
            ok += 1
        else:
            assert r.status_code == 429
    assert ok == 2  # 仅前 2 次成功，其余被限流


def test_login_lockout_after_fails(client, monkeypatch):
    """单用户名连续密码错误达上限后被临时锁定（429），锁定期内正确密码亦被拒。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_LOGIN_MAX_FAILS", 3)
    monkeypatch.setattr(main, "_LOGIN_LOCK_SEC", 900)
    u = "lock_" + uuid.uuid4().hex[:6]
    client.post("/api/auth/register", json={"username": u, "password": "secret123"})
    for _ in range(3):  # 连续 3 次错密码
        assert client.post("/api/auth/login", json={"username": u, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": u, "password": "wrong"}).status_code == 429
    # 锁定期内即便密码正确也拒（需等待解锁或走找回流程）
    assert client.post("/api/auth/login", json={"username": u, "password": "secret123"}).status_code == 429


def test_logout_invalidates_token(client, monkeypatch):
    """登出后旧令牌立即失效（token_version 自增），/me 返回 401。"""
    _reset_auth_state(monkeypatch)
    u = "out_" + uuid.uuid4().hex[:6]
    r = client.post("/api/auth/register", json={"username": u, "password": "secret123"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert client.post("/api/auth/logout", headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).status_code == 401


def test_invite_code_required_when_set(client, monkeypatch):
    """设置邀请码后，无/错邀请码注册被拒，匹配则通过。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_REGISTRATION_INVITE_CODE", "letmein")
    no_code = client.post(
        "/api/auth/register", json={"username": "inv1_" + uuid.uuid4().hex[:4], "password": "secret123"}
    )
    assert no_code.status_code == 400
    bad = client.post(
        "/api/auth/register",
        json={"username": "inv2_" + uuid.uuid4().hex[:4], "password": "secret123", "invite_code": "nope"},
    )
    assert bad.status_code == 400
    good = client.post(
        "/api/auth/register",
        json={"username": "inv3_" + uuid.uuid4().hex[:4], "password": "secret123", "invite_code": "letmein"},
    )
    assert good.status_code == 200


def test_registration_disabled(client, monkeypatch):
    """REGISTRATION_ENABLED=false 时注册返回 403。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_REGISTRATION_ENABLED", False)
    r = client.post(
        "/api/auth/register", json={"username": "off_" + uuid.uuid4().hex[:4], "password": "secret123"}
    )
    assert r.status_code == 403
