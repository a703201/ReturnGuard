// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 轻量 XLSX 读取：ZIP 解压（store+deflate）+ OpenXML 单元格文本提取，转成 CSV 文本。
// 只处理纯文本/共享字符串/数字，不处理公式缓存以外的内容；复杂格式（合并单元格/富文本片段）
// 取可见文本，不伪装成精确还原。移植自 AMS importer/zipreader.cj 的核心算法（Apache-2.0，同作者）。
package rg.api.routes

import std.collection.*
import std.io.*
import stdx.compress.zlib.*

/** XLSX 解析异常（带可读原因）。 */
public class XlsxError <: Exception {
    private let why: String
    public init(msg: String) { super(msg); this.why = msg }
    public override func toString(): String { return this.why }
}

// ---- 小端整数读取 ----
private func u16(b: Array<Byte>, at: Int64): Int64 {
    if (at < 0 || at + 2 > b.size) { return -1 }
    return Int64(b[at]) + Int64(b[at + 1]) * 256
}
private func u32(b: Array<Byte>, at: Int64): Int64 {
    if (at < 0 || at + 4 > b.size) { return -1 }
    return Int64(b[at]) + Int64(b[at + 1]) * 256 +
           Int64(b[at + 2]) * 65536 + Int64(b[at + 3]) * 16777216
}

private const CD_SIG: Int64 = 0x02014b50
private const LOCAL_SIG: Int64 = 0x04034b50
private const EOCD_SIG: Int64 = 0x06054b50

/** 一个 ZIP 条目（只保留解压所需字段）。 */
private class ZipEntry {
    public let path: String
    public let method: Int64
    public let compSize: Int64
    public let uncompSize: Int64
    public let localOffset: Int64
    public init(path: String, method: Int64, compSize: Int64, uncompSize: Int64, localOffset: Int64) {
        this.path = path; this.method = method; this.compSize = compSize
        this.uncompSize = uncompSize; this.localOffset = localOffset
    }
}

/** 裸 deflate 解压，带上限（防止 zip bomb）。 */
private func inflateLimited(comp: Array<Byte>, maxBytes: Int64): Array<Byte> {
    let src = ByteBuffer(comp)
    let out = ArrayList<Byte>()
    let dis = DecompressInputStream(src, wrap: WrapType.DeflateFormat, bufLen: 32768)
    try {
        let buf = Array<Byte>(32768, repeat: 0u8)
        while (true) {
            let n = dis.read(buf)
            if (n <= 0) { break }
            if (out.size + n > maxBytes) { throw XlsxError("XLSX 解压后超过上限") }
            for (i in 0..n) { out.add(buf[i]) }
        }
    } catch (e: XlsxError) {
        throw e
    } catch (e: Exception) {
        throw XlsxError("XLSX deflate 解压失败")
    } finally {
        try { dis.close() } catch (e: Exception) { () }
    }
    return out.toArray()
}

/** 从 ZIP 字节中找指定路径的条目并解压返回文本。 */
private func zipReadText(data: Array<Byte>, wanted: Array<String>, maxBytes: Int64): ?String {
    // 从尾部找 EOCD（末 64KB）
    if (data.size < 22) { return None }
    var eocd: Int64 = -1
    var i = data.size - 22
    let floor = if (data.size > 65557) { data.size - 65557 } else { 0 }
    while (i >= floor) {
        if (u32(data, i) == EOCD_SIG) { eocd = i; break }
        i -= 1
    }
    if (eocd < 0) { return None }
    let total = u16(data, eocd + 10)
    var cd = u32(data, eocd + 16)
    if (cd < 0) { return None }
    for (k in 0..total) {
        if (u32(data, cd) != CD_SIG) { break }
        let method = u16(data, cd + 10)
        let compSize = u32(data, cd + 20)
        let uncompSize = u32(data, cd + 24)
        let nlen = u16(data, cd + 28)
        let elen = u16(data, cd + 30)
        let clen = u16(data, cd + 32)
        let lho = u32(data, cd + 42)
        if (nlen < 0 || elen < 0 || clen < 0 || lho < 0) { break }
        let nameStart = cd + 46
        let nameEnd = nameStart + nlen
        if (nameEnd > data.size) { break }
        let path = String.fromUtf8(data[nameStart..nameEnd])
        var matched = false
        for (w in wanted) { if (path.endsWith(w)) { matched = true; break } }
        if (matched && method >= 0 && compSize >= 0 && uncompSize <= maxBytes) {
            if (u32(data, lho) != LOCAL_SIG) { return None }
            let lnlen = u16(data, lho + 26)
            let lelen = u16(data, lho + 28)
            let start = lho + 30 + lnlen + lelen
            let end = start + compSize
            if (start < 0 || end > data.size) { return None }
            let raw = data[start..end]
            let plain = if (method == 0) { raw } else { inflateLimited(raw, maxBytes) }
            // 仓颉 Byte 直接作 UTF-8 字节解码（与 AMS zipreader 一致）
            return String.fromUtf8(plain)
        }
        cd = cd + 46 + nlen + elen + clen
    }
    return None
}

/** 从 sharedStrings.xml 提取所有 <si> 的可见文本（拼接多个 <t>）。 */
private func parseSharedStrings(xml: String): Array<String> {
    let out = ArrayList<String>()
    var pos = 0
    while (true) {
        let s1 = xml.indexOf("<si>", pos)
        let s2 = xml.indexOf("<si ", pos)
        var start = -1
        if (s1.isSome()) { start = s1.getOrThrow() }
        if (s2.isSome()) {
            let v = s2.getOrThrow()
            if (start < 0 || v < start) { start = v }
        }
        if (start < 0) { break }
        let tagEnd = xml.indexOf(">", start)
        if (tagEnd.isNone()) { break }
        let close = xml.indexOf("</si>", tagEnd.getOrThrow())
        if (close.isNone()) { break }
        let ce = close.getOrThrow()
        let inner = xml[tagEnd.getOrThrow() + 1..ce]
        out.add(xmlTextOf(inner))
        pos = ce + 5
    }
    return out.toArray()
}

/** 取一段 XML 中所有 <t...>text</t> 的拼接文本，并做基础实体反转义。 */
private func xmlTextOf(xml: String): String {
    let sb = StringBuilder()
    var pos = 0
    while (true) {
        let op = xml.indexOf("<t", pos)
        if (op.isNone()) { break }
        let os = op.getOrThrow()
        let gt = xml.indexOf(">", os)
        if (gt.isNone()) { break }
        let gs = gt.getOrThrow()
        let cl = xml.indexOf("</t>", gs)
        if (cl.isNone()) { break }
        let cs = cl.getOrThrow()
        sb.append(unescapeXml(xml[gs + 1..cs]))
        pos = cs + 4
    }
    return sb.toString()
}

private func unescapeXml(s: String): String {
    var r = s.replace("&amp;", "&")
    r = r.replace("&lt;", "<")
    r = r.replace("&gt;", ">")
    r = r.replace("&quot;", "\"")
    r = r.replace("&apos;", "'")
    return r
}

/** 列字母（A,B,...）转 0 基索引。 */
private func colIndex(ref: String): Int64 {
    var n: Int64 = 0
    for (i in 0..ref.size) {
        let c = ref[i]
        if (c >= 0x41 && c <= 0x5a) { n = n * 26 + Int64(c - 0x41 + 1) }
        else if (c >= 0x61 && c <= 0x7a) { n = n * 26 + Int64(c - 0x61 + 1) }
        else { break }
    }
    return n - 1
}

/**
 * XLSX 字节 → CSV 文本。
 * 只读取第一个工作表（xl/worksheets/sheet1.xml），按 <row> 与单元格列引用补齐空列。
 * 共享字符串走 sharedStrings.xml；数字/布尔直接取 <v>；inlineStr 取 <is> 文本。
 */
public func xlsxToCsv(data: Array<Byte>, maxBytes: Int64): String {
    let sharedXml = zipReadText(data, ["xl/sharedStrings.xml"], maxBytes) ?? ""
    let shared = parseSharedStrings(sharedXml)
    let sheetOpt = zipReadText(data, ["xl/worksheets/sheet1.xml"], maxBytes)
    let sheetXml = match (sheetOpt) {
        case Some(v) => v
        case None => throw XlsxError("XLSX 缺少 sheet1.xml（不支持多表/隐藏表选择）")
    }
    let csvSb = StringBuilder()
    var rowPos = 0
    while (true) {
        let ro = sheetXml.indexOf("<row", rowPos)
        if (ro.isNone()) { break }
        let rs = ro.getOrThrow()
        let re0 = sheetXml.indexOf(">", rs)
        if (re0.isNone()) { break }
        let re = re0.getOrThrow()
        let rc = sheetXml.indexOf("</row>", re)
        if (rc.isNone()) { break }
        let rEnd = rc.getOrThrow()
        let rowXml = sheetXml[re + 1..rEnd]
        // 解析该行的每个 <c ...>...</c>
        var cells = ArrayList<String>()
        var cpos = 0
        var maxCol: Int64 = -1
        while (true) {
            let co = rowXml.indexOf("<c ", cpos)
            let co2 = rowXml.indexOf("<c>", cpos)
            var cs0 = -1
            if (co.isSome()) { cs0 = co.getOrThrow() }
            if (co2.isSome()) {
                let v = co2.getOrThrow()
                if (cs0 < 0 || v < cs0) { cs0 = v }
            }
            if (cs0 < 0) { break }
            let cheadEnd = rowXml.indexOf(">", cs0)
            if (cheadEnd.isNone()) { break }
            let che = cheadEnd.getOrThrow()
            let head = rowXml[cs0..che]
            let cc = rowXml.indexOf("</c>", che)
            if (cc.isNone()) { break }
            let cce = cc.getOrThrow()
            let body = rowXml[che + 1..cce]
            // 列引用
            var col: Int64 = cells.size
            let rIdx = head.indexOf("r=\"")
            if (rIdx.isSome()) {
                let a = rIdx.getOrThrow() + 3
                let b = head.indexOf("\"", a)
                if (b.isSome()) { col = colIndex(head[a..b.getOrThrow()]) }
            }
            // 单元格值
            var val = ""
            let tIdx = head.indexOf("t=\"")
            var typ = ""
            if (tIdx.isSome()) {
                let a = tIdx.getOrThrow() + 3
                let b = head.indexOf("\"", a)
                if (b.isSome()) { typ = head[a..b.getOrThrow()] }
            }
            let vIdx = body.indexOf("<v>")
            if (typ == "s" && vIdx.isSome()) {
                let a = vIdx.getOrThrow() + 3
                let b = body.indexOf("</v>", a)
                if (b.isSome()) {
                    let si = parseIntCell(body[a..b.getOrThrow()])
                    if (si >= 0 && si < shared.size) { val = shared[Int64(si)] }
                }
            } else if (typ == "inlineStr") {
                val = xmlTextOf(body)
            } else if (vIdx.isSome()) {
                let a = vIdx.getOrThrow() + 3
                let b = body.indexOf("</v>", a)
                if (b.isSome()) { val = unescapeXml(body[a..b.getOrThrow()]) }
            }
            while (cells.size <= col) { cells.add("") }
            cells[Int64(col)] = csvEscape(val)
            if (col > maxCol) { maxCol = col }
            cpos = cce + 4
        }
        // 补齐尾部空列，输出一行
        for (j in 0..maxCol + 1) {
            if (j > 0) { csvSb.append(",") }
            csvSb.append(if (Int64(j) < cells.size) { cells[Int64(j)] } else { "" })
        }
        csvSb.append("\n")
        rowPos = rEnd + 6
    }
    return csvSb.toString()
}

private func parseIntCell(s: String): Int64 {
    var n: Int64 = 0
    for (i in 0..s.size) {
        let c = s[i]
        if (c < 48 || c > 57) { return -1 }
        n = n * 10 + Int64(c - 48)
    }
    return n
}

/** CSV 字段转义：含逗号/引号/换行则加引号并双写引号。 */
private func csvEscape(s: String): String {
    if (s.indexOf(",").isNone() && s.indexOf("\"").isNone() &&
        s.indexOf("\n").isNone() && s.indexOf("\r").isNone()) { return s }
    let q = s.replace("\"", "\"\"")
    return "\"" + q + "\""
}
