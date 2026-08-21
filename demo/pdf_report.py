"""ReturnGuard 洞察报告 PDF 生成（服务端 reportlab，CJK 字体，直接下载而非浏览器打印）。

设计要点：
- 调用方传入与 /api/insights 一致的聚合结果（dict），本模块只负责「渲染成 PDF」。
- 使用 CID 字体 STSong-Light，无需外部 TTF 即可正确显示中文。
- 采用 Platypus 流式布局，标题紧贴上边距，从根上消除之前「window.print 整体偏下」的问题。
- 返回 PDF 字节流，由 FastAPI 端点以 attachment 形式下发，浏览器直接下载。
"""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape as _xesc

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ---- 中文字体（CID 内置中文，无需外部字体文件）----
try:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT = "STSong-Light"
except Exception:  # pragma: no cover - 兜底，极少触发
    _FONT = "Helvetica"

# ---- 主题色（浅底报告，适配打印）----
C_ACCENT = colors.HexColor("#0e7490")
C_HEAD = colors.HexColor("#0f172a")
C_SUB = colors.HexColor("#64748b")
C_LINE = colors.HexColor("#cbd5e1")
C_KPI_BG = colors.HexColor("#f1f5f9")
C_BAND = colors.HexColor("#f8fafc")
C_BAD = colors.HexColor("#b91c1c")

# ---- 页面边距（上边距小，标题贴近顶部，解决“整体偏下”）----
MARGIN_LR = 18 * mm
MARGIN_TOP = 15 * mm
MARGIN_BOTTOM = 15 * mm
AW = A4[0] - 2 * MARGIN_LR  # 可用宽度


def _esc(t) -> str:
    return _xesc(str(t if t is not None else ""))


def _styles():
    return {
        "title": ParagraphStyle(
            "title", fontName=_FONT, fontSize=20, leading=24, textColor=C_HEAD, spaceAfter=2
        ),
        "meta": ParagraphStyle(
            "meta", fontName=_FONT, fontSize=9, leading=13, textColor=C_SUB, spaceAfter=6
        ),
        "h": ParagraphStyle(
            "h",
            fontName=_FONT,
            fontSize=13,
            leading=17,
            textColor=C_ACCENT,
            spaceBefore=12,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=_FONT,
            fontSize=10,
            leading=15,
            textColor=C_HEAD,
            spaceAfter=4,
            alignment=TA_LEFT,
        ),
        "li": ParagraphStyle(
            "li",
            fontName=_FONT,
            fontSize=10,
            leading=15,
            textColor=C_HEAD,
            leftIndent=12,
            spaceAfter=2,
        ),
        "cell": ParagraphStyle(
            "cell", fontName=_FONT, fontSize=9, leading=12, textColor=C_HEAD, alignment=TA_LEFT
        ),
        "cellc": ParagraphStyle(
            "cellc", fontName=_FONT, fontSize=9, leading=12, textColor=C_HEAD, alignment=TA_CENTER
        ),
        "th": ParagraphStyle(
            "th",
            fontName=_FONT,
            fontSize=9,
            leading=12,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "kpi": ParagraphStyle(
            "kpi", fontName=_FONT, fontSize=10, leading=18, textColor=C_HEAD, alignment=TA_CENTER
        ),
        "note": ParagraphStyle(
            "note", fontName=_FONT, fontSize=9, leading=13, textColor=C_SUB, alignment=TA_LEFT
        ),
    }


def _fmt_int(x):
    try:
        return f"{int(round(float(x or 0))):,}"
    except Exception:
        return "0"


def _fmt_money(x, dec=0):
    try:
        return f"¥{float(x or 0):,.{dec}f}"
    except Exception:
        return "¥0"


def _fmt_pct(frac):
    try:
        return f"{round(float(frac or 0) * 100)}%"
    except Exception:
        return "0%"


def _wr_color(frac):
    try:
        w = float(frac or 0)
    except Exception:
        w = 0
    if w >= 0.5:
        return colors.HexColor("#15803d")
    if w >= 0.3:
        return colors.HexColor("#b45309")
    return C_BAD


def _rule():
    t = Table([[""]], colWidths=[AW], rowHeights=[2])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_ACCENT),
                ("LINEBELOW", (0, 0), (-1, -1), 0, C_ACCENT),
            ]
        )
    )
    return t


def _table(headers, data_rows, col_widths, aligns=None, zebra=True):
    s = _styles()
    head = [Paragraph(_esc(h), s["th"]) for h in headers]
    body = []
    for r in data_rows:
        cells = []
        for i, c in enumerate(r):
            if isinstance(c, Paragraph):
                cells.append(c)
            else:
                st = s["cell"] if (aligns and aligns[i] == TA_LEFT) else s["cellc"]
                cells.append(Paragraph(_esc(c), st))
        body.append(cells)
    table = Table([head] + body, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.4, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BAND]))
    table.setStyle(TableStyle(style))
    return table


def generate_insights_pdf(
    agg: dict,
    *,
    mode: str = "",
    source: str = "demo",
    category: str = "",
    platform: str = "",
    region: str = "",
    season: str = "",
) -> bytes:
    """把洞察聚合结果渲染成 A4 PDF，返回字节流。"""
    agg = agg or {}
    s = _styles()
    story = []

    scope = (category + " / " if category else "") + (platform or "全平台")
    src_label = "实际数据" if source == "real" else "演示数据"
    mode_label = "AI 实算 (live)" if mode == "live" else "规则归因 (mock)"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- 页眉：标题（紧贴顶部，避免偏下）----
    story.append(Paragraph("ReturnGuard 选品-品控洞察报告", s["title"]))
    story.append(
        Paragraph(
            f"生成时间：{now} ｜ 数据源：{src_label} ｜ 归因模式：{mode_label} ｜ 筛选：{_esc(scope)}",
            s["meta"],
        )
    )
    story.append(_rule())

    total_cases = int(agg.get("total_cases", 0) or 0)
    if total_cases == 0:
        story.append(Spacer(1, 8))
        story.append(Paragraph("当前筛选条件下暂无数据，请调整筛选或录入数据后重试。", s["note"]))
        return _build(story)

    # ---- KPI（3 列 × 2 行）----
    kpis = [
        ("已分析退货", f"{_fmt_int(total_cases)} 笔"),
        ("维权胜诉率", _fmt_pct(agg.get("win_rate", 0))),
        ("累计退款", _fmt_money(agg.get("total_refund", 0))),
        ("物流成本(估算)", _fmt_money(agg.get("logistics_cost", 0))),
        ("退货总成本", _fmt_money(agg.get("total_return_cost", 0))),
        ("货不对板嫌疑率", _fmt_pct(agg.get("avg_dispute_rate", 0))),
    ]
    cw3 = AW / 3.0
    kpi_rows = []
    for i in range(0, 6, 3):
        row = []
        for j in range(3):
            lab, val = kpis[i + j]
            row.append(
                Paragraph(
                    f'<font size="15">{_esc(val)}</font><br/>'
                    f'<font size="8.5" color="#64748b">{_esc(lab)}</font>',
                    s["kpi"],
                )
            )
        kpi_rows.append(row)
    kpi_tbl = Table(kpi_rows, colWidths=[cw3, cw3, cw3])
    kpi_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_KPI_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, C_LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(Spacer(1, 8))
    story.append(kpi_tbl)

    # ---- 根因分析 ----
    story.append(Paragraph("根因分析", s["h"]))
    story.append(Paragraph(_esc(agg.get("root_cause") or "暂无足够数据"), s["body"]))

    # ---- 洞察报告（可选）----
    if agg.get("report"):
        story.append(Paragraph("洞察报告", s["h"]))
        story.append(Paragraph(_esc(agg["report"]), s["body"]))

    # ---- 选品 / 品控建议 ----
    story.append(Paragraph("选品 / 品控建议", s["h"]))
    recs = agg.get("recommendations") or []
    if recs:
        for i, r in enumerate(recs):
            story.append(Paragraph(f"{i + 1}. {_esc(r)}", s["li"]))
    else:
        story.append(Paragraph("暂无建议。", s["note"]))

    # ---- 供应商黑名单（⑮）----
    blacks = agg.get("supplier_blacklist") or []
    if blacks:
        story.append(Paragraph("供应商黑名单（质量分 &lt; 50，建议更换）", s["h"]))
        rows = []
        for b in blacks:
            rows.append(
                [
                    Paragraph(_esc(b.get("supplier", "")), s["cell"]),
                    Paragraph(_esc(b.get("name", "")), s["cell"]),
                    Paragraph(_esc(b.get("quality_score", "")), s["cellc"]),
                    Paragraph(_esc(b.get("level", "")), s["cellc"]),
                    Paragraph(_esc(b.get("reason", "")), s["cell"]),
                ]
            )
        story.append(
            _table(
                ["供应商", "名称", "质量分", "等级", "说明"],
                rows,
                [AW * 0.15, AW * 0.18, AW * 0.1, AW * 0.1, AW * 0.47],
                aligns=[TA_LEFT, TA_LEFT, TA_CENTER, TA_CENTER, TA_LEFT],
            )
        )

    # ---- 异常 SKU 预警 ----
    alerts = agg.get("anomaly_alerts") or []
    if alerts:
        story.append(Paragraph("异常 SKU 预警（近 30 天集中爆发）", s["h"]))
        rows = []
        for a in alerts[:8]:
            rows.append(
                [
                    Paragraph(_esc(a.get("sku", "")), s["cell"]),
                    Paragraph(_esc(a.get("category", "")), s["cell"]),
                    Paragraph(_esc(a.get("reason", "")), s["cell"]),
                ]
            )
        story.append(
            _table(
                ["SKU", "品类", "预警说明"],
                rows,
                [AW * 0.2, AW * 0.18, AW * 0.62],
                aligns=[TA_LEFT, TA_LEFT, TA_LEFT],
            )
        )

    # ---- 维度扩展：地区分布（⑬）----
    rv = agg.get("region_view") or []
    if rv:
        story.append(Paragraph("退货地区分布", s["h"]))
        rows = []
        for x in rv:
            rows.append(
                [
                    Paragraph(_esc(x.get("region", "")), s["cell"]),
                    Paragraph(_fmt_int(x.get("cases", 0)), s["cellc"]),
                    Paragraph(_fmt_money(x.get("refund", 0)), s["cellc"]),
                    Paragraph(
                        _fmt_pct(x.get("win_rate", 0)),
                        ParagraphStyle(
                            "wc", parent=s["cellc"], textColor=_wr_color(x.get("win_rate", 0))
                        ),
                    ),
                ]
            )
        story.append(
            _table(
                ["地区", "纠纷量", "退款", "胜诉率"],
                rows,
                [AW * 0.28, AW * 0.24, AW * 0.24, AW * 0.24],
                aligns=[TA_LEFT, TA_CENTER, TA_CENTER, TA_CENTER],
            )
        )

    # ---- 维度扩展：季节趋势（⑭）----
    sv = agg.get("season_view") or []
    if sv:
        story.append(Paragraph("退货季节趋势", s["h"]))
        rows = []
        for x in sv:
            rows.append(
                [
                    Paragraph(_esc(x.get("season", "")), s["cell"]),
                    Paragraph(_fmt_int(x.get("cases", 0)), s["cellc"]),
                    Paragraph(_fmt_money(x.get("refund", 0)), s["cellc"]),
                    Paragraph(
                        _fmt_pct(x.get("win_rate", 0)),
                        ParagraphStyle(
                            "wc2", parent=s["cellc"], textColor=_wr_color(x.get("win_rate", 0))
                        ),
                    ),
                ]
            )
        story.append(
            _table(
                ["季节", "纠纷量", "退款", "胜诉率"],
                rows,
                [AW * 0.28, AW * 0.24, AW * 0.24, AW * 0.24],
                aligns=[TA_LEFT, TA_CENTER, TA_CENTER, TA_CENTER],
            )
        )

    return _build(story)


def _build(story) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_LR,
        rightMargin=MARGIN_LR,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="ReturnGuard 选品-品控洞察报告",
        author="ReturnGuard",
    )

    def _decorate(canvas, d):
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(C_SUB)
        canvas.drawString(
            MARGIN_LR,
            8 * mm,
            "ReturnGuard V1.0 · 本报告仅基于已沉淀退货数据的客观统计，不构成对平台裁决的替代",
        )
        canvas.drawRightString(A4[0] - MARGIN_LR, 8 * mm, f"第 {d.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


def default_filename() -> str:
    return f"ReturnGuard洞察报告_{datetime.now():%Y%m%d_%H%M}.pdf"
