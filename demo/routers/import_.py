"""真实数据回流路由：/api/import_csv、/api/import_file。

从原 main.py 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

from common import (
    _MAX_UPLOAD_BYTES,
    _require_session,
    _resolve_source,
    _resolve_tenant,
    logger,
)
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from importer import import_csv_text, import_file

router = APIRouter()

# 表单直贴 CSV 的体积上限：与上传文件共用 10MB 口径。此前只校验了 UploadFile 的
# 大小，`csv_text` 表单字段无上限——可以把任意大的 body 塞进内存解析（无鉴权前的
# 内存放大面），故一并收敛。
_MAX_CSV_TEXT_CHARS = 10 * 1024 * 1024


@router.post("/api/import_csv")
def import_csv(
    request: Request,
    csv_file: UploadFile | None = File(None),
    csv_text: str = Form(""),
):
    """B组·真实数据回流：把卖家退货 CSV 批量导入 real 源（可指向 openGauss），让洞察看板切换真实业务数据。

    两种入参（二选一）：上传 csv_file，或直接贴 csv_text。字段映射见 importer._COL_MAP
    （sku/品类/供应商/平台/地区/金额/日期/相似度/结果/缺陷 等，大小写与中文列名不敏感）。
    写接口：需登录会话（_require_session）。返回 {imported, skipped, errors}。
    """
    _require_session(request)
    source = _resolve_source(request)
    text = ""
    if csv_file is not None and csv_file.filename:
        raw = csv_file.file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，单文件上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB",
            )
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gbk", errors="replace")
    else:
        text = csv_text
    if not text.strip():
        raise HTTPException(status_code=400, detail="请提供 csv_file 或 csv_text")
    if len(text) > _MAX_CSV_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"CSV 文本过大，上限 {_MAX_CSV_TEXT_CHARS // 1024 // 1024}MB 字符",
        )
    # 仅允许导入 real 源，避免污染演示种子库；导入行归属当前租户（匿名 → public）
    if source != "real":
        logger.warning("CSV 导入强制落到 real 源（忽略 source=%s），避免污染 demo 种子库", source)
        source = "real"
    tenant_id = _resolve_tenant(request) or "public"
    res = import_csv_text(text, source, tenant_id=tenant_id)
    return {"ok": True, "source": source, "tenant": tenant_id or "public", **res}


@router.post("/api/import_file", response_model=dict)
def import_file_api(
    request: Request,
    file: UploadFile = File(...),
):
    """数据导入区·文件导入：把卖家真实数据集文件（.xlsx/.csv，类型同 Dataset/ 三大数据集）
    批量导入 real 源，并按 case_id 去重（同日跳过、异日保留最新删旧）。

    支持：Amazon 退货 xlsx / UCI Online Retail xlsx / TheLook 订单 csv（returned_at 非空）/
    RG 格式 csv（含 sku 等列）。写接口：需登录会话（_require_session）。返回
    {ok, detected, imported, updated, skipped, file_duplicates, errors}。
    """
    _require_session(request)
    # 文件导入强制落到 real 源，避免污染演示种子库
    source = "real"
    raw = file.file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"文件过大，单文件上限 {_MAX_UPLOAD_BYTES // 1024 // 1024}MB"
        )
    fname = file.filename or "upload"
    try:
        if fname.lower().endswith(".csv"):
            text = raw.decode("utf-8-sig")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001
        text = raw.decode("latin-1", errors="replace")
    # xlsx 直接传 bytes；csv 传解码后的文本
    content = raw if fname.lower().endswith(".xlsx") else text
    tenant_id = _resolve_tenant(request) or "public"
    res = import_file(fname, content, source, tenant_id=tenant_id)
    return {"ok": res.get("ok", False), "source": source, "tenant": tenant_id or "public", **res}
