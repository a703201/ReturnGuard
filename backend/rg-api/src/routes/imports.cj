// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 批量导入：CSV 文本解析（轻量实现，支持引号/逗号转义），逐行写入当前租户。
// XLSX 需 ZIP+XML 解压，仓颉标准库无现成支持——如实返回明确提示，不伪装成功。
package rg.api.routes

import std.collection.*
import std.time.*
import rg.api.http.*
import rg.app.*
import rg.data.store.*
import rg.kernel.json.*
import rg.kernel.error.*
import stdx.encoding.base64.*

/** 本地字符串工具（仓颉 String 无 trim/toLowerCase）。 */
private func trimStr(s: String): String {
    var a = 0
    var b = s.size
    while (a < b && (s[a] == 0x20 || s[a] == 0x09 || s[a] == 0x0a || s[a] == 0x0d)) { a += 1 }
    while (b > a && (s[b - 1] == 0x20 || s[b - 1] == 0x09 || s[b - 1] == 0x0a || s[b - 1] == 0x0d)) { b -= 1 }
    return s[a..b]
}
private func lowerStr(s: String): String {
    // 逐字节重建，只把 ASCII 大写转小写；非 ASCII（中文 UTF-8 多字节）原样保留，
    // 最后一次性 fromUtf8 —— 否则单字节解码会抛 "Invalid utf8 byte sequence"。
    let bytes = s.toArray()
    for (i in 0..bytes.size) {
        let c = bytes[i]
        if (c >= 0x41 && c <= 0x5a) { bytes[i] = c + 32 }
    }
    return String.fromUtf8(bytes)
}

/** 列头归一化：中英文常见列名 → 规范字段（与 Python importer.py 的 _COL_MAP 对齐）。 */
private func normHeader(h0: String): String {
    let h = lowerStr(trimStr(h0))
    match (h) {
        case "sku" => return "sku"
        case "sku_name" | "产品名" | "产品" => return "sku"
        case "category" | "品类" => return "category"
        case "supplier" | "供应商" | "supplier_name" => return "supplier"
        case "platform" | "平台" => return "platform"
        case "region" | "地区" | "国家" => return "region"
        case "season" | "季节" => return "season"
        case "amount" | "金额" | "退款" | "退款金额" => return "amount"
        case "similarity" | "相似度" => return "similarity"
        case "outcome" | "结果" | "state" => return "outcome"
        case "defect" | "defect_tags" | "缺陷" | "瑕疵" => return "defect"
        case "case_id" | "案号" | "id" => return "case_id"
        case _ => return ""
    }
}

/** 字节累积 → 字符串（一次性 UTF-8 解码，中文多字节不会被拆坏）。 */
private func bytesToStr(buf: ArrayList<Byte>): String {
    let arr = Array<Byte>(buf.size, repeat: 0u8)
    for (i in 0..buf.size) { arr[i] = buf[i] }
    return String.fromUtf8(arr)
}

/** 解析一行 CSV（支持 "..." 包裹与 "" 转义）。 */
private func parseCsvLine(line: String): Array<String> {
    let out = ArrayList<String>()
    var buf = ArrayList<Byte>()
    var quoted = false
    var i = 0
    while (i < line.size) {
        let c = line[i]
        if (quoted) {
            if (c == 0x22) {  // '"'
                if (i + 1 < line.size && line[i + 1] == 0x22) { buf.add(0x22); i += 1 }
                else { quoted = false }
            } else { buf.add(c) }
        } else {
            if (c == 0x22) { quoted = true }
            else if (c == 0x2c) { out.add(bytesToStr(buf)); buf = ArrayList<Byte>() }  // ','
            else { buf.add(c) }
        }
        i += 1
    }
    out.add(bytesToStr(buf))
    return out.toArray()
}

/** 拆行（支持 \r\n / \n）。 */
private func splitLines(text: String): Array<String> {
    let out = ArrayList<String>()
    var buf = ArrayList<Byte>()
    var i = 0
    while (i < text.size) {
        let c = text[i]
        if (c == 0x0a) { out.add(bytesToStr(buf)); buf = ArrayList<Byte>() }
        else if (c != 0x0d) { buf.add(c) }
        i += 1
    }
    out.add(bytesToStr(buf))
    return out.toArray()
}

private func parseF(s: String): Float64 {
    if (s.isEmpty()) { return 0.0 }
    let b = s.toArray()
    var i = 0
    var neg = false
    if (b[0] == 0x2d) { neg = true; i = 1 }
    var whole: Int64 = 0
    while (i < b.size && b[i] >= 0x30 && b[i] <= 0x39) {
        whole = whole * 10 + Int64(b[i]) - 48
        i += 1
    }
    var frac: Float64 = 0.0
    var scale: Float64 = 10.0
    if (i < b.size && b[i] == 0x2e) {
        i += 1
        while (i < b.size && b[i] >= 0x30 && b[i] <= 0x39) {
            frac += Float64(Int64(b[i]) - 48) / scale
            scale *= 10.0
            i += 1
        }
    }
    let v = Float64(whole) + frac
    return if (neg) { -v } else { v }
}

private func nowUnixMs(): Int64 { return DateTime.now().toUnixTimeStamp().toMilliseconds() }

/** POST /api/cases/import：body {csv: 文本, source?: csv|xlsx}。 */
public func importCases(ctx: AppContext, req: ApiRequest): ApiResponse {
    let user = currentUser(ctx, req)
    if (user.isEmpty()) { return ApiResponse.fail(ErrKind.Unauthorized, "请先登录") }
    let body = FlatJson.parse(req.bodyText())
    let source = lowerStr(body.getOr("source", "csv"))
    var csv = body.getOr("csv", "")
    if (source == "xlsx" || source == "excel") {
        // XLSX 走 base64 上传（字段名 content 或 csv 均可）→ 解码 → 轻量解析转 CSV
        try {
            let b64 = if (!csv.isEmpty()) { csv } else { body.getOr("content", "") }
            if (b64.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "XLSX 内容为空") }
            let decoded = match (fromBase64String(b64)) {
                case Some(bytes) => bytes
                case None => return ApiResponse.fail(ErrKind.BadRequest, "XLSX base64 解码失败")
            }
            csv = xlsxToCsv(decoded, 20 * 1024 * 1024)  // 解压上限 20MB，防 zip bomb
        } catch (e: XlsxError) {
            return ApiResponse.fail(ErrKind.BadRequest, e.toString())
        } catch (e: Exception) {
            return ApiResponse.fail(ErrKind.BadRequest, "XLSX 解析失败：${e.toString()}")
        }
        if (csv.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "XLSX 无可导入数据") }
    }
    if (csv.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "CSV 内容为空") }

    let lines = splitLines(csv)
    if (lines.isEmpty()) { return ApiResponse.fail(ErrKind.BadRequest, "CSV 无内容") }
    let headsRaw = parseCsvLine(lines[0])
    let heads = ArrayList<String>()
    for (h in headsRaw) { heads.add(normHeader(h)) }
    let colIndex = HashMap<String, Int64>()
    for (i in 0..heads.size) { colIndex.add(heads[i], Int64(i)) }

    var imported: Int64 = 0
    var skipped: Int64 = 0
    let errs = Arr()
    var rowNo: Int64 = 1
    while (rowNo < lines.size) {
        let cells = parseCsvLine(lines[rowNo])
        let getCell = { k: String =>
            match (colIndex.get(k)) {
                case Some(ix) => if (ix < cells.size) { cells[Int64(ix)] } else { "" }
                case None => ""
            }
        }
        let sku = trimStr(getCell("sku"))
        if (sku.isEmpty()) {
            skipped += 1
            errs.str("第 ${rowNo + 1} 行：SKU 为空")
            rowNo += 1
            continue
        }
        let c = CaseRec(
            "import-${nowUnixMs()}-${rowNo}", user,
            sku, trimStr(getCell("category")), trimStr(getCell("supplier")),
            trimStr(getCell("platform")), trimStr(getCell("region")), trimStr(getCell("season")),
            parseF(trimStr(getCell("amount"))), parseF(trimStr(getCell("similarity"))),
            if (trimStr(getCell("outcome")).isEmpty()) { "待分析" } else { trimStr(getCell("outcome")) },
            trimStr(getCell("defect")))
        ctx.store.addCase(c)
        imported += 1
        rowNo += 1
    }
    return ApiResponse.ok(Obj()
        .boolean("ok", true)
        .i64("imported", imported)
        .i64("skipped", skipped)
        .str("tenant", user)
        .raw("errors", errs.build())
        .build())
}
