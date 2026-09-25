# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""A/B 对照实验：同一批洞察任务在「提示词变体 A / B」下的可量化差异。

为什么需要它
------------
审查报告 §5-1 指出：ROI 已接入真实看板数据，但仍缺 **A/B 与因果证据**。做真 A/B 需要真实业务
流量（非纯代码可得），所以这里先把**可复现的实验台架**建起来：同一批案件、同一模型、同一
聚合输入，只改 prompt 变体，量化对比：

  - json_ok      ：LLM 返回能否解析成合法 JSON（结构化可用性）
  - mismatch     ：「幻觉对账」命中数 —— 输出文本里的数字与真实聚合值不符的次数（越低越好）
  - latency_s    ：端到端耗时
  - fields       ：root_cause / sku_insights / recommendations / sourcing_advice 非空率

跑法
----
    # 真实调用（会产生 token 费用，默认 live）
    python demo/ab_experiment.py --runs 3 --out docs/ab_result.json

    # 干跑：不调模型，用本地桩验证台架（CI / 无 Key 环境）
    python demo/ab_experiment.py --mode mock --runs 5

输出
----
  控制台 Markdown 表 + 可选 JSON（--out）。

注意：本脚本量化的是**提示词变体差异**，不是产品对业务指标的因果提升；结论引用时须如此表述。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pipeline  # noqa: E402
import prompts  # noqa: E402

# ---------------------------------------------------------------------------
# 变体定义
#   A（baseline）：当前线上 prompt，原样
#   B（strict）  ：在 A 之上追加「数字只能引用给定聚合值 / 纯 JSON / 不臆造」硬约束
# ---------------------------------------------------------------------------
VARIANT_B_ADDENDUM = (
    "\n\n【硬约束·实验变体B】\n"
    "1. 只输出纯 JSON，不要 markdown 代码块、不要任何解释性文字。\n"
    "2. 文本中出现的任何百分比、金额、案件数，必须能在上面给定的聚合数据中直接找到，"
    "禁止自行推算或估计新数字。\n"
    "3. 若某维度数据不足，写「数据不足」而不是编造结论。\n"
)

_ORIG_BUILD_PROMPT = prompts.build_insights_prompt


def _make_variant(variant: str):
    """返回一个按变体改写后的 build_insights_prompt。"""

    def _build(aggregated):
        base = _ORIG_BUILD_PROMPT(aggregated)
        return base + VARIANT_B_ADDENDUM if variant == "B" else base

    return _build


def _sample_cases(limit: int) -> list[dict]:
    """取一批案件作为实验输入（demo 源，确定性种子数据）。"""
    from db import load_cases

    cases = load_cases(source="demo")
    return cases[:limit] if limit else cases


def _run_once(cases: list[dict], variant: str, mode: str) -> dict:
    """跑单次实验，返回观测指标。

    ⚠️ 必须先清空洞察缓存：build_insights 按 (mode, source, 案件指纹, 代际) 缓存，
    同一批案件连跑 A/B 时变体 B 会**直接命中变体 A 的缓存**（实测 0.01s 返回且
    mismatch 与 A 完全相同），实验结论会被缓存污染成「A/B 无差异」。
    """
    if hasattr(pipeline, "_ins_cache"):
        with pipeline._ins_lock:
            pipeline._ins_cache.clear()
    prompts.build_insights_prompt = _make_variant(variant)
    # models_router 在 import 时已绑定 build_insights_prompt，这里同步替换其模块内引用
    import models_router

    models_router.build_insights_prompt = prompts.build_insights_prompt
    try:
        t0 = time.perf_counter()
        res = pipeline.build_insights(list(cases), mode=mode, source="demo")
        dt = time.perf_counter() - t0
    except Exception as e:  # 任何异常都记为失败，不中断实验
        return {
            "variant": variant,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "json_ok": False,
            "mismatch": None,
            "latency_s": round(time.perf_counter() - t0, 2),
        }

    filled = {
        k: bool(res.get(k))
        for k in ("root_cause", "sku_insights", "recommendations", "sourcing_advice")
    }
    return {
        "variant": variant,
        "ok": True,
        "mode": res.get("mode"),
        "json_ok": res.get("mode") == "live",
        "mismatch": res.get("_consistency_mismatches"),
        "latency_s": round(dt, 2),
        "fields": filled,
        "fields_filled": sum(1 for v in filled.values() if v),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B 提示词变体对照实验")
    ap.add_argument("--runs", type=int, default=3, help="每个变体重复次数（默认 3）")
    ap.add_argument("--cases", type=int, default=200, help="每次输入的案件数（默认 200）")
    ap.add_argument(
        "--mode", choices=["live", "mock"], default="live", help="live=真实调用(有费用)"
    )
    ap.add_argument("--out", default="", help="结果写入 JSON 的路径（可选）")
    ap.add_argument("--variants", default="A,B", help="参与对比的变体，逗号分隔")
    args = ap.parse_args()

    cases = _sample_cases(args.cases)
    if not cases:
        print("❌ 未取到案件数据，无法实验")
        return 1
    print(f"输入：{len(cases)} 条案件 ｜ 模式：{args.mode} ｜ 每变体 {args.runs} 次\n")

    rows = []
    for v in [x.strip() for x in args.variants.split(",") if x.strip()]:
        for i in range(args.runs):
            r = _run_once(cases, v, args.mode)
            r["run"] = i + 1
            rows.append(r)
            print(
                f"  变体 {v} #{i + 1}: ok={r['ok']} json_ok={r.get('json_ok')} "
                f"mismatch={r.get('mismatch')} latency={r.get('latency_s')}s"
            )

    # ---- 汇总 ----
    print("\n=== A/B 汇总 ===")
    header = (
        "| 变体 | 成功率 | JSON 可用率 | 幻觉对账 mismatch(均值) | 平均耗时(s) | 字段填充(均值/4) |"
    )
    print(header)
    print("|" + "---|" * 6)
    summary = {}
    for v in sorted({r["variant"] for r in rows}):
        rs = [r for r in rows if r["variant"] == v]
        ok_rate = sum(1 for r in rs if r.get("ok")) / len(rs)
        json_rate = sum(1 for r in rs if r.get("json_ok")) / len(rs)
        mm = [r["mismatch"] for r in rs if r.get("mismatch") is not None]
        lat = [r["latency_s"] for r in rs if r.get("latency_s") is not None]
        ff = [r["fields_filled"] for r in rs if r.get("fields_filled") is not None]
        summary[v] = {
            "runs": len(rs),
            "ok_rate": round(ok_rate, 3),
            "json_ok_rate": round(json_rate, 3),
            "mismatch_mean": round(statistics.mean(mm), 2) if mm else None,
            "latency_mean_s": round(statistics.mean(lat), 2) if lat else None,
            "fields_filled_mean": round(statistics.mean(ff), 2) if ff else None,
        }
        s = summary[v]
        print(
            f"| {v} | {s['ok_rate']:.0%} | {s['json_ok_rate']:.0%} | "
            f"{s['mismatch_mean']} | {s['latency_mean_s']} | {s['fields_filled_mean']} |"
        )

    print(
        "\n※ mismatch = 输出文本中数字与真实聚合值不符的次数（越低越可靠）。\n"
        "※ 本实验量化的是**提示词变体差异**，不是产品对业务指标的因果提升。"
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"config": vars(args), "summary": summary, "rows": rows},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n✅ 明细已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
