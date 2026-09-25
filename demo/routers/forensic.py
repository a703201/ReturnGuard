# Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
# SPDX-License-Identifier: Apache-2.0
"""单案取证 + 案件库路由：/api/analyze、/api/cases（GET/POST/DELETE）。

从原 main.py 搬出（P1-9）。行为与原实现逐行一致。
"""

from __future__ import annotations

import math
import os
import uuid

from common import (
    UPLOAD_DIR,
    _check_rate_limit,
    _require_session,
    _resolve_source,
    _resolve_tenant,
    _safe_name,
    _validate_image,
    analyze_case,
    bed_upload,
    delete_case,
    get_client_ip,
    get_platform_spec,
    is_valid_platform,
    logger,
    query_cases,
    save_case,
)
from constants import SUPPORTED_LANGUAGES
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from quota import check_live_quota
from schemas import AnalyzeResult, ManualCase

router = APIRouter()

# 入参边界（与 db.Case 的列长对齐）：超限一律 400，而不是让 DB 层截断/报错。
# 为什么在路由层就拒绝（而非只靠 db._clamp_values 截断）：
#   截断是持久层的「最后防线」，用于挡住 CSV/xlsx 这类批量脏数据；面向用户的表单接口
#   应当**明确报错**，否则用户提交了 500 字的 SKU 却只看到一条被悄悄改短的数据。
_MAX_SKU_LEN = 64
_MAX_CATEGORY_LEN = 64
_MAX_SUPPLIER_LEN = 32
_MAX_LISTING_LEN = 20_000  # 本店图文承诺（文本）
_MAX_AMOUNT = 1e9  # 单笔金额上限（防误填天文数字污染聚合）


@router.post("/api/analyze", response_model=AnalyzeResult)
def analyze(
    request: Request,
    returned_image: UploadFile = File(..., description="退回商品图"),
    product_image: UploadFile = File(..., description="本店主图/详情图"),
    listing_text: str = Form(""),
    sku: str = Form("SKU-未知"),
    amount: float = Form(0.0),
    category: str = Form(""),
    supplier: str = Form(""),
    platform: str = Form(""),
    mode: str = Form("mock"),
    language: str = Form("zh"),
):
    """阶段A · 个案举证接口。

    流程：接收两张图（校验+落盘）→ 调用 pipeline.analyze_case 完成取证
          → 把结果沉淀进案件库（供阶段B洞察）→ 返回给前端展示。
    返回字段见 schemas.AnalyzeResult；defect_boxes 为缺陷示意框（归一化坐标）。
    platform 为销售平台（可选），用于关联「平台适配举证包」的必备举证清单。
    category/supplier 为选填维度，补全后该单可干净进入洞察聚合（P1-1 防污染）。
    source(=demo|real)：取证结果沉淀到对应数据库（默认 demo）。
    """
    source = _resolve_source(request)
    # SEC-1 写接口会话鉴权：取证沉淀必须登录，避免匿名写入与资源滥用
    tenant = _require_session(request)
    # 写操作一律落到 real 源（与 import_csv 同款保护）：demo 是共享只读演示库，
    # 且删除被显式禁止（见 delete_case_api），若放任写入会造成「只增不减」的永久污染，
    # 演示数字（1206 条 / 胜诉率 34.6%）会被逐次改写，恢复只能靠 FORCE_RESEED 重建。
    # 归正必须在 tenant_id 解析之前，否则取证结果会落进 public 公共桶而非当前租户。
    if source == "demo":
        logger.warning("单案取证强制落到 real 源（忽略 source=demo），避免污染演示种子库")
        source = "real"
    # P2-8 限流：按客户端 IP 固定窗口
    client_ip = get_client_ip(request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    if mode not in ("mock", "live"):
        raise HTTPException(status_code=400, detail="mode 仅支持 mock / live")
    if platform and not is_valid_platform(platform):
        raise HTTPException(status_code=400, detail="platform 不在支持列表")
    # 母语陈述目标语言：白名单校验，避免下游模板/音色取空
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="language 不在支持列表")
    # 字段边界：长度与数值合法性（与 db.Case 列长对齐），避免落库报错或聚合被污染
    if len(sku) > _MAX_SKU_LEN:
        raise HTTPException(status_code=400, detail=f"sku 长度不得超过 {_MAX_SKU_LEN}")
    if len(category) > _MAX_CATEGORY_LEN:
        raise HTTPException(status_code=400, detail=f"category 长度不得超过 {_MAX_CATEGORY_LEN}")
    if len(supplier) > _MAX_SUPPLIER_LEN:
        raise HTTPException(status_code=400, detail=f"supplier 长度不得超过 {_MAX_SUPPLIER_LEN}")
    if len(listing_text) > _MAX_LISTING_LEN:
        raise HTTPException(status_code=400, detail=f"listing_text 长度不得超过 {_MAX_LISTING_LEN}")
    # NaN / ±Inf 会被 float() 接受但不该入库（会让聚合的金额/均值变成 NaN 并传染全看板）
    if not math.isfinite(amount) or amount < 0 or amount > _MAX_AMOUNT:
        raise HTTPException(status_code=400, detail="amount 必须为 0 ~ 1e9 的有限数值")

    # SEC-13 live 独立配额闸：live 链路真实消耗服务端付费 Key，而公网演示账号
    # demo/demo123 是已对外发布的公开凭据，通用限流（60 次/分钟）挡不住"低频持续"
    # 刷量（一天仍可累积出巨额账单）。故 live 另设按天计费周期的闸门，超限直接
    # 拒绝并说明原因——不做静默降级，否则用户会把 mock 结果误当作 AI 结论。
    if mode == "live":
        allowed, reason = check_live_quota(tenant, client_ip)
        if not allowed:
            raise HTTPException(status_code=429, detail=reason)

    # 校验 + 读取两张图原始字节（UploadFile 只读一次，先读后写）
    ret_bytes = _validate_image(returned_image)
    prod_bytes = _validate_image(product_image)

    # 用随机前缀 + 清洗后的文件名落盘，并断言最终路径仍在 UPLOAD_DIR 内（防穿越）
    rid = uuid.uuid4().hex[:8]
    rp = os.path.join(UPLOAD_DIR, f"{rid}_ret_{_safe_name(returned_image.filename or '')}")
    pp = os.path.join(UPLOAD_DIR, f"{rid}_prod_{_safe_name(product_image.filename or '')}")
    # 断言最终路径仍在 UPLOAD_DIR 内（防穿越）。用显式 raise 而非 assert：
    # python -O 会剥离 assert，导致兜底检查静默失效。
    if os.path.dirname(os.path.abspath(rp)) != UPLOAD_DIR:
        raise HTTPException(status_code=400, detail="上传路径越界")
    if os.path.dirname(os.path.abspath(pp)) != UPLOAD_DIR:
        raise HTTPException(status_code=400, detail="上传路径越界")

    # P1-2 原子性：落盘→取证→存库 全程在 try 中；任一环节异常即清理孤立图片，且不丢取证结果
    try:
        with open(rp, "wb") as f:
            f.write(ret_bytes)
        with open(pp, "wb") as f:
            f.write(prod_bytes)

        # 图床（P3-17）：把上传图同步成公网可访问 URL，供 live 模式视觉/向量/OCR 服务端回源
        ret_url = bed_upload(rp, os.path.basename(rp))
        prod_url = bed_upload(pp, os.path.basename(pp))

        # 执行取证（功能①②③④⑤）
        result = analyze_case(
            rp,
            pp,
            listing_text,
            sku,
            amount,
            mode,
            returned_url=ret_url,
            product_url=prod_url,
            language=language,
        )
        # P2-② 案件号统一：单案取证与手动录入共用 "RG-" + 8 位大写十六进制前缀，
        # 此前取证用裸 8 位小写 hex、录入用 "RG-" 前缀，格式不一致影响检索/展示。
        result["case_id"] = "RG-" + rid.upper()
        result["platform"] = platform
        # P1-1 单案无法判定输赢，标记「待分析」：不稀释胜诉率 KPI、在分布中单独分组
        result["outcome"] = "待分析"
        result["category"] = category
        result["supplier"] = supplier
        result["supplier_name"] = supplier  # 单案上传只能拿到供应商编号，名称暂同号
        # 关联「平台适配举证包」：把该平台的必备举证材料随单返回（只列客观要求，不裁决）
        if platform:
            spec = get_platform_spec(platform)
            result["platform_evidence"] = spec.get("required_evidence", []) if spec else []

        # P3-5 退回图用 URL 访问（图床公网 URL，不再内联整图 base64 撑大响应）
        result["returned_image_url"] = ret_url

        # 数据沉淀：取证结果 > 数据沉淀。save 失败只记日志，仍优先返回 result，
        # 但显式返回 persisted 标记，前端据此提示用户「本次取证未落库」（修复 P1-写库失败静默吞）
        persisted = False
        try:
            tenant_id = (_resolve_tenant(request) or "public") if source == "real" else None
            save_case(
                source,
                {
                    **result,
                    "sku": sku,
                    "amount": amount,
                    "category": category,
                    "supplier": supplier,
                    "supplier_name": supplier,
                    "outcome": "待分析",
                    "returned_image": os.path.basename(rp),
                    "product_image": os.path.basename(pp),
                },
                tenant_id=tenant_id,
            )
            persisted = True
        except Exception as e:
            logger.exception("案件沉淀失败（不影响本次取证结果返回）: %s", e)
        result["persisted"] = persisted
        return result
    except HTTPException:
        raise
    except Exception:
        # 清理可能已落盘的孤立图片，避免 UPLOAD_DIR 残留
        for p in (rp, pp):
            try:
                os.remove(p)
            except OSError:
                pass
        logger.exception("单案取证异常")
        # from None：有意把底层异常替换为干净的 500，原链已由 logger.exception 记录
        raise HTTPException(status_code=500, detail="取证处理失败，请重试") from None


@router.get("/api/cases")
def cases(
    request: Request,
    slim: bool = True,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数（上限 200）"),
    category: str = "",
    platform: str = "",
    region: str = "",
    outcome: str = "",
):
    """查看指定 source 的案件库（A23：支持过滤下推 + 分页）。

    返回信封：{items, total, page, page_size, source, filters}。
    - slim=1（默认）只返回录入列表所需关键字段（P3-①），避免整库大响应体。
    - category/platform/region/outcome：下推 SQL WHERE，减少拉库与传输量。
    - page/page_size：分页，避免一次性把整库推给前端。
    - real 源按当前租户隔离，且**必须登录**（匿名不再归 "public"）。
    """
    source = _resolve_source(request)
    # SEC-P0: real 源存的是真实退货数据（SKU / 供应商 / 商品文案），此前匿名可零凭证
    # 拉走全库。现与 /api/insights 对齐：real 源一律要求登录，且登录后租户即用户名，
    # 不再回退 "public"，因此看不到任何归属不明（tenant_id IS NULL）的历史记录。
    # demo 源是共享演示库、不含真实买家 PII，保持匿名可读以保证演示体验。
    if source == "real":
        tenant_id = _require_session(request)
    else:
        tenant_id = None
    return query_cases(
        source,
        tenant_id=tenant_id,
        category=category,
        platform=platform,
        region=region,
        outcome=outcome,
        page=page,
        page_size=page_size,
        slim=slim,
    )


@router.post("/api/cases", status_code=201)
def add_case(c: ManualCase, request: Request):
    """网页「数据录入」：手动添加一条实际退货案件到指定 source（默认 real 由前端开关控制）。

    不强制传图，填字段即可录入；落库后对应 source 的洞察看板实时刷新。
    写接口：须登录会话（_require_session），匿名 → 401；请求体为 `ManualCase`，
    字段长度与数值范围由 pydantic 校验（见 `schemas.ManualCase`），越界 → 422。
    """
    source = _resolve_source(request)
    _require_session(request)
    # 同 /api/analyze：数据录入一律落 real 源，避免污染共享演示库。
    # demo 禁止删除且允许匿名读，若任由录入写入会只增不减地改写演示基准数据。
    # 归正必须在 tenant_id 解析之前，确保录入行归属当前登录租户。
    if source == "demo":
        logger.warning("数据录入强制落到 real 源（忽略 source=demo），避免污染演示种子库")
        source = "real"
    tenant_id = (_resolve_tenant(request) or "public") if source == "real" else None
    data = c.model_dump()
    data["case_id"] = "RG-" + uuid.uuid4().hex[:8].upper()
    if not data.get("defect_tags"):
        data["defect_tags"] = ["无明显瑕疵"]
    save_case(source, data, tenant_id=tenant_id)
    location = f"/api/cases/{data['case_id']}"
    return JSONResponse(
        status_code=201,
        headers={"Location": location},
        content={
            "ok": True,
            "source": source,
            "case_id": data["case_id"],
            "tenant": tenant_id or "public",
        },
    )


@router.delete("/api/cases/{case_id}")
def delete_case_api(case_id: str, request: Request):
    """删除指定 source 下的一条案件（实际数据管理用）。写接口：须登录会话（_require_session），匿名 → 401。
    real 源仅能删除当前租户的案件，跨租户不可见不可删。

    SEC-P0: demo 源为共享演示库且测试账号公开，此前任何登录者都能把 1206 条种子数据
    逐条删光（演示现场不可逆）。现对 demo 源一律拒绝删除，种子数据只能经 FORCE_RESEED 重建。
    """
    source = _resolve_source(request)
    _require_session(request)
    if source == "demo":
        raise HTTPException(status_code=403, detail="演示库为只读，如需清空请用实际数据（real）源")
    tenant_id = _resolve_tenant(request)
    n = delete_case(source, case_id, tenant_id=tenant_id)
    if n == 0:
        # 此前删除不存在的 id 仍返回 ok:true，前端无法区分成功与"没找到"
        raise HTTPException(status_code=404, detail="未找到该案件，或不属于当前账户")
    return {"ok": True, "source": source, "deleted": n}
