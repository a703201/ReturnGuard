"""多模型归因对比：同一份聚合数据，让多个文本推理模型分别做洞察归因。

对比 JSON 有效性 / 内容质量 / 耗时，辅助选定默认模型（当前默认 qwen3.7-max）。

用法：
    python compare_models.py                 # 全量 demo 数据，跑 models 列表里所有模型
依赖：
    demo/.env 配置 MODEL_ROUTER_API_KEY（Token Plan 专属网关，OpenAI 兼容）
注意：
    - 会真实调用大模型，消耗 Token Plan 套餐额度（每模型 1 次）。
    - 纯研究工具，不改产品逻辑；如需更换默认模型，改 models_router.llm 的默认 model。
"""

import json
import logging
import time

import models_router as m
from db import load_cases
from pipeline import _aggregate

logging.basicConfig(level=logging.WARNING)

# 对比模型（均来自 Token Plan 团队版文本推理列表）
MODELS = ["qwen3.7-max", "deepseek-v4-pro", "kimi-k2.6", "glm-5.2"]


def build_prompt(agg: dict) -> str:
    """复刻 build_insights_live 的 prompt，保证各模型输入完全一致。"""
    ctx = {
        "total_cases": agg.get("total_cases"),
        "sku_ranking": agg.get("sku_ranking"),
        "defect_distribution": agg.get("defect_distribution"),
    }
    return (
        "你是一名资深的跨境电商品控与选品分析师。下面是一位跨境卖家退货案件的聚合统计（JSON）：\n"
        f"{json.dumps(ctx, ensure_ascii=False)}\n\n"
        "请完成四件事，并以 JSON 返回（不要任何解释文本，只返回 JSON）：\n"
        "1) root_cause：字符串，归纳退货高发的根因（如包装防护不足 / 供应商质量不稳定 / listing 过度承诺 / 物流暴力分拣等），并给出数据依据。\n"
        '2) sku_insights：数组，取退款金额最高的前 3 个 SKU，每个元素为 {"sku":..,"finding":..,"action":..}，'
        "finding 指出该 SKU 的核心问题，action 给可执行整改动作。\n"
        "3) recommendations：数组，3-5 条可执行的选品 / 品控 / listing 改写建议，面向卖家管理者。\n"
        "4) report：字符串，一段《选品 / 品控洞察报告》正文（中文，约 150 字），总结现状与下一步。\n"
    )


def main() -> None:
    cases = load_cases("demo")
    agg = _aggregate(cases)
    print(
        f"聚合样本：total_cases={agg.get('total_cases')}, "
        f"sku_ranking={len(agg.get('sku_ranking') or [])} 条, "
        f"defect_distribution={len(agg.get('defect_distribution') or {})} 类"
    )
    print(f"{'模型':<16}{'耗时s':>8}{'JSON':>6}  root_cause 前30字 / 建议数")
    print("-" * 92)
    results = []
    for model in MODELS:
        t0 = time.time()
        try:
            out = m.llm_json(build_prompt(agg), model=model)
            dt = round(time.time() - t0, 1)
            ok = bool(out and out.get("root_cause"))
            rc = (out.get("root_cause") or "")[:32]
            n = len(out.get("recommendations") or [])
            results.append((model, dt, ok, rc, n))
            print(f"{model:<16}{dt:>8}{'✓' if ok else '✗':>6}  {rc} / {n} 条建议")
        except Exception as e:  # noqa: BLE001 - 对比脚本需要吞异常继续
            dt = round(time.time() - t0, 1)
            results.append((model, dt, False, str(e)[:32], 0))
            print(f"{model:<16}{dt:>8}{'✗':>6}  {str(e)[:60]}")
    print("-" * 92)
    ok_models = [r for r in results if r[2]]
    print(
        f"结论：有效返回 {len(ok_models)}/{len(MODELS)}；"
        f"推荐默认模型：{ok_models[0][0] if ok_models else '（无）'}"
    )


if __name__ == "__main__":
    main()
