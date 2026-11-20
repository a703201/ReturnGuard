// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 单案取证 /api/analyze + PDF 导出 /api/export_pdf。
// mock 模式：确定性规则 + 演示示意框（与 Python 版同口径，不伪装 AI）。
// live 模式：调用 AiClient；未配置或失败 → 逐能力回退并如实标注 capabilities。
package rg.api.routes

import std.collection.*
import std.time.*
import rg.api.http.*
import rg.app.*
import rg.kernel.json.*
import rg.kernel.log.*
import rg.kernel.error.*
import stdx.encoding.base64.*

/** GET/POST /api/analyze 核心：返回契约对齐 schemas.AnalyzeResult。 */
public func analyze(ctx: AppContext, req: ApiRequest): ApiResponse {
    let body = FlatJson.parse(req.bodyText())
    let mode = body.getOr("mode", "mock")
    let sku = body.getOr("sku", "SKU-0000")
    let platform = body.getOr("platform", "")
    let listing = body.getOr("listing_text", "")
    let returnedImgUrl = body.getOr("returned_image_url", "")
    let seed = hashOf(sku + listing)

    // live 且 AI 已配置 → 真实调用；否则 mock/回退
    var liveUsed = false
    var similarity = 0.82
    var sameItem = true
    var dossier = ""
    if (mode == "live" && ctx.ai.configured()) {
        let prompt = "跨境退货取证：判断退回件与商品主图是否同款、有哪些瑕疵。SKU=" + sku +
                     " 平台=" + platform + " 商品页承诺=" + listing
        let r = ctx.ai.chat("你是客观取证助手，只给客观证据，不做裁决。", prompt)
        if (r.ok) {
            liveUsed = true
            dossier = r.content
            // 从模型回复里粗提取相似度百分比（如有），否则用确定性值
            similarity = extractSimilarity(r.content, similarity)
            sameItem = similarity >= ctx.threshold
        } else {
            Log.warn("AI 调用失败，回退 mock: " + r.reason)
        }
    }

    if (!liveUsed) {
        // 确定性 mock：基于 sku 与 listing 生成可复现结果
        similarity = 0.62 + Float64(seed % 37) / 100.0
        sameItem = similarity >= ctx.threshold
        dossier = "【演示取证卷宗 · 非 AI 结论】\nSKU: ${sku}\n平台: ${platform}\n" +
                  "同款相似度: ${similarity}\n判定: ${if (sameItem) { "疑似同款" } else { "疑似调包/非同款" }}\n" +
                  "说明: 本结果由确定性规则生成（mock），仅演示流程，不替代平台裁决。"
    }

    let caps = Obj().boolean("similarity", liveUsed).boolean("defects", false)
        .boolean("ocr", false).boolean("tts", false).build()
    let obj = Obj()
        .f64("similarity", round4(similarity))
        .boolean("same_item", sameItem)
        .raw("defect_tags", "[]")
        .str("defect_description", "")
        .str("consistency", "")
        .str("dossier", dossier)
        .str("voice_text", "")
        .f64("priority_score", 0.5)
        .raw("defect_boxes", "[]")
        .boolean("defect_boxes_live", false)
        .str("returned_image_url", returnedImgUrl)
        .str("case_id", "RG-${seed}")
        .str("platform", platform)
        .raw("platform_evidence", "[]")
        .boolean("persisted", false)
        .str("mode", if (liveUsed) { "live" } else { "mock" })
        .raw("capabilities", caps)
        .nullable("error", None)
        .build()
    return ApiResponse.ok(obj)
}

/** GET /api/export_pdf：仓颉生成基础 PDF（文本版），过滤条件与 insights 一致。 */
public func exportPdf(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    // 直接从当前租户的案件聚合出摘要（不复用 insights 函数，避免嵌套调用请求体）
    let cases = ctx.store.casesOf(user)
    var total: Int64 = 0
    var refund: Float64 = 0.0
    var decided: Int64 = 0
    var won: Int64 = 0
    for (c in cases) {
        total += 1
        refund += c.amount
        if (c.outcome != "待分析") { decided += 1; if (c.outcome == "赢") { won += 1 } }
    }
    let winStr = if (decided == 0) { "0.0%" } else { "${Float64(Int64(Float64(won) / Float64(decided) * 10000.0)) / 100.0}%" }
    let report = "退货案件 ${total} 笔，已判定 ${decided} 笔，胜诉率 ${winStr}，累计退款 ¥${Int64(refund)}"
    let totalStr = "${total}"
    let win = winStr
    // 生成真实 PDF 字节 → base64 返回（前端/调用方可解码保存为 .pdf）。
    try {
        let pdfBytes = buildPdf(report, totalStr, win)
        // ?format=binary → 真实 application/pdf 字节流；默认仍返回 base64（兼容旧调用方）。
        let fmt = match (req.queryParam("format")) {
            case Some(v) => v
            case None => "base64"
        }
        if (fmt == "binary") {
            return ApiResponse.binary(pdfBytes, "application/pdf", "ReturnGuard_report.pdf")
        }
        let obj = Obj()
            .str("format", "pdf")
            .str("encoding", "base64")
            .str("filename", "ReturnGuard_report.pdf")
            .str("content_base64", toBase64String(pdfBytes))
            .build()
        return ApiResponse.ok(obj)
    } catch (e: Exception) {
        return ApiResponse.fail(ErrKind.Internal, "PDF生成失败: " + e.toString())
    }
}

/**
 * 真·最小 PDF 生成器（单页 / Helvetica / ASCII 内容），含正确 xref 偏移。
 * 中文 report 以 ASCII 摘要替代（Helvetica 无中文字形），避免生成损坏的 PDF。
 */
private func buildPdf(report: String, total: String, win: String): Array<Byte> {
    // 内容流：仅 ASCII 行（把 report 里的非 ASCII 过滤）
    let line1 = "ReturnGuard - Market Insights Report"
    let line2 = "total_cases=" + total + "   win_rate=" + win
    let line3 = asciiOnly(report)
    let stream = "BT /F1 20 Tf 56 740 Td (" + escPdf(line1) + ") Tj " +
                 "/F1 12 Tf 0 -28 Td (" + escPdf(line2) + ") Tj " +
                 "0 -24 Td (" + escPdf(line3) + ") Tj ET"

    let objects = ArrayList<String>()
    objects.add("<< /Type /Catalog /Pages 2 0 R >>")
    objects.add("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.add("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.add("<< /Length ${stream.size} >>\nstream\n${stream}\nendstream")

    let sb = StringBuilder()
    sb.append("%PDF-1.4\n")
    let offsets = ArrayList<Int64>()
    for (i in 0..objects.size) {
        offsets.add(Int64(asciiBytes(sb.toString()).size))
        sb.append("${i + 1} 0 obj\n")
        sb.append(objects[i])
        sb.append("\nendobj\n")
    }
    let xrefPos = asciiBytes(sb.toString()).size
    sb.append("xref\n0 ${objects.size + 1}\n")
    sb.append("0000000000 65535 f \n")
    for (off in offsets) {
        let pad = 10 - decDigits(off)
        sb.append(zeroPad(off, pad))
        sb.append(" 00000 n \n")
    }
    sb.append("trailer\n<< /Size ${objects.size + 1} /Root 1 0 R >>\n")
    sb.append("startxref\n${xrefPos}\n%%EOF\n")
    return asciiBytes(sb.toString())
}

private func asciiOnly(s: String): String {
    let sb = StringBuilder()
    for (i in 0..s.size) { if (s[i] >= 0x20 && s[i] < 0x7f) { sb.append(String.fromUtf8([UInt8(s[i])])) } }
    let r = sb.toString()
    return if (r.size > 160) { r[0..160] } else { r }
}
private func escPdf(s: String): String {
    var out = ""
    for (i in 0..s.size) {
        let c = s[i]
        if (c == 0x28 || c == 0x29 || c == 0x5c) { out = out + "\\" + String.fromUtf8([UInt8(c)]) }
        else { out = out + String.fromUtf8([UInt8(c)]) }
    }
    return out
}
private func asciiBytes(s: String): Array<Byte> {
    let out = ArrayList<Byte>()
    for (i in 0..s.size) { let c = s[i]; if (c < 128) { out.add(UInt8(c)) } }
    return out.toArray()
}
private func decDigits(v: Int64): Int64 {
    if (v == 0) { return 1 }
    var n = v; var d: Int64 = 0
    while (n > 0) { n /= 10; d += 1 }
    return d
}
private func zeroPad(v: Int64, pad: Int64): String {
    let digits = decDigits(v)
    var s = "${v}"
    var i = digits
    while (i < pad) { s = "0" + s; i += 1 }
    return s
}

private func extractSimilarity(text: String, def: Float64): Float64 {
    // 从 "85%" 之类提取，简单扫描
    var i: Int64 = 0
    while (i + 1 < text.size) {
        if (text[i] >= 48 && text[i] <= 57 && text[i + 1] == 0x25) {
            var j = i - 1; var digits = ""
            while (j >= 0 && text[j] >= 48 && text[j] <= 57) { digits = String.fromUtf8([UInt8(text[j])]) + digits; j -= 1 }
            if (!digits.isEmpty()) {
                var v: Int64 = 0
                for (b in digits.toArray()) { v = v * 10 + Int64(b - 48) }
                if (v > 0 && v <= 100) { return Float64(v) / 100.0 }
            }
        }
        i += 1
    }
    return def
}

private func hashOf(s: String): Int64 {
    var h: Int64 = 5381
    for (b in s.toArray()) { h = ((h << 5) + h) + Int64(b) }
    return if (h < 0) { -h } else { h }
}

private func round4(v: Float64): Float64 { return Float64(Int64(v * 10000.0)) / 10000.0 }
