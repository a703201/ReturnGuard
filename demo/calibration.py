"""ReturnGuard · 同款阈值自标定（B组：阈值自标定）

用历史「真同款 / 真调包」样本自动标定 SAME_ITEM_THRESHOLD（PRD §11 明确「待标定」），
替代写死的 0.82 经验值。方法：在相似度轴上找使 (真同款判同款率 + 真调包判调包率) 最大化的切点
（Youden J 最优分离点）。标定结果写入 calibration.json，pipeline 与 live 统一读取，
消除此前「0.82 在 main / generate_dataset / pipeline 三处各写一份」的漂移（P2-4）。
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("returnguard.calibration")

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
DEFAULT_THRESHOLD: float = 0.82


def suggest_threshold(same_sims: list[float], diff_sims: list[float], step: float = 0.01) -> float:
    """给定真同款相似度样本与真调包相似度样本，返回最优判定阈值（最大化 Youden J）。

    若样本不足（缺任一类）返回默认经验值，避免无意义标定。
    """
    if not same_sims or not diff_sims:
        return DEFAULT_THRESHOLD
    lo = min(min(same_sims), min(diff_sims))
    hi = max(max(same_sims), max(diff_sims))
    best_t, best_j = DEFAULT_THRESHOLD, -1.0
    t = lo
    while t <= hi + 1e-9:
        tpr = sum(1 for s in same_sims if s >= t) / len(same_sims)  # 真同款判同款率
        tnr = sum(1 for s in diff_sims if s < t) / len(diff_sims)  # 真调包判调包率
        j = tpr + tnr - 1
        if j > best_j:
            best_j, best_t = j, t
        t = round(t + step, 3)
    return round(best_t, 3)


def save_calibration(threshold: float, n_same: int, n_diff: int, path: str = CALIB_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"threshold": threshold, "n_same": n_same, "n_diff": n_diff},
            f,
            ensure_ascii=False,
            indent=2,
        )


def load_calibration(path: str = CALIB_FILE) -> float | None:
    rec = load_calibration_record(path)
    return rec.get("threshold") if rec else None


def load_calibration_record(path: str = CALIB_FILE) -> dict | None:
    """读取完整标定记录 {threshold, n_same, n_diff}；无文件/损坏返回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        return {
            "threshold": float(rec["threshold"]),
            "n_same": int(rec.get("n_same", 0)),
            "n_diff": int(rec.get("n_diff", 0)),
        }
    except Exception:  # noqa: BLE001
        return None


def get_active_threshold(path: str = CALIB_FILE) -> float:
    """pipeline / live 统一读取：标定过用标定值，否则用默认经验值（单一来源）。"""
    cal = load_calibration(path)
    return cal if cal is not None else DEFAULT_THRESHOLD
