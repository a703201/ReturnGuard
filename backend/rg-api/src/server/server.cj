// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// HTTP 服务器装配：路由表挂到 stdx.net.http 的 ParamDistributor，
// 统一异常映射 + 前端静态托管（一个进程同端口提供 API 与 Vue SPA）。
// 参考 AMS ams.api.server（本机实测 stdx 1.2.0）。
package rg.api.server

import std.collection.*
import stdx.net.http.*
import rg.api.http.*
import rg.kernel.error.*
import rg.kernel.log.*

public class ApiServer {
    private let router: Router
    private let host: String
    private let port: Int64
    private let staticDir: String

    public init(host: String, port: Int64, router: Router, staticDir!: String = "") {
        this.host = host
        this.port = port
        this.router = router
        this.staticDir = staticDir
    }

    /** 启动服务（阻塞）。 */
    public func serve(): Unit {
        let builder = ServerBuilder()
        builder.addr(this.host)
        builder.port(UInt16(this.port))
        builder.maxRequestBodySize(MAX_BODY_BYTES)

        let distributor = ParamDistributor()
        // 每条路由注册一个静态路径入口；同一路径多方法由 methodDispatch 分派。
        let seen = HashSet<String>()
        for (r in this.router.allRoutes()) {
            if (seen.contains(r.pattern)) { continue }
            seen.add(r.pattern)
            distributor.register(r.pattern, { ctx: HttpContext =>
                let resp = this.dispatch(ctx)
                let rb = ctx.responseBuilder.status(UInt16(resp.status))
                for ((k, v) in resp.headers) { rb.header(k, v) }
                // 二进制响应（PDF 等）优先写字节；普通 JSON 写字符串。
                match (resp.bodyBytes) {
                    case Some(bytes) => rb.body(bytes).build()
                    case None => rb.body(resp.body).build()
                }
            })
        }
        if (!this.staticDir.isEmpty()) {
            distributor.setFallback(StaticFiles(this.staticDir).handler())
            Log.info("前端静态托管已启用: ${this.staticDir}")
        }
        builder.distributor(distributor)
        let server = builder.build()
        Log.info("服务启动 ${this.host}:${this.port}，路由 ${this.router.size()} 条")
        server.serve()
    }

    /** 分发一次请求：方法匹配 → 路径匹配 → 业务处理 → 异常映射。 */
    private func dispatch(ctx: HttpContext): ApiResponse {
        let req = ApiRequest.fromContext(ctx)
        let path = ApiRequest.pathOf(req.url)
        var matched: ?Route = None
        for (r in this.router.allRoutes()) {
            if (r.method != req.method) { continue }
            match (Router.matchPattern(r.pattern, path)) {
                case Some(params) =>
                    for ((k, v) in params) { req.pathParams.add(k, v) }
                    matched = Some(r)
                    break
                case None => ()
            }
        }
        match (matched) {
            case Some(route) =>
                // 统一守卫：OAuth scope 强制校验等（guard 返回非 null 即拦截）
                match (this.router.guard()) {
                    case Some(g) =>
                        match (g(req)) {
                            case Some(denied) => return denied
                            case None => ()
                        }
                    case None => ()
                }
                try {
                    return route.handler(req)
                } catch (e: AppError) {
                    return ApiResponse.fail(e.kind, e.detail)
                } catch (e: Exception) {
                    Log.warn("路由异常 ${e.toString()}")
                    return ApiResponse.fail(ErrKind.Internal, "服务器内部错误")
                }
            case None =>
                if (this.router.hasPath(path)) {
                    return ApiResponse.fail(ErrKind.MethodNotAllowed, "请求方法不被允许")
                }
                return ApiResponse.fail(ErrKind.NotFound, "接口不存在")
        }
    }
}
