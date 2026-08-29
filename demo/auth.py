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
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# 必须在读取 AUTH_SECRET 等环境变量之前加载 demo/.env：本模块被 main.py 最早 import，
# 早于 models_router / storage 内的 load_dotenv；若不在此显式加载，.env 配置的 AUTH_SECRET
# 会被静默忽略、回退成每进程随机密钥（SEC-2：重启令牌全失效、多 worker 登录直接坏）。
# 测试环境跳过：pytest 在启动期注入 sys.modules，用 PYTEST_CURRENT_TEST 判断不可靠
# （收集期尚未写入），故同时用 sys.modules.get("pytest") 守卫，避免真实密钥泄漏进用例。
if sys.modules.get("pytest") is None and "PYTEST_CURRENT_TEST" not in os.environ:
    load_dotenv()

logger = __import__("logging").getLogger("returnguard.auth")


# ---- 令牌签名密钥：生产必须设 AUTH_SECRET；未设则用进程内随机值（演示态，重启即失效）----
# 注意：load_dotenv() 已在本文件顶部执行，故 .env 中的 AUTH_SECRET 现在可被正确读取。
def _resolve_secret(raw: str) -> bytes:
    """把 AUTH_SECRET 环境值解析为 hmac 所需的 bytes 密钥。

    - 推荐写法：``python -c "import secrets;print(secrets.token_hex(32))"`` 产生的 64 位
      十六进制串，按字节解码回 32 字节高熵密钥（与文档示例一致）。
    - 兼容任意高熵字符串：非法十六进制时按 UTF-8 编码。
    - 空值：回退进程内随机字节（仅演示态，重启令牌即失效）。
    hmac.new 要求 bytes 密钥，直接传 str 在 Python 3.13+ 会抛 TypeError（此前潜在生产缺陷）。"""
    raw = (raw or "").strip()
    if not raw:
        logger.warning(
            "AUTH_SECRET 未设置：回退进程内随机密钥。该密钥仅当前进程有效，"
            "重启/多 worker 部署下已签发令牌将全部失效（登录后被随机踢回 401）。"
            "生产/多 worker 部署务必设置高熵 AUTH_SECRET。"
        )
        return os.urandom(32)
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


_SECRET = _resolve_secret(os.environ.get("AUTH_SECRET", ""))
_TOKEN_TTL = int(os.environ.get("AUTH_TOKEN_TTL", str(3600 * 24 * 7)))  # 默认 7 天

# ---- 口令 KDF 强度（P3）：OWASP 建议 pbkdf2 约 60 万轮；旧默认 10 万轮偏低，已提至 60 万。
# 历史账户（迁移前）沿用其落库时的轮数校验，登录成功时就地升级到当前轮数（rehash-on-login），
# 因此对存量库无破坏、且自动渐进加固。_LEGACY_PBKDF2_ITERS 仅用于 ALTER 补列默认值与回退。
CURRENT_PBKDF2_ITERS = 600_000
_LEGACY_PBKDF2_ITERS = 100_000

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
    pw_iters = Column(
        Integer, default=CURRENT_PBKDF2_ITERS, nullable=False
    )  # 落库时的 KDF 轮数（rehash-on-login 渐进升级）
    tenant_name = Column(String(128), default="")  # 展示用企业/店铺名
    created_at = Column(DateTime, default=datetime.utcnow)
    token_version = Column(
        Integer, default=0, nullable=False
    )  # 令牌吊销/登出：自增即令旧 token 失效


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
    # 非破坏迁移：旧库缺列时补列（保留现有账号，含演示账号）。
    # token_version 默认 0；pw_iters 默认沿用旧轮数 _LEGACY_PBKDF2_ITERS（注意：不可写成
    # CURRENT_PBKDF2_ITERS，否则存量账号会用「新轮数 + 旧哈希」校验失败、登录直接坏）。
    for col, ddl in (
        ("token_version", "INTEGER NOT NULL DEFAULT 0"),
        ("pw_iters", f"INTEGER NOT NULL DEFAULT {_LEGACY_PBKDF2_ITERS}"),
    ):
        try:
            with _auth_engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
        except Exception:  # noqa: BLE001
            pass  # 列已存在 / 方言不支持（如某些 openGauss 变体），忽略


def _auth_session():
    # get_auth_engine 内部已加锁；此处不可再嵌套加锁（threading.Lock 非重入，会死锁）
    return sessionmaker(bind=get_auth_engine(), expire_on_commit=False)()


def _hash_password(pw: str, salt: bytes, iters: int = CURRENT_PBKDF2_ITERS) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters).hex()


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
            pw_iters=CURRENT_PBKDF2_ITERS,
            tenant_name=tenant_name or username,
        )
        s.add(u)
        s.commit()
    logger.info("新账户注册：%s", username)
    return True, "ok"


def authenticate(username: str, password: str) -> str | None:
    """校验凭证，成功返回令牌，失败返回 None。

    安全加固（P3）：
    - 时序侧信道消除：用户名不存在时也执行一次等代价 pbkdf2，避免「用户枚举」时序差异。
    - 轮数兼容：用该账户落库时的 pw_iters 校验（存量账户可能低于当前值）。
    - rehash-on-login：校验通过但轮数低于当前值时，成功登录后就地升级到 CURRENT_PBKDF2_ITERS，
      渐进加固所有存量账户，无需一次性迁移。
    """
    with _auth_session() as s:
        u = s.query(User).filter_by(username=username).first()
    if u is None:
        # 时序均衡：不存在的用户也跑一次满代价哈希，使「用户不存在」与「密码错」耗时不可区分
        _hash_password(password or "x", os.urandom(16))
        return None
    iters = getattr(u, "pw_iters", None) or _LEGACY_PBKDF2_ITERS
    salt = bytes.fromhex(u.pw_salt)
    if not hmac.compare_digest(u.pw_hash, _hash_password(password, salt, iters)):
        return None
    # 登录成功：若历史轮数偏低，就地升级哈希到当前强度（不影响本次登录）
    if iters < CURRENT_PBKDF2_ITERS:
        try:
            ns = os.urandom(16)
            new_hash = _hash_password(password, ns)
            with _auth_session() as s:
                row = s.query(User).filter_by(username=username).first()
                if row is not None:
                    row.pw_salt = ns.hex()
                    row.pw_hash = new_hash
                    row.pw_iters = CURRENT_PBKDF2_ITERS
                    s.commit()
            logger.info("账户口令哈希已升级到 %d 轮：%s", CURRENT_PBKDF2_ITERS, username)
        except Exception:  # noqa: BLE001
            logger.warning("口令哈希升级失败（不影响本次登录）", exc_info=True)
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
