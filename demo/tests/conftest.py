"""共享测试夹具。

【关键】本文件顶部会在**导入任何项目模块之前**把三个数据库重定向到临时目录。
db.py / auth.py / shared_state.py 都在模块顶层读取连接串并缓存引擎，因此环境变量
必须在 import 之前设好，否则测试会直接读写真实业务库——实测曾把演示库从 1206 条
污染到 1214 条，并在 demo/ 下生成 users.db、rg_state.db-wal 等残留。
"""

import os
import shutil
import tempfile
from pathlib import Path

# ---- 必须在 import 项目模块之前完成的环境重定向 ----
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix="rg_test_"))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB_DIR / 'cases_demo.db'}")
os.environ.setdefault("REAL_DATABASE_URL", f"sqlite:///{_TMP_DB_DIR / 'cases_real.db'}")
os.environ.setdefault("AUTH_DATABASE_URL", f"sqlite:///{_TMP_DB_DIR / 'users.db'}")
os.environ.setdefault("STATE_DB_URL", f"sqlite:///{_TMP_DB_DIR / 'rg_state.db'}")
# 注册默认已关闭（secure-by-default，见 main.py）。测试要覆盖注册链路，故在此开启；
# 「未开启时应拒绝」由 test_security.py 里的用例专门验证。
os.environ.setdefault("REGISTRATION_ENABLED", "true")

import pytest  # noqa: E402
import shared_state  # noqa: E402  SEC-12：限流/封禁落库，需每测试隔离
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _tmp_db_dir():
    """会话结束时回收临时数据库目录，保证工作区零残留。"""
    yield _TMP_DB_DIR
    shutil.rmtree(_TMP_DB_DIR, ignore_errors=True)


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
