"""账户体系 + 多租户隔离测试（C组）。

运行需隔离数据库（与现有测试同约定）：
  DATABASE_URL=sqlite:///./_ci_cases.db REAL_DATABASE_URL=sqlite:///./_ci_cases_real.db AUTH_DATABASE_URL=sqlite:///./_ci_users.db python -m pytest tests/test_auth.py -q
"""

import uuid

import auth  # 用于重置懒引擎，确保用户库隔离
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
