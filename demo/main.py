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

import base64
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager

from db import init_db  # 数据持久层（SQLite / openGauss 双轨）
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# 导入业务逻辑层（pipeline 负责取证+洞察，models_router 负责真实模型调用）
from pipeline import analyze_case, build_insights, load_cases, save_case
from platforms import get_platform_spec, is_valid_platform, list_platforms
from schemas import AnalyzeResult, InsightsResponse

logger = logging.getLogger("returnguard.api")

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


@asynccontextmanager
async def lifespan(app):
    """服务启动时初始化数据库（建表 + 首次从 cases.json 导入种子数据）。"""
    init_db()
    yield


app = FastAPI(title="ReturnGuard Demo", lifespan=lifespan)
# 把 static 目录挂成 /static，前端可加载其中的资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
# 上传目录静态挂载：便于 live 模式下由 PUBLIC_IMAGE_BASE 指向本服务的 /uploads 提供图片
# （注意：live 仍需图片可被 Model Router 服务端公网回源，纯内网部署需配对象存储）
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


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
    returned_image: UploadFile = File(..., description="退回商品图"),
    product_image: UploadFile = File(..., description="本店主图/详情图"),
    listing_text: str = Form(""),
    sku: str = Form("SKU-未知"),
    amount: float = Form(0.0),
    platform: str = Form(""),
    mode: str = Form("mock"),
):
    """阶段A · 个案举证接口。

    流程：接收两张图（校验+落盘）→ 调用 pipeline.analyze_case 完成取证
          → 把结果沉淀进案件库（供阶段B洞察）→ 返回给前端展示。
    返回字段见 schemas.AnalyzeResult；defect_boxes 为缺陷示意框（归一化坐标）。
    platform 为销售平台（可选），用于关联「平台适配举证包」的必备举证清单。
    """
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
    assert os.path.dirname(os.path.abspath(rp)) == UPLOAD_DIR, "上传路径越界"
    assert os.path.dirname(os.path.abspath(pp)) == UPLOAD_DIR, "上传路径越界"
    with open(rp, "wb") as f:
        f.write(ret_bytes)
    with open(pp, "wb") as f:
        f.write(prod_bytes)

    # 执行取证（功能①②③④⑤）
    result = analyze_case(rp, pp, listing_text, sku, amount, mode)
    result["case_id"] = rid
    result["platform"] = platform
    # 关联「平台适配举证包」：把该平台的必备举证材料随单返回，便于前端直接展示清单
    # （只列客观要求，不做裁决结论，守住「只取证不裁决」）
    if platform:
        spec = get_platform_spec(platform)
        result["platform_evidence"] = spec.get("required_evidence", []) if spec else []

    # 关键帧红框标注：把退回图原图 base64 回传前端，叠加缺陷示意框展示
    try:
        with open(rp, "rb") as f:
            result["returned_image_b64"] = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        logger.warning("退回图读取失败，红框预览不可用: %s", rp)
        result["returned_image_b64"] = ""

    # 数据沉淀：把这一单写入案件库，阶段B 洞察才有"米"下锅
    save_case(
        {
            **result,
            "sku": sku,
            "amount": amount,
            "platform": platform,
            "returned_image": os.path.basename(rp),
            "product_image": os.path.basename(pp),
        }
    )
    return result


@app.get("/api/platforms")
def platforms():
    """平台适配举证包（交付物 A 数据源）：返回各大平台退货/纠纷举证规则
    与 ReturnGuard 取证能力的映射。前端据此渲染「平台举证包」面板与单案清单。"""
    return {"platforms": list_platforms()}


@app.get("/api/insights", response_model=InsightsResponse)
def insights(mode: str = "mock", category: str = "", platform: str = ""):
    """阶段B · 群体洞察接口（AI 市场洞察核心交付物）。

    参数：
        mode     mock（规则归因，可复现）/ live（LLM 归因，需 Key）
        category 按品类下钻（可选）
        platform 按平台下钻（可选）
    返回：KPI、品类热力、根因归因、供应商红黑榜、平台对比、异常预警、SKU明细、洞察报告、选品建议。
    """
    if mode not in ("mock", "live"):
        raise HTTPException(status_code=400, detail="mode 仅支持 mock / live")
    cases = load_cases()
    if category:
        cases = [c for c in cases if c.get("category") == category]
    if platform:
        cases = [c for c in cases if c.get("platform") == platform]
    return build_insights(cases, mode)


@app.get("/api/cases")
def cases():
    """查看已沉淀的案件库（调试/演示用）。"""
    return load_cases()


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 便于容器化/公网部署；本地访问 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
