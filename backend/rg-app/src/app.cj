// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// rg.app 顶层包：应用上下文（持有各服务单例）。子包 config/ auth/ insights/ 目录。
package rg.app

import std.env.*
import rg.data.store.*
import rg.data.db.*
import rg.security.authn.*
import rg.security.quota.*
import rg.security.oauth.*
import rg.ai.*
import rg.kernel.log.*

/** 应用上下文：所有路由共享的服务单例。 */
public class AppContext {
    public let store: Store
    public let auth: AuthService
    public let quota: Quota
    public let version: String
    public let threshold: Float64
    public let persistence: String          // "opengauss" / "memory"（如实呈现当前形态）
    public let ai: AiClient                 // AI 网关客户端（未配置时 configured()=false）
    public let aiProviders: ProviderRegistry  // 14 平台注册表（能力矩阵单一来源）
    public let aiProviderKey: String          // 当前生效平台 key
    public let oauth: OAuthService           // OAuth2 client_credentials 开放平台
    private var dbRef: ?Database = None     // 供 /health 深探针使用（内存模式为空）

    /** DB 健康探针：内存模式恒 true；持久化模式执行一次 SELECT 1。 */
    public func dbHealthy(): Bool {
        match (this.dbRef) {
            case Some(db) => return db.ping()
            case None => return true
        }
    }

    public init(version: String, threshold: Float64, secret: Array<Byte>) {
        this.version = version
        this.threshold = threshold
        this.aiProviders = ProviderRegistry()
        this.aiProviderKey = this.aiProviders.activeKey()
        // 当前 provider 的基地址/密钥/模型；模型名可用 RG_AI_MODEL 覆盖。
        let cur = this.aiProviders.get(this.aiProviderKey)
        let baseUrl = match (cur) { case Some(s) => s.resolvedBaseUrl(); case None => "" }
        let apiKey = match (cur) { case Some(s) => s.resolvedKey(); case None => "" }
        let defModel = match (cur) { case Some(s) => s.resolvedModel(); case None => "qwen-plus" }
        let model = getVariable("RG_AI_MODEL") ?? defModel
        this.ai = AiClient(baseUrl, apiKey, model)
        this.store = Store()
        // 每用户并发会话上限（0=不限；默认 5）
        let maxSessions = match (getVariable("RG_SESSION_MAX")) {
            case Some(v) => parseIntEnv(v, 5)
            case None => 5
        }
        this.auth = AuthService(this.store, secret, maxSessions: maxSessions)
        // OAuth2：用当前 auth 的签发函数发放 client 令牌（闭包捕获局部引用，构造期不能用 this）
        let oauthAuth = this.auth
        this.oauth = OAuthService({ clientId => oauthAuth.issueToken(clientId) })
        var quotaRef = Quota(QuotaConfig.fromEnv(), QuotaCounter.inMemory(), "memory")
        var persistMode = "memory"       // 局部，DB 分支里覆盖，末尾统一赋值
        let authRef = this.auth          // 局部引用，供闭包使用（构造期访问 this 受限）

        let dbHost = getVariable("RG_DB_HOST") ?? ""
        if (!dbHost.isEmpty()) {
            // ---- openGauss 持久化模式 ----
            let port = parseIntEnv(getVariable("RG_DB_PORT") ?? "15432", 15432)
            let dbName = getVariable("RG_DB_NAME") ?? "returnguard_cj"
            let dbUser = getVariable("RG_DB_USER") ?? "gaussdb"
            let dbPass = getVariable("RG_DB_PASSWORD") ?? ""
            let poolSize = parseIntEnv(getVariable("RG_DB_POOL") ?? "16", 16)
            let db = Database(DbConfig(dbHost, port, dbName, dbUser, dbPass, maxPoolSize: poolSize))
            this.dbRef = Some(db)
            db.initSchema()
            let userRepo = UserRepo(db)
            let caseRepo = CaseRepo(db)
            let auditRepo = AuditRepo(db)
            let quotaRepo = QuotaRepo(db)
            // 配额计数存 DB：跨 worker / 跨进程共享（同一 quota 表）
            quotaRef = Quota(QuotaConfig.fromEnv(),
                QuotaCounter({ s, b => quotaRepo.get(s, b) }, { s, b => quotaRepo.incr(s, b) }),
                "opengauss")
            // 服务端会话存储：令牌摘要落库，支持即时吊销 / 会话列表 / 远程踢出
            authRef.setSessionStore(DbSessionBridge(SessionRepo(db)))

            // 从库加载历史（用户 / 案件 / 审计链）
            userRepo.loadAll(this.store)
            caseRepo.loadAll(this.store)
            auditRepo.loadAll({ seq, ts, actor, action, ip, outcome, detail, prev, hash =>
                authRef.audit.restore(seq, ts, actor, action, ip, outcome, detail, prev, hash)
            })

            // 注入写路径回调：所有变更同步落库
            this.store.setCasePersist({ c => caseRepo.upsertBulk([c]) })
            this.store.setCaseRemove({ id, t => caseRepo.delete(id, t) })
            authRef.setPersist({ u => userRepo.upsert(u) })
            authRef.audit.setPersist({ ev => auditRepo.insert(
                ev.seq, ev.tsMs, ev.actor, ev.action, ev.ip, ev.outcome, ev.detail, ev.prevHash, ev.hash) })
            persistMode = "opengauss"
            Log.info("持久化已启用：用户 ${this.store.userCount()} / 案件 ${this.store.caseCount()} / 审计 ${authRef.audit.size()} 条已从库加载")
        } else {
            // ---- 内存回退（离线 / CI）----
            persistMode = "memory"
            Log.warn("未配置 RG_DB_HOST：使用内存存储，重启后数据丢失（仅开发/CI 可用）")
        }

        // 预置演示账户 + 演示案件（仅当库里还没有时补种；幂等由 upsert/DO NOTHING 保证）
        if (!this.store.userExists("demo")) {
            authRef.seedAccount("demo", "demo123", "ReturnGuard 演示租户")
        }
        if (this.store.caseCount() == 0) {
            let seeds = this.store.seedDemoCollect(1206)
            for (c in seeds) { this.store.addCase(c) }   // 内存也装入，insights 立即可用
            if (persistMode == "opengauss") {
                let port = parseIntEnv(getVariable("RG_DB_PORT") ?? "15432", 15432)
                let db = Database(DbConfig(getVariable("RG_DB_HOST") ?? "", port,
                    getVariable("RG_DB_NAME") ?? "returnguard_cj",
                    getVariable("RG_DB_USER") ?? "gaussdb", getVariable("RG_DB_PASSWORD") ?? "",
                    maxPoolSize: 0))  // 种子批量写同样禁用池，避免仓颉池死锁
                CaseRepo(db).upsertBulk(seeds)
            }
        }
        this.persistence = persistMode
        this.quota = quotaRef
        Log.info("配额闸后端=${this.quota.backend}（全局日/租户日/IP小时）")
    }
}

/** 把 SessionRepo 适配成 AuthService 的 SessionStore 抽象。 */
private class DbSessionBridge <: SessionStore {
    private let repo: SessionRepo
    public init(repo: SessionRepo) { this.repo = repo }
    public override func save(sid: String, username: String, tokenHash: String,
                              device: String, ip: String, createdMs: Int64, expiresMs: Int64): Unit {
        this.repo.save(sid, username, tokenHash, device, ip, createdMs, expiresMs)
    }
    public override func isActive(tokenHash: String, nowMs: Int64): Bool {
        return this.repo.isActive(tokenHash, nowMs)
    }
    public override func revokeAll(username: String): Unit { this.repo.revokeAll(username) }
    public override func listOf(username: String): String { return this.repo.listOf(username) }
    public override func revokeSid(username: String, sid: String): Unit { this.repo.revokeSid(username, sid) }
    public override func enforceSessionLimit(username: String, keep: Int64): Int64 {
        return this.repo.enforceSessionLimit(username, keep)
    }
    public override func saveWithRefresh(sid: String, username: String, tokenHash: String,
                                         refreshHash: String, ip: String, createdMs: Int64, expiresMs: Int64): Unit {
        this.repo.saveWithRefresh(sid, username, tokenHash, refreshHash, ip, createdMs, expiresMs)
    }
    public override func redeemRefresh(refreshHash: String, nowMs: Int64): String {
        return this.repo.redeemRefresh(refreshHash, nowMs)
    }
}

private func parseIntEnv(s: String, def: Int64): Int64 {
    // 空串或含非数字才回退默认值；"0" 是合法值（用于禁用连接池），不能当解析失败。
    if (s.isEmpty()) { return def }
    var acc: Int64 = 0
    for (b in s.toArray()) { if (b < 48 || b > 57) { return def }; acc = acc * 10 + Int64(b - 48) }
    return acc
}
