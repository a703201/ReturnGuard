"""ReturnGuard · 真实数据回流（CSV 批量导入到 real 库）+ 平台连接器位（B组：真实数据回流）

把卖家真实退货数据批量导入 real 源，让洞察看板从「合成种子」切换到「真实业务数据」。
- import_csv_text / import_csv_file：解析 CSV → ManualCase → save_case，带字段映射与类型转换。
- 平台 API 连接器（Amazon SP-API / AliExpress）预留接口 import_from_connector，当前为
  可插拔位，待平台凭证就绪后接入，不改变现有导入主链路。

启动自动导入：部署期设置 env RG_AUTO_IMPORT_CSV=<路径>，服务启动即对 real 源导入该 CSV
（openGauss 部署下真实数据自动回流，见 C组 openGauss 自动导入）。
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid

from db import load_cases, save_case
from schemas import ManualCase

logger = logging.getLogger("returnguard.importer")

# CSV 列 → ManualCase 字段映射（兼容常见导出列名；大小写/下划线/中文不敏感）
_COL_MAP = {
    "sku": "sku",
    "sku_name": "sku_name",
    "产品名": "sku_name",
    "产品": "sku_name",
    "category": "category",
    "品类": "category",
    "supplier": "supplier",
    "供应商": "supplier",
    "supplier_name": "supplier_name",
    "platform": "platform",
    "平台": "platform",
    "region": "region",
    "地区": "region",
    "国家": "region",
    "amount": "amount",
    "金额": "amount",
    "退款": "amount",
    "退款金额": "amount",
    "date": "date",
    "日期": "date",
    "similarity": "similarity",
    "相似度": "similarity",
    "outcome": "outcome",
    "结果": "outcome",
    "defect_tags": "defect_tags",
    "缺陷": "defect_tags",
    "瑕疵": "defect_tags",
    "listing_text": "listing_text",
    "承诺": "listing_text",
}
_BOOLEAN = {"true", "1", "是", "yes", "y"}


def _norm_header(h: str) -> str:
    return (h or "").strip().lower()


def import_csv_text(
    text: str, source: str = "real", dedupe: bool = False, tenant_id: str | None = None
) -> dict:
    """解析 CSV 文本，逐行转 ManualCase 落库。返回 {imported, skipped, errors}。

    dedupe=True（启动自动导入场景）：按自然键 (sku, date, 相似度) 跳过 source 中已存在的行，
    使容器重启重复挂载同一份 CSV 时不会重复堆积（openGauss 自动导入幂等）。
    tenant_id：real 源多租户隔离，缺省 "public"（启动自动导入/匿名录入归公共租户）。
    """
    reader = csv.DictReader(io.StringIO(text))
    imported = skipped = 0
    errors: list[str] = []
    # 幂等基：现有行的自然键集合（仅在开启 dedupe 时加载，避免非必要全表扫描）
    existing: set[tuple] = set()
    if dedupe:
        try:
            existing = {
                (c.get("sku"), c.get("date") or "", round(float(c.get("similarity") or 0), 3))
                for c in load_cases(source)
            }
        except Exception:  # noqa: BLE001
            logger.warning("去重基线加载失败，退化为全量导入", exc_info=True)
            existing = set()
    for i, row in enumerate(reader, 1):
        mapped: dict = {}
        for h, v in row.items():
            if h is None:
                continue
            key = _COL_MAP.get(_norm_header(h))
            if key and v not in (None, ""):
                mapped[key] = v.strip()
        if not mapped.get("sku"):
            skipped += 1
            errors.append(f"第{i}行缺 sku，跳过")
            continue
        # 类型转换与多值拆分
        try:
            if "amount" in mapped:
                mapped["amount"] = float(mapped["amount"])
            if "similarity" in mapped:
                mapped["similarity"] = float(mapped["similarity"])
            if "same_item" in mapped:
                mapped["same_item"] = str(mapped["same_item"]).lower() in _BOOLEAN
            if "defect_tags" in mapped:
                mapped["defect_tags"] = [
                    t.strip() for t in re.split(r"[;,、]", mapped["defect_tags"]) if t.strip()
                ] or ["无明显瑕疵"]
        except Exception as e:  # noqa: BLE001
            skipped += 1
            errors.append(f"第{i}行字段解析失败: {e}")
            continue
        # 去重：自然键已存在则跳过（幂等导入，避免重启重复堆积）
        if dedupe:
            nat = (
                mapped.get("sku"),
                mapped.get("date") or "",
                round(float(mapped.get("similarity") or 0), 3),
            )
            if nat in existing:
                skipped += 1
                continue
        try:
            data = ManualCase(**mapped).model_dump()
            # 生成稳定案件号（原导入链路缺 case_id → NULL，导致无法按 ID 删除/去重；
            # 这里补齐，与 /api/cases 手动录入保持一致）
            data["case_id"] = "RG-" + uuid.uuid4().hex[:8].upper()
            save_case(source, data, tenant_id=tenant_id)
            imported += 1
            if dedupe:
                existing.add(nat)
        except Exception as e:  # noqa: BLE001
            skipped += 1
            errors.append(f"第{i}行落库失败: {e}")
    logger.info(
        "CSV 导入完成 source=%s imported=%d skipped=%d dedupe=%s", source, imported, skipped, dedupe
    )
    return {"imported": imported, "skipped": skipped, "errors": errors}


def import_csv_file(path: str, source: str = "real") -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return import_csv_text(f.read(), source)


def import_from_connector(connector, source: str = "real") -> dict:
    """平台连接器接入位（Amazon SP-API / AliExpress 等）。

    待平台凭证就绪后，connector.fetch_return_cases() 返回与 ManualCase 对齐的字典列表，
    此处统一落库。当前为可插拔接口，不改变 CSV 导入主链路。
    """
    rows = connector.fetch_return_cases()
    imported = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows, 1):
        try:
            save_case(source, ManualCase(**row).model_dump())
            imported += 1
        except Exception as e:  # noqa: BLE001
            skipped += 1
            errors.append(f"第{i}行落库失败: {e}")
    logger.info("连接器导入完成 source=%s imported=%d skipped=%d", source, imported, skipped)
    return {"imported": imported, "skipped": skipped, "errors": errors}
