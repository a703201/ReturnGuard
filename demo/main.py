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

import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from db import (  # 数据持久层（SQLite / openGauss 双源隔离）
    DEFAULT_SOURCE,
    VALID_SOURCES,
    delete_case,
    init_db,
    list_cases,
    load_cases,
    save_case,
)
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# 导入业务逻辑层（pipeline 负责取证+洞察，models_router 负责真实模型调用）
from pipeline import analyze_case, build_insights
from platforms import get_platform_spec, is_valid_platform, list_platforms
from schemas import AnalyzeResult, InsightsResponse, ManualCase

logger = logging.getLogger("returnguard.api")

# ---- 版本（单一来源：仓库根 VERSION 文件；前端顶栏与 /api/config 均从此读取）----
def _read_app_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "VERSION"), encoding="utf-8") as _vf:
            return _vf.read().strip() or "unknown"
    except FileNotFoundError:
        return "unknown"
APP_VERSION = _read_app_version()

# ---- 可观测性（P2-9）：结构化日志 + 基础指标 ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
_metrics = defaultdict(int)
_metrics["start_time"] = int(time.time())

# ---- 写接口限流（P2-8）：演示态默认开启；环境 ANALYZE_RATE_LIMIT=0 关闭 ----
_RATE_LIMIT = int(os.environ.get("ANALYZE_RATE_LIMIT", "60"))  # 每客户端每分钟上限
_rate_window: dict[str, list[float]] = {}
# 线程安全锁（P3-⑧）：uvicorn 默认线程池跑同步端点，_metrics / _rate_window 为进程内共享可变结构
_state_lock = threading.Lock()

# 演示态可选鉴权：设置 ANALYZE_API_KEY 后，/api/analyze 须带 X-API-Key 头或 ?key=
_API_KEY = os.environ.get("ANALYZE_API_KEY", "")

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

    说明：/uploads 当前为演示态静态托管；复赛若对外，应改为签名 URL + 短期过期，
    而非长期静态可读。此处先消除磁盘无限增长风险。
    """
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


def _check_rate_limit(client_ip: str) -> bool:
    """P2-8：固定窗口限流（每客户端每分钟 _RATE_LIMIT 次）。返回 True=放行。"""
    if _RATE_LIMIT <= 0:
        return True
    now = time.time()
    with _state_lock:
        hits = [t for t in _rate_window.get(client_ip, []) if now - t < 60]
        if len(hits) >= _RATE_LIMIT:
            _rate_window[client_ip] = hits
            return False
        hits.append(now)
        _rate_window[client_ip] = hits
    return True


def _resolve_source(request: Request) -> str:
    """从请求 query 参数解析数据来源（demo/real），非法或缺失一律回退 demo。"""
    src = request.query_params.get("source", DEFAULT_SOURCE)
    return src if src in VALID_SOURCES else DEFAULT_SOURCE


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
    _cleanup_old_uploads(max_age_hours=float(os.environ.get("UPLOAD_MAX_AGE_HOURS", "24")))
    yield


app = FastAPI(title="ReturnGuard Demo", lifespan=lifespan)
# 把 static 目录挂成 /static，前端可加载其中的资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
# 上传目录静态挂载：便于 live 模式下由 PUBLIC_IMAGE_BASE 指向本服务的 /uploads 提供图片
# （注意：live 仍需图片可被 Model Router 服务端公网回源，纯内网部署需配对象存储）
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.middleware("http")
async def observe_middleware(request: Request, call_next):
    """P2-9：请求耗时日志 + 基础指标计数（便于容器采集与排障）。"""
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
    logger.info("%s %s -> %d (%.1fms)", request.method, path, response.status_code, dur_ms)
    return response


@app.get("/", response_class=HTMLResponse)
def index():
    """返回「退货情报站」前端页面。"""
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    """健康检查探针（编排 healthcheck / 负载均衡用）。"""
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResult)
async def analyze(
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
    # P2-8 演示态可选鉴权：设置 ANALYZE_API_KEY 后必须携带
    if _API_KEY:
        provided = request.headers.get("X-API-Key", "") or request.query_params.get("key", "")
        if provided != _API_KEY:
            raise HTTPException(status_code=401, detail="需要有效的 API Key")
    # P2-8 限流：按客户端 IP 固定窗口
    client_ip = request.client.host if request.client else "unknown"
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

        # 执行取证（功能①②③④⑤）
        result = analyze_case(rp, pp, listing_text, sku, amount, mode)
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

        # P3-5 退回图用 URL 访问（/uploads/<文件名>），不再内联整图 base64 撑大响应
        result["returned_image_url"] = UPLOAD_URL_PREFIX + os.path.basename(rp)

        # 数据沉淀：取证结果 > 数据沉淀。save 失败只记日志，仍优先返回 result
        try:
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
            )
        except Exception as e:
            logger.exception("案件沉淀失败（不影响本次取证结果返回）: %s", e)
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
    """前端常量单一来源（P2-4）：返回同款一致性阈值、应用版本、可用数据源等。"""
    from constants import SAME_ITEM_THRESHOLD

    return {
        "same_item_threshold": SAME_ITEM_THRESHOLD,
        "version": APP_VERSION,
        "sources": list(VALID_SOURCES),
        "default_source": DEFAULT_SOURCE,
    }


@app.get("/metrics")
def metrics():
    """P2-9：基础运行指标（请求量 / 平均耗时 / 错误数 / 取证·洞察调用量）。"""
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


@app.get("/api/insights", response_model=InsightsResponse)
def insights(request: Request, mode: str = "mock", category: str = "", platform: str = ""):
    """阶段B · 群体洞察接口（AI 市场洞察核心交付物）。

    参数：
        source   demo（演示数据）/ real（实际数据），决定读取哪个数据库
        mode     mock（规则归因，可复现）/ live（LLM 归因，需 Key）
        category 按品类下钻（可选）
        platform 按平台下钻（可选）
    返回：KPI、品类热力、根因归因、供应商红黑榜、平台对比、异常预警、SKU明细、洞察报告、选品建议。
    """
    source = _resolve_source(request)
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
    cases = load_cases(source)
    if category:
        cases = [c for c in cases if c.get("category") == category]
    if platform:
        cases = [c for c in cases if c.get("platform") == platform]
    agg = build_insights(cases, mode, source)
    agg = dict(agg)  # 浅拷贝，避免就地修改 build_insights 的共享缓存对象
    agg["source"] = source  # 让前端知道当前看板基于哪个数据源
    return agg


@app.get("/api/cases")
def cases(request: Request, slim: bool = False):
    """查看指定 source 的案件库。

    - 默认返回全字段（调试/演示用，含 voice_audio_b64 等大字段）。
    - slim=1 时只返回录入列表所需关键字段（P3-①），用于数据录入页列表展示与删除，
      从源头避免整库大响应体（demo 库约 25MB 级）。
    """
    source = _resolve_source(request)
    return list_cases(source) if slim else load_cases(source)


@app.post("/api/cases")
def add_case(c: ManualCase, request: Request):
    """网页「数据录入」：手动添加一条实际退货案件到指定 source（默认 real 由前端开关控制）。

    不强制传图，填字段即可录入；落库后对应 source 的洞察看板实时刷新。
    """
    source = _resolve_source(request)
    data = c.model_dump()
    data["case_id"] = "RG-" + uuid.uuid4().hex[:8].upper()
    if not data.get("defect_tags"):
        data["defect_tags"] = ["无明显瑕疵"]
    save_case(source, data)
    return {"ok": True, "source": source, "case_id": data["case_id"]}


@app.delete("/api/cases/{case_id}")
def delete_case_api(case_id: str, request: Request):
    """删除指定 source 下的一条案件（实际数据管理用）。"""
    source = _resolve_source(request)
    n = delete_case(source, case_id)
    return {"ok": True, "source": source, "deleted": n}


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 便于容器化/公网部署；本地访问 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
