# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""群体洞察路由：/api/insights、/api/export_pdf。

从原 main.py 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

import os
from urllib.parse import quote

from common import _check_rate_limit, _get_insights, get_client_ip
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pdf_report import default_filename, generate_insights_pdf
from schemas import InsightsResponse

router = APIRouter()

# PDF 导出限流（每客户端每分钟）：报告生成是 CPU 重的同步任务（reportlab 排版 + 中文字体），
# demo 源又允许匿名读，若不限流可被反复触发拖垮 single-worker 部署。
_EXPORT_PDF_LIMIT = int(os.environ.get("EXPORT_PDF_RATE_LIMIT", "20"))


@router.get("/api/insights", response_model=InsightsResponse)
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


@router.get("/api/export_pdf")
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
    按客户端 IP 限流（`EXPORT_PDF_RATE_LIMIT`，默认 20 次/分钟，置 0 关闭）：
    PDF 生成为 CPU 重的同步任务，且 demo 源允许匿名读，需防被反复触发。
    """
    if not _check_rate_limit(get_client_ip(request), scope="export_pdf", limit=_EXPORT_PDF_LIMIT):
        raise HTTPException(status_code=429, detail="报告导出过于频繁，请稍后再试")
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
