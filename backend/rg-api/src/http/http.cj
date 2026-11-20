// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// HTTP 基础类型（请求上下文 / 响应封装 / 路由表）。
// 基于 AMS ams.api.http 的已验证实现裁剪；响应采用 ReturnGuard 前端的扁平契约
// （/api/config 直接返回字段，/api/auth/login 返回 {ok,token,username}）。
package rg.api.http

import std.collection.*
import stdx.net.http.*
import rg.kernel.error.*
import rg.kernel.json.*

public const MAX_BODY_BYTES: Int64 = 1048576

/** 请求上下文（包装 stdx HttpContext）。 */
public class ApiRequest {
    public let method: String
    public let url: String
    public let bodyBytes: Array<Byte>
    public let headers: HashMap<String, String>
    public let remoteAddr: String
    public var pathParams: HashMap<String, String> = HashMap<String, String>()

    public init(method: String, url: String, bodyBytes: Array<Byte>,
                headers: HashMap<String, String>, remoteAddr: String) {
        this.method = method.toAsciiUpper()
        this.url = url
        this.bodyBytes = bodyBytes
        this.headers = headers
        this.remoteAddr = remoteAddr
    }

    public static func fromContext(ctx: HttpContext): ApiRequest {
        let req = ctx.request
        let hs = HashMap<String, String>()
        for ((k, vs) in req.headers) {
            for (v in vs.iterator()) { hs.add(k.toAsciiLower(), v); break }
        }
        return ApiRequest(req.method, req.url.toString(), ApiRequest.readBody(req), hs, req.remoteAddr.toString())
    }

    private static func readBody(req: HttpRequest): Array<Byte> {
        let chunks = ArrayList<Array<Byte>>()
        var total: Int64 = 0
        let buf = Array<Byte>(65536, repeat: 0u8)
        try {
            while (true) {
                let n = req.body.read(buf)
                if (n <= 0) { break }
                if (total + n > MAX_BODY_BYTES) { break }
                let part = Array<Byte>(n, repeat: 0u8)
                for (i in 0..n) { part[i] = buf[i] }
                chunks.add(part)
                total += n
            }
        } catch (e: Exception) { chunks.clear(); total = 0 }
        let flat = Array<Byte>(total, repeat: 0u8)
        var at: Int64 = 0
        for (c in chunks) { for (b in c) { flat[at] = b; at += 1 } }
        return flat
    }

    public func header(name: String): ?String { return this.headers.get(name.toAsciiLower()) }
    public func bearerToken(): ?String {
        match (this.header("authorization")) {
            case Some(v) => if (v.toAsciiLower().startsWith("bearer ")) { return Some(trim(v[7..])) } else { return None }
            case None => return None
        }
    }
    public func bodyText(): String { return String.fromUtf8(this.bodyBytes) }
    public func pathParam(name: String): ?String { return this.pathParams.get(name) }

    public static func pathOf(url: String): String {
        let i = indexOf(url, "?")
        return if (i < 0) { url } else { url[0..i] }
    }
    public static func indexOf(s: String, sub: String): Int64 {
        match (s.indexOf(sub)) { case Some(i) => return i; case None => return -1 }
    }
    public func queryParam(name: String): ?String {
        let qi = indexOf(this.url, "?")
        if (qi < 0) { return None }
        for (pair in this.url[qi + 1..].split("&")) {
            let kv = pair.split("=", 2)
            if (kv.size >= 2 && kv[0] == name) { return Some(percentDecode(kv[1])) }
        }
        return None
    }
    private static func percentDecode(s: String): String {
        let src = s.toArray()
        let out = ArrayList<Byte>()
        var i: Int64 = 0
        while (i < src.size) {
            if (src[i] == 37 && i + 2 < src.size) {
                let hi = hexVal(src[i + 1]); let lo = hexVal(src[i + 2])
                if (hi >= 0 && lo >= 0) { out.add(UInt8(hi * 16 + lo)); i += 3; continue }
            }
            out.add(src[i]); i += 1
        }
        return String.fromUtf8(out.toArray())
    }
    private static func hexVal(c: Byte): Int64 {
        let v = Int64(c)
        if (v >= 48 && v <= 57) { return v - 48 }
        if (v >= 97 && v <= 102) { return v - 87 }
        if (v >= 65 && v <= 70) { return v - 55 }
        return -1
    }
}

/** 统一响应：status + 扁平 JSON body + headers。 */
public class ApiResponse {
    public let status: Int64
    public let body: String
    public let headers: HashMap<String, String>
    /** 二进制响应体（非空时 server 优先写它，用于 PDF 等字节流）。 */
    public let bodyBytes: ?Array<Byte>
    public init(status: Int64, body: String) {
        this.status = status; this.body = body; this.headers = jsonHeaders(); this.bodyBytes = None
    }
    public init(status: Int64, body: String, headers: HashMap<String, String>) {
        this.status = status; this.body = body; this.headers = headers; this.bodyBytes = None
    }
    private init(status: Int64, body: String, headers: HashMap<String, String>, bytes: Array<Byte>) {
        this.status = status; this.body = body; this.headers = headers; this.bodyBytes = Some(bytes)
    }
    /** 二进制字节流响应（如 application/pdf）。 */
    public static func binary(bytes: Array<Byte>, contentType: String, filename: String): ApiResponse {
        let h = HashMap<String, String>()
        h["content-type"] = contentType
        if (!filename.isEmpty()) { h["content-disposition"] = "attachment; filename=" + filename }
        h["x-content-type-options"] = "nosniff"
        return ApiResponse(200, "", h, bytes)
    }
    public static func ok(json: String): ApiResponse { return ApiResponse(200, json) }
    public static func fail(kind: ErrKind, message: String): ApiResponse {
        let obj = Obj().str("detail", message).build()
        let st = Int64(httpStatusOf(kind))
        return ApiResponse(st, obj)
    }
    private static func jsonHeaders(): HashMap<String, String> {
        let hs = HashMap<String, String>()
        hs["content-type"] = "application/json; charset=utf-8"
        return hs
    }
}

public type Handler = (ApiRequest) -> ApiResponse

public class Route {
    public let method: String
    public let pattern: String
    public let handler: Handler
    public init(method: String, pattern: String, handler: Handler) {
        this.method = method; this.pattern = pattern; this.handler = handler
    }
}

/** 路由表：支持 :param 占位。 */
public class Router {
    private let routes = ArrayList<Route>()
    // 可选守卫：返回非 null 时直接作为响应返回（用于 OAuth scope 等统一鉴权）
    private var guardFn: ?(ApiRequest) -> ?ApiResponse = None
    public init() {}
    public func setGuard(fn!: (ApiRequest) -> ?ApiResponse): Unit { this.guardFn = Some(fn) }
    public func guard(): ?(ApiRequest) -> ?ApiResponse { return this.guardFn }
    public func add(method: String, pattern: String, handler: Handler): Unit {
        this.routes.add(Route(method.toAsciiUpper(), pattern, handler))
    }
    public func get(p: String, h: Handler): Unit { this.add("GET", p, h) }
    public func post(p: String, h: Handler): Unit { this.add("POST", p, h) }
    public func put(p: String, h: Handler): Unit { this.add("PUT", p, h) }
    public func delete(p: String, h: Handler): Unit { this.add("DELETE", p, h) }
    public func size(): Int64 { return this.routes.size }
    public func allRoutes(): ArrayList<Route> { return this.routes }

    public func find(method: String, path: String): ?(Route, Map<String, String>) {
        let m = method.toAsciiUpper()
        for (r in this.routes) {
            if (r.method != m) { continue }
            match (Router.matchPattern(r.pattern, path)) {
                case Some(params) => return Some((r, params))
                case None => ()
            }
        }
        return None
    }
    public func hasPath(path: String): Bool {
        for (r in this.routes) { if (Router.matchPattern(r.pattern, path).isSome()) { return true } }
        return false
    }
    public static func matchPattern(pattern: String, path: String): ?Map<String, String> {
        let ps = pattern.split("/"); let qs = path.split("/")
        if (ps.size != qs.size) { return None }
        let params = HashMap<String, String>()
        for (i in 0..ps.size) {
            let seg = ps[i]
            if (seg.startsWith(":")) {
                if (qs[i].isEmpty()) { return None }
                params.add(seg[1..], qs[i])
            } else if (seg != qs[i]) { return None }
        }
        return Some(params)
    }
}

public type Middleware = (ApiRequest) -> ?ApiResponse

private func trim(s: String): String {
    var a: Int64 = 0; var b = s.size
    while (a < b && (s[a] == 0x20 || s[a] == 0x09 || s[a] == 0x0a || s[a] == 0x0d)) { a += 1 }
    while (b > a && (s[b - 1] == 0x20 || s[b - 1] == 0x09 || s[b - 1] == 0x0a || s[b - 1] == 0x0d)) { b -= 1 }
    return s[a..b]
}
