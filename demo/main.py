"""ReturnGuard 复赛 Demo 后端（FastAPI 入口）

本服务把「方案文档」的两大阶段暴露成 HTTP 接口：
    阶段A 个案举证  → POST /api/analyze   （上传退回图+本店主图，返回一单取证结果）
    阶段B 群体洞察  → GET  /api/insights  （聚合案件库，返回多维洞察看板，支持品类/平台下钻）
    数据沉淀        → GET  /api/cases     （查看已沉淀的案件库，便于调试）

前端（static/index.html）即「退货情报站」页面：上半部是洞察看板（阶段B 产品主体），
下半部折叠着单案举证入口（阶段A 数据采集管道）。
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 导入业务逻辑层（pipeline 负责取证+洞察，models_router 负责真实模型调用）
from pipeline import analyze_case, load_cases, save_case, build_insights
from db import init_db   # 数据持久层（SQLite / openGauss 双轨）

# ---- 路径配置 ----
BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")          # 上传图片临时目录
os.makedirs(UPLOAD_DIR, exist_ok=True)
INDEX = os.path.join(BASE, "static", "index.html")   # 前端页面

@asynccontextmanager
async def lifespan(app):
    """服务启动时初始化数据库（建表 + 首次从 cases.json 导入种子数据）。"""
    init_db()
    yield


app = FastAPI(title="ReturnGuard Demo", lifespan=lifespan)
# 把 static 目录挂成 /static，前端可加载其中的资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    """返回「退货情报站」前端页面。"""
    with open(INDEX, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/analyze")
async def analyze(
    returned_image: UploadFile = File(..., description="退回商品图"),
    product_image: UploadFile = File(..., description="本店主图/详情图"),
    listing_text: str = Form(""),
    sku: str = Form("SKU-未知"),
    amount: float = Form(0.0),
    mode: str = Form("mock"),
):
    """阶段A · 个案举证接口。

    流程：接收两张图 → 落盘到 uploads → 调用 pipeline.analyze_case 完成取证
          → 把结果沉淀进案件库（供阶段B洞察）→ 返回给前端展示。
    返回字段：similarity / same_item / defect_tags / consistency / dossier / voice_* / priority_score / mode
    """
    # 用随机前缀避免文件名冲突
    rid = uuid.uuid4().hex[:8]
    rp = os.path.join(UPLOAD_DIR, f"{rid}_ret_{returned_image.filename}")
    pp = os.path.join(UPLOAD_DIR, f"{rid}_prod_{product_image.filename}")
    with open(rp, "wb") as f:
        f.write(await returned_image.read())
    with open(pp, "wb") as f:
        f.write(await product_image.read())

    # 执行取证（功能①②③④⑤）
    result = analyze_case(rp, pp, listing_text, sku, amount, mode)
    result["case_id"] = rid

    # 数据沉淀：把这一单写入案件库，阶段B 洞察才有"米"下锅
    save_case({
        **result, "sku": sku, "amount": amount,
        "returned_image": os.path.basename(rp),
        "product_image": os.path.basename(pp),
    })
    return JSONResponse(result)


@app.get("/api/insights")
def insights(mode: str = "mock", category: str = "", platform: str = ""):
    """阶段B · 群体洞察接口（AI 市场洞察核心交付物）。

    参数：
        mode     mock（规则归因，可复现）/ live（LLM 归因，需 Key）
        category 按品类下钻（可选）
        platform 按平台下钻（可选）
    返回：KPI、品类热力、根因归因、供应商红黑榜、平台对比、异常预警、SKU明细、洞察报告、选品建议。
    """
    cases = load_cases()
    if category:
        cases = [c for c in cases if c.get("category") == category]
    if platform:
        cases = [c for c in cases if c.get("platform") == platform]
    return JSONResponse(build_insights(cases, mode))


@app.get("/api/cases")
def cases():
    """查看已沉淀的案件库（调试/演示用）。"""
    return JSONResponse(load_cases())


if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0 便于容器化/公网部署；本地访问 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
