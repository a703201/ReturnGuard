// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// HTTP 路由集合：health / config / auth / insights。
// 响应契约与 Python FastAPI 版逐字段对齐（前端无需改动即可切换后端）。
package rg.api.routes

import std.collection.*
import std.time.*
import std.env.*
import rg.api.http.*
import rg.app.*
import rg.data.store.*
import rg.security.authn.*
import rg.ai.*
import rg.kernel.json.*
import rg.kernel.log.*
import rg.kernel.error.*

/** 路由装配入口：把所有路由注册到 router。 */
public func registerRoutes(router: Router, ctx: AppContext): Unit {
    router.get("/health", { req => health(ctx) })
    router.get("/api/config", { req => config(ctx) })
    router.get("/api/platforms", { req => platforms(ctx) })
    router.get("/api/ai/providers", { req => aiProviders(ctx, req) })
    router.get("/api/ai/settings", { req => aiSettingsGet(ctx, req) })
    router.post("/api/ai/settings", { req => aiSettingsPost(ctx, req) })
    router.post("/api/auth/register", { req => register(ctx, req) })
    router.post("/api/auth/register-sm3", { req => registerSm3(ctx, req) })
    router.get("/api/crypto/capabilities", { req => cryptoCapabilities(ctx, req) })
    router.post("/api/auth/totp/setup", { req => totpSetup(ctx, req) })
    router.post("/api/auth/totp/enable", { req => totpEnable(ctx, req) })
    router.post("/api/auth/totp/verify", { req => totpVerify(ctx, req) })
    router.post("/api/auth/totp/disable", { req => totpDisable(ctx, req) })
    router.get("/api/auth/totp/status", { req => totpStatus(ctx, req) })
    router.get("/api/auth/sessions", { req => sessions(ctx, req) })
    router.post("/api/auth/sessions/revoke", { req => revokeSession(ctx, req) })
    router.post("/api/auth/login", { req => login(ctx, req) })
    router.post("/api/oauth/register", { req => oauthRegister(ctx, req) })
    router.post("/api/oauth/token", { req => oauthToken(ctx, req) })
    router.get("/api/oauth/clients", { req => oauthClients(ctx, req) })
    router.post("/api/oauth/rotate", { req => oauthRotate(ctx, req) })
    router.post("/api/auth/refresh", { req => refreshToken(ctx, req) })
    router.get("/api/auth/me", { req => me(ctx, req) })
    router.post("/api/auth/logout", { req => logout(ctx, req) })
    router.get("/api/insights", { req => insights(ctx, req) })
    router.get("/api/cases", { req => listCases(ctx, req) })
    router.post("/api/cases", { req => addCase(ctx, req) })
    router.post("/api/cases/import", { req => importCases(ctx, req) })
    router.delete("/api/cases/:caseId", { req => deleteCase(ctx, req) })
    router.post("/api/analyze", { req => analyze(ctx, req) })
    router.get("/api/export_pdf", { req => exportPdf(ctx, req) })
    router.get("/api/audit/list", { req => auditList(ctx, req) })
    router.get("/api/audit/verify", { req => auditVerify(ctx, req) })
    Log.info("已注册 ${router.size()} 条路由")
}

/** 从请求解析当前用户名（未登录返回 ""）。 */
public func currentUser(ctx: AppContext, req: ApiRequest): String {
    match (req.bearerToken()) {
        case Some(t) => return ctx.auth.verify(t) ?? ""
        case None => return ""
    }
}

private func health(ctx: AppContext): ApiResponse {
    // 深健康探针：持久化模式下确认 DB 可用，避免连接池僵死时容器仍报 healthy 无法自愈。
    // 内存模式恒 ok。DB 不可用时返回 503 → healthcheck 判 unhealthy → 容器重启。
    if (!ctx.dbHealthy()) {
        return ApiResponse(503, "{\"status\":\"degraded\",\"db\":\"unavailable\"}")
    }
    return ApiResponse.ok(Obj().str("status", "ok").str("persistence", ctx.persistence).build())
}

/** /api/config：前端常量单一来源，字段与 Python 版对齐。 */
private func config(ctx: AppContext): ApiResponse {
    let suppliers = Obj()
        .str("S1", "鼎峰精密").str("S2", "云仓优选").str("S3", "鑫源电子")
        .str("S4", "通达包装").str("S5", "联创供货").str("S6", "海贸乱发")
        .str("S7", "锐捷制造").str("S8", "万通杂货").build()
    let langs = Arr()
        .raw(Obj().str("code", "zh").str("label", "中文").str("voice", "Chelsie").build())
        .raw(Obj().str("code", "en").str("label", "English").str("voice", "Ava").build())
        .raw(Obj().str("code", "fr").str("label", "Français").str("voice", "Denise").build())
        .build()
    // 当前 AI provider（来自注册表，密钥不进响应）
    let curSpec = ctx.aiProviders.get(ctx.aiProviderKey)
    let curLabel = match (curSpec) { case Some(s) => s.label; case None => ctx.aiProviderKey }
    let curSupported = match (curSpec) { case Some(s) => s.supported; case None => false }
    let provider = Obj()
        .str("key", ctx.aiProviderKey)
        .str("name", curLabel)
        .boolean("openaiCompatible", curSupported)
        .boolean("current", true)
        .boolean("configured", ctx.ai.configured())
        .build()
    let obj = Obj()
        .f64("same_item_threshold", ctx.threshold)
        .str("version", ctx.version)
        .str("persistence", ctx.persistence)
        .str("quota_backend", ctx.quota.backend)
        .raw("sources", "[\"unified\"]")
        .str("default_source", "unified")
        .str("image_bed", "local")
        .boolean("image_bed_public", false)
        .raw("suppliers", suppliers)
        .raw("languages", langs)
        .str("default_language", "zh")
        .str("model_router_profile", ctx.aiProviderKey)
        .raw("provider", provider)
        .build()
    return ApiResponse.ok(obj)
}

/**
 * /api/platforms：9 大平台举证包规格。
 * 数据唯一事实来源为 Python demo/platforms.py 的 EVIDENCE_SPECS（逐字段照搬，
 * 仅把 Python 的字符串数组/对象转成 Obj/Arr 构造）。platforms.py 未定义 region，
 * 这里按平台主要市场补一个合理的宏观地区值。
 */
private func platforms(ctx: AppContext): ApiResponse {
    let items = Arr()
        // ---------------- Amazon ----------------
        .raw(Obj()
            .str("key", "Amazon")
            .str("label", "Amazon")
            .str("return_window", "自营 30 天；FBA 由 Amazon 处理退货与退款")
            .str("response_window", "A-to-z 索赔须在 72 小时内响应，否则自动判负并扣款")
            .str("shipping_payer", "A-to-z 下买家先垫付，裁决后由责任方承担；使用 Buy Shipping 准时发货可获保护")
            .str("burden_bias", "偏向买家（A-to-z 保障对买家极友好，卖家须主动举证）")
            .raw("required_evidence", Arr()
                .str("有效物流追踪号（平台认可承运商，如 ePacket / DHL Global Mail）")
                .str("妥投证明 POD（签收 / 签名确认截图）")
                .str("商品状况照片 / 视频（含瑕疵特写）")
                .str("Buyer-Seller Messaging 内的沟通记录")
                .str("正品采购发票（应对假货投诉）")
                .str("商品合规认证（CE / FCC 等，如适用）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("72 小时内未响应 A-to-z → 自动判负并扣款")
                .str("缺妥投证明 POD，无法证明已送达")
                .str("假货投诉无采购发票佐证")
                .str("实物与 listing 描述不符（货不对板）")
                .str("FBA 仍可能因错发 / 过期 / 侵权判卖家责")
                .build())
            .raw("special_clauses", Arr()
                .str("ODR 订单缺陷率目标 <1%（建议 ≤0.8%）")
                .str("裁决后 30 天内可凭新证据申诉（成功率 <15%）")
                .str("AI 自动裁决试点中，处理周期目标缩至 5 天")
                .str("禁止诱导线下退款（Anti-Incentives，扣绩效分、可能冻店）")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "退货图红框标注瑕疵/污损，证明退回时真实状态，反驳「无损」主张")
                .str("SKU 同款比对", "相似度证明退回件与售出货品为同一件，反驳调包/发错货指控")
                .str("瑕疵聚类归因", "定位高频缺陷品类，反哺选品与供应商整改，降低 ODR")
                .str("胜诉率参考", "同类目/供应商历史胜诉率，评估举证投入产出")
                .str("取证卷宗", "一键归档追踪号/POD/沟通/照片，生成可提交的 A-to-z 举证材料")
                .build())
            .str("region", "全球")
            .build())
        // ---------------- AliExpress ----------------
        .raw(Obj()
            .str("key", "AliExpress")
            .str("label", "AliExpress")
            .str("return_window", "确认收货后 15 天内可开纠纷（保护期通常 60 天，部分 90 天免退）")
            .str("response_window", "纠纷协商期卖家 5 天响应；清晰证据案件 2025 起 48 小时内裁定")
            .str("shipping_payer", "未收到 / 严重不符由卖家承担；低值（<$5）可免退仅退款")
            .str("burden_bias", "偏向买家（escrow 放款前须买家确认，举证清晰则高胜率）")
            .raw("required_evidence", Arr()
                .str("瑕疵照片 / 视频（电子类建议视频）")
                .str("商品与 listing 图文差异截图")
                .str("物流追踪页截图（未收到时）")
                .str("与卖家的沟通记录")
                .str("完整证据包（照片+视频可显著提升胜率）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("未提供 / 证据不足 → 纠纷关闭、放款给卖家（买家败诉）")
                .str("过早点击「确认收货」放弃保护")
                .str("提前关闭纠纷无法重开")
                .str("描述与实物差异但无图文对比证据")
                .build())
            .raw("special_clauses", Arr()
                .str("2025 起清晰证据案件 48 小时内裁定")
                .str("<$5 低值订单自动免退仅退款")
                .str("Free Returns 计划：部分商品 90 天免运费退")
                .str("务必确认收货前满意再确认，勿私下和解")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注瑕疵部位，直观证明「与描述不符」")
                .str("SKU 同款比对", "证明发出商品与订单一致，反驳「错发/调包」")
                .str("瑕疵聚类归因", "识别高频不符品类，优化 listing 图文一致性")
                .str("胜诉率参考", "类目胜诉率辅助判断申诉优先级")
                .str("取证卷宗", "归档图文证据与沟通，形成可提交纠纷的证据链")
                .build())
            .str("region", "全球")
            .build())
        // ---------------- Temu ----------------
        .raw(Obj()
            .str("key", "Temu")
            .str("label", "Temu")
            .str("return_window", "无理由退货签收后 30 天内；质量问题凭证据可延至 90 天")
            .str("response_window", "收到退货申请 24 小时内确认（2025 新规逾期默认同意）；争议 48 小时内上传凭证")
            .str("shipping_payer", "质量问题卖家/平台承担；非质量买家承担，手续费 5–15%（最低 $2）")
            .str("burden_bias", "平台主导仲裁（AI 辅助判责，卖家须自证无过错）")
            .raw("required_evidence", Arr()
                .str("发货前商品完好证明（带时间戳照片 / 视频）")
                .str("发货单 / 物流轨迹")
                .str("质检报告（质量争议）")
                .str("与买家沟通截图")
                .str("高价值品建议开箱视频")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("描述误导（材质虚标）→ 全额退款 + 商品下架")
                .str("证据不足 → 判卖家责、扣保证金")
                .str("逾期未响应 → 默认同意退货 / 自动判负")
                .str("非质量退货未保持原状被拒收")
                .build())
            .raw("special_clauses", Arr()
                .str("2025-07 上线争议仲裁系统，86% 案件 7 工作日内裁定")
                .str("AI 判责准确率 87%，争议 >$50 触发人工复核")
                .str("默认支持 7 天无理由，卖家不可拒绝")
                .str("全托管模式退货由平台主导")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "对比发货前/退货后红框，证明商品状态变化非卖家责")
                .str("SKU 同款比对", "证明所发即所售，反驳「发错货」指控")
                .str("瑕疵聚类归因", "定位质量争议高发品类，推动供应商整改")
                .str("胜诉率参考", "供应商维度胜诉率，识别高风险供货方")
                .str("取证卷宗", "归档发货前证据链，提交平台仲裁自证")
                .build())
            .str("region", "全球")
            .build())
        // ---------------- SHEIN ----------------
        .raw(Obj()
            .str("key", "SHEIN")
            .str("label", "SHEIN")
            .str("return_window", "收货后 30 天无忧退货；欧盟仓须遵守 14 天无理由")
            .str("response_window", "争议由 SHEIN 客服裁决，供应商须在 48 小时内提供证据链")
            .str("shipping_payer", "质量 / 发错货卖家承担（平台发预付标签）；个人偏好买家承担")
            .str("burden_bias", "平台裁判，供应商须提供生产 / 质检证据自证")
            .raw("required_evidence", Arr()
                .str("发货前质检照片（易损部位特写）")
                .str("生产记录 / 质检单（LOT 批次）")
                .str("物流追踪（≥17 位单号）+ 签收记录")
                .str("与买家沟通记录")
                .str("批次留样（建议保存 3 个月）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("无法证明发货前质量 → 判卖家责")
                .str("图文 / 实物不一致被判定误导")
                .str("恶意退货（买家损坏后退回）无发货前照片反驳")
                .str("退货率 >8% 触发供应商约谈，>1% 品质投诉暂停上新")
                .build())
            .raw("special_clauses", Arr()
                .str("退货地须标注 'China' 而非 'Hong Kong'，否则视为虚假发货罚款")
                .str("EPR / CE / REACH 合规前置（违规扣保证金 ¥50,000）")
                .str("批次留样 3 个月 + LOT 追溯降低举证难度")
                .str("纠纷率红线 3%，>5% 扣分（12 分/月暂停销售）")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注发货前完好/退货后差异，反驳恶意退货")
                .str("SKU 同款比对", "证明所发商品与订单一致，反驳错发")
                .str("瑕疵聚类归因", "定位品质投诉高发品类，指导留样与质检重点")
                .str("胜诉率参考", "供应商质量分辅助遴选合规工厂")
                .str("取证卷宗", "归档生产/质检/LOT 证据，满足 SHEIN 48h 举证时效")
                .build())
            .str("region", "全球")
            .build())
        // ---------------- eBay ----------------
        .raw(Obj()
            .str("key", "eBay")
            .str("label", "eBay")
            .str("return_window", "交付/预计交付后 30 天（以较长者为准）；卖家自设退货政策须 ≥ MBG 标准")
            .str("response_window", "3 个工作日内响应买家请求；收到退货后 2 个工作日内退款（逾期 eBay 自动代退）")
            .str("shipping_payer", "\"Not as described\" 卖家承担退回运费；买家 remorse 按卖家退货政策执行")
            .str("burden_bias", "偏向买家（MBG 即使卖家不提供退货也强制退款；假货无需退回即退款）")
            .raw("required_evidence", Arr()
                .str("商品与 listing 描述一致的图文对比（反驳 SNAD — Significantly Not As Described）")
                .str("发货前商品状况照片/视频（证明发出时完好）")
                .str("有效物流追踪号 + 妥投证明 POD")
                .str("正品采购发票/授权书（应对假货/仿冒投诉）")
                .str("买卖双方沟通记录（eBay Messages 截图）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("3 个工作日内未响应 → eBay 自动接受退货")
                .str("收到退货后超 2 天未退款 → eBay 自动代退并扣款")
                .str("无法证明\"与描述一致\" → SNAD 判买家胜")
                .str("假货投诉无采购凭证 → 直接判负 + 可能账号限制")
                .str("退货政策低于 MBG 最低标准 → 政策违规")
                .build())
            .raw("special_clauses", Arr()
                .str("MBG 覆盖几乎所有品类（车辆/房产/数字内容/工业设备除外），自动生效、无额外费用")
                .str("14 天退货政策仅限特定品类（珠宝/收藏品/相机/医疗器械）")
                .str("TRS（Top Rated Seller）可享部分退款折扣 + 额外保护")
                .str("禁止诱导线下退款（违反可能降权/冻结）")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注 SNAD 争议点（与 listing 描述差异），支持 MBG 申诉")
                .str("SKU 同款比对", "MBG 下证明\"收到的即发出的\"，反驳调包假货")
                .str("瑕疵聚类归因", "定位 SNAD 高发品类，优化 listing 准确性")
                .str("胜诉率参考", "MBG 历史裁决趋势 + 卖家 Defect Rate 变化")
                .str("取证卷宗", "归档 MBG 所需全套证据（追踪/POD/发票/沟通），3 日响应窗口内可用")
                .build())
            .str("region", "全球")
            .build())
        // ---------------- Shopee ----------------
        .raw(Obj()
            .str("key", "Shopee")
            .str("label", "Shopee")
            .str("return_window", "Mall 店铺 = 15 天（送达起）；Non-Mall（Marketplace/Preferred）= 7 天；In-Transit RR 可在途中拦截")
            .str("response_window", "质询 48h 内响应；Dispute 申诉 Online=3 天、Offline=1 个月；warranty case 14 天内提供解决方案")
            .str("shipping_payer", "SSL（Shopee Supported Logistics）丢件 Shopee 自动补偿卖家；非 SSL 卖家自理承运商索赔；质量争议卖家承担退货运费")
            .str("burden_bias", "平台裁决为主，卖家可在裁决后 2 天内 Dispute 并附证据申诉（但成功率有限）")
            .raw("required_evidence", Arr()
                .str("发货前商品完好照片/视频（含时间戳、防伪标签）")
                .str("物流追踪号 + 承运商交接证明（非 SSL 尤其重要）")
                .str("商品与 listing 图文差异对比截图")
                .str("与买家的站内沟通记录")
                .str("批次留样 / 生产质检单（Mall 店铺建议保留 3 个月）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("48h 内未响应质询 → 平台直接批准买家请求")
                .str("非 SSL 物流无法提供有效追踪 → 丢件判卖家责且无法获补偿")
                .str("无发货前照片 → \"损坏/瑕疵\" 类争议难以反驳")
                .str("买家滥用退货（可疑账户被 watch list 限制，但普通卖家难触发此机制）")
                .str("电子产品拆封/使用痕迹 → 不符合「原封/可转售」条件")
                .build())
            .raw("special_clauses", Arr()
                .str("Shopee Guarantee Period 内资金由平台托管（escrow 模式）")
                .str("Return on the Spot: COD 单当场验货退货（2025-07 新增）")
                .str("2025-08 起\"I want to return in original/sealed condition\"设免费退货额度（Platinum 3 次/月，普通 2 次/月）")
                .str("Counterfeit 理由仅限 Mall/FBS/Preferred+ 卖家使用")
                .str("东南亚六国本地化规则差异大（新加坡/马来西亚/菲律宾/泰国/印尼/越南各自有变体）")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注瑕疵/缺件/破损，支撑 Dispute 申诉证据包")
                .str("SKU 同款比对", "SSL 物流下证明包裹完整性；非 SSL 佐证承运商责任")
                .str("瑕疵聚类归因", "按 Mall/Non-Mall 分层定位缺陷热点，指导质检投入")
                .str("胜诉率参考", "Dispute 胜诉率 + Shopee 裁决倾向分析")
                .str("取证卷宗", "归档 SSL 追踪/非 SSL 承运商证据 + 2 日 Dispute 窗口材料")
                .build())
            .str("region", "东南亚")
            .build())
        // ---------------- Lazada ----------------
        .raw(Obj()
            .str("key", "Lazada")
            .str("label", "Lazada")
            .str("return_window", "LazMall / Choice 订单 = 30 天；Marketplace / LazGlobal = 15 天；RedMart = 7 天")
            .str("response_window", "2 个工作日内响应退款申请（逾期系统自动批准）；LazMall 退款处理 3-5 个工作日")
            .str("shipping_payer", "非质量问题买家承担；质量问题/错发卖家承担；LazMall Guaranteed Return 未按时处理赔 LazCash")
            .str("burden_bias", "LazMall Guaranteed Return 强保障买家；平台仲裁 + LazCash 补偿机制")
            .raw("required_evidence", Arr()
                .str("发货前商品完好照片（原始包装/标签完整）")
                .str("物流追踪 + 签收证明（尤其 LazGlobal 跨境订单）")
                .str("商品与 listing 描述一致性证据")
                .str("生产批次 / LOT 追溯信息（LazMall 品牌/授权卖家建议备）")
                .str("开箱视频（高价值品必备）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("2 日内未响应 → 系统自动批准退款")
                .str("LazMall Guaranteed Return 超时（>3 工作日）→ 赔偿买家 LazCash（从卖家扣除）")
                .str("退货商品状态不符（已使用/缺配件/包装破损）→ 可拒收但需举证")
                .str("跨境订单退货至香港/当地仓 → 处理周期长（2-4 周），期间资金冻结")
                .str("错发产品每件罚款 $5（Lazada 新措施）")
                .build())
            .raw("special_clauses", Arr()
                .str("LazMall 三重保证：Guaranteed Stock / Guaranteed Return / Guaranteed Delivery")
                .str("LazCash 补偿机制（15 天内领取，1 年有效期）")
                .str("东南亚六国本地化退货中心（印尼/泰国设跨境中心处理退货）")
                .str("Choice 计划卖家享更高曝光 + 退货优惠")
                .str("\"无理由退款\"标记仅在部分商品显示，非全品类支持")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框对比发出 vs 退回状态，LazMall Guaranteed Return 举证")
                .str("SKU 同款比对", "跨境订单证明发出-退回一致性（防调包）")
                .str("瑕疵聚类归因", "LazMall vs Marketplace 分层缺陷分析，品牌保护")
                .str("胜诉率参考", "LazMall Guaranteed Return 赔付率 + 退款时效")
                .str("取证卷宗", "归档 LazMall Claim Form + 退货凭证 + LOT 追溯")
                .build())
            .str("region", "东南亚")
            .build())
        // ---------------- Walmart ----------------
        .raw(Obj()
            .str("key", "Walmart")
            .str("label", "Walmart")
            .str("return_window", "标准品 30 天（多数品类）；部分品类 90 天（无线电话/大型家电等例外更短）；旺季（10/1–12/31 购买）延长至次年 1 月 31 日")
            .str("response_window", "收到退货后 **48 小时**内确认并退款（逾期 Walmart 自动代退，计入 ODR 缺陷率）")
            .str("shipping_payer", "Walmart 过失（运输破损/丢失/错发）承担退货运费；否则卖家承担（含 return processing fee）；Keep It 规则可免退回")
            .str("burden_bias", "偏向买家（ODR<1% 红线极严；Walmart 可代表卖家拒绝/批准退货；Keep It 规则买家保留商品仍获退款）")
            .raw("required_evidence", Arr()
                .str("有效物流追踪码（17 位以上，Walmart 要求）")
                .str("退货签收入库记录 / 仓库扫描证明")
                .str("商品状况照片（退回时的实际状态 vs 发出时）")
                .str("采购发票 / 品牌授权（应对假货/知识产权投诉）")
                .str("Dispute 申诉材料（若对退货判定有异议）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("超 48 小时未退款 → Walmart 自动代退 + ODR 扣分")
                .str("ODR >1% 连续两月 → 商品下架 / 店铺冻结")
                .str("无有效追踪码 → 丢失件判卖家责")
                .str("退回商品不可售状态（已使用/损坏）→ Keep It 场景下卖家损失商品 + 退款")
                .str("手动修改退款金额 → 触发财务审计")
                .build())
            .raw("special_clauses", Arr()
                .str("ODR（Order Defect Rate）红线 <1%（建议 ≤0.8%）")
                .str("WFS（Walmart Fulfillment Services）：平台代管退货全流程，费用 $5.99/件")
                .str("Keep It Rule：按品类设置价格区间，买家保留商品仍获退款（防退回损耗）")
                .str("Free & Easy Returns 全渠道计划（线上/门店 ~5000 家店均可退）")
                .str("2026 年\"一键通全球\"：美国站卖家一键拓展加拿大/墨西哥/智利")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注退回商品实际状况，支撑 Dispute 或 ODR 申诉")
                .str("SKU 同款比对", "WFS vs Seller Fulfilled 均适用：证明退回件即原商品")
                .str("瑕疵聚类归因", "按 WFS vs Seller Fulfilled 分层，ODR 驱动整改")
                .str("胜诉率参考", "ODR 趋势 + Dispute 成功率 + Keep It 规则命中率")
                .str("取证卷宗", "归档追踪码(17位)/签收/Dispute 材料，48h 退款窗口内就绪")
                .build())
            .str("region", "北美")
            .build())
        // ---------------- TikTok Shop ----------------
        .raw(Obj()
            .str("key", "TikTok Shop")
            .str("label", "TikTok Shop")
            .str("return_window", "标准 30 天（交付起）；质量问题/损坏 90 天 Money-Back Guarantee；节假日可延长（如 2025 黑五至 2026/2/10）")
            .str("response_window", "退货审核 ≤$100 为 2 日、>$100 为 4 日；取消请求 24h 内响应；纠纷升级 2-4 日（按金额）")
            .str("shipping_payer", "多数商品免费退货（55K 投递点 UPS/USPS/FedEx/Walgreens）；质量问题平台可能报销退货运费；商家可设自主退款不退货规则")
            .str("burden_bias", "平台主导（TikTok Shop 客服最终裁决；商家可申诉但需按标准仲裁流程；店铺停用时 TikTok 代处理全部退款）")
            .raw("required_evidence", Arr()
                .str("发货前商品完好照片/视频（原包装/标签/序列号）")
                .str("物流追踪号 + 签收证明")
                .str("商品与直播/短视频展示一致性证据（TikTok 特有：内容 vs 实物）")
                .str("与买家的站内沟通记录")
                .str("退货商品状态比对（退回时 vs 发出时，证明是否被调包/使用过）")
                .build())
            .raw("common_loss_reasons", Arr()
                .str("2-4 日内未审核 → 系统自动批准退货/退款")
                .str("买家退回错误商品 → 商家需在 2-4 日内拒付并说明原因（否则默认通过）")
                .str("直播/短视频展示与实物严重不符 → 'Not as described' 高发区")
                .str("SFCR（商责取消率）过高 → 限流/降权")
                .str("退货商品已被使用/损坏 → 可反转退款但需强证据")
                .build())
            .raw("special_clauses", Arr()
                .str("Money-Back Guarantee：90 天质量保障（即使标准退货窗已关闭）")
                .str("TikTok Shop Balance：虚拟余额即时退款（分钟级到账，替代传统支付 3-10 天）")
                .str("FBT（Fulfillment by TikTok）：平台仓发订单退货由 TikTok 代处理")
                .str("55K 线下投递点 + QR Code 免标签退货")
                .str("直播电商特有风险：主播口头承诺与 listing 不一致易引发纠纷")
                .str("禁止将交易引导至 TikTok 之外（违规处罚包括限流/关店）")
                .build())
            .raw("capability_map", Obj()
                .str("关键帧红框标注", "红框标注直播展示 vs 实物差异（TikTok 特有高频纠纷源）")
                .str("SKU 同款比对", "直播电商高价值场景：证明实物与直播展示品一致")
                .str("瑕疵聚类归因", "直播话术 vs 实物偏差聚类，反哺主播培训")
                .str("胜诉率参考", "纠纷升级裁决率 + SFCR 趋势 + 90 天保障利用率")
                .str("取证卷宗", "归档直播截图/发货证据/沟通记录，2-4 日审核窗口内可用")
                .build())
            .str("region", "全球")
            .build())
        .build()
    return ApiResponse.ok(Obj().raw("platforms", items).build())
}

private func register(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    let username = body.getOr("username", "")
    let password = body.getOr("password", "")
    let tenant = body.getOr("tenant_name", "")
    let r = ctx.auth.register(username, password, tenant)
    if (!r.ok) { return ApiResponse.fail(ErrKind.BadRequest, r.reason) }
    return ApiResponse.ok(Obj().boolean("ok", true).str("token", r.token).str("username", username).build())
}

/** 国密注册：PBKDF2-HMAC-SM3 派生口令（信创场景）。 */
private func registerSm3(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    let username = body.getOr("username", "")
    let password = body.getOr("password", "")
    let tenant = body.getOr("tenant_name", "")
    let r = ctx.auth.registerSm3(username, password, tenant)
    if (!r.ok) { return ApiResponse.fail(ErrKind.BadRequest, r.reason) }
    return ApiResponse.ok(Obj().boolean("ok", true).str("token", r.token)
        .str("username", username).str("hash_algo", "sm3").build())
}

/** 国密能力声明（如实呈现：密钥派生 SM3 可用；令牌签名仍 HMAC-SHA256 兼容存量）。 */
/** /api/ai/providers：14 平台能力矩阵（公开端点，不含密钥/密钥状态）。 */
private func aiProviders(ctx: AppContext, req: ApiRequest): ApiResponse {
    return ApiResponse.ok(Obj()
        .str("current", ctx.aiProviderKey)
        .boolean("configured", ctx.ai.configured())
        .raw("providers", ctx.aiProviders.capabilitiesJson())
        .build())
}

/** 密钥掩码：只保留后 4 位，其余以 * 代替；空串返回空串。 */
private func maskKey(key: String): String {
    if (key.isEmpty()) { return "" }
    if (key.size <= 4) { return "****" }
    var out = ""
    for (i in 0..(key.size - 4)) { out += "*" }
    return out + key[key.size - 4..key.size]
}

/**
 * GET /api/ai/settings：完整 AI 配置（需登录）。
 * 密钥绝不回传，只给 apiKeySet + 后四位掩码；apiKey 字段恒为空串（留空不改语义）。
 */
private func aiSettingsGet(ctx: AppContext, req: ApiRequest): ApiResponse {
    if (currentUser(ctx, req).isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let cfg = AiSettingsStore().load()
    let current = ctx.aiProviderKey
    let effectiveSaved = if (cfg.provider.isEmpty()) { current } else { cfg.provider }
    return ApiResponse.ok(Obj()
        .str("current", current)
        .str("provider", effectiveSaved)
        .str("baseUrl", cfg.baseUrl)
        .str("model", cfg.model)
        .boolean("enabled", cfg.enabled)
        .boolean("onlineAllowed", cfg.onlineAllowed)
        .boolean("apiKeySet", !cfg.apiKey.isEmpty())
        .str("apiKeyMask", maskKey(cfg.apiKey))
        .str("apiKey", "")   // 永不回传密钥
        .boolean("pendingRestart", effectiveSaved != current || !cfg.apiKey.isEmpty() || !cfg.baseUrl.isEmpty() || !cfg.model.isEmpty())
        .boolean("envOverride", !(getVariable("RG_AI_PROVIDER") ?? "").isEmpty() || !(getVariable("MODEL_ROUTER_PROFILE") ?? "").isEmpty())
        .build())
}

/**
 * POST /api/ai/settings：保存完整 AI 配置（需登录）。
 * 校验：provider 必须在注册表；baseUrl 须 http(s)://；apiKey 留空则保留原密钥。重启后生效。
 */
private func aiSettingsPost(ctx: AppContext, req: ApiRequest): ApiResponse {
    if (currentUser(ctx, req).isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let body = FlatJson.parse(req.bodyText())
    let provider = body.getOr("provider", "")
    if (provider.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "provider 必填") }
    if (ctx.aiProviders.get(provider).isNone()) { return ApiResponse.fail(ErrKind.BadRequest, "未知 provider：${provider}") }
    let baseUrl = body.getOr("baseUrl", "")
    if (!baseUrl.isEmpty() && !(baseUrl.startsWith("https://") || baseUrl.startsWith("http://"))) {
        return ApiResponse.fail(ErrKind.BadRequest, "端点须以 http:// 或 https:// 开头")
    }
    let model = body.getOr("model", "")
    let apiKey = body.getOr("apiKey", "")
    let clearKey = body.getOr("clearKey", "false") == "true"
    // 防止换行注入配置文件（值按行存储）
    if (apiKey.contains("\n") || apiKey.contains("\r") || baseUrl.contains("\n") || model.contains("\n")) {
        return ApiResponse.fail(ErrKind.BadRequest, "字段不能包含换行")
    }
    let enabledStr = body.getOr("enabled", "true")
    let onlineStr = body.getOr("onlineAllowed", "true")
    let cfg = AiConfig(provider, apiKey, baseUrl, model,
        enabledStr != "false" && enabledStr != "0", onlineStr != "false" && onlineStr != "0")
    let ok = AiSettingsStore().save(cfg, clearKey: clearKey)
    if (!ok) { return ApiResponse.fail(ErrKind.Internal, "保存失败：配置目录不可写") }
    return ApiResponse.ok(Obj()
        .str("provider", provider)
        .str("current", ctx.aiProviderKey)
        .boolean("apiKeySet", !AiSettingsStore().load().apiKey.isEmpty())
        .boolean("pendingRestart", true)
        .str("note", "已保存，重启后端服务后生效")
        .build())
}

private func cryptoCapabilities(ctx: AppContext, req: ApiRequest): ApiResponse {
    let algos = Arr().str("SM3").str("SM4-CBC").str("PBKDF2-HMAC-SM3").build()
    return ApiResponse.ok(Obj()
        .boolean("sm3", true).boolean("sm4", true)
        .raw("algorithms", algos)
        .str("password_kdf", "PBKDF2-HMAC-SM3 (可选) / PBKDF2-HMAC-SHA256 (默认，兼容存量)")
        .str("token_signature", "HMAC-SHA256 (兼容存量令牌；后续可切 HMAC-SM3)")
        .build())
}

private func totpSetup(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let pair = ctx.auth.totpSetup(user, "ReturnGuard")
    let parts = pair.split("|").toArray()
    let secret = if (parts.size >= 1) { parts[0] } else { "" }
    let uri = if (parts.size >= 2) { parts[1] } else { "" }
    return ApiResponse.ok(Obj().str("secret", secret).str("otpauth_url", uri).build())
}

private func totpEnable(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let body = FlatJson.parse(req.bodyText())
    let ok = ctx.auth.totpEnable(user, body.getOr("secret", ""), body.getOr("code", ""))
    if (!ok) { return ApiResponse.fail(ErrKind.BadRequest, "验证码错误") }
    return ApiResponse.ok(Obj().boolean("ok", true).build())
}

private func totpVerify(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let body = FlatJson.parse(req.bodyText())
    return ApiResponse.ok(Obj().boolean("ok", ctx.auth.totpVerify(user, body.getOr("code", ""))).build())
}

private func totpDisable(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let body = FlatJson.parse(req.bodyText())
    let ok = ctx.auth.totpDisable(user, body.getOr("code", ""))
    if (!ok) { return ApiResponse.fail(ErrKind.BadRequest, "验证码错误或未绑定") }
    return ApiResponse.ok(Obj().boolean("ok", true).build())
}

private func totpStatus(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    return ApiResponse.ok(Obj().boolean("enabled", ctx.auth.totpEnabled(user)).build())
}

/** 当前用户的会话列表（设备/IP/时间/撤销状态）。 */
private func sessions(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let listJson = ctx.auth.sessionsOf(user)
    return ApiResponse.ok(Obj().raw("sessions", listJson).build())
}

/** 远程踢出指定会话（sid）。 */
private func revokeSession(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let body = FlatJson.parse(req.bodyText())
    let sid = body.getOr("sid", "")
    if (sid.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "缺少 sid") }
    ctx.auth.revokeSession(user, sid)
    return ApiResponse.ok(Obj().boolean("ok", true).build())
}

private func login(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    let username = body.getOr("username", "")
    let password = body.getOr("password", "")
    let r = ctx.auth.login(username, password, req.remoteAddr)
    if (!r.ok) { return ApiResponse.fail(ErrKind.Unauthorized, r.reason) }
    // 登录成功后签发 access + refresh 令牌对（refresh 一次性轮换）
    let pair = ctx.auth.issueTokenPair(username, req.remoteAddr)
    return ApiResponse.ok(Obj()
        .boolean("ok", true).str("token", pair.access).str("refresh_token", pair.refresh)
        .str("username", username).build())
}

/** POST /api/auth/refresh：一次性轮换 access+refresh；重放检测触发全会话撤销。 */
/** POST /api/oauth/register：注册第三方客户端（需登录；secret 仅返回一次）。 */
private func oauthRegister(ctx: AppContext, req: ApiRequest): ApiResponse {
    let owner = currentUser(ctx, req)
    if (owner.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let body = FlatJson.parse(req.bodyText())
    let name = body.getOr("name", "")
    if (name.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "name 必填") }
    let scope = body.getOr("scope", "insights:read")
    let r = ctx.oauth.register(name, owner, scope: scope)
    return ApiResponse.ok(Obj()
        .str("client_id", r.clientId).str("client_secret", r.clientSecret)
        .str("scope", r.scope).str("note", "client_secret 仅本次返回，请妥善保存").build())
}

/** POST /api/oauth/token：client_credentials 换令牌（公开端点）。 */
private func oauthToken(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    if (body.getOr("grant_type", "client_credentials") != "client_credentials") {
        return ApiResponse.fail(ErrKind.BadRequest, "仅支持 client_credentials")
    }
    let cid = body.getOr("client_id", "")
    let secret = body.getOr("client_secret", "")
    if (cid.isEmpty() || secret.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "client_id/client_secret 必填") }
    match (ctx.oauth.issueToken(cid, secret)) {
        case Some(t) => return ApiResponse.ok(Obj()
            .str("access_token", t.accessToken).str("token_type", t.tokenType)
            .i64("expires_in", t.expiresIn).str("scope", t.scope).build())
        case None => return ApiResponse.fail(ErrKind.Unauthorized, "客户端凭据无效")
    }
}

/** GET /api/oauth/clients：列出已注册客户端（脱敏，需登录）。 */
private func oauthClients(ctx: AppContext, req: ApiRequest): ApiResponse {
    if (currentUser(ctx, req).isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    return ApiResponse.ok(Obj().raw("clients", ctx.oauth.listClients()).build())
}

/** POST /api/oauth/rotate：轮换客户端密钥（需登录，旧 secret 校验通过后立即失效）。 */
private func oauthRotate(ctx: AppContext, req: ApiRequest): ApiResponse {
    if (currentUser(ctx, req).isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let body = FlatJson.parse(req.bodyText())
    let cid = body.getOr("client_id", "")
    let old = body.getOr("client_secret", "")
    if (cid.isEmpty() || old.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "client_id 与 client_secret 必填") }
    let fresh = ctx.oauth.rotateSecret(cid, old)
    match (fresh) {
        case Some(s) => return ApiResponse.ok(Obj().str("client_id", cid).str("client_secret", s)
            .str("note", "新密钥仅返回一次，旧密钥已失效").build())
        case None => return ApiResponse.fail(ErrKind.BadRequest, "客户端不存在或旧密钥错误")
    }
}

private func refreshToken(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    let refresh = body.getOr("refresh_token", "")
    if (refresh.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "缺少 refresh_token") }
    match (ctx.auth.rotateRefresh(refresh, req.remoteAddr)) {
        case Some(pair) =>
            return ApiResponse.ok(Obj()
                .boolean("ok", true).str("token", pair.access)
                .str("refresh_token", pair.refresh).build())
        case None => return ApiResponse.fail(ErrKind.Unauthorized, "refresh 无效或已使用")
    }
}

private func me(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let u = ctx.auth.userOf(user)
    let tenantName = match (u) { case Some(rec) => rec.tenantName; case None => user }
    let userObj = Obj().str("username", user).str("tenant_name", tenantName).build()
    return ApiResponse.ok(Obj().boolean("ok", true).raw("user", userObj).str("tenant", user).build())
}

/** 数据录入：列出当前租户最近案件（新录入的在前，最多 50 条）。 */
private func listCases(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let all = ctx.store.casesOf(user)
    let arr = Arr()
    var start = all.size - 50
    if (start < 0) { start = 0 }
    var i = all.size - 1
    while (i >= start) {
        let c = all[i]
        arr.raw(Obj()
            .str("case_id", c.caseId)
            .str("sku", c.sku)
            .str("category", c.category)
            .str("supplier", c.supplier)
            .str("platform", c.platform)
            .str("region", c.region)
            .str("season", c.season)
            .f64("amount", c.amount)
            .f64("similarity", c.similarity)
            .str("outcome", c.outcome)
            .str("defect", c.defect)
            .build())
        i -= 1
    }
    return ApiResponse.ok(Obj().i64("total", all.size).raw("cases", arr.build()).build())
}

/** 数据录入：手动新增一条案件（写入当前租户内存 + 落库回调）。 */
private func addCase(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let body = FlatJson.parse(req.bodyText())
    let sku = body.getOr("sku", "")
    if (sku.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "SKU 不能为空") }
    let caseId = "manual-${DateTime.now().toUnixTimeStamp().toMilliseconds()}"
    let c = CaseRec(
        caseId, user,
        sku, body.getOr("category", ""), body.getOr("supplier", ""),
        body.getOr("platform", ""), body.getOr("region", ""), body.getOr("season", ""),
        parseF64Safe(body.getOr("amount", "0")), parseF64Safe(body.getOr("similarity", "0")),
        body.getOr("outcome", "待分析"), body.getOr("defect", ""))
    ctx.store.addCase(c)
    return ApiResponse.ok(Obj().boolean("ok", true).str("case_id", c.caseId).build())
}

/** 删除一条案件（严格限定当前租户，防越权删除）。 */
private func deleteCase(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let caseId = match (req.pathParam("caseId")) {
        case Some(v) => v
        case None => return ApiResponse.fail(ErrKind.BadRequest, "缺少案件编号")
    }
    if (caseId.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "缺少案件编号") }
    let removed = ctx.store.removeCase(caseId, user)
    if (!removed) { return ApiResponse.fail(ErrKind.NotFound, "案件不存在或无权删除") }
    return ApiResponse.ok(Obj().boolean("ok", true).str("case_id", caseId).build())
}

/** 宽松浮点解析：解析失败返回 0（录入表单容错）。 */
private func parseF64Safe(s: String): Float64 {
    if (s.isEmpty()) { return 0.0 }
    let bytes = s.toArray()
    let n = bytes.size
    var neg = false
    var i = 0
    if (n > 0 && bytes[0] == 0x2d) { neg = true; i = 1 }  // '-'
    var whole: Int64 = 0
    var digits = 0
    while (i < n && bytes[i] >= 0x30 && bytes[i] <= 0x39) {
        whole = whole * 10 + Int64(bytes[i]) - 48
        digits += 1
        i += 1
    }
    var frac: Float64 = 0.0
    var scale: Float64 = 10.0
    if (i < n && bytes[i] == 0x2e) {  // '.'
        i += 1
        while (i < n && bytes[i] >= 0x30 && bytes[i] <= 0x39) {
            frac += Float64(Int64(bytes[i]) - 48) / scale
            scale *= 10.0
            i += 1
        }
    }
    if (digits == 0 && frac == 0.0) { return 0.0 }
    let v = Float64(whole) + frac
    return if (neg) { -v } else { v }
}

private func logout(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    ctx.auth.logout(user)
    return ApiResponse.ok(Obj().boolean("ok", true).build())
}

/** 审计链自证端点：需登录（防匿名探测），返回链完整性、事件数与链头哈希。 */
/** GET /api/audit/list?limit=50：审计事件列表（最近 N 条，需登录）。 */
private func auditList(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    var limit: Int64 = 50
    match (req.queryParam("limit")) {
        case Some(v) =>
            let n = Int64(parseF64Safe(v))
            if (n > 0 && n <= 1000) { limit = n }
        case None => ()
    }
    return ApiResponse.ok(Obj()
        .i64("total", ctx.auth.audit.size())
        .raw("events", ctx.auth.audit.tail(limit))
        .build())
}

private func auditVerify(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "未登录") }
    let badSeq = ctx.auth.audit.verifyChain()
    let obj = Obj()
        .boolean("ok", badSeq == 0)
        .i64("events", ctx.auth.audit.size())
        .i64("first_bad_seq", badSeq)
        .str("head", ctx.auth.audit.head())
        .build()
    return ApiResponse.ok(obj)
}
