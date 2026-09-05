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
    event,
    inspect,
    text,
)
from sqlalchemy.pool import NullPool

# openGauss 复用 db.py 的方言版本探测补丁：openGauss 的 `version()` 字符串非标准，
# 不经补丁时 SQLAlchemy 会在引擎初始化期抛 AssertionError（见 db._patch_opengauss_dialect）。
# 此处仅在指向 PostgreSQL/openGauss 时挂接，SQLite 不受影响。db.py 不反向依赖本模块，无循环导入。
from db import _patch_opengauss_dialect  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
_STATE_URL = os.environ.get("STATE_DB_URL") or ("sqlite:///" + os.path.join(BASE, "rg_state.db"))

# check_same_thread=False：uvicorn 默认线程池跑同步端点，多线程会并发访问该引擎。
# NullPool：状态库全是单行 upsert，连接创建开销可忽略；关键收益是连接用完即关，SQLite
# 在最后一个连接关闭时自动 checkpoint，杜绝 WAL 无限膨胀（实测曾达主库 200 倍）。
# 注意：check_same_thread 是 SQLite 专属选项，PostgreSQL/openGauss 不支持，须按 URL 区分
# （P1-C 起 STATE_DB_URL 可指向 openGauss，避免多 worker 各自持本地 SQLite 不一致）。
_connect_args = {"check_same_thread": False} if _STATE_URL.startswith("sqlite") else {}
# 指向 openGauss/PostgreSQL 时先挂接方言补丁，否则 create_engine 初始化即抛版本探测 AssertionError。
if not _STATE_URL.startswith("sqlite"):
    _patch_opengauss_dialect(_STATE_URL)
_engine = create_engine(
    _STATE_URL,
    connect_args=_connect_args,
    poolclass=NullPool,
)

# PRAGMA 必须挂在 connect 事件上：此前只对「建池时的那一条连接」执行过，池内后续新建的
# 连接完全不生效，并发写时仍会撞 SQLITE_BUSY。
if _STATE_URL.startswith("sqlite"):

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=5000")  # 并发写时自动退避
        cur.execute("PRAGMA journal_mode=WAL")  # 降低读写互斥
        cur.close()


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
                conn.execute(
                    text("ALTER TABLE login_lock ADD COLUMN start FLOAT NOT NULL DEFAULT 0.0")
                )
    except Exception:  # pragma: no cover - 表不存在等
        pass


_migrate()


def rate_check(key: str, limit: int, window: int = 60) -> bool:
    """按 key 的固定窗口限流（默认 60s）。返回 True=放行。

    窗口过期（now - start >= window）即重置计数，避免计数无限累积。
    使用原子 UPSERT 规避并发读-改-写导致的主键冲突（IntegrityError → 500）。"""
    now = time.time()
    with _engine.begin() as conn:
        # 原子 upsert：过期则重置为 1，否则自增 1（单语句，事务内持写锁，并发安全）
        conn.execute(
            text(
                "INSERT INTO rate_limit(key,cnt,start) VALUES(:k,1,:now) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  cnt = CASE WHEN :now - rate_limit.start >= :window THEN 1 "
                "            ELSE rate_limit.cnt + 1 END, "
                "  start = CASE WHEN :now - rate_limit.start >= :window THEN :now "
                "            ELSE rate_limit.start END"
            ),
            {"k": key, "now": now, "window": window},
        )
        row = conn.execute(_t_rl.select().where(_t_rl.c.key == key)).first()
        if row.cnt > limit:
            # 超限：撤销本次自增，保持计数原值（避免透支，并发下仍准确）
            conn.execute(_t_rl.update().where(_t_rl.c.key == key).values(cnt=row.cnt - 1))
            return False
        return True


def login_lock_register(username: str, max_fails: int, lock_sec: int) -> bool:
    """记录一次登录失败；返回当前是否已进入封禁（until > now）。

    滑动窗口：同一窗口（now - start < lock_sec）内失败次数累加；达 max_fails 即锁定 lock_sec 秒。
    锁定期间（until > now）维持锁定；窗口过期后从头计数。
    使用原子 UPSERT 规避并发读-改-写主键冲突。"""
    now = time.time()
    with _engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO login_lock(username,fails,start,until) VALUES(:u,1,:now,0) "
                "ON CONFLICT(username) DO UPDATE SET "
                "  fails = CASE WHEN login_lock.until > :now THEN login_lock.fails "
                "            WHEN :now - login_lock.start < :lock THEN login_lock.fails + 1 "
                "            ELSE 1 END, "
                "  start = CASE WHEN login_lock.until > :now THEN login_lock.start "
                "            WHEN :now - login_lock.start < :lock THEN login_lock.start "
                "            ELSE :now END, "
                "  until = CASE WHEN login_lock.until > :now THEN login_lock.until "
                "            WHEN login_lock.fails + 1 >= :mf THEN :now + :lock "
                "            ELSE 0.0 END"
            ),
            {"u": username, "now": now, "lock": lock_sec, "mf": max_fails},
        )
        row = conn.execute(_t_lock.select().where(_t_lock.c.username == username)).first()
        return bool(row and row.until > now)


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
