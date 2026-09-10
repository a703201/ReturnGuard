"""ReturnGuard · 供应商维度分配（单一来源）

把「退货缺陷 → 供应商」的分配规则收敛到一处，供**数据集构建**（`convert_datasets` /
`dataset_parse`）与**演示种子重映射**共用，杜绝「生成器改了、种子没改」的口径漂移。

设计要点：
- **缺陷类型决定候选池**（质量关联）：真实质量/履约缺陷落到「高发问题供应商」，包装类缺陷落到
  「包装偏弱供应商」，干净退货落到「相对优质供应商」——使供应商红黑榜真实收敛，而非全员飘红。
- **SKU 提供池内熵**：同一缺陷类型也按 SKU 散落到池内不同供应商，避免退化成 1~2 家
  （历史缺陷：只用 `缺陷组合` 做哈希 → 组合仅 5 种 → 实际只产出 S2/S3/S6 三家）。
- **稳定哈希**：跨进程 / 跨重跑一致，保证数据集可复现。

供应商池对应 `constants.SUPPLIERS`：
    S1 鼎峰精密 / S2 云仓优选 / S5 联创供货 / S7 锐捷制造 —— 相对优质
    S3 鑫源电子(劣) / S6 海贸乱发(劣) / S8 万通杂货 —— 质量 / 履约高发问题
    S4 通达包装弱 —— 包装 / 物流环节偏弱
"""

from __future__ import annotations

import hashlib

from constants import SEVERITY

# 缺陷类型 → 供应商候选池（编号对应 constants.SUPPLIERS）
POOL_BY_DEFECT: dict[str, tuple[str, ...]] = {
    # 供应商质量 / 履约：劣供
    "功能故障": ("S3", "S6", "S8"),
    "商品缺件": ("S3", "S6", "S8"),
    # Listing 与图文：中游供货
    "货不对板": ("S5", "S7", "S8"),
    "色差明显": ("S5", "S7"),
    # 物流与包装：包装偏弱的 S4 参与
    "外包装破损": ("S4", "S1"),
    "污渍划痕": ("S4", "S1"),
    # 非质量（倾向买家）：优质供
    "使用痕迹": ("S2", "S5"),
    "无明显瑕疵": ("S1", "S2", "S5", "S7"),
}
# 未收录缺陷的默认池（优质）
DEFAULT_POOL: tuple[str, ...] = ("S1", "S2", "S5", "S7")


def _stable_hash(text: str) -> int:
    """跨进程稳定的哈希（内置 hash() 受 PYTHONHASHSEED 随机化影响，不可用于持久化产物）。"""
    return int.from_bytes(hashlib.md5(str(text).encode("utf-8")).digest()[:8], "big")


def dominant_defect(defects) -> str:
    """取一笔案件的主缺陷（忽略「无明显瑕疵」），与 pipeline 归因口径一致（严重度高优先）。"""
    real = [d for d in (defects or []) if d and d != "无明显瑕疵"]
    if not real:
        return "无明显瑕疵"
    return max(real, key=lambda d: SEVERITY.get(d, 0.2))


def assign_supplier(defects, sku: str = "") -> str:
    """按「主缺陷候选池 + SKU 熵」确定性地分配一个供应商编号（S1~S8）。

    - 池由主缺陷类型决定（质量关联，见 `POOL_BY_DEFECT`）；
    - 池内选择用 `_stable_hash(缺陷串 | sku)`，让同一缺陷类型也散落到池内不同供应商。
    """
    dom = dominant_defect(defects)
    pool = POOL_BY_DEFECT.get(dom, DEFAULT_POOL)
    salt = f"{'|'.join(sorted(d for d in (defects or []) if d))}|{sku}"
    return pool[_stable_hash(salt) % len(pool)]
