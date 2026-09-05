"""ReturnGuard 复赛 Demo 后端（FastAPI 入口）

本服务把「方案文档」的两大阶段暴露成 HTTP 接口：
    阶段A 个案举证  → POST /api/analyze   （上传退回图+本店主图，返回一单取证结果）
    阶段B 群体洞察  → GET  /api/insights  （聚合案件库，返回多维洞察看板，支持品类/平台下钻）
    数据沉淀        → GET  /api/cases     （查看已沉淀的案件库，便于调试）
    健康检查        → GET  /health        （编排/探针用）

前端（static/index.html）即「退货情报站」页面：上半部是洞察看板（阶段B 产品主体），
下半部折叠着单案举证入口（阶段A 数据采集管道）。

工程化（大厂对标）：上传文件名白名单清洗 + 路径越界断言（防穿越）；PNG/JPEG 魔数 +
大小校验；端点挂 Pydantic response_model（强契约 + OpenAPI）；/health 探针；/uploads 静态挂载。
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import quote

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
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from importer import import_csv_text, import_file  # B组：真实数据回流（CSV / 数据集文件导入）
from logging_setup import configure_logging, new_request_id, request_id
from pdf_report import default_filename, generate_insights_pdf

# 导入业务逻辑层（pipeline 负责取证+洞察，models_router 负责真实模型调用）
from pipeline import _empty_aggregate, _season_of, analyze_case, build_insights
from platforms import get_platform_spec, is_valid_platform, list_platforms
from pydantic import BaseModel
from schemas import AnalyzeResult, InsightsResponse, ManualCase
from storage import backend_name, is_public_ready  # 图床（P3-17）
from storage import upload as bed_upload

logger = logging.getLogger("returnguard.api")


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
_metrics = defaultdict(int)
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

    - Cloudflare Tunnel 等反向代理优先采用其下发的 CF-Connecting-IP（最权威的真实客户端 IP）；
    - 其次 X-Forwarded-For 首段 / X-Real-IP。
    未配置 AUTH_TRUSTED_PROXIES 时一律使用直连 IP，避免伪造转发头绕过限流（SEC-3）。
    部署在 Cloudflare Tunnel 后，直连 IP 恒为 127.0.0.1，须把 AUTH_TRUSTED_PROXIES 设为
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


@asynccontextmanager
async def lifespan(app):
    """服务启动时：初始化双源数据库（demo 播种 / real 空库）+ 清理过期上传图。

    支持 FORCE_RESEED=1 仅重置 demo 种子库（real 实际库始终保留，避免误清真实数据）。
    """
    if os.environ.get("FORCE_RESEED") == "1":
        init_db("demo", force=True)
    else:
        init_db("demo")
    init_db("real")  # 实际数据库：确保表存在，初始空库待录入
    # C组：账户/用户表（多租户隔离的租户目录）
    auth.init_auth_db()
    # 复赛交付：预置演示测试账号（评委可直接登录 real 源体验多租户隔离 + 实际数据洞察）
    try:
        auth.register("demo", "demo123", "ReturnGuard 演示租户")
        logger.info("已预置演示测试账号 demo/demo123")
    except Exception:
        logger.exception("预置演示账号失败（不影响启动）")
    # 安全自检：生产必须固化 AUTH_SECRET，否则令牌重启即失效且不利于统一轮换
    if not os.environ.get("AUTH_SECRET"):
        logger.critical(
            "AUTH_SECRET 未设置：使用进程内随机密钥，重启将令所有令牌失效，且不利于统一轮换；生产环境务必固化 AUTH_SECRET"
        )
    # C组 openGauss 自动导入：部署期设 RG_AUTO_IMPORT_CSV=<路径>，real 源（可指向 openGauss）
    # 启动即批量回流真实退货数据，使洞察看板开箱即用真实业务数据（B组 importer 主链路）。
    auto_csv = os.environ.get("RG_AUTO_IMPORT_CSV", "")
    if auto_csv and os.path.exists(auto_csv):
        try:
            # dedupe=True：按自然键幂等导入，容器重启重复挂载同一份 CSV 不重复堆积
            res = import_csv_text(open(auto_csv, encoding="utf-8-sig").read(), "real", dedupe=True)
            logger.info("启动自动导入 CSV 完成 source=real: %s", res)
        except Exception:
            logger.exception("启动自动导入 CSV 失败（不影响服务启动）")
    _cleanup_old_uploads(max_age_hours=float(os.environ.get("UPLOAD_MAX_AGE_HOURS", "24")))
    # 启动时先截断一次历史 WAL，再起巡检线程，关闭前最后截断一次
    _wal_checkpoint_all()
    _wal_stop = _start_wal_watcher(_WAL_CHECKPOINT_INTERVAL)
    try:
        yield
    finally:
        if _wal_stop is not None:
            _wal_stop.set()
        _wal_checkpoint_all()


app = FastAPI(title="ReturnGuard Demo", lifespan=lifespan)
# 把 static 目录挂成 /static，前端可加载其中的资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
# 上传目录不再公开静态挂载（SEC-8）：图片经签名 + 短期过期的 /api/file/{sig} 提供，
# 杜绝退货图（PII）被匿名长期拉取。live 模式仍由 PUBLIC_IMAGE_BASE / 对象存储公网回源。

# 公网部署跨域白名单（可选）：仅当设置 CORS_ALLOW_ORIGINS 才挂，禁止 "*"
if _CORS_ALLOW_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )


# 缓存策略（B-前端 P1）：静态资源可缓存，页面与接口保持新鲜。
# 原先全站 no-cache 致每次刷新重传约 66KB 的 app.js + 图片；现对 /static/*
# 下发短时效强校验缓存，其余（HTML/API）仍 no-cache，兼顾性能与「代码即见最新」。
@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method != "GET":
        return response
    path = request.url.path
    if path.startswith("/static/"):
        # 内容寻址由文件名/版本控制；60s 短缓存避免演示期间反复重传
        response.headers["Cache-Control"] = "public, max-age=60, must-revalidate"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
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


@app.middleware("http")
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


# index.html 中内联 <script> 的 nonce 占位符（见 index() 内的注入逻辑）
_NONCE_PLACEHOLDER = "<!--RG_CSP_NONCE-->"


@app.get("/", response_class=HTMLResponse)
def index():
    """返回「退货情报站」前端页面（SEC-9：每请求生成 nonce 注入 CSP，阻断内联脚本注入执行）。"""
    nonce = secrets.token_urlsafe(16)
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    # 前端脚本已外置为 /static/app.js（ES module，同域加载），由 CSP 的 script-src 'self'
    # 放行，无需 nonce 注入；仍保留 nonce 机制以兼容将来可能回嵌的内联脚本。
    # <style> 块及大量 HTML 属性 style="..." 无法 nonce，style-src 保留 'unsafe-inline'
    # （CSS 注入无脚本执行能力，危害低），记为已知权衡。
    #
    # 注入方式用显式占位符：原先 html.replace("<script>", ..., 1) 依赖"全文只有一个
    # <script> 且它恰好是最先出现的"这一巧合，一旦后续新增任何内联块或更早出现
    # "<script>" 字符串，nonce 就会打偏 → 全站 JS 被 CSP 阻断而白屏。
    if _NONCE_PLACEHOLDER in html:
        html = html.replace(_NONCE_PLACEHOLDER, f' nonce="{nonce}"')
    csp = (
        "default-src 'self'; img-src 'self' data: https:; media-src 'self' data:; "
        f"style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-{nonce}'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return HTMLResponse(content=html, headers={"Content-Security-Policy": csp})


@app.get("/api/file/{sig}")
async def serve_upload(sig: str, f: str = Query(...), e: int = Query(...)):
    """SEC-8：签名 + 过期的上传图访问（退货图 PII 不可匿名长期拉取）。

    签名 = HMAC(filename|exp, AUTH_SECRET)，URL 带 ?f=<文件名>&e=<过期时间戳>。
    校验失败 / 过期 / 越界 → 404（不泄露文件是否存在）。"""
    now = int(time.time())
    if e < now:
        raise HTTPException(status_code=404, detail="not found")
    expected = hmac.new(auth._SECRET, f"{f}|{e}".encode(), "sha256").hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=404, detail="not found")
    safe = _safe_name(f)
    path = os.path.join(UPLOAD_DIR, safe)
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(UPLOAD_DIR)
    if not abs_path.startswith(abs_dir + os.sep) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(abs_path)


@app.get("/api/img/{key}")
async def serve_img(key: str):
    """自托管 HTTPS 取图（RG_SELF_IMAGE_BASE）：退货图经本服务隧道暴露给视觉网关回源。

    key 为 256-bit 不可猜测随机名（storage._public_object_key），与七牛公网图同等级隐私；
    文件随 UPLOAD_DIR 24h 清理（cleanup_old_uploads）。校验越界/不存在/含路径符 -> 404。"""
    if not key or "/" in key or "\\" in key or ".." in key:
        raise HTTPException(status_code=404, detail="not found")
    path = os.path.join(UPLOAD_DIR, key)
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(UPLOAD_DIR)
    if not abs_path.startswith(abs_dir + os.sep) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(abs_path)


@app.get("/health")
def health():
    """健康检查探针（编排 healthcheck / 负载均衡用）。"""
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResult)
def analyze(
    request: Request,
    returned_image: UploadFile = File(..., description="退回商品图"),
    product_image: UploadFile = File(..., description="本店主图/详情图"),
    listing_text: str = Form(""),
    sku: str = Form("SKU-未知"),
    amount: float = Form(0.0),
    category: str = Form(""),
    supplier: str = Form(""),
    platform: str = Form(""),
    mode: str = Form("mock"),
):
    """阶段A · 个案举证接口。

    流程：接收两张图（校验+落盘）→ 调用 pipeline.analyze_case 完成取证
          → 把结果沉淀进案件库（供阶段B洞察）→ 返回给前端展示。
    返回字段见 schemas.AnalyzeResult；defect_boxes 为缺陷示意框（归一化坐标）。
    platform 为销售平台（可选），用于关联「平台适配举证包」的必备举证清单。
    category/supplier 为选填维度，补全后该单可干净进入洞察聚合（P1-1 防污染）。
    source(=demo|real)：取证结果沉淀到对应数据库（默认 demo）。
    """
    source = _resolve_source(request)
    # SEC-1 写接口会话鉴权：取证沉淀必须登录，避免匿名写入与资源滥用
    _require_session(request)
    # 写操作一律落到 real 源（与 import_csv 同款保护）：demo 是共享只读演示库，
    # 且删除被显式禁止（见 delete_case_api），若放任写入会造成「只增不减」的永久污染，
    # 演示数字（1206 条 / 胜诉率 34.6%）会被逐次改写，恢复只能靠 FORCE_RESEED 重建。
    # 归正必须在 tenant_id 解析之前，否则取证结果会落进 public 公共桶而非当前租户。
    if source == "demo":
        logger.warning("单案取证强制落到 real 源（忽略 source=demo），避免污染演示种子库")
        source = "real"
    # P2-8 限流：按客户端 IP 固定窗口
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if mode not in ("mock", "live"):
        raise HTTPException(status_code=400, detail="mode 仅支持 mock / live")
    if platform and not is_valid_platform(platform):
        raise HTTPException(status_code=400, detail="platform 不在支持列表")

    # 校验 + 读取两张图原始字节（UploadFile 只读一次，先读后写）
    ret_bytes = _validate_image(returned_image)
    prod_bytes = _validate_image(product_image)

    # 用随机前缀 + 清洗后的文件名落盘，并断言最终路径仍在 UPLOAD_DIR 内（防穿越）
    rid = uuid.uuid4().hex[:8]
    rp = os.path.join(UPLOAD_DIR, f"{rid}_ret_{_safe_name(returned_image.filename)}")
    pp = os.path.join(UPLOAD_DIR, f"{rid}_prod_{_safe_name(product_image.filename)}")
    # 断言最终路径仍在 UPLOAD_DIR 内（防穿越）。用显式 raise 而非 assert：
    # python -O 会剥离 assert，导致兜底检查静默失效。
    if os.path.dirname(os.path.abspath(rp)) != UPLOAD_DIR:
        raise HTTPException(status_code=400, detail="上传路径越界")
    if os.path.dirname(os.path.abspath(pp)) != UPLOAD_DIR:
        raise HTTPException(status_code=400, detail="上传路径越界")

    # P1-2 原子性：落盘→取证→存库 全程在 try 中；任一环节异常即清理孤立图片，且不丢取证结果
    try:
        with open(rp, "wb") as f:
            f.write(ret_bytes)
        with open(pp, "wb") as f:
            f.write(prod_bytes)

        # 图床（P3-17）：把上传图同步成公网可访问 URL，供 live 模式视觉/向量/OCR 服务端回源
        ret_url = bed_upload(rp, os.path.basename(rp))
        prod_url = bed_upload(pp, os.path.basename(pp))

        # 执行取证（功能①②③④⑤）
        result = analyze_case(
            rp,
            pp,
            listing_text,
            sku,
            amount,
            mode,
            returned_url=ret_url,
            product_url=prod_url,
        )
        result["case_id"] = rid
        result["platform"] = platform
        # P1-1 单案无法判定输赢，标记「待分析」：不稀释胜诉率 KPI、在分布中单独分组
        result["outcome"] = "待分析"
        result["category"] = category
        result["supplier"] = supplier
        result["supplier_name"] = supplier  # 单案上传只能拿到供应商编号，名称暂同号
        # 关联「平台适配举证包」：把该平台的必备举证材料随单返回（只列客观要求，不裁决）
        if platform:
            spec = get_platform_spec(platform)
            result["platform_evidence"] = spec.get("required_evidence", []) if spec else []

        # P3-5 退回图用 URL 访问（图床公网 URL，不再内联整图 base64 撑大响应）
        result["returned_image_url"] = ret_url

        # 数据沉淀：取证结果 > 数据沉淀。save 失败只记日志，仍优先返回 result，
        # 但显式返回 persisted 标记，前端据此提示用户「本次取证未落库」（修复 P1-写库失败静默吞）
        persisted = False
        try:
            tenant_id = (_resolve_tenant(request) or "public") if source == "real" else None
            save_case(
                source,
                {
                    **result,
                    "sku": sku,
                    "amount": amount,
                    "category": category,
                    "supplier": supplier,
                    "supplier_name": supplier,
                    "outcome": "待分析",
                    "returned_image": os.path.basename(rp),
                    "product_image": os.path.basename(pp),
                },
                tenant_id=tenant_id,
            )
            persisted = True
        except Exception as e:
            logger.exception("案件沉淀失败（不影响本次取证结果返回）: %s", e)
        result["persisted"] = persisted
        return result
    except HTTPException:
        raise
    except Exception:
        # 清理可能已落盘的孤立图片，避免 UPLOAD_DIR 残留
        for p in (rp, pp):
            try:
                os.remove(p)
            except OSError:
                pass
        logger.exception("单案取证异常")
        # from None：有意把底层异常替换为干净的 500，原链已由 logger.exception 记录
        raise HTTPException(status_code=500, detail="取证处理失败，请重试") from None


@app.get("/api/config")
def api_config():
    """前端常量单一来源（P2-4）：返回同款一致性阈值、应用版本、可用数据源、图床状态等。"""
    from models_router import MODEL_ROUTER_PROFILE

    return {
        # 阈值走标定后的运行期值，而非硬编码常量（P1-阈值过期）：前端显示的判定线与判定逻辑一致。
        "same_item_threshold": get_active_threshold(),
        "version": APP_VERSION,
        "sources": list(VALID_SOURCES),
        "default_source": DEFAULT_SOURCE,
        "image_bed": backend_name(),
        "image_bed_public": is_public_ready(),
        # 模型网关 profile：tokenplan=Token Plan 测试网关 / official=赛事指定 Model Router，
        # 复赛提交时切到 official 即演示用赛事指定端点（详见 demo/.env.example）。
        # 注意：不再回传内部网关地址 model_router_endpoint（P2-信息泄露），前端无需该值。
        "model_router_profile": MODEL_ROUTER_PROFILE,
    }


@app.get("/metrics")
def metrics(request: Request):
    """P2-9：基础运行指标（请求量 / 平均耗时 / 错误数 / 取证·洞察调用量）。

    管理端点：需管理员密钥（ADMIN_API_KEY）或登录会话（_require_admin），
    避免匿名暴露内部运行指标（P2 信息泄露面收敛）。"""
    _require_admin(request)
    uptime = int(time.time()) - int(_metrics["start_time"])
    avg = (_metrics["latency_ms_sum"] / _metrics["requests"]) if _metrics["requests"] else 0
    return {
        "uptime_seconds": uptime,
        "requests": _metrics["requests"],
        "avg_latency_ms": round(avg, 2),
        "errors_5xx": _metrics["errors"],
        "analyze_count": _metrics["analyze_count"],
        "insights_count": _metrics["insights_count"],
    }


@app.get("/api/platforms")
def platforms():
    """平台适配举证包（交付物 A 数据源）：返回各大平台退货/纠纷举证规则
    与 ReturnGuard 取证能力的映射。前端据此渲染「平台举证包」面板与单案清单。"""
    return {"platforms": list_platforms()}


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


@app.get("/api/insights", response_model=InsightsResponse)
def insights(
    request: Request,
    mode: str = "mock",
    category: str = "",
    platform: str = "",
    region: str = "",
    season: str = "",
):
    """阶段B · 群体洞察接口（AI 市场洞察核心交付物）。

    参数：
        source   demo（演示数据）/ real（实际数据），决定读取哪个数据库
        mode     mock（规则归因，可复现）/ live（LLM 归因，需 Key）
        category 按品类下钻（可选）
        platform 按平台下钻（可选）
        region   按销售地区下钻（可选，方向2 维度扩展）
        season   按季节下钻：春/夏/秋/冬（可选，方向2 维度扩展）
    返回：KPI、品类热力、根因归因、供应商红黑榜、平台对比、异常预警、SKU明细、洞察报告、选品建议，
         以及维度扩展字段（region_view / season_view / supplier_blacklist / 退货成本估算）。
    """
    return _get_insights(request, mode, category, platform, region, season)


@app.get("/api/export_pdf")
def export_pdf(
    request: Request,
    mode: str = "mock",
    category: str = "",
    platform: str = "",
    region: str = "",
    season: str = "",
):
    """导出洞察报告为 PDF（服务端生成，浏览器直接下载，不再依赖 window.print）。

    过滤条件与 /api/insights 完全一致，确保导出内容与当前看板对应。
    """
    agg = _get_insights(request, mode, category, platform, region, season)
    source = agg.get("source", "demo")
    pdf_bytes = generate_insights_pdf(
        agg,
        mode=mode,
        source=source,
        category=category,
        platform=platform,
        region=region,
        season=season,
    )
    filename = default_filename()
    ascii_name = (
        filename.encode("ascii", "ignore").decode().replace(" ", "_") or "ReturnGuard_report.pdf"
    )
    utf8_name = quote(filename, safe="")
    content_disposition = f"attachment; filename=\"{ascii_name}\"; filename*=utf-8''{utf8_name}"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition},
    )


@app.get("/api/cases")
def cases(
    request: Request,
    slim: bool = True,
    page: int = 1,
    page_size: int = 50,
    category: str = "",
    platform: str = "",
    region: str = "",
    outcome: str = "",
):
    """查看指定 source 的案件库（A23：支持过滤下推 + 分页）。

    返回信封：{items, total, page, page_size, source, filters}。
    - slim=1（默认）只返回录入列表所需关键字段（P3-①），避免整库大响应体。
    - category/platform/region/outcome：下推 SQL WHERE，减少拉库与传输量。
    - page/page_size：分页，避免一次性把整库推给前端。
    - real 源按当前租户隔离，且**必须登录**（匿名不再归 "public"）。
    """
    source = _resolve_source(request)
    # SEC-P0: real 源存的是真实退货数据（SKU / 供应商 / 商品文案），此前匿名可零凭证
    # 拉走全库。现与 /api/insights 对齐：real 源一律要求登录，且登录后租户即用户名，
    # 不再回退 "public"，因此看不到任何归属不明（tenant_id IS NULL）的历史记录。
    # demo 源是共享演示库、不含真实买家 PII，保持匿名可读以保证演示体验。
    if source == "real":
        tenant_id = _require_session(request)
    else:
        tenant_id = None
    return query_cases(
        source,
        tenant_id=tenant_id,
        category=category,
        platform=platform,
        region=region,
        outcome=outcome,
        page=page,
        page_size=page_size,
        slim=slim,
    )


@app.post("/api/cases", status_code=201)
def add_case(c: ManualCase, request: Request):
    """网页「数据录入」：手动添加一条实际退货案件到指定 source（默认 real 由前端开关控制）。

    不强制传图，填字段即可录入；落库后对应 source 的洞察看板实时刷新。
    写接口：设置 ANALYZE_API_KEY 后需携带 API Key（_require_api_key）。
    """
    source = _resolve_source(request)
    _require_session(request)
    # 同 /api/analyze：数据录入一律落 real 源，避免污染共享演示库。
    # demo 禁止删除且允许匿名读，若任由录入写入会只增不减地改写演示基准数据。
    # 归正必须在 tenant_id 解析之前，确保录入行归属当前登录租户。
    if source == "demo":
        logger.warning("数据录入强制落到 real 源（忽略 source=demo），避免污染演示种子库")
        source = "real"
    tenant_id = (_resolve_tenant(request) or "public") if source == "real" else None
    data = c.model_dump()
    data["case_id"] = "RG-" + uuid.uuid4().hex[:8].upper()
    if not data.get("defect_tags"):
        data["defect_tags"] = ["无明显瑕疵"]
    save_case(source, data, tenant_id=tenant_id)
    location = f"/api/cases/{data['case_id']}"
    return JSONResponse(
        status_code=201,
        headers={"Location": location},
        content={
            "ok": True,
            "source": source,
            "case_id": data["case_id"],
            "tenant": tenant_id or "public",
        },
    )


@app.delete("/api/cases/{case_id}")
def delete_case_api(case_id: str, request: Request):
    """删除指定 source 下的一条案件（实际数据管理用）。写接口：须登录会话（_require_session），匿名 → 401。
    real 源仅能删除当前租户的案件，跨租户不可见不可删。

    SEC-P0: demo 源为共享演示库且测试账号公开，此前任何登录者都能把 1206 条种子数据
    逐条删光（演示现场不可逆）。现对 demo 源一律拒绝删除，种子数据只能经 FORCE_RESEED 重建。
    """
    source = _resolve_source(request)
    _require_session(request)
    if source == "demo":
        raise HTTPException(status_code=403, detail="演示库为只读，如需清空请用实际数据（real）源")
    tenant_id = _resolve_tenant(request)
    n = delete_case(source, case_id, tenant_id=tenant_id)
    if n == 0:
        # 此前删除不存在的 id 仍返回 ok:true，前端无法区分成功与"没找到"
        raise HTTPException(status_code=404, detail="未找到该案件，或不属于当前账户")
    return {"ok": True, "source": source, "deleted": n}


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


@app.post("/api/auth/register")
def register_api(req: RegisterRequest, request: Request):
    """注册账户（一个用户 = 一个租户），成功即返回令牌（自动登录）。

    real 源案件按租户隔离：注册后可录入/查看/删除属于自己租户的真实退货数据；
    demo 源为共享演示库，不参与隔离。写接口鉴权与登录独立（登录凭用户名/密码）。

    防 spam：注册按 IP 限流；可经 REGISTRATION_ENABLED 关闭、REGISTRATION_INVITE_CODE 邀请制。"""
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip, scope="register", limit=_AUTH_REGISTER_LIMIT):
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    if not _REGISTRATION_ENABLED:
        raise HTTPException(status_code=403, detail="注册已关闭")
    if _REGISTRATION_INVITE_CODE and req.invite_code != _REGISTRATION_INVITE_CODE:
        raise HTTPException(status_code=400, detail="邀请码无效")
    ok, reason = auth.register(req.username, req.password, req.tenant_name)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    logger.info("新租户注册：%s (ip=%s)", req.username, client_ip)
    return {"ok": True, "token": auth.issue_token(req.username), "username": req.username}


@app.post("/api/auth/login")
def login_api(req: LoginRequest, request: Request):
    """登录，返回 HMAC 签名令牌（无状态，7 天有效）。

    防爆破：按 IP 限流 + 按用户名连续失败计数封禁（LOGIN_MAX_FAILS / LOGIN_LOCK_MIN）。
    SEC-12：限流/封禁状态外置到 shared_state，跨 worker 共享，避免单进程绕过。"""
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip, scope="login", limit=_AUTH_LOGIN_IP_LIMIT):
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
        shared_state.login_lock_register(req.username, _LOGIN_MAX_FAILS, _LOGIN_LOCK_SEC)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 成功：清空该用户名失败计数
    shared_state.login_clear(req.username)
    return {"ok": True, "token": token, "username": req.username}


@app.get("/api/auth/me")
def me(request: Request):
    """当前登录用户信息（含租户标识），供前端恢复会话。"""
    username = _resolve_tenant(request)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    u = auth.get_user(username)
    return {"ok": True, "user": u, "tenant": username}


@app.post("/api/auth/logout")
def logout_api(request: Request):
    """登出：自增该用户 token_version，使其所有已签发令牌立即失效（等价服务端注销/踢人）。"""
    username = _resolve_tenant(request)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    auth.logout(username)
    return {"ok": True}


# ===================== B组：相似度阈值自标定 + 真实数据回流 =====================
class CalibrateRequest(BaseModel):
    """阈值自标定输入：真同款样本相似度、真调包样本相似度。"""

    same_sims: list[float] = []
    diff_sims: list[float] = []


@app.get("/api/calibrate")
def calibrate_get():
    """返回当前生效的同款阈值（标定值或默认 0.82）及标定样本量。"""
    from calibration import load_calibration_record

    rec = load_calibration_record()
    return {
        "threshold": get_active_threshold(),
        "source": "calibrated" if rec else "default",
        "n_same": rec["n_same"] if rec else 0,
        "n_diff": rec["n_diff"] if rec else 0,
    }


@app.post("/api/calibrate")
def calibrate_post(req: CalibrateRequest, request: Request):
    """用历史「真同款 / 真调包」样本标定 SAME_ITEM_THRESHOLD（Youden J 最优分离点），并落盘。
    样本不足（缺任一类）返回默认经验值，不覆盖既有标定（避免无意义回写）。
    管理动作：需管理员密钥（ADMIN_API_KEY）或登录会话（_require_admin），演示态/公网均不可匿名篡改。"""
    _require_admin(request)
    t = suggest_threshold(req.same_sims, req.diff_sims)
    if not req.same_sims or not req.diff_sims:
        return {
            "threshold": t,
            "saved": False,
            "insufficient": True,
            "message": "样本不足（需同时提供 same_sims 与 diff_sims），返回默认阈值，未落盘",
        }
    save_calibration(t, len(req.same_sims), len(req.diff_sims))
    logger.info(
        "阈值自标定完成：%.3f（same=%d, diff=%d）", t, len(req.same_sims), len(req.diff_sims)
    )
    return {
        "threshold": t,
        "saved": True,
        "insufficient": False,
        "n_same": len(req.same_sims),
        "n_diff": len(req.diff_sims),
    }


@app.post("/api/import_csv")
def import_csv(
    request: Request,
    csv_file: UploadFile | None = File(None),
    csv_text: str = Form(""),
):
    """B组·真实数据回流：把卖家退货 CSV 批量导入 real 源（可指向 openGauss），让洞察看板切换真实业务数据。

    两种入参（二选一）：上传 csv_file，或直接贴 csv_text。字段映射见 importer._COL_MAP
    （sku/品类/供应商/平台/地区/金额/日期/相似度/结果/缺陷 等，大小写与中文列名不敏感）。
    写接口：需登录会话（_require_session）。返回 {imported, skipped, errors}。
    """
    _require_session(request)
    source = _resolve_source(request)
    text = ""
    if csv_file is not None and csv_file.filename:
        raw = csv_file.file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，单文件上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB",
            )
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gbk", errors="replace")
    else:
        text = csv_text
    if not text.strip():
        raise HTTPException(status_code=400, detail="请提供 csv_file 或 csv_text")
    # 仅允许导入 real 源，避免污染演示种子库；导入行归属当前租户（匿名 → public）
    if source != "real":
        logger.warning("CSV 导入强制落到 real 源（忽略 source=%s），避免污染 demo 种子库", source)
        source = "real"
    tenant_id = _resolve_tenant(request) or "public"
    res = import_csv_text(text, source, tenant_id=tenant_id)
    return {"ok": True, "source": source, "tenant": tenant_id or "public", **res}


@app.post("/api/import_file")
def import_file_api(
    request: Request,
    file: UploadFile = File(...),
):
    """数据导入区·文件导入：把卖家真实数据集文件（.xlsx/.csv，类型同 Dataset/ 三大数据集）
    批量导入 real 源，并按 case_id 去重（同日跳过、异日保留最新删旧）。

    支持：Amazon 退货 xlsx / UCI Online Retail xlsx / TheLook 订单 csv（returned_at 非空）/
    RG 格式 csv（含 sku 等列）。写接口：需登录会话（_require_session）。返回
    {ok, detected, imported, updated, skipped, file_duplicates, errors}。
    """
    _require_session(request)
    # 文件导入强制落到 real 源，避免污染演示种子库
    source = "real"
    raw = file.file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"文件过大，单文件上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB"
        )
    fname = file.filename or "upload"
    try:
        if fname.lower().endswith(".csv"):
            text = raw.decode("utf-8-sig")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001
        text = raw.decode("latin-1", errors="replace")
    # xlsx 直接传 bytes；csv 传解码后的文本
    content = raw if fname.lower().endswith(".xlsx") else text
    tenant_id = _resolve_tenant(request) or "public"
    res = import_file(fname, content, source, tenant_id=tenant_id)
    return {"ok": res.get("ok", False), "source": source, "tenant": tenant_id or "public", **res}


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 便于容器化/公网部署；本地访问 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
