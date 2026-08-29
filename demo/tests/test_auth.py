"""账户体系 + 多租户隔离测试（C组）。

运行需隔离数据库（与现有测试同约定）：
  DATABASE_URL=sqlite:///./_ci_cases.db REAL_DATABASE_URL=sqlite:///./_ci_cases_real.db AUTH_DATABASE_URL=sqlite:///./_ci_users.db python -m pytest tests/test_auth.py -q
"""

import uuid

import auth  # 用于重置懒引擎，确保用户库隔离
import main  # 用于 monkeypatch 限流/封禁/注册开关等模块级状态
import pytest
import shared_state  # SEC-12：共享状态（限流/封禁）落库，测试需 reset
from db import save_case  # 构造 public 基准数据（API 写入一律归属当前租户）
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
    """多租户：私有数据严格隔离，public 基准对登录用户可见，匿名访问 real 源一律 401。"""
    ua, ta = _reg(client, prefix="acme")
    ub, tb = _reg(client, prefix="beta")
    # public 基准数据来自系统导入路径（启动期 RG_AUTO_IMPORT_CSV / 数据层直写），
    # API 写入一律归属当前租户，故此处在数据层构造，模拟系统导入的公共基准。
    save_case(
        "real",
        {
            "case_id": "RG-PUB-" + uuid.uuid4().hex[:6].upper(),
            "sku": "SKU-PUB",
            "category": "饰品配件",
        },
        tenant_id="public",
    )
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
            x["sku"]
            for x in client.get("/api/cases?source=real&slim=1", headers=hdrs).json()["items"]
        )

    a, b = skus(ta), skus(tb)
    # 各自能看到自己的私有数据
    assert "SKU-" + ua in a
    assert "SKU-" + ub in b
    # 私有数据不跨租户泄露
    assert "SKU-" + ub not in a
    assert "SKU-" + ua not in b
    # public 基准对登录用户可见
    assert "SKU-PUB" in a and "SKU-PUB" in b
    # SEC-P0：匿名访问 real 源（真实退货数据）被拒，不再返回数据
    anon = client.get("/api/cases?source=real&slim=1")
    assert anon.status_code == 401


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
        ).json()["items"]
        if x["sku"] == "SKU-DEL-" + ub
    ][0]
    r = client.delete(
        "/api/cases/" + bid + "?source=real", headers={"Authorization": "Bearer " + ta}
    )
    # REST 语义：跨租户不可见 → 视为不存在，返回 404。
    # 原先返回 200 + deleted=0，前端无法区分"删成功"与"压根没这条"。
    assert r.status_code == 404
    # 关键不变量：B 的数据依然健在
    assert "SKU-DEL-" + ub in [
        x["sku"]
        for x in client.get(
            "/api/cases?source=real&slim=1", headers={"Authorization": "Bearer " + tb}
        ).json()["items"]
    ]


def test_demo_source_delete_blocked(client, monkeypatch):
    """SEC-P0：demo 共享演示库禁止删除（公开测试账号不可删光 1206 条种子）。"""
    _reset_auth_state(monkeypatch)
    r = client.delete(
        "/api/cases/RG-ANY?source=demo", headers={"Authorization": "Bearer " + _reg(client)[1]}
    )
    assert r.status_code == 403


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
    """单用户名连续密码错误达上限后被临时锁定，锁定期内正确密码亦被拒。

    SEC: 锁定态与「凭证错误」对外必须完全一致（401 + 同文案）。原先锁定返回 429，
    攻击者可用「429 已锁定」vs「401 不存在」的差异枚举出真实用户名。
    """
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_LOGIN_MAX_FAILS", 3)
    monkeypatch.setattr(main, "_LOGIN_LOCK_SEC", 900)
    u = "lock_" + uuid.uuid4().hex[:6]
    client.post("/api/auth/register", json={"username": u, "password": "secret123"})
    for _ in range(3):  # 连续 3 次错密码
        assert (
            client.post("/api/auth/login", json={"username": u, "password": "wrong"}).status_code
            == 401
        )
    # 锁定生效：仍为 401（不再用 429 暴露"该账户存在"）
    locked = client.post("/api/auth/login", json={"username": u, "password": "wrong"})
    assert locked.status_code == 401
    # 锁定期内即便密码正确也拒（需等待解锁或走找回流程）
    assert (
        client.post("/api/auth/login", json={"username": u, "password": "secret123"}).status_code
        == 401
    )
    # 防护不变量：锁定账户 与 不存在的账户，响应码与文案必须完全一致 —— 否则仍可枚举
    ghost = "ghost_" + uuid.uuid4().hex[:6]
    missing = client.post("/api/auth/login", json={"username": ghost, "password": "wrong"})
    assert missing.status_code == locked.status_code
    assert missing.json()["detail"] == locked.json()["detail"]


def test_logout_invalidates_token(client, monkeypatch):
    """登出后旧令牌立即失效（token_version 自增），/me 返回 401。"""
    _reset_auth_state(monkeypatch)
    u = "out_" + uuid.uuid4().hex[:6]
    r = client.post("/api/auth/register", json={"username": u, "password": "secret123"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert (
        client.post("/api/auth/logout", headers={"Authorization": "Bearer " + tok}).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).status_code == 401


def test_invite_code_required_when_set(client, monkeypatch):
    """设置邀请码后，无/错邀请码注册被拒，匹配则通过。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_REGISTRATION_INVITE_CODE", "letmein")
    no_code = client.post(
        "/api/auth/register",
        json={"username": "inv1_" + uuid.uuid4().hex[:4], "password": "secret123"},
    )
    assert no_code.status_code == 400
    bad = client.post(
        "/api/auth/register",
        json={
            "username": "inv2_" + uuid.uuid4().hex[:4],
            "password": "secret123",
            "invite_code": "nope",
        },
    )
    assert bad.status_code == 400
    good = client.post(
        "/api/auth/register",
        json={
            "username": "inv3_" + uuid.uuid4().hex[:4],
            "password": "secret123",
            "invite_code": "letmein",
        },
    )
    assert good.status_code == 200


def test_registration_disabled(client, monkeypatch):
    """REGISTRATION_ENABLED=false 时注册返回 403。"""
    _reset_auth_state(monkeypatch)
    monkeypatch.setattr(main, "_REGISTRATION_ENABLED", False)
    r = client.post(
        "/api/auth/register",
        json={"username": "off_" + uuid.uuid4().hex[:4], "password": "secret123"},
    )
    assert r.status_code == 403
