// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 轻量 JSON 工具：字符串转义 + 扁平对象构建/解析。
// 设计取舍：不引入完整 JSON AST（stdx.encoding.json 对本项目过重），
// 参考 AMS 的做法用 StringBuilder 拼装响应、极简解析请求体。
package rg.kernel.json

import std.collection.*

/** JSON 字符串转义（引号/反斜杠/控制字符）。 */
public func esc(s: String): String {
    let sb = StringBuilder()
    for (ch in s.runes()) {
        let code = UInt32(ch)
        if (code == 0x22) { sb.append("\\\"") }
        else if (code == 0x5c) { sb.append("\\\\") }
        else if (code == 0x0a) { sb.append("\\n") }
        else if (code == 0x0d) { sb.append("\\r") }
        else if (code == 0x09) { sb.append("\\t") }
        else { sb.append(ch.toString()) }
    }
    return sb.toString()
}

/** 把一个字符串包装成 JSON 字符串字面量。 */
public func q(s: String): String { return "\"" + esc(s) + "\"" }

/**
 * 对象构建器：按插入顺序拼 {"k":v,...}。
 * v 必须是已序列化的 JSON 片段（用 q() / num() / bool() / arr() 生成）。
 */
public class Obj {
    private let sb = StringBuilder()
    private var first = true
    public init() { this.sb.append("{") }
    public func raw(key: String, valueJson: String): Obj {
        if (!this.first) { this.sb.append(",") }
        this.first = false
        this.sb.append(q(key))
        this.sb.append(":")
        this.sb.append(valueJson)
        return this
    }
    public func str(key: String, value: String): Obj { return this.raw(key, q(value)) }
    public func i64(key: String, value: Int64): Obj { return this.raw(key, "${value}") }
    public func f64(key: String, value: Float64): Obj { return this.raw(key, "${value}") }
    public func boolean(key: String, value: Bool): Obj { return this.raw(key, if (value) { "true" } else { "false" }) }
    public func nullable(key: String, value: ?String): Obj {
        match (value) { case Some(v) => return this.str(key, v); case None => return this.raw(key, "null") }
    }
    public func build(): String { this.sb.append("}"); return this.sb.toString() }
}

/** 数组构建器：拼 [v1,v2,...]。 */
public class Arr {
    private let sb = StringBuilder()
    private var first = true
    public init() { this.sb.append("[") }
    public func raw(valueJson: String): Arr {
        if (!this.first) { this.sb.append(",") }
        this.first = false
        this.sb.append(valueJson)
        return this
    }
    public func obj(value: Obj): Arr { return this.raw(value.build()) }
    public func str(value: String): Arr { return this.raw(q(value)) }
    public func build(): String { this.sb.append("]"); return this.sb.toString() }
}

/**
 * 极简扁平对象解析：只取顶层字段的字符串值。
 * 足以解析 {username,password,tenant_name,invite_code} 等登录/注册请求体。
 */
public class FlatJson {
    private let fields = HashMap<String, String>()
    private init() {}

    private var bytes: Array<Byte> = []
    private var pos: Int64 = 0

    public static func parse(text: String): FlatJson {
        let r = FlatJson()
        r.bytes = text.toArray()
        r.pos = 0
        let n = r.bytes.size
        while (r.pos < n) {
            if (r.bytes[r.pos] != 0x22) { r.pos += 1; continue } // '"'
            let key = r.readString()
            r.pos += 1
            while (r.pos < n && (r.bytes[r.pos] == 0x20 || r.bytes[r.pos] == 0x0a || r.bytes[r.pos] == 0x0d)) { r.pos += 1 }
            if (r.pos >= n || r.bytes[r.pos] != 0x3a) { continue } // ':'
            r.pos += 1
            while (r.pos < n && (r.bytes[r.pos] == 0x20 || r.bytes[r.pos] == 0x0a || r.bytes[r.pos] == 0x0d)) { r.pos += 1 }
            if (r.pos >= n) { break }
            if (r.bytes[r.pos] == 0x22) {
                let val = r.readString()
                r.fields.add(key, val)
                r.pos += 1   // 跳过 value 的结束引号
            } else {
                // 数字/布尔/null：按原样收集到空白或 , } 为止
                var j = r.pos
                while (j < n && r.bytes[j] != 0x2c && r.bytes[j] != 0x7d && r.bytes[j] != 0x20) { j += 1 }
                let val = String.fromUtf8(r.bytes[r.pos..j])
                r.fields.add(key, val)
                r.pos = j
            }
        }
        return r
    }

    public func get(key: String): ?String { return this.fields.get(key) }
    public func getOr(key: String, fallback: String): String {
        match (this.fields.get(key)) { case Some(v) => return v; case None => return fallback }
    }

    /** 从当前 pos（指向起始引号）读一个字符串，pos 停在结束引号处。 */
    private func readString(): String {
        let sb = StringBuilder()
        var j = this.pos + 1
        let n = this.bytes.size
        while (j < n && this.bytes[j] != 0x22) {
            if (this.bytes[j] == 0x5c && j + 1 < n) { // 反斜杠转义
                j += 1
                let ec = this.bytes[j]
                if (ec == 0x6e) { sb.append("\n") }
                else if (ec == 0x72) { sb.append("\r") }
                else if (ec == 0x74) { sb.append("\t") }
                else if (ec == 0x22) { sb.append("\"") }
                else if (ec == 0x5c) { sb.append("\\") }
                else { sb.append(String.fromUtf8(this.bytes[j..j+1])) }
            } else {
                sb.append(String.fromUtf8(this.bytes[j..j+1]))
            }
            j += 1
        }
        this.pos = j
        return sb.toString()
    }
}
