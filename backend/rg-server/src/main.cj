// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// ReturnGuard 仓颉后端可执行文件入口。
// 装配顺序：配置 -> 应用上下文(存储/认证/配额/种子) -> 路由 -> HTTP 服务。
// 环境变量：RG_HTTP_HOST / RG_HTTP_PORT / RG_WEB_DIR / AUTH_SECRET / RG_THRESHOLD。
package rg.server

import std.env.*
import std.collection.*
import stdx.net.http.*
import rg.app.*
import rg.api.http.*
import rg.api.server.*
import rg.api.routes.*
import rg.kernel.log.*
import rg.security.authn.{randomBytes, sha256, toHex}

main() {
    let host = getVariable("RG_HTTP_HOST") ?? "127.0.0.1"
    let portStr = getVariable("RG_HTTP_PORT") ?? "8001"
    let port = parseIntOr(portStr, 8001)
    let webDir = getVariable("RG_WEB_DIR") ?? "../demo/webapp"
    let version = getVariable("RG_VERSION") ?? "3.1.0"
    let threshold = Float64(parseIntOr(getVariable("RG_THRESHOLD_PCT") ?? "82", 82)) / 100.0

    // 令牌签名密钥：生产必须显式提供（失败关闭），本地开发用程序内随机值。
    let secretEnv = getVariable("AUTH_SECRET") ?? ""
    let secret = if (secretEnv.isEmpty()) { randomBytes(32) } else { secretEnv.toArray() }
    if (secretEnv.isEmpty()) {
        Log.warn("AUTH_SECRET 未设置：使用进程内随机密钥，重启后令牌失效（开发默认值，生产务必固化）")
    }

    Log.info("ReturnGuard 仓颉后端启动 host=${host} port=${port} version=${version}")

    let ctx = AppContext(version, threshold, secret)
    let router = Router()
    registerRoutes(router, ctx)
    // OAuth2 scope 强制校验：只读客户端（insights:read）的令牌禁止调用写端点。
    // 普通会话令牌无 OAuth scope 记录，放行；登录/换令牌等公开端点不在限制内（未带 OAuth 令牌）。
    router.setGuard(fn: { req =>
        let m = req.method.toAsciiUpper()
        if (m == "GET" || m == "HEAD" || m == "OPTIONS") { return None }
        match (req.bearerToken()) {
            case Some(t) =>
                let th = toHex(sha256(t.toArray()))
                if (!ctx.oauth.allowsWrite(th)) {
                    return ApiResponse(403, "{\"detail\":\"OAuth scope 不足：该客户端仅授予只读权限\"}")
                }
                return None
            case None => return None
        }
    })
    let server = ApiServer(host, port, router, staticDir: webDir)
    server.serve()
}

private func parseIntOr(s: String, def: Int64): Int64 {
    let v = parseInt(s)
    return if (v == 0 && s != "0") { def } else { v }
}
private func parseInt(s: String): Int64 {
    var acc: Int64 = 0
    for (b in s.toArray()) {
        if (b < 48 || b > 57) { return 0 }
        acc = acc * 10 + Int64(b - 48)
    }
    return acc
}
