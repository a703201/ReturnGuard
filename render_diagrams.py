"""Render ReturnGuard diagrams (flow + architecture) to PNG and a combined PDF."""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

FONT_PATH = r"C:/Windows/Fonts/simhei.ttf"
fp = FontProperties(fname=FONT_PATH)
plt.rcParams["font.family"] = fp.get_name()
plt.rcParams["axes.unicode_minus"] = False

OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUTDIR, exist_ok=True)

# palette
C_FORE = "#2E5BFF"  # 个案举证 (blue)
C_STORE = "#8A94A6"  # 沉淀 (gray)
C_INSIGHT = "#1FA971"  # 洞察 (green)
C_BACK = "#7C3AED"  # 后端/编排 (purple)
C_FRONT = "#F59E0B"  # 前端 (amber)
C_MODEL = "#0EA5E9"  # 模型层 (sky)
C_DATA = "#64748B"  # 数据层 (slate)
INK = "#1F2937"


def box(ax, x, y, w, h, text, fc, ec=None):
    ec = ec or fc
    p = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.04,rounding_size=0.08",
        linewidth=1.6,
        edgecolor=ec,
        facecolor=fc,
        zorder=3,
    )
    ax.add_patch(p)
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=11,
        color="white",
        fontproperties=fp,
        zorder=4,
        wrap=True,
    )
    return p


def arrow(ax, x1, y1, x2, y2, style="-|>", color="#374151", ls="-", lw=2.0):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle=style,
            mutation_scale=16,
            linewidth=lw,
            color=color,
            linestyle=ls,
            zorder=2,
        )
    )


# ---------------------------------------------------------------------------
# Diagram 1: 双闭环取证工作流
# ---------------------------------------------------------------------------
fig1, ax1 = plt.subplots(figsize=(12, 6.2))
ax1.set_xlim(-0.6, 4.6)
ax1.set_ylim(-3.4, 0.7)
ax1.axis("off")

nodes = {
    "A": (0, 0, "① 上传与预处理"),
    "B": (1, 0, "② 并行取证\n图向量+VL+OCR"),
    "C": (2, 0, "③ 一致性核验"),
    "D": (3, 0, "④ 卷宗+母语语音"),
    "E": (4, 0, "⑤ 优先级排序"),
    "F": (4, -1.3, "案件结构化沉淀"),
    "G": (2, -2.7, "⑥ 群体洞察层\n聚类归因+选品建议"),
}
w, h = 1.15, 0.78
for k, (x, y, t) in nodes.items():
    if k in ("A", "B", "C", "D", "E"):
        box(ax1, x, y, w, h, t, C_FORE)
    elif k == "F":
        box(ax1, x, y, w, h, t, C_STORE)
    else:
        box(ax1, x, y, w + 0.2, h, t, C_INSIGHT)

# sequential arrows (top row)
for s, e in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]:
    x1, y1, _ = nodes[s]
    x2, y2, _ = nodes[e]
    arrow(ax1, x1 + w / 2, y1, x2 - w / 2, y2)
# E -> F
arrow(ax1, nodes["E"][0], nodes["E"][1] - h / 2, nodes["F"][0], nodes["F"][1] + h / 2)
# F -> G
arrow(
    ax1, nodes["F"][0] - w / 2, nodes["F"][1], nodes["G"][0] + (w + 0.2) / 2, nodes["G"][1] + h / 2
)
# G -.-> A (feedback, dashed)
ax1.add_patch(
    FancyArrowPatch(
        (nodes["G"][0] - (w + 0.2) / 2, nodes["G"][1] + h / 2),
        (nodes["A"][0], nodes["A"][1] - h / 2),
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=2.0,
        color=C_INSIGHT,
        linestyle=(0, (5, 4)),
        zorder=2,
    )
)
ax1.text(
    nodes["G"][0] - 1.6,
    nodes["G"][1] + 0.55,
    "反哺选品/品控（闭环）",
    fontsize=9.5,
    color=C_INSIGHT,
    fontproperties=fp,
    ha="center",
)

ax1.text(
    2.0,
    0.45,
    "阶段 A · 个案举证（实时，单笔纠纷取证）",
    fontsize=12.5,
    color=C_FORE,
    fontproperties=fp,
    ha="center",
    fontweight="bold",
)
ax1.text(
    2.0,
    -3.25,
    "阶段 B · 群体洞察（异步批处理，沉淀数据反哺选品）",
    fontsize=12.5,
    color=C_INSIGHT,
    fontproperties=fp,
    ha="center",
    fontweight="bold",
)

flow_png = os.path.join(OUTDIR, "flow.png")
fig1.savefig(flow_png, dpi=160, bbox_inches="tight", facecolor="white")
plt.close(fig1)

# ---------------------------------------------------------------------------
# Diagram 2: 系统架构图
# ---------------------------------------------------------------------------
fig2, ax2 = plt.subplots(figsize=(11, 7.2))
ax2.set_xlim(-0.2, 1.2)
ax2.set_ylim(-0.3, 4.3)
ax2.axis("off")

# layer boxes (centered x=0.5)
W = 0.92
FE = (0.5, 3.7, "前端层\n上传 / 卷宗 / 洞察看板", C_FRONT)
BE = (0.5, 2.9, "后端编排层 · FastAPI 工作流（DAG 编排取证+洞察）", C_BACK)
IN = (0.27, 1.9, "洞察层\n聚类归因 / 选品建议", C_INSIGHT)
MO = (0.73, 1.9, "模型能力层 · Model Router\n图向量/VL/OCR/LLM/Rerank/TTS/推理", C_MODEL)
DA = (0.5, 0.8, "数据层 · 对象存储 + 案例库 + 阈值样本", C_DATA)
hh = 0.62
box(ax2, FE[0], FE[1], W, hh, FE[2], FE[3])
box(ax2, BE[0], BE[1], W, hh + 0.05, BE[2], BE[3])
box(ax2, IN[0], IN[1], 0.46, hh, IN[2], IN[3])
box(ax2, MO[0], MO[1], 0.46, hh, MO[2], MO[3])
box(ax2, DA[0], DA[1], W, hh, DA[2], DA[3])

# arrows
arrow(ax2, FE[0], FE[1] - hh / 2, BE[0], BE[1] + (hh + 0.05) / 2)
arrow(ax2, BE[0] - 0.20, BE[1] - (hh + 0.05) / 2, IN[0], IN[1] + hh / 2)
arrow(ax2, BE[0] + 0.20, BE[1] - (hh + 0.05) / 2, MO[0], MO[1] + hh / 2)
# BE <-> D (double arrow)
ax2.add_patch(
    FancyArrowPatch(
        (BE[0], BE[1] - (hh + 0.05) / 2),
        (DA[0], DA[1] + hh / 2),
        arrowstyle="<->",
        mutation_scale=16,
        linewidth=2.0,
        color=C_DATA,
        zorder=2,
    )
)

ax2.text(
    0.5,
    4.05,
    "ReturnGuard 系统架构（阿里云百炼 · Model Router 驱动）",
    fontsize=13,
    color=INK,
    fontproperties=fp,
    ha="center",
    fontweight="bold",
)

arch_png = os.path.join(OUTDIR, "arch.png")
fig2.savefig(arch_png, dpi=160, bbox_inches="tight", facecolor="white")
plt.close(fig2)

print("saved:", flow_png, arch_png)

# ---------------------------------------------------------------------------
# Combined PDF (2 panels) for easy upload
# ---------------------------------------------------------------------------
pdf_path = os.path.join(OUTDIR, "ReturnGuard_图表.pdf")
with PdfPages(pdf_path) as pdf:
    fig = plt.figure(figsize=(11, 14))
    axf = fig.add_subplot(2, 1, 1)
    axf.imshow(plt.imread(flow_png))
    axf.axis("off")
    axf.set_title("图1 · 双闭环取证工作流", fontsize=13, fontproperties=fp, color=INK)
    axa = fig.add_subplot(2, 1, 2)
    axa.imshow(plt.imread(arch_png))
    axa.axis("off")
    axa.set_title("图2 · 系统架构图", fontsize=13, fontproperties=fp, color=INK)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
print("saved:", pdf_path)
