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
# Diagram 2: 系统架构图（简洁版 — 大画布、少文字、高呼吸感）
# ---------------------------------------------------------------------------
fig2, ax2 = plt.subplots(figsize=(14, 10))
ax2.set_xlim(-0.2, 1.2)
ax2.set_ylim(-0.2, 5.6)
ax2.axis("off")
fig2.patch.set_facecolor("#F8FAFC")

# 层定义：(x_center, y, width, height, title, subtitle, color)
# 层间距加大到 1.0（盒子高 0.55，间隙 ~0.45）
LH = 0.55          # 盒子高度
layers = [
    (0.50, 4.80, 0.80, LH, "前端层", "看板 / 取证上传 / 证据卷宗 / demo-real 切换", C_FRONT),
    (0.50, 3.80, 0.80, LH, "后端编排层", "FastAPI DAG · 并行取证 + 洞察聚合", C_BACK),
    (0.50, 2.80, 0.80, LH, "模型能力层", "阿里云百炼 Model Router · 7 能力 live/mock 韧性", C_MODEL),
    (0.50, 1.80, 0.80, LH, "洞察层（产品核心）", "聚类归因 · 预测预警 · 选品避坑 · 供应商品控", C_INSIGHT),
]

for x, y, w, h, title, sub, fc in layers:
    p = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.03,rounding_size=0.06",
        linewidth=0, facecolor=fc, edgecolor="none",
        zorder=3, alpha=0.92,
    )
    ax2.add_patch(p)
    # 标题（白色粗体）— 盒内偏上
    ax2.text(x, y + 0.10, title,
             fontsize=13.5, fontweight="bold", color="white",
             fontproperties=fp, ha="center", va="center", zorder=4)
    # 副标题（白色半透明小字）— 盒内偏下
    ax2.text(x, y - 0.12, sub,
             fontsize=9, color=(1, 1, 1, 0.85),
             fontproperties=fp, ha="center", va="center", zorder=4)

# 数据层：双库并排（加宽间距）
dh = 0.46
da_w = 0.34
gap = 0.10       # 两盒之间明确间隙
da_center_gap = da_w + gap   # 0.44
da_left = 0.50 - da_center_gap / 2   # 0.28
da_right = 0.50 + da_center_gap / 2   # 0.72
DA1 = (da_left, 0.80, da_w, dh, "demo 库", "cases.json\n(演示种子)", C_DATA)
DA2 = (da_right, 0.80, da_w, dh, "real 库", "cases_real.db\n(真实·隔离)", C_DATA)
for x, y, w, h, title, sub, fc in [DA1, DA2]:
    p = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.03,rounding_size=0.05",
        linewidth=1.2, facecolor=fc, edgecolor="#94A3B8",
        zorder=3, alpha=0.85,
    )
    ax2.add_patch(p)
    ax2.text(x, y + 0.08, title,
             fontsize=10.5, fontweight="bold", color="#1E293B",
             fontproperties=fp, ha="center", va="center", zorder=4)
    ax2.text(x, y - 0.09, sub,
             fontsize=8, color="#64748B",
             fontproperties=fp, ha="center", va="center", zorder=4)

# 连接箭头（简洁灰色）
arrow_style = dict(arrowstyle="-|>", mutation_scale=14, lw=2.0,
                   color="#94A3B8", zorder=2)
ly = [l[1] for l in layers]
# 垂直向下箭头：前端->后端->模型->洞察
for i in range(len(layers) - 1):
    ax2.add_patch(FancyArrowPatch(
        (0.50, ly[i] - layers[i][3]/2), (0.50, ly[i+1] + layers[i+1][3]/2),
        **arrow_style))
# 洞察 -> 双库（分叉箭头）
ax2.add_patch(FancyArrowPatch(
    (0.38, ly[-1] - layers[-1][3]/2), (DA1[0], DA1[1] + dh/2), **arrow_style))
ax2.add_patch(FancyArrowPatch(
    (0.62, ly[-1] - layers[-1][3]/2), (DA2[0], DA2[1] + dh/2), **arrow_style))

# 标注文字
ax2.text(0.50, 0.38, "双源物理隔离 · tenant 级 · 跨源不可见",
         fontsize=9, color="#64748B", fontproperties=fp, ha="center")
ax2.text(1.16, 3.80, "任一模型不可用\n则该步回退演示\n其余能力仍真实生效",
         fontsize=8, color=C_BACK, fontproperties=fp, ha="center",
         style="italic", linespacing=1.5,
         bbox=dict(boxstyle="round,pad=0.35", facecolor="#F5F3FF", edgecolor=C_BACK,
                   linewidth=0.8, alpha=0.9))

# 总标题（远高于最上层盒子）
ax2.text(0.50, 5.40,
         "ReturnGuard 系统架构",
         fontsize=17, fontweight="bold", color=INK,
         fontproperties=fp, ha="center")
ax2.text(0.50, 5.15,
         "阿里云百炼 Model Router 驱动 · 退货数据反哺选品洞察",
         fontsize=10.5, color="#64748B",
         fontproperties=fp, ha="center")

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
