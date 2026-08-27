"""ReturnGuard · 跨 worker 共享状态（SEC-12 收口）

问题：原限流计数 `_rate_window`、登录失败计数 `_login_fails`、登录封禁 `_login_lock_until`
均为进程内 dict。单 worker 演示态无碍；但多 worker / 多实例部署时，限流与封禁只在命中
同进程时生效（可被绕过），失去防护意义。

本模块把这些「需跨进程一致」的状态落地到独立 SQLite（rg_state.db），无需新增依赖；
同一主机的多 worker 实例共享同一文件即一致。多主机部署可后续将 STATE_DB_URL 指向
PostgreSQL/openGauss 或在此抽象上换 Redis 后端。
"""

from __future__ import annotations

import os
import time

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import sessionmaker

BASE = os.path.dirname(os.path.abspath(__file__))
_STATE_URL = os.environ.get("STATE_DB_URL") or ("sqlite:///" + os.path.join(BASE, "rg_state.db"))

# check_same_thread=False：uvicorn 默认线程池跑同步端点，多线程会并发访问该引擎
_engine = create_engine(_STATE_URL, connect_args={"check_same_thread": False})
try:
    with _engine.connect() as _c:
        _c.exec_driver_sql("PRAGMA busy_timeout=5000")  # 多 worker 并发写时自动退避，避免 SQLITE_BUSY
except Exception:  # pragma: no cover - 仅非 sqlite 后端可能无 PRAGMA
    pass

_meta = MetaData()
_t_rl = Table(
    "rate_limit",
    _meta,
    Column("key", String(128), primary_key=True),
    Column("cnt", Integer, default=0),
    Column("start", Float, default=0.0),
)
_t_lock = Table(
    "login_lock",
    _meta,
    Column("username", String(64), primary_key=True),
    Column("fails", Integer, default=0),
    Column("start", Float, default=0.0),  # 当前失败窗口起点（用于滑动窗口计数）
    Column("until", Float, default=0.0),  # 锁定解封时间戳（0 = 未锁定）
)
_meta.create_all(_engine)


def _migrate() -> None:
    """演进：存量 rg_state.db 补缺失列（与 db.py 同思路，避免 ALTER 不补列导致报错）。"""
    try:
        cols = {c["name"] for c in inspect(_engine).get_columns("login_lock")}
        with _engine.begin() as conn:
            if "start" not in cols:
                conn.execute(text("ALTER TABLE login_lock ADD COLUMN start FLOAT NOT NULL DEFAULT 0.0"))
    except Exception:  # pragma: no cover - 表不存在等
        pass


_migrate()


def rate_check(key: str, limit: int, window: int = 60) -> bool:
    """按 key 的固定窗口限流（默认 60s）。返回 True=放行。

    窗口过期（now - start >= window）即重置计数，避免计数无限累积。"""
    now = time.time()
    with _engine.begin() as conn:
        row = conn.execute(_t_rl.select().where(_t_rl.c.key == key)).first()
        if row is None or now - row.start >= window:
            if row is None:
                conn.execute(_t_rl.insert().values(key=key, cnt=1, start=now))
            else:
                conn.execute(_t_rl.update().where(_t_rl.c.key == key).values(cnt=1, start=now))
            return True
        if row.cnt >= limit:
            return False
        conn.execute(_t_rl.update().where(_t_rl.c.key == key).values(cnt=row.cnt + 1))
        return True


def login_lock_register(username: str, max_fails: int, lock_sec: int) -> bool:
    """记录一次登录失败；返回当前是否已进入封禁（until > now）。

    滑动窗口：同一窗口（now - start < lock_sec）内失败次数累加；达 max_fails 即锁定 lock_sec 秒。
    锁定期间（until > now）维持锁定；窗口过期后从头计数。"""
    now = time.time()
    with _engine.begin() as conn:
        row = conn.execute(_t_lock.select().where(_t_lock.c.username == username)).first()
        if row and row.until > now:
            return True  # 锁定期内，维持锁定
        if row and row.start and now - row.start < lock_sec:
            fails = row.fails + 1
            start = row.start
        else:
            fails = 1
            start = now
        until = now + lock_sec if fails >= max_fails else 0.0
        if row is None:
            conn.execute(
                _t_lock.insert().values(username=username, fails=fails, start=start, until=until)
            )
        else:
            conn.execute(
                _t_lock.update()
                .where(_t_lock.c.username == username)
                .values(fails=fails, start=start, until=until)
            )
        return until > now


def login_locked(username: str) -> bool:
    with _engine.connect() as conn:
        row = conn.execute(_t_lock.select().where(_t_lock.c.username == username)).first()
    return bool(row and row.until > time.time())


def login_clear(username: str) -> None:
    with _engine.begin() as conn:
        conn.execute(_t_lock.delete().where(_t_lock.c.username == username))


def reset_state() -> None:
    """清空共享状态（测试隔离用）。"""
    with _engine.begin() as conn:
        conn.execute(_t_rl.delete())
        conn.execute(_t_lock.delete())
