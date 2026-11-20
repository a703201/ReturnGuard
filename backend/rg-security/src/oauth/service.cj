// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// OAuth2 client_credentials 最小实现：客户端注册 + 令牌签发。
// 客户端密钥只存 SHA256 摘要（明文仅注册时返回一次）；令牌复用 AuthService 的标准令牌体系。
// 客户端注册表与令牌 scope 落本地文件（容器卷持久化，重启不丢）；密钥只存 SHA256 摘要。
package rg.security.oauth

import std.collection.*
import std.time.*
import rg.security.authn.{toHex, sha256, randomBytes, constantEq}

/** 一个 OAuth2 客户端（secretHash = SHA256(明文 secret)）。 */
public class OAuthClient {
    public let clientId: String
    public let name: String
    public let secretHash: String
    public let scope: String
    public let owner: String              // 令牌归属的真实用户（决定租户）
    public let createdMs: Int64
    public init(clientId: String, name: String, secretHash: String, scope: String, owner: String, createdMs: Int64) {
        this.clientId = clientId
        this.name = name
        this.secretHash = secretHash
        this.scope = scope
        this.owner = owner
        this.createdMs = createdMs
    }
}

/** 注册结果：明文 secret 仅此一次返回。 */
public class RegisteredClient {
    public let clientId: String
    public let clientSecret: String
    public let scope: String
    public init(clientId: String, clientSecret: String, scope: String) {
        this.clientId = clientId
        this.clientSecret = clientSecret
        this.scope = scope
    }
}

/** 令牌响应。 */
public class OAuthToken {
    public let accessToken: String
    public let tokenType: String
    public let expiresIn: Int64
    public let scope: String
    public init(accessToken: String, tokenType: String, expiresIn: Int64, scope: String) {
        this.accessToken = accessToken
        this.tokenType = tokenType
        this.expiresIn = expiresIn
        this.scope = scope
    }
}

/** OAuth2 客户端注册表（本地文件持久化，单进程内共享）。 */
public class OAuthService {
    private let clients = HashMap<String, OAuthClient>()
    private let store: OAuthStore
    private let issueFn: (String) -> String   // owner -> access token
    private let ttlSeconds: Int64

    public init(issueFn: (String) -> String, ttlSeconds!: Int64 = 604800) {
        this.issueFn = issueFn
        this.ttlSeconds = ttlSeconds
        this.store = OAuthStore()
        // 从文件加载已注册客户端（重启不丢）
        for (row in this.store.loadClients()) {
            this.clients.add(row[0], OAuthClient(row[0], row[1], row[2], row[3], row[4], 0))
        }
    }

    private func randomHex(bytes: Int64): String {
        let b = randomBytes(bytes)
        let digits = "0123456789abcdef"
        let sb = StringBuilder()
        for (i in 0..b.size) {
            let v = Int64(b[i])
            sb.append(digits[(v >> 4) & 0xf].toString())
            sb.append(digits[v & 0xf].toString())
        }
        return sb.toString()
    }

    /** 把内存注册表整表写回文件。 */
    private func persistClients(): Bool {
        let rows = ArrayList<Array<String>>()
        for ((_, c) in this.clients) {
            rows.add([c.clientId, c.name, c.secretHash, c.scope, c.owner, "0"])
        }
        return this.store.saveClients(rows.toArray())
    }

    /** 注册客户端：生成 client_id/client_secret，secret 只返回明文一次。 */
    public func register(name: String, owner: String, scope!: String = "insights:read"): RegisteredClient {
        let cid = "rgc_" + this.randomHex(12)
        let secret = "rgs_" + this.randomHex(24)
        let hash = toHex(sha256(secret.toArray()))
        let now = DateTime.now().toUnixTimeStamp().toMilliseconds()
        this.clients.add(cid, OAuthClient(cid, name, hash, scope, owner, now))
        this.persistClients()
        return RegisteredClient(cid, secret, scope)
    }

    /** client_credentials 换令牌：校验 id/secret 后签发标准 access token，并记录令牌 scope 供写操作校验。 */
    public func issueToken(clientId: String, clientSecret: String): ?OAuthToken {
        let c = match (this.clients.get(clientId)) {
            case Some(v) => v
            case None => return None
        }
        let hash = toHex(sha256(clientSecret.toArray()))
        if (!constantEq(hash, c.secretHash)) { return None }
        let token = this.issueFn(c.owner)   // 以归属用户签发（令牌可正常 verify 且租户隔离正确）
        let now = DateTime.now().toUnixTimeStamp().toMilliseconds()
        this.store.addScope(toHex(sha256(token.toArray())), c.scope, now + this.ttlSeconds * 1000)
        return OAuthToken(token, "Bearer", this.ttlSeconds, c.scope)
    }

    /** 密钥轮换：校验旧 secret 后生成新 secret（明文只返回一次），旧密钥立即失效。 */
    public func rotateSecret(clientId: String, oldSecret: String): ?String {
        let c = match (this.clients.get(clientId)) {
            case Some(v) => v
            case None => return None
        }
        let oldHash = toHex(sha256(oldSecret.toArray()))
        if (!constantEq(oldHash, c.secretHash)) { return None }
        let newSecret = "rgs_" + this.randomHex(24)
        let newHash = toHex(sha256(newSecret.toArray()))
        this.clients.add(clientId, OAuthClient(clientId, c.name, newHash, c.scope, c.owner, c.createdMs))
        this.persistClients()
        return newSecret
    }

    /**
     * scope 强制校验：给定令牌摘要，判断其 scope 是否允许写操作。
     * 普通会话令牌（无 OAuth 记录）放行；insights:read 等只读 scope 拒绝写。
     * 返回 true=允许，false=拒绝。
     */
    public func allowsWrite(tokenHash: String): Bool {
        let scope = this.store.scopeOf(tokenHash)
        if (scope.isEmpty()) { return true }   // 非 OAuth 令牌走原鉴权
        return scope.contains("write") || scope.contains("*")
    }

    /** 列出已注册客户端（脱敏，不含 secret）。 */
    public func listClients(): String {
        let sb = StringBuilder()
        sb.append("[")
        var first = true
        for ((_, c) in this.clients) {
            if (!first) { sb.append(",") }
            first = false
            sb.append("{\"client_id\":\"")
            sb.append(c.clientId)
            sb.append("\",\"name\":\"")
            sb.append(c.name)
            sb.append("\",\"scope\":\"")
            sb.append(c.scope)
            sb.append("\"}")
        }
        sb.append("]")
        return sb.toString()
    }
}
