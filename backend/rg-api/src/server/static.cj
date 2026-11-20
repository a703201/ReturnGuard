// ============================================================
// ams.api.server.static · 前端静态资源托管（前后端同进程部署）
//
// 目的：**一次启动 = 前后端同时上线**。
//   发布形态从「后端 8080 + 前端另起一个静态服务器/nginx」变成
//   「一个 ams-server 同时提供 /（前端 SPA）与 /api/*（接口）」，
//   部署时不用再维护第二份端口、反代与跨域配置。
//
// 三条必须遵守的规则：
//   ① **`/api/` 前缀永不走静态**：接口不存在就该返回 JSON 404，
//      而不是把 index.html 当作 200 返回（前端拿到 HTML 去 JSON.parse
//      是这个设计最容易踩的坑，且报错信息极具误导性）。
//   ② **SPA history 回落**：Vue Router 的 /family、/share/xxx、/invite/xxx
//      在服务端没有对应文件，必须回落到 index.html，否则用户刷新即 404。
//      但回落只对「看起来像页面路径」的请求生效 —— 带扩展名却找不到的文件
//      必须真 404，否则打包缺失的 js 会被悄悄替换成 HTML。
//   ③ **目录穿越防护**：路径先拒绝 `..`、再拒绝反斜杠与盘符，
//      任何情况下拼接结果都必须落在根目录内。
//
// [std.fs 能力边界]
//   本工具链的 std.fs 只稳定提供 `File.readFrom` / `File.writeTo` /
//   `Directory.create`（见 ams-storage 的说明），没有 `exists`。
//   故「文件是否存在」统一用「读成功即存在」表达，避免 TOCTOU。
// ============================================================
package rg.api.server

import std.collection.*
import std.fs.*
import stdx.net.http.*

/**
 * 静态资源托管器。
 */
public class StaticFiles {
    /** 根目录（构造时保证不以 / 结尾） */
    private let root: String

    public init(root: String) {
        var r = root
        while (r.endsWith("/")) {
            r = r[0..r.size - 1]
        }
        this.root = r
    }

    /**
     * 探测前端产物目录。
     *
     * 为什么要有探测：同一个可执行文件要同时适配两种布局 ——
     *   · 源码树：  仓库根/web/dist   （npm run build 的产物）
     *   · 发布包：  包根/web          （package.sh 把 dist 内容平铺进 web/）
     * 让运维去记「该配哪个相对路径」是最容易出错的环节，能自动就别让人配。
     *
     * @param explicit 显式配置（AMS_WEB_DIR）；非空时直接采用，不做探测
     * @return 探测到的根目录；都没找到返回空串（= 关闭静态托管）
     */
    public static func detect(explicit: String): String {
        if (!explicit.isEmpty()) {
            return explicit
        }
        let candidates = ArrayList<String>()
        candidates.add("./web/dist")
        candidates.add("web/dist")
        candidates.add("./web")
        candidates.add("web")
        candidates.add("../web/dist")
        for (c in candidates) {
            if (StaticFiles.exists("${c}/index.html")) {
                return c
            }
        }
        return ""
    }

    /**
     * 读文件判存在（std.fs 无 exists，读失败即不存在）。
     */
    private static func exists(path: String): Bool {
        try {
            let _ = File.readFrom(path)
            return true
        } catch (e: Exception) {
            return false
        }
    }

    /**
     * 生成供 distributor 兜底使用的处理器。
     */
    public func handler(): HttpRequestHandler {
        return StaticHandler(this)
    }

    /**
     * 处理一次静态请求。
     */
    public func serve(ctx: HttpContext): Unit {
        let rawPath = StaticFiles.pathOnly(ctx.request.url.toString())
        // ① 接口前缀一律不接管（交给 404，或本不该走到这里）
        if (rawPath.startsWith("/api/") || rawPath == "/api") {
            StaticFiles.writeJson404(ctx)
            return
        }
        var decoded = ApiPath.decode(rawPath)
        // 前端产物 build base='/new/'：资源请求形如 /new/assets/xxx.js，
        // 而静态根目录是 webapp/（assets 直接在其下），故剥离 /new 前缀。
        if (decoded == "/new" || decoded == "/new/") {
            decoded = "/index.html"
        } else if (decoded.startsWith("/new/")) {
            decoded = decoded[4..]
        }
        if (!StaticFiles.isSafe(decoded)) {
            StaticFiles.writeText(ctx, 400, "text/plain; charset=utf-8", "Bad Request")
            return
        }
        var rel = decoded
        if (rel == "/") {
            rel = "/index.html"
        }
        // ② 命中真实文件 → 直接给；给了长缓存（Vite 产物带内容哈希）
        match (this.read(rel)) {
            case Some(bytes) =>
                let mime = StaticFiles.mimeOf(rel)
                let cache = if (rel.startsWith("/assets/")) {
                    "public, max-age=31536000, immutable"
                } else {
                    "no-cache"
                }
                StaticFiles.writeBytes(ctx, 200, mime, cache, bytes)
                return
            case None => ()
        }
        // ③ SPA history 回落：仅当「看起来是页面路径」（无扩展名）时回落，
        //    带扩展名却找不到 = 真缺失，必须 404（否则缺文件被 HTML 掩盖）。
        if (!StaticFiles.hasExtension(rel)) {
            match (this.read("/index.html")) {
                case Some(bytes) =>
                    StaticFiles.writeBytes(
                        ctx, 200, "text/html; charset=utf-8", "no-cache", bytes)
                    return
                case None => ()
            }
        }
        StaticFiles.writeText(ctx, 404, "text/plain; charset=utf-8", "Not Found")
    }

    /** 读根目录下的相对路径文件。 */
    private func read(rel: String): Option<Array<Byte>> {
        try {
            return Some(File.readFrom("${this.root}${rel}"))
        } catch (e: Exception) {
            return None
        }
    }

    /**
     * 路径安全校验。
     *
     * 拒绝：`..` 段、反斜杠、盘符冒号、空字节。
     * 只做黑名单是不够的，但结合「拼在 root 之后 + 上面这几类全拒」，
     * 已覆盖 `../../etc/passwd`、`..\\..\\win.ini`、`C:/windows/...` 三类
     * 典型穿越；不做 realpath 归一化是因为 std.fs 无对应 API。
     */
    private static func isSafe(path: String): Bool {
        if (path.contains("..")) {
            return false
        }
        if (path.contains("\\")) {
            return false
        }
        if (path.contains(":")) {
            return false
        }
        if (path.contains("\u{0}")) {
            return false
        }
        return true
    }

    /** 是否带扩展名（用最后一段判断，避免把 /assets/a.b/c 误判）。 */
    private static func hasExtension(path: String): Bool {
        let segs = path.split("/")
        if (segs.size == 0) {
            return false
        }
        let last = segs[segs.size - 1]
        // ⚠️ 仓颉的 String.lastIndexOf 返回 Option<Int64>（None = 不含该字符），
        //    不能直接与 0 比较 —— 必须先解包。
        return match (last.lastIndexOf(".")) {
            case Some(i) => i > 0
            case None => false
        }
    }

    /** 去掉查询串与 fragment。 */
    private static func pathOnly(url: String): String {
        var end = url.size
        match (url.indexOf("?")) {
            case Some(q) => end = q
            case None => ()
        }
        match (url.indexOf("#")) {
            case Some(h) =>
                if (h < end) {
                    end = h
                }
            case None => ()
        }
        return url[0..end]
    }

    /** 扩展名 → MIME。未知一律 application/octet-stream（配合 nosniff 不猜）。 */
    private static func mimeOf(path: String): String {
        let dot = match (path.lastIndexOf(".")) {
            case Some(i) => i
            case None => 0
        }
        if (dot <= 0) {
            return "application/octet-stream"
        }
        let ext = path[dot + 1..].toAsciiLower()
        match (ext) {
            case "html" => return "text/html; charset=utf-8"
            case "js" => return "text/javascript; charset=utf-8"
            case "mjs" => return "text/javascript; charset=utf-8"
            case "css" => return "text/css; charset=utf-8"
            case "json" => return "application/json; charset=utf-8"
            case "map" => return "application/json; charset=utf-8"
            case "svg" => return "image/svg+xml"
            case "png" => return "image/png"
            case "jpg" => return "image/jpeg"
            case "jpeg" => return "image/jpeg"
            case "gif" => return "image/gif"
            case "webp" => return "image/webp"
            case "ico" => return "image/x-icon"
            case "woff" => return "font/woff"
            case "woff2" => return "font/woff2"
            case "ttf" => return "font/ttf"
            case "wasm" => return "application/wasm"
            case "txt" => return "text/plain; charset=utf-8"
            case _ => return "application/octet-stream"
        }
    }

    // ---------------- 响应写出 ----------------

    private static func writeBytes(
        ctx: HttpContext,
        status: UInt16,
        mime: String,
        cache: String,
        body: Array<Byte>
    ): Unit {
        ctx.responseBuilder
            .status(status)
            .header("content-type", mime)
            .header("cache-control", cache)
            .header("x-content-type-options", "nosniff")
            .header("referrer-policy", "no-referrer")
            .header("x-frame-options", "DENY")
            .body(body)
            .build()
    }

    private static func writeText(
        ctx: HttpContext,
        status: UInt16,
        mime: String,
        text: String
    ): Unit {
        ctx.responseBuilder
            .status(status)
            .header("content-type", mime)
            .header("cache-control", "no-store")
            .header("x-content-type-options", "nosniff")
            .body(text)
            .build()
    }

    /**
     * 未命中的 `/api/` 路径 → JSON 404。
     *
     * 形状与 ApiResponse.error 保持一致（code/message），
     * 让前端那一层不需要为「静态兜底」写特例分支。
     */
    private static func writeJson404(ctx: HttpContext): Unit {
        let body = "{\"code\":\"NOT_FOUND\",\"message\":\"接口不存在\"}"
        ctx.responseBuilder
            .status(404)
            .header("content-type", "application/json; charset=utf-8")
            .header("cache-control", "no-store")
            .header("x-content-type-options", "nosniff")
            .body(body)
            .build()
    }
}

/**
 * 把静态托管包装成 distributor 的兜底处理器。
 */
public class StaticHandler <: HttpRequestHandler {
    private let files: StaticFiles

    public init(files: StaticFiles) {
        this.files = files
    }

    public func handle(ctx: HttpContext): Unit {
        this.files.serve(ctx)
    }
}

/**
 * 百分号解码（静态路径用）。
 *
 * 只处理 %XX；非法序列原样保留（后续安全校验会拦下异常字符）。
 */
class ApiPath {
    static func decode(s: String): String {
        if (!s.contains("%")) {
            return s
        }
        let bytes = s.toArray()
        let out = ArrayList<Byte>()
        var i: Int64 = 0
        while (i < bytes.size) {
            let b = bytes[i]
            if (b == 37 && i + 2 < bytes.size) {      // '%'
                let hi = ApiPath.hexVal(bytes[i + 1])
                let lo = ApiPath.hexVal(bytes[i + 2])
                if (hi >= 0 && lo >= 0) {
                    // ⚠️ Byte 没有 `Byte(Int64)` 这种构造调用；数值转换一律走 UInt8(...)
                    out.add(UInt8(hi * 16 + lo))
                    i = i + 3
                    continue
                }
            }
            out.add(b)
            i = i + 1
        }
        return String.fromUtf8(out.toArray())
    }

    private static func hexVal(b: Byte): Int64 {
        let v = Int64(b)
        if (v >= 48 && v <= 57) {
            return v - 48
        }
        if (v >= 97 && v <= 102) {
            return v - 87
        }
        if (v >= 65 && v <= 70) {
            return v - 55
        }
        return -1
    }
}
