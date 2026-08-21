"""B组新增能力单测：阈值自标定 / CSV 导入 / 时间序列预测 / 选品避坑闭环。

纯函数优先走单元断言；涉及 DB 的 importer 用 monkeypatch 收集落库行，避免污染测试库。
"""

import os
import sys

# 确保在 demo 目录下可被 import（CI 下 cwd 即 demo）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration as calibration
import importer as importer
from pipeline import _build_sourcing_loop, _build_time_series, _forecast_monthly


# ===================== 阈值自标定 =====================
def test_suggest_threshold_youden_separation():
    # 真同款集中在高相似度、真调包集中在低相似度 → 应在中间找到最优分离点
    same = [0.95, 0.92, 0.97, 0.90, 0.93]
    diff = [0.40, 0.55, 0.48, 0.62, 0.50]
    t = calibration.suggest_threshold(same, diff, step=0.01)
    assert 0.62 < t < 0.90  # 落在两类之间
    # 该阈值下真同款几乎全判同款、真调包几乎全判调包
    assert all(s >= t for s in same)
    assert all(d < t for d in diff)


def test_suggest_threshold_insufficient_returns_default():
    assert calibration.suggest_threshold([], [0.5]) == calibration.DEFAULT_THRESHOLD
    assert calibration.suggest_threshold([0.9], []) == calibration.DEFAULT_THRESHOLD


def test_calibration_save_load_roundtrip(tmp_path):
    p = tmp_path / "calibration.json"
    calibration.save_calibration(0.78, 10, 12, path=str(p))
    assert calibration.load_calibration(path=str(p)) == 0.78
    rec = calibration.load_calibration_record(path=str(p))
    assert rec == {"threshold": 0.78, "n_same": 10, "n_diff": 12}
    # get_active_threshold 回退默认（文件不存在）
    assert (
        calibration.get_active_threshold(path=str(tmp_path / "missing.json"))
        == calibration.DEFAULT_THRESHOLD
    )


# ===================== CSV 导入（真实数据回流）=====================
def test_import_csv_text_mapping_and_types(monkeypatch):
    rows = []

    def fake_save(source, data, tenant_id=None):
        rows.append((source, data))

    monkeypatch.setattr(importer, "save_case", fake_save)
    csv = (
        "sku,品类,供应商,平台,地区,金额,日期,相似度,结果,缺陷\n"
        "SKU-A,3C数码,S1,Amazon,北美,120,2026-03-01,0.91,赢,外包装破损\n"
        "SKU-B,服饰鞋包,S2,Temu,欧洲,89,2026-03-02,0.55,输,功能故障;色差明显\n"
        ",缺失SKU,不导入,,,,,,\n"  # 缺 sku → 跳过
    )
    res = importer.import_csv_text(csv, "real")
    assert res["imported"] == 2
    assert res["skipped"] == 1
    assert res["errors"]  # 含缺 sku 说明
    # 字段映射 + 类型转换正确
    by_sku = {r[1]["sku"]: r[1] for r in rows}
    a = by_sku["SKU-A"]
    assert a["category"] == "3C数码"
    assert a["amount"] == 120.0
    assert a["similarity"] == 0.91
    assert a["outcome"] == "赢"
    b = by_sku["SKU-B"]
    assert b["defect_tags"] == ["功能故障", "色差明显"]


def test_import_csv_text_chinese_headers(monkeypatch):
    rows = []

    def fake_save(source, data, tenant_id=None):
        rows.append(data)

    monkeypatch.setattr(importer, "save_case", fake_save)
    csv = "sku,退款,瑕疵\nSKU-C,200,污渍划痕\n"
    res = importer.import_csv_text(csv, "real")
    assert res["imported"] == 1
    assert rows[0]["sku"] == "SKU-C"
    assert rows[0]["amount"] == 200.0
    assert rows[0]["defect_tags"] == ["污渍划痕"]


# ===================== 时间序列 + 预测 =====================
def test_build_time_series_sorts_by_month():
    ts = {"2026-03": {"cases": 5, "refund": 500.0}, "2026-01": {"cases": 2, "refund": 100.0}}
    out = _build_time_series(ts)
    assert [x["month"] for x in out] == ["2026-01", "2026-03"]
    assert out[0]["cases"] == 2


def test_forecast_monthly_up_trend():
    series = [
        {"month": "2026-01", "cases": 4, "refund": 400.0},
        {"month": "2026-02", "cases": 6, "refund": 600.0},
        {"month": "2026-03", "cases": 9, "refund": 900.0},
        {"month": "2026-04", "cases": 12, "refund": 1200.0},
    ]
    f = _forecast_monthly(series)
    assert f["available"] is True
    assert f["trend"] == "up"
    assert len(f["points"]) == 3
    # 预测下一个月应大于近期，且月份连续
    assert f["next_month_cases"] > f["recent_avg"]
    assert f["points"][0]["month"] == "2026-05"


def test_forecast_monthly_insufficient_samples():
    f = _forecast_monthly([{"month": "2026-01", "cases": 3, "refund": 100.0}])
    assert f["available"] is False
    assert f["trend"] == "flat"


def test_forecast_monthly_flat_weak_noise():
    # 弱波动不应误报 up/down
    series = [
        {"month": "2026-01", "cases": 10, "refund": 100.0},
        {"month": "2026-02", "cases": 10, "refund": 100.0},
        {"month": "2026-03", "cases": 11, "refund": 110.0},
    ]
    f = _forecast_monthly(series)
    assert f["trend"] == "flat"


# ===================== 选品避坑闭环 =====================
def test_build_sourcing_loop_structured_items():
    agg = {
        "supplier_blacklist": [
            {"supplier": "S9", "name": "劣质厂", "quality_score": 12, "reason": "质量分 12"}
        ],
        "category_heatmap": [
            {"category": "3C数码", "win_rate": 0.20, "top_defect": "功能故障"},
        ],
        "anomaly_alerts": [{"sku": "SKU-X", "reason": "近30天纠纷集中爆发"}],
        "forecast_alerts": [{"reason": "退货量预测上行"}],
    }
    items = _build_sourcing_loop(agg)
    actions = {i["action"] for i in items}
    assert "规避供应商" in actions
    assert "上新前必核验" in actions
    assert "暂停推广·排查批次" in actions
    assert "前置品控·备货物流" in actions
    # 高严重度排在前
    assert items[0]["severity"] == "高"


def test_build_sourcing_loop_empty_when_no_signals():
    agg = {
        "supplier_blacklist": [],
        "category_heatmap": [],
        "anomaly_alerts": [],
        "forecast_alerts": [],
    }
    assert _build_sourcing_loop(agg) == []
