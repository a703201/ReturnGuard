"""共享测试夹具：安全复审后，写接口要求登录会话，提供 demo/demo123 的令牌夹具。"""

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def demo_token() -> str:
    """登录内置 demo/demo123，返回有效 Bearer 令牌（写接口鉴权用）。"""
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
        assert r.status_code == 200, "demo 测试账号登录失败"
        return r.json()["token"]


@pytest.fixture
def auth_headers(demo_token: str) -> dict:
    """已登录 demo 账户的请求头（Authorization: Bearer）。"""
    return {"Authorization": f"Bearer {demo_token}"}
