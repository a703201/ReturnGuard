"""ReturnGuard · 平台适配举证包文档生成器

从 platforms.EVIDENCE_SPECS 单一来源生成两份「交付物 A」：
    - ../docs/platform_evidence.html   可渲染/打印的对照表 + 举证模板（评委直接看）
    - ../docs/PLATFORM_EVIDENCE.md    同源 Markdown（便于纳入仓库/README 引用）

与 platforms.py 同源，改规则只改一处，文档随之更新，杜绝文档与代码漂移。
"""

from __future__ import annotations

import os

from platforms import ATTRIBUTES, CAPABILITY_KEYS, PLATFORM_KEYS, list_platforms

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(ROOT), "docs")
os.makedirs(OUT_DIR, exist_ok=True)

SCALAR_ATTRS = [
    k
    for k, _ in ATTRIBUTES
    if k
    not in (
        "required_evidence",
        "common_loss_reasons",
        "special_clauses",
    )
]


def _attr_label(key: str) -> str:
    return dict(ATTRIBUTES).get(key, key)


def _li(items) -> str:
    return "\n".join(f"          <li>{x}</li>" for x in items)


# ----------------------------- HTML -----------------------------
def build_html(specs: list[dict]) -> str:
    scalar_rows = ""
    for k in SCALAR_ATTRS:
        cells = "".join(f"<td>{s.get(k, '-')}</td>" for s in specs)
        scalar_rows += f"        <tr><th>{_attr_label(k)}</th>{cells}</tr>\n"

    tmpl = ""
    for s in specs:
        tmpl += f"""
      <div class="plat">
        <h3>{s["label"]}</h3>
        <div class="kv"><span>退货窗口</span><b>{s["return_window"]}</b></div>
        <div class="kv"><span>卖家响应时限</span><b>{s["response_window"]}</b></div>
        <div class="kv"><span>运费承担</span><b>{s["shipping_payer"]}</b></div>
        <div class="kv"><span>举证责任偏向</span><b>{s["burden_bias"]}</b></div>
        <h4>必备举证材料（清单）</h4>
        <ul>{_li(s["required_evidence"])}</ul>
        <h4>常见失分 / 败诉原因</h4>
        <ul class="bad">{_li(s["common_loss_reasons"])}</ul>
        <h4>平台特殊条款</h4>
        <ul class="dim">{_li(s["special_clauses"])}</ul>
      </div>"""

    cap_rows = ""
    for cap in CAPABILITY_KEYS:
        cells = "".join(f"<td>{s['capability_map'].get(cap, '-')}</td>" for s in specs)
        cap_rows += f"        <tr><th>{cap}</th>{cells}</tr>\n"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ReturnGuard · 平台适配举证包（交付物 A）</title>
<style>
  :root{{--bg:#f7f8fa;--card:#fff;--line:#e3e8ef;--txt:#1f2937;--mut:#64748b;--acc:#0b6bcb;--bad:#c0392b;--dim:#475569}}
  *{{box-sizing:border-box;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
  body{{margin:0;background:var(--bg);color:var(--txt);padding:32px 18px;line-height:1.6}}
  .wrap{{max-width:1080px;margin:0 auto}}
  h1{{font-size:26px;margin:0 0 6px}}
  .lead{{color:var(--mut);margin:0 0 22px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
  h2{{font-size:18px;margin:0 0 12px;border-left:4px solid var(--acc);padding-left:10px}}
  h3{{font-size:16px;margin:18px 0 10px;color:var(--acc)}}
  h4{{font-size:13px;margin:14px 0 6px;color:var(--dim);text-transform:none}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{border:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}}
  th{{background:#f1f5f9;font-weight:600;width:140px}}
  ul{{margin:6px 0;padding-left:20px}}
  li{{margin:3px 0}}
  ul.bad li{{color:var(--bad)}}
  ul.dim li{{color:var(--dim);font-size:12.5px}}
  .kv{{display:flex;gap:10px;font-size:13px;padding:4px 0;border-bottom:1px dashed var(--line)}}
  .kv span{{width:120px;flex:none;color:var(--mut)}}
  .kv b{{font-weight:600}}
  .plat{{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}}
  .note{{color:var(--mut);font-size:12px;margin-top:8px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  @media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">
  <h1>ReturnGuard · 平台适配举证包</h1>
  <p class="lead">复赛交付物 A ｜ 把 ReturnGuard 的「只取证不裁决」能力对齐到各平台实际纠纷规则，
  让商家按平台拿到"该交什么证据"的清单。规则依据各平台 2025–2026 公开退货/争议政策整理。</p>

  <div class="card">
    <h2>① 核心规则对照表</h2>
    <table>
{scalar_rows}    </table>
    <p class="note">说明：以上为各平台客观政策事实，ReturnGuard 据此提示举证重点，不下"赢/输"裁决结论。</p>
  </div>

  <div class="card">
    <h2>② 各平台举证模板（必备材料 / 失分点 / 特殊条款）</h2>
    <div class="grid">{tmpl}
    </div>
  </div>

  <div class="card">
    <h2>③ ReturnGuard 能力 ↔ 平台举证 映射总览</h2>
    <table>
{cap_rows}    </table>
    <p class="note">每项能力均为客观取证工具，用于支撑对应举证环节；是否采信由平台仲裁决定。</p>
  </div>

  <div class="card">
    <h2>④ 怎么用这份举证包</h2>
    <ul>
      <li>在 ReturnGuard 单案举证时选择<b>销售平台</b>，系统自动附带该平台的「必备举证材料」清单。</li>
      <li>看板内置「平台适配举证包」面板，可随时查阅四大平台规则与 ReturnGuard 能力映射。</li>
      <li>证据沉淀进案件库后，洞察看板按<b>平台维度</b>拆分胜诉率，定位"哪个平台最难赢、该换谁供货"。</li>
      <li>覆盖平台：{", ".join(PLATFORM_KEYS)}（eBay / TikTok Shop / Shopee 等可后续扩展）。</li>
    </ul>
  </div>
</div>
</body>
</html>"""


# ----------------------------- Markdown -----------------------------
def build_md(specs: list[dict]) -> str:
    lines = [
        "# ReturnGuard · 平台适配举证包（交付物 A）",
        "",
        "> 复赛交付物 A。把 ReturnGuard 的「只取证不裁决」能力对齐到各平台实际纠纷规则，"
        "让商家按平台拿到「该交什么证据」的清单。规则依据各平台 2025–2026 公开退货/争议政策整理。",
        "",
        "## ① 核心规则对照表",
        "",
        "| 维度 | " + " | ".join(s["label"] for s in specs) + " |",
        "| --- | " + " | ".join(["---"] * len(specs)) + " |",
    ]
    for k in SCALAR_ATTRS:
        row = "| " + _attr_label(k) + " | " + " | ".join(s.get(k, "-") for s in specs) + " |"
        lines.append(row)
    lines.append("")

    for s in specs:
        lines += [
            f"## ② {s['label']} 举证模板",
            "",
            f"- **退货窗口**：{s['return_window']}",
            f"- **卖家响应时限**：{s['response_window']}",
            f"- **运费承担**：{s['shipping_payer']}",
            f"- **举证责任偏向**：{s['burden_bias']}",
            "- **必备举证材料**：",
        ]
        lines += [f"  - {x}" for x in s["required_evidence"]]
        lines += ["- **常见失分 / 败诉原因**："]
        lines += [f"  - {x}" for x in s["common_loss_reasons"]]
        lines += ["- **平台特殊条款**："]
        lines += [f"  - {x}" for x in s["special_clauses"]]
        lines.append("")

    lines += ["## ③ ReturnGuard 能力 ↔ 平台举证 映射总览", ""]
    lines.append("| 能力 | " + " | ".join(s["label"] for s in specs) + " |")
    lines.append("| --- | " + " | ".join(["---"] * len(specs)) + " |")
    for cap in CAPABILITY_KEYS:
        row = (
            "| " + cap + " | " + " | ".join(s["capability_map"].get(cap, "-") for s in specs) + " |"
        )
        lines.append(row)
    lines.append("")

    lines += [
        "## ④ 怎么用这份举证包",
        "",
        "- 单案举证时选择**销售平台**，系统自动附带该平台「必备举证材料」清单。",
        "- 看板内置「平台适配举证包」面板，随时查阅四大平台规则与能力映射。",
        "- 证据沉淀后，洞察看板按**平台维度**拆分胜诉率，定位「哪个平台最难赢、该换谁供货」。",
        f"- 覆盖平台：{', '.join(PLATFORM_KEYS)}（eBay / TikTok Shop / Shopee 等可后续扩展）。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    specs = list_platforms()
    html_path = os.path.join(OUT_DIR, "platform_evidence.html")
    md_path = os.path.join(OUT_DIR, "PLATFORM_EVIDENCE.md")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(specs))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_md(specs))
    print(f"已生成 {html_path}\n已生成 {md_path}\n平台数: {len(specs)}")


if __name__ == "__main__":
    main()
