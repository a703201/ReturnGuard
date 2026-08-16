"""pytest 会话级配置：把 DATABASE_URL 指向临时 SQLite，避免污染开发库 cases.db。

必须在导入 main/db 之前设置环境变量（db.py 在 import 期读取 DATABASE_URL），
因此放在 conftest 顶层（conftest 先于测试模块被导入）。
"""

import os
import sys
import tempfile

import pytest

# 把 demo/ 加入模块搜索路径，使测试可 import 同目录的 main / pipeline / db
_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
