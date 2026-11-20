// ============================================================
// ams.api.server.dispatcher · 支持参数化路径的请求分发器
//
// 需求：实现 stdx.net.http 的 HttpRequestDistributor 接口，
//   解决 stdx 内置 DirectDistributor **不支持 ":param" 占位**的问题。
//
// 【stdx 内置分发器的限制】（实测 1.2.0.1）
//   ① 只做**精确路径**匹配：
//      注册 "/api/users" 后，请求 "/api/users/900001" 返回 404；
//   ② 不支持通配：注册 "/api/*" 无效，注册 "*" 抛
//      "HttpException: Invalid path"；
//   ③ 同一路径不能注册两次（GET/POST 同路径会抛 "already registered"）。
//
// 【本实现】
//   ① 注册时保存「模式 → 处理器」（模式可含 ":param"）；
//   ② 分发时按**段数**筛出候选，再用 matchPattern 做参数匹配；
//      多个候选时**最长模式优先**（更具体的路由优先）；
//   ③ 同一模式可注册多次（不同方法），由 AMS 的 Router 在 handler 内分派，
//      故这里按「模式 + 方法」去重。
// ============================================================
package rg.api.server

import std.collection.*
import std.sync.*
import stdx.net.http.*

import rg.api.http.*
import rg.kernel.error.*

/**
 * 支持 ":param" 占位的请求分发器。
 */
public class ParamDistributor <: HttpRequestDistributor {
    /** 模式 → 处理器（同一模式可有多个方法，故用列表） */
    private let handlers: HashMap<String, ArrayList<HttpRequestHandler>>
    /** 已注册的「方法 + 模式」键（防重复注册） */
    private let registered: HashSet<String>
    /** 锁（register/distribute 可能跨线程） */
    private let lock: Mutex
    /**
     * 兜底处理器（所有模式都未命中时使用）。
     *
     * 用途：前端静态资源托管（`ams.api.server.static`）。
     * 没有它就没法在同一个端口上同时提供 SPA 与 /api —— 因为
     * SPA 的路径（/family、/share/xxx）是**任意**的，无法逐一注册。
     */
    private var fallback: ?HttpRequestHandler

    public init() {
        this.handlers = HashMap<String, ArrayList<HttpRequestHandler>>()
        this.registered = HashSet<String>()
        this.lock = Mutex()
        this.fallback = None
    }

    /**
     * 设置兜底处理器。
     *
     * 只允许设置一次：多次覆盖会让「到底哪段代码在接请求」变得不可知，
     * 而这类问题在日志里只表现为「返回内容不对」。
     */
    public func setFallback(handler: HttpRequestHandler): Unit {
        this.lock.lock()
        try {
            if (this.fallback.isNone()) {
                this.fallback = Some(handler)
            }
        } finally {
            this.lock.unlock()
        }
    }

    /**
     * 注册请求处理器。
     *
     * @param path    路径模式（可含 ":param"，也可带方法前缀 "GET /api/x"）
     * @param handler 处理器
     */
    public func register(path: String, handler: HttpRequestHandler): Unit {
        this.lock.lock()
        try {
            // 同一路径可注册多个（不同方法），故不用「模式」做唯一键，
            // 而是用「方法 + 模式」。方法信息在 path 前缀里（可选）。
            let key = path
            if (this.registered.contains(key)) {
                return
            }
            this.registered.add(key)
            match (this.handlers.get(path)) {
                case Some(list) => list.add(handler)
                case None =>
                    let list = ArrayList<HttpRequestHandler>()
                    list.add(handler)
                    this.handlers[path] = list
            }
        } finally {
            this.lock.unlock()
        }
    }

    /**
     * 查找匹配路径的处理器。
     *
     * @param path 请求路径
     * @return 匹配到的处理器；未匹配返回 None
     */
    public func distribute(path: String): HttpRequestHandler {
        this.lock.lock()
        try {
            // 候选：段数相同的模式
            let segCount = path.split("/").size
            var best: ?HttpRequestHandler = None
            var bestLen: Int64 = -1
            for ((pattern, list) in this.handlers) {
                if (pattern.split("/").size != segCount) {
                    continue
                }
                if (!ParamDistributor.matchPattern(pattern, path)) {
                    continue
                }
                // 最长模式优先（更具体）
                if (pattern.size > bestLen) {
                    bestLen = pattern.size
                    best = Some(list[0])
                }
            }
            match (best) {
                case Some(h) => return h
                case None => ()
            }
            match (this.fallback) {
                case Some(h) => return h
                case None => return ParamDistributor.notFoundHandler()
            }
        } finally {
            this.lock.unlock()
        }
    }

    /**
     * 路径模式匹配（":param" 匹配一段非空内容）。
     */
    private static func matchPattern(pattern: String, path: String): Bool {
        let ps = pattern.split("/")
        let qs = path.split("/")
        if (ps.size != qs.size) {
            return false
        }
        for (i in 0..ps.size) {
            if (ps[i].startsWith(":")) {
                if (qs[i].isEmpty()) {
                    return false
                }
            } else if (ps[i] != qs[i]) {
                return false
            }
        }
        return true
    }

    /**
     * 未匹配时的兜底处理器（返回 404，与 stdx 内置行为一致）。
     */
    private static func notFoundHandler(): HttpRequestHandler {
        return NotFoundHandler()
    }
}

/**
 * 404 处理器。
 *
 * 统一走 ApiResponse.error 信封（code/message/requestId），
 * 与 AMS 路由层的 404 形状一致，前端无需为分发器兜底写特例分支。
 */
public class NotFoundHandler <: HttpRequestHandler {
    public func handle(ctx: HttpContext): Unit {
        let resp = ApiResponse.fail(ErrKind.NotFound, "接口不存在")
        let rb = ctx.responseBuilder.status(UInt16(resp.status))
        for ((k, v) in resp.headers) {
            rb.header(k, v)
        }
        rb.body(resp.body).build()
    }
}
