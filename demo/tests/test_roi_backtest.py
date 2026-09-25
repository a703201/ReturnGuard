# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""ROI 回测（pipeline._roi_backtest）回归测试。

诚实性要求：回测是**基于真实聚合值的模型估算**，不是 A/B 实测因果。
测试除了校验算数正确，还强制 `method` / `disclaimer` 必须随结果下发——
防止后续重构时把「非实测」的边界说明悄悄丢掉，导致对外被当成实测收益引用。
"""

import pipeline


def _agg(**over):
    base = {
        "total_cases": 1000,
        "total_refund": 150000.0,
        "win_rate": 0.30,
        "avg_dispute_rate": 0.20,
        "logistics_cost": 25000.0,
    }
    base.update(over)
    return base


def test_roi_backtest_basic_math():
    """基础算数：争议案件 = 1000×20% = 200；基准档由败转胜 = 200×15% = 30 笔。"""
    bt = pipeline._roi_backtest(_agg())
    assert bt["available"] is True
    assert bt["basis"]["dispute_cases"] == 200.0
    assert bt["basis"]["avg_refund"] == 150.0
    base = next(s for s in bt["scenarios"] if s["key"] == "base")
    assert base["cases_won_back"] == 30.0
    assert base["recover_refund"] == 4500.0  # 30 × 150
    assert base["recover_logistics"] == 750.0  # 30 × 25


def test_roi_backtest_scenarios_monotonic():
    """保守 < 基准 < 乐观；且三档必须齐全。"""
    bt = pipeline._roi_backtest(_agg())
    keys = [s["key"] for s in bt["scenarios"]]
    assert keys == ["conservative", "base", "optimistic"]
    vals = [s["recover_refund"] for s in bt["scenarios"]]
    assert vals == sorted(vals) and vals[0] < vals[-1]


def test_roi_backtest_win_rate_capped():
    """胜诉率已接近上限时，提升幅度必须被 headroom 截住，不能算出 >95% 的胜诉率。"""
    bt = pipeline._roi_backtest(_agg(win_rate=0.93))
    for s in bt["scenarios"]:
        assert s["effective_delta"] <= 0.02 + 1e-9, "提升幅度应被上限截住"
        assert 0.93 + s["effective_delta"] <= pipeline.ROI_MAX_WIN_RATE + 1e-9


def test_roi_backtest_empty_cases():
    """无案件时不可用，且给出 reason，而不是抛异常或返回 0 误导。"""
    bt = pipeline._roi_backtest(_agg(total_cases=0))
    assert bt["available"] is False
    assert bt.get("reason")


def test_roi_backtest_honesty_fields():
    """必须随结果下发 method / disclaimer / assumptions —— 防止被当成实测因果引用。"""
    bt = pipeline._roi_backtest(_agg())
    assert "非 A/B 实测" in bt["method"]
    assert "未经 A/B 实测" in bt["disclaimer"]
    assert bt["assumptions"]["win_rate_cap"] == pipeline.ROI_MAX_WIN_RATE


def test_roi_backtest_sensitivity_bounds_base():
    """敏感性：案件量 -20% 应低于基准，+20% 应高于基准。"""
    bt = pipeline._roi_backtest(_agg())
    base = next(s for s in bt["scenarios"] if s["key"] == "base")["recover_refund"]
    assert bt["sensitivity"]["cases_-20%"] < base < bt["sensitivity"]["cases_+20%"]


def test_build_insights_includes_roi_backtest():
    """build_insights 必须把 roi_backtest 带进洞察响应，供前端 ROI 面板渲染。"""
    cases = [
        {
            "case_id": f"RG-ROI-{i}",
            "sku": "SKU-A",
            "amount": 150,
            "outcome": "赢" if i % 3 == 0 else "输",
            "defect_tags": ["功能故障"],
            "date": "2025-03-01",
        }
        for i in range(10)
    ]
    res = pipeline.build_insights(cases, mode="mock", source="demo")
    assert "roi_backtest" in res
    assert res["roi_backtest"]["available"] is True
