"""前端装配路由：页面 / 签名文件 / 配置 / 指标 / 平台举证包。

从原 main.py 的 `/`、`/api/file/{sig}`、`/api/img/{key}`、`/health`、`/api/config`、
`/metrics`、`/api/platforms` 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from common import (
    APP_VERSION,
    INDEX,
    UPLOAD_DIR,
    _NONCE_PLACEHOLDER,
    _metrics,
    _state_lock,
    _require_admin,
    _safe_name,
    auth,
    backend_name,
    is_public_ready,
)
from db import DEFAULT_SOURCE, VALID_SOURCES
from calibration import get_active_threshold
from platforms import list_platforms

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
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


@router.get("/api/file/{sig}")
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


@router.get("/api/img/{key}")
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


@router.get("/health")
def health():
    """健康检查探针（编排 healthcheck / 负载均衡用）。"""
    return {"status": "ok"}


@router.get("/api/config")
def api_config():
    """前端常量单一来源（P2-4）：返回同款一致性阈值、应用版本、可用数据源、图床状态等。"""
    from constants import SUPPLIERS
    from models_router import MODEL_ROUTER_PROFILE

    return {
        # 阈值走标定后的运行期值，而非硬编码常量（P1-阈值过期）：前端显示的判定线与判定逻辑一致。
        "same_item_threshold": get_active_threshold(),
        "version": APP_VERSION,
        "sources": list(VALID_SOURCES),
        "default_source": DEFAULT_SOURCE,
        "image_bed": backend_name(),
        "image_bed_public": is_public_ready(),
        # 供应商花名册（P1-15）：唯一事实来源在 constants.SUPPLIERS，前端据此渲染下拉/下钻，
        # 不再内嵌硬编码副本（消除与 convert_datasets.py 双份漂移）。
        "suppliers": SUPPLIERS,
        # 模型网关 profile：tokenplan=Token Plan 测试网关 / official=赛事指定 Model Router，
        # 复赛提交时切到 official 即演示用赛事指定端点（详见 demo/.env.example）。
        # 注意：不再回传内部网关地址 model_router_endpoint（P2-信息泄露），前端无需该值。
        "model_router_profile": MODEL_ROUTER_PROFILE,
    }


@router.get("/metrics")
def metrics(request: Request):
    """P2-9：基础运行指标（请求量 / 平均耗时 / 错误数 / 取证·洞察调用量）。

    管理端点：需管理员密钥（ADMIN_API_KEY）或登录会话（_require_admin），
    避免匿名暴露内部运行指标（P2 信息泄露面收敛）。"""
    _require_admin(request)
    uptime = int(time.time()) - int(_metrics["start_time"])
    avg = (_metrics["latency_ms_sum"] / _metrics["requests"]) if _metrics["requests"] else 0
    # P1-6：模型网关侧指标（调用量 / 错误 / 时延 / token）并入同一管理端点
    try:
        from models_router import get_model_metrics

        model_metrics = get_model_metrics()
    except Exception:  # noqa: BLE001
        model_metrics = {}
    return {
        "uptime_seconds": uptime,
        "requests": _metrics["requests"],
        "avg_latency_ms": round(avg, 2),
        "errors_5xx": _metrics["errors"],
        "analyze_count": _metrics["analyze_count"],
        "insights_count": _metrics["insights_count"],
        "model_gateway": model_metrics,
    }


@router.get("/api/platforms")
def platforms():
    """平台适配举证包（交付物 A 数据源）：返回各大平台退货/纠纷举证规则
    与 ReturnGuard 取证能力的映射。前端据此渲染「平台举证包」面板与单案清单。"""
    return {"platforms": list_platforms()}
