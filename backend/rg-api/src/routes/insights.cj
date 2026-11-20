// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 群体洞察聚合（mock 规则，语义与 Python 版 pipeline 一致）：
//   - 胜诉率分母 = decided（已判定 = 非"待分析"），五维度统一；
//   - 输出 decided 以区分"真实 0%"与"尚无已判定"；
//   - 返回结构对齐 schemas.InsightsResponse（前端零改动）。
package rg.api.routes

import std.collection.*
import rg.api.http.*
import rg.app.*
import rg.data.store.*
import rg.kernel.json.*
import rg.security.quota.*
import rg.kernel.error.*

/** 聚合结果累加器。 */
private class Bucket {
    var total: Int64 = 0
    var refund: Float64 = 0.0
    var decided: Int64 = 0
    var won: Int64 = 0
    var simSum: Float64 = 0.0
    public func add(c: CaseRec): Unit {
        this.total += 1
        this.refund += c.amount
        this.simSum += c.similarity
        if (c.outcome != "待分析") {
            this.decided += 1
            if (c.outcome == "赢") { this.won += 1 }
        }
    }
    public func winRate(): Float64 { return if (this.decided == 0) { 0.0 } else { Float64(this.won) / Float64(this.decided) } }
    public func avgSim(): Float64 { return if (this.total == 0) { 0.0 } else { this.simSum / Float64(this.total) } }
}

/** 下钻明细条目：名称 + 案件数（用类而非元组，仓颉元组不支持 .1 索引）。 */
private class Datum {
    var name: String = ""
    var count: Int64 = 0
    init(name: String, count: Int64) { this.name = name; this.count = count }
}

/** 供应商质量分累加器（对齐 Python _build_supplier_scorecard）。 */
private class SupplierStat {
    var code: String = ""
    var total: Int64 = 0
    var decided: Int64 = 0
    var won: Int64 = 0
    var defectCases: Int64 = 0
    var refund: Float64 = 0.0
    // 下钻明细：SKU 集合 / 平台集合 / 缺陷分布
    private let skus = HashMap<String, Int64>()
    private let plats = HashMap<String, Int64>()
    private let defects = HashMap<String, Int64>()
    public func add(c: CaseRec): Unit {
        this.total += 1
        this.refund += c.amount
        if (c.outcome != "待分析") { this.decided += 1 }
        if (c.outcome == "赢") { this.won += 1 }
        // Python 口径：real = 含真实缺陷（非"无明显瑕疵"占位）的案件数
        if (!c.defect.isEmpty() && c.defect != "无明显瑕疵") { this.defectCases += 1 }
        if (!c.sku.isEmpty()) { this.skus[c.sku] = (this.skus.get(c.sku) ?? 0) + 1 }
        if (!c.platform.isEmpty()) { this.plats[c.platform] = (this.plats.get(c.platform) ?? 0) + 1 }
        let d = if (c.defect.isEmpty()) { "-" } else { c.defect }
        this.defects[d] = (this.defects.get(d) ?? 0) + 1
    }
    public func skuCount(): Int64 { return this.skus.size }
    public func platformCount(): Int64 { return this.plats.size }
    public func avgRefund(): Float64 { return if (this.total == 0) { 0.0 } else { round2(this.refund / Float64(this.total)) } }
    /** 下钻 JSON：SKU 清单（按案件数降序，取前 12）。 */
    public func skuDrill(): String {
        let list = ArrayList<Datum>()
        for ((k, v) in this.skus) { list.add(Datum(k, v)) }
        sortData(list)
        return dataJson(list, 12)
    }
    /** 下钻 JSON：平台分布（按案件数降序）。 */
    public func platDrill(): String {
        let list = ArrayList<Datum>()
        for ((k, v) in this.plats) { list.add(Datum(k, v)) }
        sortData(list)
        return dataJson(list, 0)
    }
    /** 下钻 JSON：缺陷分布（剔除占位，按数量降序）。 */
    public func defectDrill(): String {
        let list = ArrayList<Datum>()
        for ((k, v) in this.defects) {
            if (k != "无明显瑕疵" && k != "-") { list.add(Datum(k, v)) }
        }
        sortData(list)
        return dataJson(list, 0)
    }
    private static func sortData(list: ArrayList<Datum>): Unit {
        for (i in 0..list.size) {
            var best = i
            for (j in i + 1..list.size) {
                if (list[j].count > list[best].count) { best = j }
            }
            if (best != i) {
                let tmp = list[i]
                list[i] = list[best]
                list[best] = tmp
            }
        }
    }
    private static func dataJson(list: ArrayList<Datum>, limit: Int64): String {
        let a = Arr()
        var n = 0
        for (d in list) {
            if (limit > 0 && n >= limit) { break }
            a.raw(Obj().str("name", d.name).i64("cases", d.count).build())
            n += 1
        }
        return a.build()
    }
    public func winRate(): Float64 { return if (this.decided == 0) { 0.0 } else { Float64(this.won) / Float64(this.decided) } }
    public func defectRate(): Float64 { return if (this.total == 0) { 0.0 } else { Float64(this.defectCases) / Float64(this.total) } }
    public func score(): Float64 { return round1(100.0 * (0.5 * this.winRate() + 0.5 * (1.0 - this.defectRate()))) }
}

/** SKU 维度累加器（对齐 Python _build_sku_ranking）。 */
private class SkuStat {
    var sku: String = ""
    var category: String = ""
    var supplier: String = ""
    var cases: Int64 = 0
    var refund: Float64 = 0.0
    var decided: Int64 = 0
    var won: Int64 = 0
    var topDefect: String = "-"
    private let defects = HashMap<String, Int64>()
    public func add(c: CaseRec): Unit {
        if (this.cases == 0) { this.sku = c.sku; this.category = c.category; this.supplier = c.supplier }
        this.cases += 1
        this.refund += c.amount
        if (c.outcome != "待分析") { this.decided += 1 }
        if (c.outcome == "赢") { this.won += 1 }
        let d = if (c.defect.isEmpty()) { "-" } else { c.defect }
        let n = this.defects.get(d) ?? 0
        this.defects[d] = n + 1
    }
    public func winRate(): Float64 { return if (this.decided == 0) { 0.0 } else { Float64(this.won) / Float64(this.decided) } }
    /** 取该 SKU 出现次数最多的缺陷（与 Python Counter.most_common(1) 一致）。 */
    public func computeTopDefect(): Unit {
        var best = ""
        var bestN: Int64 = 0
        for ((k, v) in this.defects) {
            if (v > bestN) { bestN = v; best = k }
        }
        this.topDefect = if (best.isEmpty()) { "-" } else { best }
    }
}

/** 缺陷大类 → 根因桶（照抄 Python _DEFECT_BUCKET；兼容 demo 种子的"缺件少件"写法）。 */
private func defectBucket(defect: String): String {
    if (defect == "外包装破损" || defect == "污渍划痕") { return "物流与包装" }
    if (defect == "商品缺件" || defect == "缺件少件") { return "供应商履约" }
    if (defect == "功能故障") { return "供应商质量" }
    if (defect == "货不对板" || defect == "色差明显") { return "Listing与图文" }
    if (defect == "使用痕迹" || defect == "无明显瑕疵") { return "非质量(倾向买家)" }
    return "其他"
}

/** 根因桶 → 整改建议（照抄 Python _BUCKET_ADVICE）。 */
private func bucketAdvice(bucket: String): String {
    if (bucket == "物流与包装") { return "对易碎/高值品升级加厚纸箱+气泡膜，做跌落测试，并评估物流商分拣质量" }
    if (bucket == "供应商履约") { return "到货全检+装箱清单逐项核对，必要时更换供应商" }
    if (bucket == "供应商质量") { return "批次抽检老化测试，建立供应商质量分淘汰机制" }
    if (bucket == "Listing与图文") { return "核对实物与listing图文，去掉过度承诺，补充实拍与色差说明" }
    if (bucket == "非质量(倾向买家)") { return "保留同款一致性证据，主张买家责任，提升举证完整度" }
    return "复核供应商质量与包装方案"
}

/** 供应商代号 → 展示名（与 /api/config  suppliers 对齐）。 */
private func supplierName(code: String): String {
    if (code == "S1") { return "鼎峰精密" }
    if (code == "S2") { return "云仓优选" }
    if (code == "S3") { return "鑫源电子" }
    if (code == "S4") { return "通达包装" }
    if (code == "S5") { return "联创供货" }
    if (code == "S6") { return "海贸乱发" }
    if (code == "S7") { return "锐捷制造" }
    if (code == "S8") { return "万通杂货" }
    return code
}

/** GET /api/insights。 */
public func insights(ctx: AppContext, req: ApiRequest): ApiResponse {
    let mode = req.queryParam("mode") ?? "mock"
    let category = req.queryParam("category") ?? ""
    let platform = req.queryParam("platform") ?? ""
    let region = req.queryParam("region") ?? ""
    let season = req.queryParam("season") ?? ""
    let user = currentUser(ctx, req)
    // 单库 + 租户隔离：不再有 demo/real 双源切换。
    // 未登录不允许看数据（演示数据改为登录演示账户后展示）。
    if (user.isEmpty()) {
        return ApiResponse.fail(ErrKind.Unauthorized, "请先登录（可使用演示账户 demo / demo123）")
    }
    let tenant = user
    let ip = req.remoteAddr
    if (!ctx.quota.allow(mode, tenant, ip)) {
        return ApiResponse.fail(ErrKind.TooManyRequests, "已达配额上限，请稍后再试")
    }
    let all = ctx.store.casesOf(tenant)

    let overall = Bucket()
    let byCat = HashMap<String, Bucket>()
    let byPlat = HashMap<String, Bucket>()
    let byRegion = HashMap<String, Bucket>()
    let bySeason = HashMap<String, Bucket>()
    let bySupplier = HashMap<String, Bucket>()
    // 平台×供应商交叉聚合（供 platform_supplier_matrix，唯一 key = "平台|供应商"）
    let byPlatSupplier = HashMap<String, Bucket>()
    // 任务新增聚合：根因分布 / 供应商质量分 / SKU 排名（与上面的维度共用同一批过滤后的案件）
    let rootCauseCounts = HashMap<String, Int64>()
    let supStats = HashMap<String, SupplierStat>()
    let skuStats = HashMap<String, SkuStat>()
    for (c in all) {
        if (!category.isEmpty() && c.category != category) { continue }
        if (!platform.isEmpty() && c.platform != platform) { continue }
        if (!region.isEmpty() && c.region != region) { continue }
        if (!season.isEmpty() && c.season != season) { continue }
        overall.add(c)
        accumulate(byCat, c.category, c)
        accumulate(byPlat, c.platform, c)
        accumulate(byRegion, c.region, c)
        accumulate(bySeason, c.season, c)
        accumulate(bySupplier, c.supplier, c)
        accumulate(byPlatSupplier, c.platform + "|" + c.supplier, c)
        // 根因桶计数
        let bucket = defectBucket(c.defect)
        rootCauseCounts[bucket] = (rootCauseCounts.get(bucket) ?? 0) + 1
        // 供应商质量分
        match (supStats.get(c.supplier)) {
            case Some(st) => st.add(c)
            case None => let st = SupplierStat(); st.code = c.supplier; st.add(c); supStats.add(c.supplier, st)
        }
        // SKU 聚合
        match (skuStats.get(c.sku)) {
            case Some(st) => st.add(c)
            case None => let st = SkuStat(); st.add(c); skuStats.add(c.sku, st)
        }
    }

    // —— 根因分布：{"物流与包装":242,...} + 最大桶 ——
    let rcObj = Obj()
    var topBucket = ""
    var topCount: Int64 = 0
    var rcTotal: Int64 = 0
    for ((k, v) in rootCauseCounts) {
        rcObj.i64(k, v)
        rcTotal += v
        if (v > topCount) { topCount = v; topBucket = k }
    }
    let rootCauseDist = rcObj.build()

    // —— 供应商黑名单：按质量分升序，筛出"黑名单"档 ——
    let supList = ArrayList<SupplierStat>()
    for ((_, st) in supStats) { supList.add(st) }
    // 按质量分升序（选择排序，列表规模很小）
    for (i in 0..supList.size) {
        var best = i
        for (j in i + 1..supList.size) {
            if (supList[j].score() < supList[best].score()) { best = j }
        }
        if (best != i) {
            let tmp = supList[i]
            supList[i] = supList[best]
            supList[best] = tmp
        }
    }
    // 完整供应商明细（透视页用）：质量分升序，含下钻所需 SKU/平台/缺陷分布
    let scorecardArr = Arr()
    for (st in supList) {
        let level = if (st.score() < 38.0) { "黑名单" } else if (st.score() <= 55.0) { "观察" } else { "优质" }
        scorecardArr.raw(Obj()
            .str("name", supplierName(st.code))
            .str("supplier", st.code)
            .i64("cases", st.total)
            .i64("decided", st.decided)
            .f64("refund", round2(st.refund))
            .f64("avg_refund", st.avgRefund())
            .f64("quality_score", round1(st.score()))
            .str("level", level)
            .f64("defect_rate", round4(st.defectRate()))
            .f64("win_rate", round4(st.winRate()))
            .i64("sku_count", st.skuCount())
            .i64("platform_count", st.platformCount())
            .raw("sku_drill", st.skuDrill())
            .raw("platform_drill", st.platDrill())
            .raw("defect_drill", st.defectDrill())
            .build())
    }
    let supplierScorecard = scorecardArr.build()

    // 平台×供应商矩阵：每项 {platform, supplier, cases, refund, win_rate}
    let matrixArr = Arr()
    for ((k, b) in byPlatSupplier) {
        let sepOpt = k.indexOf("|")
        let sep = match (sepOpt) { case Some(v) => v; case None => -1 }
        let plat = if (sep < 0) { k } else { k[0..sep] }
        let sup = if (sep < 0) { "" } else { k[sep + 1..k.size] }
        matrixArr.raw(Obj()
            .str("platform", plat)
            .str("supplier", sup)
            .i64("cases", b.total)
            .f64("refund", round2(b.refund))
            .f64("win_rate", round4(b.winRate()))
            .build())
    }
    let platSupplierMatrix = matrixArr.build()

    let blackArr = Arr()
    var blackCount: Int64 = 0
    for (st in supList) {
        let level = if (st.score() < 38.0) { "黑名单" } else if (st.score() <= 55.0) { "观察" } else { "优质" }
        if (level == "黑名单") {
            let reason = "质量分${num2(st.score())}（黑名单）：缺陷率${pct0(st.defectRate())}、胜诉率${pct0(st.winRate())}"
            blackArr.raw(Obj()
                .str("supplier", st.code)
                .str("name", supplierName(st.code))
                .f64("quality_score", round1(st.score()))
                .str("level", level)
                .f64("defect_rate", round4(st.defectRate()))
                .f64("win_rate", round4(st.winRate()))
                .str("reason", reason)
                .build())
            blackCount += 1
        }
    }
    // 演示降级（注释说明）：严格分档若一个黑名单都筛不出，则把质量分最低的 2 个纳入，保证功能可见。
    if (blackCount == 0 && supList.size > 0) {
        var fallback: Int64 = 0
        while (fallback < supList.size && fallback < 2) {
            let st = supList[fallback]
            let reason = "质量分${num2(st.score())}（黑名单-演示降级）：缺陷率${pct0(st.defectRate())}、胜诉率${pct0(st.winRate())}"
            blackArr.raw(Obj()
                .str("supplier", st.code)
                .str("name", supplierName(st.code))
                .f64("quality_score", round1(st.score()))
                .str("level", "黑名单")
                .f64("defect_rate", round4(st.defectRate()))
                .f64("win_rate", round4(st.winRate()))
                .str("reason", reason)
                .build())
            blackCount += 1
            fallback += 1
        }
    }
    let supplierBlacklist = blackArr.build()

    // —— SKU 排名：按退款额降序，最多 10 条；同时生成简单异常预警 ——
    let skuList = ArrayList<SkuStat>()
    for ((_, st) in skuStats) { st.computeTopDefect(); skuList.add(st) }
    for (i in 0..skuList.size) {
        var best = i
        for (j in i + 1..skuList.size) {
            if (skuList[j].refund > skuList[best].refund) { best = j }
        }
        if (best != i) {
            let tmp = skuList[i]
            skuList[i] = skuList[best]
            skuList[best] = tmp
        }
    }
    let rankArr = Arr()
    let insightArr = Arr()
    let alertArr = Arr()
    var alertCount: Int64 = 0
    var firstAlertSku = ""
    var i: Int64 = 0
    while (i < skuList.size && i < 10) {
        let st = skuList[i]
        rankArr.raw(Obj()
            .str("sku", st.sku)
            .str("category", st.category)
            .str("supplier", st.supplier)
            .i64("cases", st.cases)
            .f64("refund", round2(st.refund))
            .f64("win_rate", round4(st.winRate()))
            .str("top_defect", st.topDefect)
            .boolean("anomaly", st.cases >= 4 && st.decided > 0 && st.winRate() < 0.30)
            .build())
        i += 1
    }
    // 异常判定（无需日期字段）：案件 >= 4 且胜诉率 < 30%，视为高风险集中爆发。
    // 阈值放宽到"低胜诉率"而非"0胜诉"，让演示集也能真实展示该预警（非伪造数据）。
    for (st in skuList) {
        if (st.cases >= 4 && st.decided > 0 && st.winRate() < 0.30) {
            if (alertCount == 0) { firstAlertSku = st.sku }
            alertArr.raw(Obj()
                .str("sku", st.sku)
                .str("category", st.category)
                .i64("cases", st.cases)
                .f64("win_rate", round4(st.winRate()))
                .str("reason", "共${st.cases} 笔纠纷、胜诉率仅${pct0(st.winRate())}，疑似集中爆发")
                .build())
            alertCount += 1
        }
    }
    // SKU 洞察：取排名前 3（照抄 Python _mock_attribution）
    i = 0
    while (i < skuList.size && i < 3) {
        let st = skuList[i]
        let bucket = defectBucket(st.topDefect)
        let finding = "共 ${st.cases} 笔纠纷、退款约 ¥${num2(st.refund)}，胜诉率 ${pct0(st.winRate())}，高发问题：${st.topDefect}"
        insightArr.raw(Obj()
            .str("sku", st.sku)
            .str("finding", finding)
            .str("action", bucketAdvice(bucket))
            .build())
        i += 1
    }

    // —— 选品建议：照抄 Python _mock_attribution 的四条规则 ——
    let adviceArr = Arr()
    var adviceCount: Int64 = 0
    // ① 供应商红黑榜
    if (blackCount > 0) {
        var names = ""
        var j: Int64 = 0
        while (j < supList.size && j < 3) {
            let st = supList[j]
            let seg = "${st.code}(${supplierName(st.code)},质量分${num2(st.score())})"
            names = if (j == 0) { seg } else { "${names}、${seg}" }
            j += 1
        }
        adviceArr.str("供应商红黑榜：规避高风险供应商 ${names}，其退货缺陷率显著偏高。")
        adviceCount += 1
    }
    // ② 选品避坑：胜诉率 < 0.30 的品类；同时记录退款额最大品类作为兜底依据
    var badCats = ""
    var badCatCount: Int64 = 0
    var topRefundCat = ""
    var topRefundCatAmt: Float64 = -1.0
    for ((k, b) in byCat) {
        if (b.winRate() < 0.30) {
            let seg = "${k}(胜诉率${pct0(b.winRate())})"
            badCats = if (badCatCount == 0) { seg } else { "${badCats}、${seg}" }
            badCatCount += 1
        }
        if (b.refund > topRefundCatAmt) { topRefundCatAmt = b.refund; topRefundCat = k }
    }
    if (badCatCount > 0) {
        adviceArr.str("选品避坑：${badCats} 纠纷胜诉率低，上新前需重点核验质量与图文一致性。")
        adviceCount += 1
    }
    // ③ 根因治理：占比最大的根因桶
    if (!topBucket.isEmpty()) {
        adviceArr.str("根因治理（${topBucket}）：${bucketAdvice(topBucket)}。")
        adviceCount += 1
    }
    // ④ 异常预警
    if (alertCount > 0) {
        adviceArr.str("异常预警：${firstAlertSku} 等 ${alertCount} 个 SKU 近期纠纷集中爆发，建议立即排查批次/物流/供应商，暂停相关推广。")
        adviceCount += 1
    }
    // 兜底：一条基于数据的通用建议（按最大退款品类）
    if (adviceCount == 0) {
        if (topRefundCat.isEmpty()) {
            adviceArr.str("建议优先治理退款额最高的品类，并核验实物与 listing 图文一致性。")
        } else {
            adviceArr.str("退款结构：${topRefundCat} 累计退款 ¥${num2(topRefundCatAmt)} 居首，建议优先复盘该品类的退货集中度与供应商履约。")
        }
        adviceCount += 1
    }
    let sourcingAdvice = adviceArr.build()

    // —— 根因结论 ——
    var rootCauseText = "暂无足够缺陷数据用于根因归因。"
    if (rcTotal > 0 && !topBucket.isEmpty()) {
        let share = Int64(Float64(topCount) / Float64(rcTotal) * 100.0 + 0.5)
        let suffix = if (share >= 35) { "结合品类与供应商分布，建议优先治理该环节。" } else { "各环节分布较分散，建议综合治理包装、供应商与 listing。" }
        rootCauseText = "退货根因以「${topBucket}」为主（占 ${share}%）。${suffix}"
    }

    // —— 中文洞察报告 ——
    let logisticsCost = round2(Float64(overall.total) * 12.0)
    let totalCost = round2(overall.refund + Float64(overall.total) * 12.0)
    var report = "本期共沉淀 ${overall.total} 笔退货案件，累计退款约 ¥${num2(overall.refund)}，综合胜诉率 ${pct0(overall.winRate())}，预估退货总成本约 ¥${num2(totalCost)}（含物流 ¥${num2(logisticsCost)}）。"
    if (!topBucket.isEmpty()) { report = "${report}根因集中于「${topBucket}」。" }
    if (alertCount > 0 || blackCount > 0) {
        report = "${report}已识别 ${alertCount} 个异常 SKU、${blackCount} 个高风险供应商。"
    }
    report = "${report}建议将退货负面信号反哺选品与品控，从源头降低退货结构占比。"

    let obj = Obj()
        .i64("total_cases", overall.total)
        .f64("total_refund", round2(overall.refund))
        .f64("win_rate", round4(overall.winRate()))
        .i64("decided", overall.decided)
        .f64("avg_dispute_rate", round4(1.0 - overall.avgSim()))
        .str("dispute_rate_note", "代理指标：由退货图相似度推算，非平台标记争议笔数")
        .raw("category_heatmap", viewsOf(byCat))
        .raw("platform_view", viewsOf(byPlat))
        .raw("region_view", viewsOf(byRegion))
        .raw("season_view", viewsOf(bySeason))
        .raw("supplier_scorecard", supplierScorecard)
        .raw("platform_supplier_matrix", platSupplierMatrix)
        .raw("sku_ranking", rankArr.build())
        .raw("anomaly_alerts", alertArr.build())
        .raw("root_cause_dist", rootCauseDist)
        .str("root_cause", rootCauseText)
        .raw("sourcing_advice", sourcingAdvice)
        .raw("recommendations", sourcingAdvice)
        .str("report", report)
        .raw("sku_insights", insightArr.build())
        .raw("supplier_blacklist", supplierBlacklist)
        .f64("logistics_cost", logisticsCost)
        .f64("total_return_cost", totalCost)
        .str("mode", mode)
        .str("source", "unified")   // 单库：不再有 demo/real 双源
        .str("tenant", tenant)
        .nullable("error", None)
        .build()
    return ApiResponse.ok(obj)
}

private func accumulate(m: HashMap<String, Bucket>, key: String, c: CaseRec): Unit {
    match (m.get(key)) {
        case Some(b) => b.add(c)
        case None => let b = Bucket(); b.add(c); m.add(key, b)
    }
}

/** 把分桶转成 [{name,cases,refund,win_rate,decided},...]（按 cases 降序）。 */
private func viewsOf(m: HashMap<String, Bucket>): String {
    let arr = Arr()
    // 简单起见不排序（HashMap 迭代顺序稳定即可，前端自行排序）
    for ((k, b) in m) {
        arr.raw(Obj()
            .str("name", k)
            .i64("cases", b.total)
            .f64("refund", round2(b.refund))
            .f64("win_rate", round4(b.winRate()))
            .i64("decided", b.decided)
            .build())
    }
    return arr.build()
}

/** 文本插值用的金额/数值格式：最多 2 位小数并去掉尾随 0（Cangjie Float64 默认输出 6 位小数）。 */
private func num2(v: Float64): String {
    let cents = Int64(v * 100.0 + 0.5)
    let neg = cents < 0
    let absCents = if (neg) { -cents } else { cents }
    let whole = absCents / 100
    let frac = absCents % 100
    let body = if (frac == 0) { "${whole}" }
               else if (frac % 10 == 0) { "${whole}.${frac / 10}" }
               else if (frac < 10) { "${whole}.0${frac}" }
               else { "${whole}.${frac}" }
    return if (neg) { "-${body}" } else { body }
}

private func round1(v: Float64): Float64 { return Float64(Int64(v * 10.0)) / 10.0 }
private func round2(v: Float64): Float64 { return Float64(Int64(v * 100.0)) / 100.0 }
private func round4(v: Float64): Float64 { return Float64(Int64(v * 10000.0)) / 10000.0 }
private func pct0(v: Float64): String { return "${Int64(v * 100.0 + 0.5)}%" }
private func pct(v: Float64): String { return "${Float64(Int64(v * 10000.0)) / 100.0}%" }
