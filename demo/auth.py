"""ReturnGuard · 账户体系 + 多租户隔离（C组：多租户 + 账户体系）

设计原则（零新依赖，stdlib 实现，开发/部署同构）：
- 密码：pbkdf2_hmac 加盐哈希（SHA-256，10 万轮），不存明文。
- 令牌：HMAC-SHA256 签名的无状态令牌 `b64(username)|exp|sig`，后端可校验、免存储。
- 租户：用户名即租户标识（tenant_id）。real 源案件按 tenant_id 隔离；demo 源为共享演示库，
  不参与租户隔离（保持复赛演示零改造）。
- 用户库：独立引擎（AUTH_DATABASE_URL，默认 sqlite users.db；可指向 openGauss 与生产案件同库）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import threading
import time
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = __import__("logging").getLogger("returnguard.auth")

# ---- 令牌签名密钥：生产必须设 AUTH_SECRET；未设则用进程内随机值（演示态，重启即失效）----
_SECRET = os.environ.get("AUTH_SECRET", os.urandom(32))
_TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", str(3600 * 24 * 7)))  # 默认 7 天

# ---- 用户库引擎（与案件库解耦，可独立指向 openGauss）----
# 懒初始化：首用创建，便于测试用 AUTH_DATABASE_URL 注入独立内存/临时库（与 db.get_engine 同思路）
BASE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_AUTH_URL = "sqlite:///" + os.path.join(BASE, "users.db")
_auth_engine = None
AuthBase = declarative_base()
_auth_lock = threading.Lock()

_USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

# 令牌版本缓存：降低每次鉴权的 DB 查询；登出时清缓存
_version_cache: dict[str, tuple[int, float]] = {}
_VERSION_TTL = 60.0


class User(AuthBase):
    """账户表：一个用户即一个租户（tenant_id = username）。"""

    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    pw_hash = Column(String(128), nullable=False)
    pw_salt = Column(String(64), nullable=False)
    tenant_name = Column(String(128), default="")  # 展示用企业/店铺名
    created_at = Column(DateTime, default=datetime.utcnow)
    token_version = Column(Integer, default=0, nullable=False)  # 令牌吊销/登出：自增即令旧 token 失效


def get_auth_engine():
    """返回（必要时创建）用户库引擎；测试可用 AUTH_DATABASE_URL 注入独立库。"""
    global _auth_engine
    with _auth_lock:
        if _auth_engine is None:
            _auth_engine = create_engine(
                os.environ.get("AUTH_DATABASE_URL", _DEFAULT_AUTH_URL),
                future=True,
                pool_pre_ping=True,
            )
        return _auth_engine


def init_auth_db() -> None:
    AuthBase.metadata.create_all(get_auth_engine())
    # 非破坏迁移：旧库缺 token_version 列时补列（保留现有账号，含演示账号）
    try:
        with _auth_engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
            )
    except Exception:  # noqa: BLE001
        pass  # 列已存在 / 方言不支持（如某些 openGauss 变体），忽略


def _auth_session():
    # get_auth_engine 内部已加锁；此处不可再嵌套加锁（threading.Lock 非重入，会死锁）
    return sessionmaker(bind=get_auth_engine(), expire_on_commit=False)()


def _hash_password(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 100_000).hex()


def register(username: str, password: str, tenant_name: str = "") -> tuple[bool, str]:
    """注册账户（同时即创建一个租户）。返回 (ok, reason)。"""
    if not _USER_RE.match(username or ""):
        return False, "用户名需为 3-32 位字母/数字/._-"
    if not password or len(password) < 6:
        return False, "密码至少 6 位"
    with _auth_session() as s:
        if s.query(User).filter_by(username=username).first():
            return False, "注册失败，请稍后重试"
        salt = os.urandom(16)
        u = User(
            username=username,
            pw_salt=salt.hex(),
            pw_hash=_hash_password(password, salt),
            tenant_name=tenant_name or username,
        )
        s.add(u)
        s.commit()
    logger.info("新账户注册：%s", username)
    return True, "ok"


def authenticate(username: str, password: str) -> str | None:
    """校验凭证，成功返回令牌，失败返回 None。"""
    with _auth_session() as s:
        u = s.query(User).filter_by(username=username).first()
        if not u:
            return None
        salt = bytes.fromhex(u.pw_salt)
        if not hmac.compare_digest(u.pw_hash, _hash_password(password, salt)):
            return None
    return issue_token(username)


def get_user(username: str) -> dict | None:
    with _auth_session() as s:
        u = s.query(User).filter_by(username=username).first()
        if not u:
            return None
        return {
            "username": u.username,
            "tenant_name": u.tenant_name,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }


def _current_version(username: str) -> int | None:
    """读取用户当前 token_version（带短 TTL 缓存）；用户不存在返回 None。"""
    now = time.time()
    cached = _version_cache.get(username)
    if cached and now - cached[1] < _VERSION_TTL:
        return cached[0]
    with _auth_session() as s:
        u = s.query(User).filter_by(username=username).first()
        if not u:
            return None
        v = getattr(u, "token_version", 0) or 0
    _version_cache[username] = (v, now)
    return v


def logout(username: str) -> None:
    """自增 token_version，使该用户所有已签发令牌立即失效（等价服务端登出/踢人）。"""
    with _auth_session() as s:
        u = s.query(User).filter_by(username=username).first()
        if not u:
            return
        u.token_version = (getattr(u, "token_version", 0) or 0) + 1
        s.commit()
    _version_cache.pop(username, None)


def issue_token(username: str, ttl: int = _TOKEN_TTL) -> str:
    # 取当前 token_version，编入令牌；登出/吊销后版本变化，旧令牌即失效
    ver = _current_version(username) or 0
    payload = (
        base64.urlsafe_b64encode(username.encode("utf-8")).decode("ascii")
        + "|"
        + str(ver)
        + "|"
        + str(int(time.time()) + ttl)
    )
    sig = hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return payload + "." + sig


def verify_token(token: str | None) -> str | None:
    """校验令牌，返回用户名（即 tenant_id），过期/篡改/已吊销返回 None。

    令牌格式：b64(username)|token_version|exp；旧格式（无版本段）仍兼容解析。"""
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        parts = payload.split("|")
        if len(parts) == 2:
            b64u, exp = parts
            ver = None
        elif len(parts) == 3:
            b64u, ver, exp = parts
        else:
            return None
        if int(exp) < time.time():
            return None
        expect = hmac.new(_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        username = base64.urlsafe_b64decode(b64u).decode("utf-8")
        # 版本校验（仅新格式令牌）：与当前版本不一致 → 已登出/吊销
        if ver is not None:
            cur = _current_version(username)
            if cur is None or int(ver) != cur:
                return None
        return username
    except Exception:  # noqa: BLE001
        return None
