// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 三个 Repo：用户 / 案件 / 审计链。全部参数化 SQL（防注入），连接用 try/finally 归还。
package rg.data.db

import std.database.sql.*
import std.collection.*
import std.env.*
import rg.data.store.*
import rg.kernel.json.*

/** 用户持久化。 */
public class UserRepo {
    private let db: Database
    public init(db: Database) { this.db = db }

    /** 加载全部用户到内存 Store（启动时调用一次）。 */
    public func loadAll(store: Store): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement("SELECT username, password_hash, tenant_name, token_version, failed_count, locked_until_ms, totp_secret, hash_algo, display_name, email FROM rg_users")
            for (row in readRows(st.query())) {
                let u = UserRec(row.get("username") ?? "", row.get("password_hash") ?? "", row.get("tenant_name") ?? "")
                u.tokenVersion = parseInt64(row.get("token_version"))
                u.failedCount = parseInt64(row.get("failed_count"))
                u.lockedUntilMs = parseInt64(row.get("locked_until_ms"))
                u.totpSecret = row.get("totp_secret") ?? ""
                let algo = row.get("hash_algo") ?? "sha256"
                u.hashAlgo = if (algo.isEmpty()) { "sha256" } else { algo }
                u.displayName = row.get("display_name") ?? ""
                u.email = row.get("email") ?? ""
                store.addUser(u)
            }
        } finally { c.close() }
    }

    /** 插入或更新用户（注册时）。 */
    public func upsert(u: UserRec): Unit {
        let c = this.db.connect()
        try {
            // openGauss 5.0 不支持 ON CONFLICT，用 MERGE INTO 实现 upsert。
            let st = c.prepareStatement(
                "MERGE INTO rg_users t USING (SELECT ? AS k) s ON (t.username = s.k) " +
                "WHEN MATCHED THEN UPDATE SET password_hash=?, tenant_name=?, token_version=?, failed_count=?, locked_until_ms=?, totp_secret=?, hash_algo=?, display_name=?, email=? " +
                "WHEN NOT MATCHED THEN INSERT(username,password_hash,tenant_name,token_version,failed_count,locked_until_ms,totp_secret,hash_algo,display_name,email) " +
                "VALUES(?,?,?,?,?,?,?,?,?,?)")
            st.set(0, u.username)
            st.set(1, u.passwordHash); st.set(2, u.tenantName); st.set(3, u.tokenVersion)
            st.set(4, u.failedCount); st.set(5, u.lockedUntilMs); st.set(6, u.totpSecret); st.set(7, u.hashAlgo)
            st.set(8, u.displayName); st.set(9, u.email)
            st.set(10, u.username); st.set(11, u.passwordHash); st.set(12, u.tenantName)
            st.set(13, u.tokenVersion); st.set(14, u.failedCount); st.set(15, u.lockedUntilMs)
            st.set(16, u.totpSecret); st.set(17, u.hashAlgo)
            st.set(18, u.displayName); st.set(19, u.email)
            st.update()
        } finally { c.close() }
    }

    /** 更新认证状态（失败计数 / 锁定 / 令牌版本）。 */
    public func updateAuthState(u: UserRec): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "UPDATE rg_users SET token_version=?, failed_count=?, locked_until_ms=?, totp_secret=?, hash_algo=?, display_name=?, email=? WHERE username=?")
            st.set(0, u.tokenVersion); st.set(1, u.failedCount); st.set(2, u.lockedUntilMs)
            st.set(3, u.totpSecret); st.set(4, u.hashAlgo); st.set(5, u.displayName)
            st.set(6, u.email); st.set(7, u.username)
            st.update()
        } finally { c.close() }
    }
}

/** 案件持久化。 */
public class CaseRepo {
    private let db: Database
    public init(db: Database) { this.db = db }

    public func loadAll(store: Store): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "SELECT case_id, tenant, sku, category, supplier, platform, region, season, amount, similarity, outcome, defect FROM rg_cases")
            for (row in readRows(st.query())) {
                store.addCase(CaseRec(
                    row.get("case_id") ?? "", row.get("tenant") ?? "",
                    row.get("sku") ?? "", row.get("category") ?? "", row.get("supplier") ?? "",
                    row.get("platform") ?? "", row.get("region") ?? "", row.get("season") ?? "",
                    parseFloat64(row.get("amount")), parseFloat64(row.get("similarity")),
                    row.get("outcome") ?? "", row.get("defect") ?? ""))
            }
        } finally { c.close() }
    }

    /** 按 caseId + tenant 删除案件（防跨租户误删）。 */
    public func delete(caseId: String, tenant: String): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement("DELETE FROM rg_cases WHERE case_id=? AND tenant=?")
            st.set(0, caseId); st.set(1, tenant)
            st.update()
        } finally { c.close() }
    }

    public func upsertBulk(cases: Array<CaseRec>): Unit {
        if (cases.isEmpty()) { return }
        let c = this.db.connect()
        try {
            // MERGE 只插入不存在（重复 case_id 跳过）。
            let st = c.prepareStatement(
                "MERGE INTO rg_cases t USING (SELECT ? AS k) s ON (t.case_id = s.k) " +
                "WHEN NOT MATCHED THEN INSERT(case_id,tenant,sku,category,supplier,platform,region,season,amount,similarity,outcome,defect) " +
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
            for (cs in cases) {
                st.set(0, cs.caseId)
                st.set(1, cs.caseId); st.set(2, cs.tenant); st.set(3, cs.sku); st.set(4, cs.category)
                st.set(5, cs.supplier); st.set(6, cs.platform); st.set(7, cs.region); st.set(8, cs.season)
                st.set(9, cs.amount); st.set(10, cs.similarity); st.set(11, cs.outcome); st.set(12, cs.defect)
                st.update()
            }
        } finally { c.close() }
    }
}

/** 审计链持久化。事件按 seq 主键 append（只 INSERT，不改历史 → 防篡改）。 */
public class AuditRepo {
    private let db: Database
    public init(db: Database) { this.db = db }

    public func loadAll(append: (Int64, Int64, String, String, String, String, String, String, String) -> Unit): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "SELECT seq, ts_ms, actor, action, ip, outcome, detail, prev_hash, hash FROM rg_audit ORDER BY seq")
            for (row in readRows(st.query())) {
                append(parseInt64(row.get("seq")), parseInt64(row.get("ts_ms")),
                       row.get("actor") ?? "", row.get("action") ?? "", row.get("ip") ?? "",
                       row.get("outcome") ?? "", row.get("detail") ?? "",
                       row.get("prev_hash") ?? "", row.get("hash") ?? "")
            }
        } finally { c.close() }
    }

    public func insert(seq: Int64, tsMs: Int64, actor: String, action: String,
                       ip: String, outcome: String, detail: String, prevHash: String, hash: String): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "INSERT INTO rg_audit (seq, ts_ms, actor, action, ip, outcome, detail, prev_hash, hash) " +
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
            st.set(0, seq); st.set(1, tsMs); st.set(2, actor); st.set(3, action); st.set(4, ip)
            st.set(5, outcome); st.set(6, detail); st.set(7, prevHash); st.set(8, hash)
            st.update()
        } finally { c.close() }
    }
}

/** 服务端会话持久化：存令牌摘要（不存原文），支持即时吊销与会话列表。 */
public class SessionRepo {
    private let db: Database
    private let idleMs: Int64   // 空闲超时（毫秒）；<=0 表示禁用

    private static func envIdleMs(): Int64 {
        // RG_SESSION_IDLE_MS：默认 24h；0=禁用（用绝对有效期兜底）
        let s = getVariable("RG_SESSION_IDLE_MS") ?? ""
        if (s.isEmpty()) { return 24 * 60 * 60 * 1000 }
        let n = parseInt64(s)
        return if (n < 0) { 0 } else { n }
    }

    public init(db: Database) {
        this.db = db
        this.idleMs = SessionRepo.envIdleMs()
    }

    /** 记录一个已签发令牌（tokenHash = SHA256(token)）。 */
    public func save(sid: String, username: String, tokenHash: String,
                     device: String, ip: String, createdMs: Int64, expiresMs: Int64): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "INSERT INTO rg_sessions(sid,username,token_hash,device,ip,created_ms,expires_ms,revoked,last_used_ms) " +
                "VALUES(?,?,?,?,?,?,?,0,?)")
            st.set(0, sid); st.set(1, username); st.set(2, tokenHash); st.set(3, device)
            st.set(4, ip); st.set(5, createdMs); st.set(6, expiresMs); st.set(7, createdMs)
            st.update()
        } finally { c.close() }
    }

    /** 记录带 refresh 摘要的会话（一次登录/轮换各生成一对）。 */
    public func saveWithRefresh(sid: String, username: String, tokenHash: String,
                                refreshHash: String, ip: String,
                                createdMs: Int64, expiresMs: Int64): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "INSERT INTO rg_sessions(sid,username,token_hash,refresh_hash,device,ip,created_ms,expires_ms,revoked,used,last_used_ms) " +
                "VALUES(?,?,?,?,?,?,?,?,0,0,?)")
            st.set(0, sid); st.set(1, username); st.set(2, tokenHash); st.set(3, refreshHash)
            st.set(4, ""); st.set(5, ip); st.set(6, createdMs); st.set(7, expiresMs); st.set(8, createdMs)
            st.update()
        } finally { c.close() }
    }

    /**
     * 兑换 refresh token（一次性）。返回：
     *   "ok"       —— 成功（旧 refresh 标 used）
     *   "replay"   —— 该 refresh 已使用（重放攻击，需撤销全部会话）
     *   "invalid"  —— 不存在 / 已撤销 / 过期
     */
    public func redeemRefresh(refreshHash: String, nowMs: Int64): String {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "SELECT sid,username,used,revoked,expires_ms FROM rg_sessions WHERE refresh_hash=?")
            st.set(0, refreshHash)
            let rows = readRows(st.query())
            if (rows.isEmpty()) { return "invalid" }
            let row = rows[0]
            let sid = row.get("sid") ?? ""
            let user = row.get("username") ?? ""
            let used = parseInt64(row.get("used"))
            let revoked = parseInt64(row.get("revoked"))
            let exp = parseInt64(row.get("expires_ms"))
            if (revoked != 0 || exp < nowMs) { return "invalid" }
            if (used != 0) {
                // 重放：撤销该用户全部会话
                let st2 = c.prepareStatement("UPDATE rg_sessions SET revoked=1 WHERE username=?")
                st2.set(0, user); st2.update()
                return "replay"
            }
            let st3 = c.prepareStatement("UPDATE rg_sessions SET used=1 WHERE sid=?")
            st3.set(0, sid); st3.update()
            return "ok|" + sid + "|" + user
        } finally { c.close() }
    }

    /**
     * 令牌摘要是否对应一个有效会话：未撤销、未过期、且未空闲超时。
     * 空闲超时判定：nowMs - last_used_ms > idleMs 则撤销该会话并返回 false。
     * 活跃时刷新 last_used_ms（滑动窗口）。idleMs<=0 时跳过空闲判定（兼容旧行为）。
     */
    public func isActive(tokenHash: String, nowMs: Int64): Bool {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "SELECT sid,last_used_ms FROM rg_sessions WHERE token_hash=? AND revoked=0 AND expires_ms>?")
            st.set(0, tokenHash); st.set(1, nowMs)
            let rows = readRows(st.query())   // 读至 EOF，连接才能归还
            if (rows.isEmpty()) { return false }
            let row = rows[0]
            let sid = row.get("sid") ?? ""
            let lastUsed = parseInt64(row.get("last_used_ms"))
            if (this.idleMs > 0 && lastUsed > 0 && (nowMs - lastUsed) > this.idleMs) {
                let st2 = c.prepareStatement("UPDATE rg_sessions SET revoked=1 WHERE sid=?")
                st2.set(0, sid); st2.update()
                return false
            }
            if (this.idleMs > 0) {
                let st3 = c.prepareStatement("UPDATE rg_sessions SET last_used_ms=? WHERE sid=?")
                st3.set(0, nowMs); st3.set(1, sid); st3.update()
            }
            return true
        } finally { c.close() }
    }

    /**
     * 并发会话上限：保留该用户最近 keep 个活跃会话（按 created_ms 倒序），撤销更早的。
     * 用子查询取保留集合的 MIN(created_ms)，把 created_ms 更早的置 revoked。
     */
    public func enforceSessionLimit(username: String, keep: Int64): Int64 {
        if (keep < 0) { return 0 }
        let c = this.db.connect()
        try {
            // 先查第 keep 新的 created_ms 作为门槛（keep=0 表示全踢）
            var threshold: Int64 = 0
            if (keep == 0) {
                threshold = 9223372036854775807  // 踢全部：门槛设最大
            } else {
                let st = c.prepareStatement(
                    "SELECT created_ms FROM rg_sessions WHERE username=? AND revoked=0 " +
                    "ORDER BY created_ms DESC LIMIT 1 OFFSET ?")
                st.set(0, username); st.set(1, keep - 1)
                let rows = readRows(st.query())
                if (rows.isEmpty()) { return 0 }  // 活跃会话不足 keep 个，无需踢
                threshold = parseInt64(rows[0].get("created_ms"))
            }
            // 撤销 created_ms 严格早于门槛的会话（并列时间不误踢）
            // openGauss 用受影响行数；先 count 再 update 以避免 UPDATE 返回值差异
            let cntSt = c.prepareStatement(
                "SELECT COUNT(*) AS n FROM rg_sessions WHERE username=? AND revoked=0 AND created_ms<?")
            cntSt.set(0, username); cntSt.set(1, threshold)
            let cntRows = readRows(cntSt.query())
            var cnt: Int64 = 0
            if (!cntRows.isEmpty()) { cnt = parseInt64(cntRows[0].get("n")) }
            if (cnt > 0) {
                let up = c.prepareStatement(
                    "UPDATE rg_sessions SET revoked=1 WHERE username=? AND revoked=0 AND created_ms<?")
                up.set(0, username); up.set(1, threshold); up.update()
            }
            return cnt
        } finally { c.close() }
    }

    /** 撤销某用户全部会话（登出/改密/TOTP 变更时）。返回撤销数。 */
    public func revokeAll(username: String): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement("UPDATE rg_sessions SET revoked=1 WHERE username=? AND revoked=0")
            st.set(0, username)
            st.update()
        } finally { c.close() }
    }

    /** 列出用户会话（JSON 数组，供 /api/auth/sessions）。 */
    public func listOf(username: String): String {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "SELECT sid,device,ip,created_ms,expires_ms,revoked FROM rg_sessions WHERE username=? ORDER BY created_ms DESC")
            st.set(0, username)
            let arr = Arr()
            for (row in readRows(st.query())) {
                arr.raw(Obj()
                    .str("sid", row.get("sid") ?? "")
                    .str("device", row.get("device") ?? "")
                    .str("ip", row.get("ip") ?? "")
                    .str("created_ms", row.get("created_ms") ?? "0")
                    .str("expires_ms", row.get("expires_ms") ?? "0")
                    .str("revoked", row.get("revoked") ?? "0")
                    .build())
            }
            return arr.build()
        } finally { c.close() }
    }

    /** 远程踢出单个会话。 */
    public func revokeSid(username: String, sid: String): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement("UPDATE rg_sessions SET revoked=1 WHERE username=? AND sid=?")
            st.set(0, username); st.set(1, sid)
            st.update()
        } finally { c.close() }
    }
}

/** 配额计数持久化（跨 worker 共享）。用 MERGE 原子递增。 */
public class QuotaRepo {
    private let db: Database
    public init(db: Database) { this.db = db }

    /** 读取当前窗口计数。 */
    public func get(scope: String, bucket: String): Int64 {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement("SELECT cnt FROM rg_quota WHERE scope=? AND bucket=?")
            st.set(0, scope); st.set(1, bucket)
            let rows = readRows(st.query())
            if (rows.isEmpty()) { return 0 }
            return parseInt64(rows[0].get("cnt"))
        } finally { c.close() }
    }

    /** 计数 +1（MERGE 原子：存在则 cnt+1，否则插入 1）。 */
    public func incr(scope: String, bucket: String): Unit {
        let c = this.db.connect()
        try {
            let st = c.prepareStatement(
                "MERGE INTO rg_quota t USING (SELECT ? AS s, ? AS b) src ON (t.scope=src.s AND t.bucket=src.b) " +
                "WHEN MATCHED THEN UPDATE SET cnt=t.cnt+1 " +
                "WHEN NOT MATCHED THEN INSERT(scope,bucket,cnt) VALUES(?,?,1)")
            st.set(0, scope); st.set(1, bucket); st.set(2, scope); st.set(3, bucket)
            st.update()
        } finally { c.close() }
    }
}

private func parseInt64(s: ?String): Int64 {
    match (s) { case Some(v) => return parseI64(v); case None => return 0 }
}
private func parseFloat64(s: ?String): Float64 {
    match (s) { case Some(v) => return parseF64(v); case None => return 0.0 }
}
private func parseI64(s: String): Int64 {
    var acc: Int64 = 0; var neg = false; var i: Int64 = 0
    if (s.size > 0 && s[0] == 0x2d) { neg = true; i = 1 }
    while (i < s.size) {
        let b = s[i]
        if (b < 48 || b > 57) { break }
        acc = acc * 10 + Int64(b - 48); i += 1
    }
    return if (neg) { -acc } else { acc }
}
private func parseF64(s: String): Float64 {
    // 精简：只解析常见 "123.45"（负号支持），科学计数法留给后续
    var acc: Float64 = 0.0; var frac = false; var scale = 1.0; var neg = false; var i: Int64 = 0
    if (s.size > 0 && s[0] == 0x2d) { neg = true; i = 1 }
    while (i < s.size) {
        let b = s[i]
        if (b == 0x2e) { frac = true; i += 1; continue }
        if (b < 48 || b > 57) { break }
        if (frac) { scale /= 10.0; acc += Float64(b - 48) * scale }
        else { acc = acc * 10.0 + Float64(b - 48) }
        i += 1
    }
    return if (neg) { -acc } else { acc }
}
