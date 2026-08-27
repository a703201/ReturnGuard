"""共享测试夹具：安全复审后，写接口要求登录会话，提供 demo/demo123 的令牌夹具。"""

import pytest
from fastapi.testclient import TestClient

import shared_state  # SEC-12：限流/封禁落库，需每测试隔离
from main import app


@pytest.fixture(autouse=True)
def _isolate_shared_state():
    """每个测试前清空共享状态（rg_state.db 的限流/封禁计数），避免跨测试累积导致误 429。

    原进程内 dict 虽也跨测试共享，但秒级窗口内几乎不超限；落库后跨测试/跨运行持久化，
    必须显式重置以保证用例独立。"""
    shared_state.reset_state()
    yield


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
