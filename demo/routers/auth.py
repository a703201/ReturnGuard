"""账户体系 + 多租户隔离路由：/api/auth/{register,login,me,logout}。

从原 main.py 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

import common  # 配置开关（_REGISTRATION_ENABLED 等）需在调用时实时读取 common 模块全局，
# 以便测试 monkeypatch.setattr(common, ...) 能生效（P1-9 拆分后这些值位于 common 模块）。
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from common import (
    get_client_ip,
    _check_rate_limit,
    _resolve_tenant,
    auth,
    logger,
    _state_lock,
    _metrics,
    shared_state,
)

router = APIRouter()


# ===================== C组：账户体系 + 多租户隔离 =====================
class RegisterRequest(BaseModel):
    """注册请求：一个用户即一个租户。"""

    username: str
    password: str
    tenant_name: str = ""
    invite_code: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/auth/register")
def register_api(req: RegisterRequest, request: Request):
    """注册账户（一个用户 = 一个租户），成功即返回令牌（自动登录）。

    real 源案件按租户隔离：注册后可录入/查看/删除属于自己租户的真实退货数据；
    demo 源为共享演示库，不参与隔离。写接口鉴权与登录独立（登录凭用户名/密码）。

    防 spam：注册按 IP 限流；可经 REGISTRATION_ENABLED 关闭、REGISTRATION_INVITE_CODE 邀请制。"""
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip, scope="register", limit=common._AUTH_REGISTER_LIMIT):
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    if not common._REGISTRATION_ENABLED:
        raise HTTPException(status_code=403, detail="注册已关闭")
    if common._REGISTRATION_INVITE_CODE and req.invite_code != common._REGISTRATION_INVITE_CODE:
        raise HTTPException(status_code=400, detail="邀请码无效")
    ok, reason = auth.register(req.username, req.password, req.tenant_name)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    logger.info("新租户注册：%s (ip=%s)", req.username, client_ip)
    return {"ok": True, "token": auth.issue_token(req.username), "username": req.username}


@router.post("/api/auth/login")
def login_api(req: LoginRequest, request: Request):
    """登录，返回 HMAC 签名令牌（无状态，7 天有效）。

    防爆破：按 IP 限流 + 按用户名连续失败计数封禁（LOGIN_MAX_FAILS / LOGIN_LOCK_MIN）。
    SEC-12：限流/封禁状态外置到 shared_state，跨 worker 共享，避免单进程绕过。"""
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip, scope="login", limit=common._AUTH_LOGIN_IP_LIMIT):
        raise HTTPException(status_code=429, detail="登录过于频繁，请稍后再试")
    # 用户名级临时封禁（靶向爆破防护）
    # SEC: 锁定态必须与"凭证错误"对外完全一致（同为 401 + 同文案）。否则攻击者可用
    # 「429 已锁定」vs「401 不存在」的响应差异枚举出真实用户名。
    if shared_state.login_locked(req.username):
        logger.warning("登录被拒（账户锁定中）ip=%s user=%s", client_ip, req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.authenticate(req.username, req.password)
    if not token:
        # 失败审计 + 计数封禁
        logger.warning("登录失败 ip=%s user=%s reason=invalid_credentials", client_ip, req.username)
        with _state_lock:
            _metrics["auth_fail"] += 1
        shared_state.login_lock_register(req.username, common._LOGIN_MAX_FAILS, common._LOGIN_LOCK_SEC)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 成功：清空该用户名失败计数
    shared_state.login_clear(req.username)
    return {"ok": True, "token": token, "username": req.username}


@router.get("/api/auth/me")
def me(request: Request):
    """当前登录用户信息（含租户标识），供前端恢复会话。"""
    username = _resolve_tenant(request)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    u = auth.get_user(username)
    return {"ok": True, "user": u, "tenant": username}


@router.post("/api/auth/logout")
def logout_api(request: Request):
    """登出：自增该用户 token_version，使其所有已签发令牌立即失效（等价服务端注销/踢人）。"""
    username = _resolve_tenant(request)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    auth.logout(username)
    return {"ok": True}
