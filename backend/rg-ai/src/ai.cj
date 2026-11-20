// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 轻量 OpenAI 兼容客户端（stdx.net.http ClientBuilder，本机实测 API）。
// 失败关闭：非 2xx / 无 content → 返回 failure(reason)，由上层诚实回退，不伪装成功。
// 密钥只进 Authorization 头，不进日志 / 异常。
package rg.ai

import stdx.net.http.*
import std.collection.*
import std.io.*
import rg.kernel.json.{esc}

/** AI 调用结果：成功带 content，失败带原因码。 */
public class AiResult {
    public let ok: Bool
    public let content: String
    public let reason: String
    public init(ok: Bool, content: String, reason: String) {
        this.ok = ok; this.content = content; this.reason = reason
    }
    public static func success(c: String): AiResult { return AiResult(true, c, "") }
    public static func failure(r: String): AiResult { return AiResult(false, "", r) }
}

/** OpenAI 兼容 chat 客户端。 */
public class AiClient {
    private let baseUrl: String
    private let apiKey: String
    private let model: String
    private let timeoutMs: Int64

    public init(baseUrl: String, apiKey: String, model: String, timeoutMs!: Int64 = 30000) {
        var u = baseUrl
        while (u.endsWith("/")) { u = u[0..u.size - 1] }
        this.baseUrl = u
        this.apiKey = apiKey
        this.model = model
        this.timeoutMs = timeoutMs
    }

    /** 是否已配置（无密钥时上层应回退 mock，不调用）。 */
    public func configured(): Bool { return !this.baseUrl.isEmpty() && !this.apiKey.isEmpty() }

    /** 发送 chat 请求。userContent 可含图片 URL / base64（视觉模型）。 */
    public func chat(system: String, userContent: String): AiResult {
        if (!this.configured()) { return AiResult.failure("not_configured") }
        let body = AiClient.buildBody(this.model, system, userContent)
        let url = this.baseUrl + "/chat/completions"
        let client = ClientBuilder().build()
        let rb = HttpRequestBuilder().method("POST").url(url)
        rb.header("Content-Type", "application/json")
        rb.header("Authorization", "Bearer " + this.apiKey)
        rb.body(body.toArray())
        let resp = client.send(rb.build())
        if (resp.status < 200 || resp.status >= 300) {
            return AiResult.failure("http_${resp.status}")
        }
        let raw = AiClient.readAll(resp.body)
        let text = String.fromUtf8(raw)
        match (AiClient.extractContent(text)) {
            case Some(c) => return AiResult.success(c)
            case None => return AiResult.failure("no_content")
        }
    }

    private static func buildBody(model: String, system: String, userContent: String): String {
        let sb = StringBuilder()
        sb.append("{")
        sb.append("\"model\":\"")
        sb.append(esc(model))
        sb.append("\",\"messages\":[")
        sb.append("{\"role\":\"system\",\"content\":\"")
        sb.append(esc(system))
        sb.append("\"},{\"role\":\"user\",\"content\":\"")
        sb.append(esc(userContent))
        sb.append("\"}]")
        sb.append(",\"temperature\":0}")
        return sb.toString()
    }

    /** 从响应中提取 choices[0].message.content（含转义还原）。 */
    private static func extractContent(text: String): ?String {
        // 先定位 "content": 之后（message 内的），再取到匹配引号结束
        let marker = "\"content\":"
        var from: Int64 = 0
        var found = false
        while (from < text.size) {
            let idx = AiClient.indexOfFrom(text, marker, from)
            if (idx < 0) { break }
            let afterColon = idx + marker.size
            let val = AiClient.readJsonString(text, afterColon)
            match (val) {
                case Some(v) =>
                    if (!v.isEmpty()) { return Some(v) }
                    from = afterColon
                case None => from = afterColon
            }
            found = true
        }
        if (!found) { return None }
        return None
    }

    private static func indexOfFrom(s: String, sub: String, from: Int64): Int64 {
        var i = from
        while (i + sub.size <= s.size) {
            var same = true
            for (j in 0..sub.size) {
                if (s[i + j] != sub[j]) { same = false; break }
            }
            if (same) { return i }
            i += 1
        }
        return -1
    }

    /** 从 pos 开始跳空白，读一个 JSON 字符串（处理转义）。 */
    private static func readJsonString(s: String, pos: Int64): ?String {
        var p = pos
        while (p < s.size && (s[p] == 0x20 || s[p] == 0x0a || s[p] == 0x0d)) { p += 1 }
        if (p >= s.size || s[p] != 0x22) { return None }
        p += 1
        let sb = StringBuilder()
        while (p < s.size && s[p] != 0x22) {
            if (s[p] == 0x5c && p + 1 < s.size) {
                p += 1
                let ec = s[p]
                if (ec == 0x6e) { sb.append("\n") }
                else if (ec == 0x72) { sb.append("\r") }
                else if (ec == 0x74) { sb.append("\t") }
                else if (ec == 0x22) { sb.append("\"") }
                else if (ec == 0x5c) { sb.append("\\") }
                else { sb.append(String.fromUtf8([UInt8(ec)])) }
            } else {
                sb.append(String.fromUtf8([UInt8(s[p])]))
            }
            p += 1
        }
        return Some(sb.toString())
    }

    private static func readAll(stream: InputStream): Array<Byte> {
        let out = ArrayList<Byte>()
        let buf = Array<Byte>(8192, repeat: 0u8)
        while (true) {
            let n = stream.read(buf)
            if (n <= 0) { break }
            for (i in 0..n) { out.add(buf[i]) }
        }
        return out.toArray()
    }
}
