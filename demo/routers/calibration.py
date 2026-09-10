"""相似度阈值自标定路由：/api/calibrate（GET/POST）。

从原 main.py 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

from calibration import load_calibration_record
from common import _require_admin, get_active_threshold, logger, save_calibration, suggest_threshold
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


# ===================== B组：相似度阈值自标定 + 真实数据回流 =====================
class CalibrateRequest(BaseModel):
    """阈值自标定输入：真同款样本相似度、真调包样本相似度。"""

    same_sims: list[float] = []
    diff_sims: list[float] = []


@router.get("/api/calibrate")
def calibrate_get():
    """返回当前生效的同款阈值（标定值或默认 0.82）及标定样本量。"""
    rec = load_calibration_record()
    return {
        "threshold": get_active_threshold(),
        "source": "calibrated" if rec else "default",
        "n_same": rec["n_same"] if rec else 0,
        "n_diff": rec["n_diff"] if rec else 0,
    }


@router.post("/api/calibrate", response_model=dict)
def calibrate_post(req: CalibrateRequest, request: Request):
    """用历史「真同款 / 真调包」样本标定 SAME_ITEM_THRESHOLD（Youden J 最优分离点），并落盘。
    样本不足（缺任一类）返回默认经验值，不覆盖既有标定（避免无意义回写）。
    管理动作：需管理员密钥（ADMIN_API_KEY）或登录会话（_require_admin），演示态/公网均不可匿名篡改。"""
    _require_admin(request)
    t = suggest_threshold(req.same_sims, req.diff_sims)
    if not req.same_sims or not req.diff_sims:
        return {
            "threshold": t,
            "saved": False,
            "insufficient": True,
            "message": "样本不足（需同时提供 same_sims 与 diff_sims），返回默认阈值，未落盘",
        }
    save_calibration(t, len(req.same_sims), len(req.diff_sims))
    logger.info(
        "阈值自标定完成：%.3f（same=%d, diff=%d）", t, len(req.same_sims), len(req.diff_sims)
    )
    return {
        "threshold": t,
        "saved": True,
        "insufficient": False,
        "n_same": len(req.same_sims),
        "n_diff": len(req.diff_sims),
    }
