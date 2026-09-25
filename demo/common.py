# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ReturnGuard 共享配置 / 依赖 / 中间件（从原 main.py 拆出，P1-9）。

本模块承载原先散落在 main.py 顶部与中段的所有模块级状态：
    - 配置常量（限流 / 鉴权 / 跨域 / WAL / 上传基线 / 路径）
    - 可观测性（结构化日志、_metrics、_state_lock）
    - 依赖与鉴权辅助（_resolve_source / _resolve_tenant / _require_session / _require_admin / get_client_ip / _check_rate_limit）
    - 上传安全（_safe_name / _validate_image / _cleanup_old_uploads）
    - HTTP 中间件（no_cache / observe / security_headers）
    - 洞察聚合辅助（_get_insights）

业务路由（routers/*）与本装配层（main.py）都从这里取共享依赖，避免重复定义与漂移。
中间件函数本身不带装饰器，统一在 main.py 以与原始一致的顺序注册为 app 中间件。
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import re
import threading
import time
from collections import defaultdict

import auth  # C组：账户体系 + 多租户隔离
import shared_state  # SEC-12：跨 worker 共享状态（限流 / 登录封禁）
from calibration import get_active_threshold, save_calibration, suggest_threshold  # B组：阈值自标定
from db import (  # 数据持久层（SQLite / openGauss 双源隔离）
    DEFAULT_SOURCE,
    VALID_SOURCES,
    checkpoint_wal,
    delete_case,
    init_db,
    load_filtered_cases,
    query_cases,
    save_case,
)
from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from importer import import_csv_text  # B组：真实数据回流（CSV / 数据集文件导入）
from logging_setup import configure_logging, new_request_id, request_id

# 导入业务逻辑层（pipeline 负责取证+洞察，models_router 负责真实模型调用）
from pipeline import _empty_aggregate, _season_of, analyze_case, build_insights
from platforms import get_platform_spec, is_valid_platform
from quota import check_live_quota  # SEC-13：live 配额闸（分析 + 洞察 + PDF 导出共用）
from schemas import AnalyzeResult, ManualCase
from storage import backend_name, is_public_ready  # 图床（P3-17）
from storage import upload as bed_upload

logger = logging.getLogger("returnguard.api")

# 本模块对外再导出（re-export）的名单：以下名称均从其他模块（db / calibration / importer /
# pipeline / platforms / schemas / storage / auth / shared_state）导入后，由 routers/* 与
# main.py 经 `from common import X` 转手取得。显式列入 __all__ 可避免 `ruff --fix` 将它们的
# import 误判为 F401（未使用）而删除，从而破坏下游路由的导入契约（P1-9 拆分后尤为关键）。
__all__ = [
    # —— 来自 db（被 main / forensic 转手）——
    "init_db",
    "delete_case",
    "query_cases",
    "save_case",
    # —— 来自 calibration（被 routers/calibration 转手）——
    "get_active_threshold",
    "save_calibration",
    "suggest_threshold",
    # —— 来自 importer（被 main 转手）——
    "import_csv_text",
    # —— 来自 pipeline（被 forensic 转手）——
    "analyze_case",
    # —— 来自 platforms（被 forensic 转手）——
    "get_platform_spec",
    "is_valid_platform",
    # —— 来自 schemas（被 forensic 转手）——
    "AnalyzeResult",
    "ManualCase",
    # —— 来自 storage（被 forensic / frontend 转手）——
    "bed_upload",
    "backend_name",
    "is_public_ready",
    # —— 模块级对象（被 auth / frontend 转手）——
    "auth",
    "shared_state",
]


# ---- 版本（单一来源：仓库根 VERSION 文件；前端顶栏与 /api/config 均从此读取）----
def _read_app_version() -> str:
    """读取仓库根 VERSION 文件，支持本地开发与 Docker 两种目录结构。"""
    base = os.path.dirname(__file__)
    candidates = [
        # 本地开发 / 新版 Docker：main.py 在 demo/，VERSION 在仓库根
        os.path.join(base, "..", "VERSION"),
        # 旧版 Docker 拍平结构：main.py 与 VERSION 同目录（fallback，向后兼容）
        os.path.join(base, "VERSION"),
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as _vf:
                value = _vf.read().strip()
                if value:
                    return value
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            continue
    return "unknown"


APP_VERSION = _read_app_version()

# ---- 可观测性（P2-9 / A26）：结构化 JSON 日志 + 请求追踪 + 基础指标 ----
configure_logging()
_metrics: defaultdict[str, float] = defaultdict(float)
_metrics["start_time"] = int(time.time())

# ---- 写接口限流（P2-8）：演示态默认开启；环境 ANALYZE_RATE_LIMIT=0 关闭 ----
_RATE_LIMIT = int(os.environ.get("ANALYZE_RATE_LIMIT", "60"))  # 每客户端每分钟上限
# 限流/登录封禁状态已外置到 shared_state（SEC-12：跨 worker 共享），不再用进程内 dict。
# 线程安全锁（P3-⑧）：uvicorn 默认线程池跑同步端点，_metrics 为进程内共享可变结构
_state_lock = threading.Lock()

# ---- 认证安全加固（防 spam / 防攻击）----
# 注册/登录限流：注册更严（每建一个租户=一套隔离数据），登录按 IP + 按用户名双重防护
_AUTH_REGISTER_LIMIT = int(os.environ.get("AUTH_REGISTER_LIMIT", "10"))  # 每 IP 每分钟注册上限
_AUTH_LOGIN_IP_LIMIT = int(os.environ.get("AUTH_LOGIN_IP_LIMIT", "30"))  # 每 IP 每分钟登录上限
_LOGIN_MAX_FAILS = int(os.environ.get("LOGIN_MAX_FAILS", "5"))  # 单用户名连续失败上限
_LOGIN_LOCK_SEC = int(os.environ.get("LOGIN_LOCK_MIN", "15")) * 60  # 锁定持续时间（秒）
# SEC: 注册默认关闭（secure-by-default）。公网部署须在 .env 显式开启并配合邀请码，
# 否则任何人都可批量创建租户并灌入数据。开关语义：未配置 = 关闭。
_REGISTRATION_ENABLED = os.environ.get("REGISTRATION_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_REGISTRATION_INVITE_CODE = os.environ.get("REGISTRATION_INVITE_CODE", "").strip()
# 仅当直连客户端属于可信代理时才采纳 X-Forwarded-For / X-Real-IP（逗号分隔 IP/CIDR；默认空=不信任）
_AUTH_TRUSTED_PROXIES = [
    p.strip() for p in os.environ.get("AUTH_TRUSTED_PROXIES", "").split(",") if p.strip()
]
# 公网部署跨域白名单（逗号分隔具体域名；默认空=不挂 CORS，同源）；禁止 "*"
_CORS_ALLOW_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
]

# 登录失败计数 / 封禁（按用户名）：靶向爆破防护，已外置到 shared_state（SEC-12 跨 worker 共享）。

# 写接口鉴权只保留「登录会话」一条通道（_require_session），不再提供 API Key 免登录通道，
# 公网演示统一使用预置的 demo/demo123 账户。历史版本留有 ANALYZE_API_KEY 常量，
# 但其校验函数 _require_api_key 从未被任何端点调用，属「配了却不生效」的伪防护，
# 易造成安全错觉，故整体移除；脚本化调用请走 POST /api/auth/login 取令牌后带 Bearer。

# 上传图访问前缀（P3-5）：返回 /uploads/<文件名> 而非内联整图 base64
UPLOAD_URL_PREFIX = "/uploads/"

# ---- 路径配置 ----
BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")  # 上传图片临时目录
os.makedirs(UPLOAD_DIR, exist_ok=True)
INDEX = os.path.join(BASE, "static", "index.html")  # 前端页面
# 前端压缩产物索引（N4 构建链路）：npm run build 生成，SERVE_MINIFIED=1 时改发此页。
MINIFIED_INDEX = os.path.join(BASE, "static", "dist", "index.html")

# ---- 上传安全基线 ----
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 单文件上限 10MB
_ALLOWED_MAGIC = {  # 仅放行 PNG / JPEG（魔数校验，防伪装）
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")  # 文件名白名单


def _safe_name(name: str) -> str:
    """清洗上传文件名：只保留安全字符，去除路径成分，防止路径穿越。"""
    base = os.path.basename(name or "file").strip()
    cleaned = _SAFE_NAME.sub("_", base)
    return cleaned or "file"


def _validate_image(upload: UploadFile) -> bytes:
    """读取并校验上传文件：非空、大小、PNG/JPEG 魔数；返回原始字节。"""
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"文件过大，单文件上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB"
        )
    if not any(data.startswith(magic) for magic in _ALLOWED_MAGIC):
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPEG 图片")
    return data


def _cleanup_old_uploads(max_age_hours: float = 24) -> None:
    """P2-1：清理上传目录中超过阈值的孤立图片，避免退货照片（PII）无限堆积。

    上传图已改为签名短链（/api/file/{sig}，SEC-8），但仍落盘于 UPLOAD_DIR，
    此处按 mtime 清理过期文件，消除磁盘无限增长风险（双保险）。"""
    try:
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for fn in os.listdir(UPLOAD_DIR):
            if fn == ".gitkeep":  # 保留目录占位文件，避免 git 丢失空目录约定
                continue
            fp = os.path.join(UPLOAD_DIR, fn)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    removed += 1
            except OSError:
                pass
        logger.info("已清理上传目录中 %d 个过期文件（>%.0f 小时）", removed, max_age_hours)
    except Exception:
        logger.warning("上传图清理失败（可忽略）", exc_info=True)


def _check_rate_limit(client_ip: str, scope: str = "analyze", limit: int | None = None) -> bool:
    """P2-8：按 scope 分桶的固定窗口限流（默认 analyze 用 _RATE_LIMIT）。返回 True=放行。

    SEC-12：计数外置到 shared_state（rg_state.db），多 worker 同一主机共享，避免限流被绕过。"""
    cap = limit if limit is not None else _RATE_LIMIT
    if cap <= 0:
        return True
    return shared_state.rate_check(f"{scope}:{client_ip}", cap, 60)


def _ip_in_set(ip: str, nets: list[str]) -> bool:
    """判断 IP 是否落在可信代理列表（支持 CIDR / 精确 IP）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for n in nets:
        try:
            if addr in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            if ip == n:
                return True
    return False


def get_client_ip(request: Request) -> str:
    """代理感知客户端 IP：仅当直连客户端属于可信代理时才采纳转发头。

    - 反向代理 / CDN优先采用其下发的 CF-Connecting-IP（最权威的真实客户端 IP）；
    - 其次 X-Forwarded-For 首段 / X-Real-IP。
    未配置 AUTH_TRUSTED_PROXIES 时一律使用直连 IP，避免伪造转发头绕过限流（SEC-3）。
    部署在反向代理 / CDN 之后，直连 IP 恒为 127.0.0.1，须把 AUTH_TRUSTED_PROXIES 设为
    127.0.0.1 才能正确还原真实访客 IP（否则按 IP 限流/防爆破会坍缩成全局单桶）。"""
    direct = request.client.host if request.client else "unknown"
    if _AUTH_TRUSTED_PROXIES and _ip_in_set(direct, _AUTH_TRUSTED_PROXIES):
        cf = request.headers.get("CF-Connecting-IP", "").strip()
        if cf:
            return cf
        xff = request.headers.get("X-Forwarded-For", "").strip()
        if xff:
            return xff.split(",")[0].strip()
        xri = request.headers.get("X-Real-IP", "").strip()
        if xri:
            return xri
    return direct


def _resolve_source(request: Request) -> str:
    """从请求 query 参数解析数据来源（demo/real），非法或缺失一律回退 demo。"""
    src = request.query_params.get("source", DEFAULT_SOURCE)
    return src if src in VALID_SOURCES else DEFAULT_SOURCE


def _resolve_tenant(request: Request) -> str | None:
    """从 Authorization: Bearer / X-Token 头解析当前租户（=用户名）。

    仅信任请求头（Bearer / X-Token），不再接受 ?token= 查询参数（P2：避免令牌经
    URL/Referer/代理日志泄露）。无令牌（匿名）返回 None → 数据归 public 租户；
    demo 源忽略租户（共享演示库）。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer ") :].strip()
    else:
        token = request.headers.get("X-Token", "")
    return auth.verify_token(token)


def _require_session(request: Request) -> str:
    """写接口会话鉴权（SEC-1）：要求已登录（持有有效令牌），返回 tenant(=username)。

    公网部署下所有数据写入（取证沉淀 / 案件录入 / CSV 导入）必须登录，
    避免匿名写入、数据污染与资源滥用。匿名请求返回 401 并提示登录。"""
    username = _resolve_tenant(request)
    if not username:
        raise HTTPException(status_code=401, detail="请先登录后再操作")
    return username


# 管理动作密钥（独立变量，与写接口的登录会话鉴权解耦）：用于 /api/calibrate 等管理动作。
# 设了 ADMIN_API_KEY 则必须携带 X-Admin-Key 头或 admin_key 查询参数；未设则退化为要求登录，
# 确保匿名仍无法执行管理动作。
_ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def _require_admin(request: Request) -> None:
    """管理动作鉴权（SEC-1）：阈值自标定 /api/calibrate 等会改写全局判定逻辑的动作。

    - 配置了 ADMIN_API_KEY：必须携带匹配的管理密钥（常量时间比较）；
    - 未配置：退化为要求登录会话，至少杜绝匿名篡改。
    该接口此前演示态默认可调，任何人可覆写胜诉率判定阈值，属高危写面，必须收口。"""
    if _ADMIN_KEY:
        provided = request.headers.get("X-Admin-Key", "") or request.query_params.get(
            "admin_key", ""
        )
        if not hmac.compare_digest(provided, _ADMIN_KEY):
            raise HTTPException(status_code=401, detail="需要有效的管理员密钥")
        return
    if not _resolve_tenant(request):
        raise HTTPException(status_code=401, detail="请先登录后再操作")


# ---- WAL 巡检：SQLite 长连接持读锁，WAL 无法自动 truncate，需显式 checkpoint ----
# 实测：rg_state.db 主库 20KB / WAL 4.1MB（206 倍），cases.db 495KB / WAL 1.6MB。
_WAL_CHECKPOINT_INTERVAL = float(os.environ.get("WAL_CHECKPOINT_INTERVAL_SEC", "1800"))


def _wal_checkpoint_all() -> None:
    """对 demo / real 两个案件库各执行一次 TRUNCATE checkpoint（失败不影响运行）。"""
    for src in VALID_SOURCES:
        try:
            checkpoint_wal(src)
        except Exception:  # noqa: BLE001
            logger.debug("WAL checkpoint 跳过 source=%s", src, exc_info=True)


def _start_wal_watcher(interval_sec: float) -> threading.Event | None:
    """后台守护线程：周期性截断 WAL。设 WAL_CHECKPOINT_INTERVAL_SEC<=0 可关闭。"""
    if interval_sec <= 0:
        return None
    stop = threading.Event()

    def _loop():
        while not stop.wait(interval_sec):
            _wal_checkpoint_all()

    t = threading.Thread(target=_loop, name="wal-watcher", daemon=True)
    t.start()
    logger.info("WAL 巡检线程已启动（间隔 %.0f 秒）", interval_sec)
    return stop


# ===================== HTTP 中间件（防御纵深 + 可观测性） =====================
# index.html 中内联 <script> 的 nonce 占位符（见 index() 内的注入逻辑）
_NONCE_PLACEHOLDER = "<!--RG_CSP_NONCE-->"


async def no_cache_middleware(request: Request, call_next):
    """缓存策略（B-前端 P1）：静态资源禁缓存，页面与接口保持新鲜。

    演进过程（两次踩坑，都是「升级后前端不生效」）：
      1. 曾对 /static/* 下发 `public, max-age=60, must-revalidate`——其语义是「60 秒内直接用
         本地副本、不回源」，而前端是无构建 ESM（app.js 相对路径 import，子模块 URL 带不了
         版本号），于是出现「HTML 新 / JS 旧」撕裂；改为 `no-cache`（每次回源校验）。
      2. 改 `no-cache` 后本机正常、**公网仍不正常**：中间 CDN 会把 origin 的 `no-cache`
         覆写成 `max-age=14400` 再下发给浏览器（实测 Cloudflare）。说明「靠响应头协商」
         不可靠——只要链路里有一层不尊重头部的代理就会失效。

    最终方案：静态资源发 `no-store`（任何层级都无正当理由缓存），并配合
    main.VersionedStaticFiles 把 APP_VERSION 写进每个模块 URL——发版即换 URL，
    从机制上不依赖对方是否遵守缓存头。页面(HTML)/接口保持 `no-cache`。
    """
    response = await call_next(request)
    if request.method != "GET":
        return response
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


async def observe_middleware(request: Request, call_next):
    """P2-9 / A26：请求追踪（RequestId）+ 耗时日志 + 基础指标计数。

    request_id 经 contextvars 透传（并发安全），注入每条日志；若客户端带 X-Request-Id
    则沿用（便于网关/链路追踪串联），否则生成。响应回写 X-Request-Id 供前端排障。
    """
    rid = request.headers.get("X-Request-Id") or new_request_id()
    token = request_id.set(rid)
    try:
        start = time.time()
        response = await call_next(request)
        dur_ms = (time.time() - start) * 1000
        with _state_lock:
            _metrics["requests"] += 1
            _metrics["latency_ms_sum"] += dur_ms
            if response.status_code >= 500:
                _metrics["errors"] += 1
            path = request.url.path
            if path == "/api/analyze":
                _metrics["analyze_count"] += 1
            elif path == "/api/insights":
                _metrics["insights_count"] += 1
        response.headers["X-Request-Id"] = rid
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            path,
            response.status_code,
            dur_ms,
            extra={
                "event": "request",
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "latency_ms": round(dur_ms, 1),
            },
        )
        return response
    finally:
        request_id.reset(token)


async def security_headers(request: Request, call_next):
    """P1-3 防御纵深：即便前端偶发漏转义，CSP 也能阻断脚本注入执行。

    SEC-P0 收紧：原先所有非 `/` 路由都下发含 `'unsafe-inline'` 的宽松 script-src，而
    `/static` 是整体挂载的，于是 `/static/index.html` 可直连拿到无 nonce 的宽松策略，
    与前端一处未转义的 title 属性叠加即构成存储型 XSS。现改为：
      ① 直接掐断一切 *.html 静态直连（页面只应由 `/` 经 nonce 注入后下发）；
      ② HTML 响应一律严格 CSP（script-src 'self'，禁止内联），`/` 用 nonce 策略覆盖；
      ③ 补齐 HSTS / X-Frame-Options / Permissions-Policy。
    """
    # ① 页面只能通过 / 拿（带 nonce），不允许 /static/index.html 这类直连绕过
    if request.url.path.lower().endswith((".html", ".htm")):
        return PlainTextResponse("Not Found", status_code=404)

    response = await call_next(request)
    is_html = "text/html" in response.headers.get("content-type", "").lower()
    # ② HTML 严格、非 HTML（JSON/图片/音频）无需脚本策略但仍收紧其余项
    script_src = "'self'" if is_html else "'self' 'unsafe-inline'"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; media-src 'self' data:; "
        f"style-src 'self' 'unsafe-inline'; script-src {script_src}; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    # ③ 仅公网 HTTPS 下发 HSTS（隧道/CDN 场景看 X-Forwarded-Proto），避免污染本地 http 开发
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    if proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def _get_insights(
    request: Request,
    mode: str,
    category: str,
    platform: str,
    region: str,
    season: str,
) -> dict:
    """与 /api/insights 一致的过滤 + 聚合逻辑，供 insights 与 export_pdf 复用。"""
    source = _resolve_source(request)
    # C组：实际数据(real)要求登录后查看（按租户隔离，匿名不暴露公共基准）
    if source == "real" and not _resolve_tenant(request):
        # 复用 pipeline._empty_aggregate() 单一来源，避免手写空字典与聚合结果字段漂移（P1-空结果契约分裂）。
        empty = _empty_aggregate()
        empty.update(
            {
                "source": "real",
                "mode": mode,
                "requires_login": True,
                "message": "实际数据按租户隔离，请登录后查看您的数据。",
            }
        )
        return empty
    # real 源必须解析出具体租户（匿名归 "public"），否则 load_cases 无过滤会跨租户泄露
    tenant_id = (_resolve_tenant(request) or "public") if source == "real" else None
    if mode not in ("mock", "live"):
        raise HTTPException(status_code=400, detail="mode 仅支持 mock / live")
    if category:
        # 品类为自由文本，仅做非空校验（空值视为不过滤）
        if not isinstance(category, str) or not category.strip():
            raise HTTPException(status_code=400, detail="category 非法")
    if platform:
        # 平台必须是举证包支持列表中的合法值，避免静默返回空看板
        if not is_valid_platform(platform):
            raise HTTPException(status_code=400, detail="platform 不在支持列表")
    if season and season not in ("春", "夏", "秋", "冬"):
        raise HTTPException(status_code=400, detail="season 仅支持 春/夏/秋/冬")
    # SEC-13 配额闸覆盖洞察链路：`/api/insights?mode=live` 与 `/api/export_pdf?mode=live`
    # 同样会调用付费 LLM（build_insights → build_insights_live），此前只给 /api/analyze
    # 上了闸门，等于留了一条「换个端点绕开配额」的旁路——攻击者只需不断切换
    # category/platform 过滤条件（每次都产生新的缓存键）即可持续消耗 Key 额度。
    # 语义与 /api/analyze 一致：超限返回 429 + 明确原因，**不静默降级为 mock**。
    if mode == "live":
        allowed, reason = check_live_quota(
            _resolve_tenant(request) or "anonymous", get_client_ip(request)
        )
        if not allowed:
            raise HTTPException(status_code=429, detail=reason)
    # A23：过滤下推 SQL——category/platform/region 直接在查询层 WHERE 命中，
    # 不再全量 load_cases 后在 Python 逐条过滤；season 仍需 date→季节映射，留 Python 二次过滤。
    cases = load_filtered_cases(
        source, tenant_id=tenant_id, category=category, platform=platform, region=region
    )
    if season:
        cases = [c for c in cases if _season_of(c.get("date")) == season]
    agg = build_insights(cases, mode, source)
    agg = dict(agg)  # 浅拷贝，避免就地修改 build_insights 的共享缓存对象
    agg["source"] = source  # 让前端知道当前看板基于哪个数据源
    return agg
