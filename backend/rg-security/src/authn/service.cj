// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 认证服务：注册 / 登录 / 令牌签发校验 / 失败锁定 / 会话吊销。
// 安全基线参考 AMS：口令 PBKDF2 40 万轮、令牌 HMAC-SHA256、
// 失败锁定、token_version 吊销、失败响应不区分用户是否存在。
package rg.security.authn

import std.collection.*
import std.time.*
import rg.data.store.*
import rg.security.audit.*
import rg.security.crypto.{Pbkdf2}
import rg.security.totp.{Totp}

/** 用户变更持久化回调（由上层用 UserRepo.upsert / updateAuthState 注入）。 */
public type UserPersist = (UserRec) -> Unit

/**
 * 服务端会话存储抽象（由上层用 SessionRepo 实现；避免 security 依赖 data）。
 * 令牌签发即登记，校验时查存在性 → 支持即时吊销（AMS §5.2）。
 */
public abstract class SessionStore {
    public open func save(sid: String, username: String, tokenHash: String,
                     device: String, ip: String, createdMs: Int64, expiresMs: Int64): Unit {}
    public open func isActive(tokenHash: String, nowMs: Int64): Bool { return true }  // 默认放行（未注入时兼容）
    public open func revokeAll(username: String): Unit {}
    public open func listOf(username: String): String { return "[]" }
    public open func revokeSid(username: String, sid: String): Unit {}
    /** 并发会话上限：保留最近 keep 个活跃会话，撤销更旧的；返回撤销数。 */
    public open func enforceSessionLimit(username: String, keep: Int64): Int64 { return 0 }
    /** refresh token 支持：保存 refresh 摘要（默认空实现，兼容内存模式）。 */
    public open func saveWithRefresh(sid: String, username: String, tokenHash: String,
                                     refreshHash: String, ip: String, createdMs: Int64, expiresMs: Int64): Unit {}
    /** 兑换 refresh，返回 "ok|sid|user" / "replay" / "invalid"。 */
    public open func redeemRefresh(refreshHash: String, nowMs: Int64): String { return "invalid" }
}

/** 令牌对：access（短 TTL）+ refresh（一次性轮换）。 */
public class TokenPair {
    public let access: String
    public let refresh: String
    public init(access: String, refresh: String) { this.access = access; this.refresh = refresh }
}

/** 登录结果。 */
public class AuthResult {
    public let ok: Bool
    public let token: String
    public let reason: String
    public init(ok: Bool, token: String, reason: String) {
        this.ok = ok; this.token = token; this.reason = reason
    }
}

/** 常见弱口令（注册时拒绝，参考 AMS authn/weakdict）。骨架内置高频样本，可外部扩充。 */
private let WEAK_PASSWORDS: Array<String> = [
    "123456", "password", "12345678", "qwerty", "abc123", "111111",
    "123456789", "000000", "admin", "letmein", "demo123", "123123"
]

private func isWeakPassword(p: String): Bool {
    let lower = p.toAsciiLower()
    for (w in WEAK_PASSWORDS) { if (lower == w) { return true } }
    // 纯数字或长度 < 8 视为弱
    if (p.size < 8) { return true }
    var allDigit = true
    for (b in p.toArray()) { if (b < 48 || b > 57) { allDigit = false; break } }
    return allDigit
}

/** 认证服务（持有全局 Store 引用 + 签名密钥）。 */
public class AuthService {
    private let store: Store
    private let secret: Array<Byte>
    private let maxFails: Int64
    private let lockSeconds: Int64
    private let tokenTtlSeconds: Int64
    private let maxSessions: Int64              // 每用户并发活跃会话上限（0=不限）
    public let audit: AuditLog                    // 认证审计链（供管理端点校验）
    private var onPersist: ?UserPersist = None   // 用户状态持久化回调（可选，离线时为空）
    private var sessionStore: ?SessionStore = None  // 服务端会话存储（可选，注入后启用即时吊销）
    // 时序防护哨兵：用户不存在时对固定盐跑一次等价 PBKDF2，抹平时序差异（AMS §5.3）
    private let dummySalt: Array<Byte> = [0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
                                          0x69, 0x6a, 0x6b, 0x6c, 0x6d, 0x6e, 0x6f, 0x70]

    public init(store: Store, secret: Array<Byte>,
                maxFails!: Int64 = 5, lockSeconds!: Int64 = 900, tokenTtlSeconds!: Int64 = 604800,
                maxSessions!: Int64 = 5) {
        this.store = store
        this.secret = secret
        this.maxFails = maxFails
        this.lockSeconds = lockSeconds
        this.tokenTtlSeconds = tokenTtlSeconds
        this.maxSessions = maxSessions
        this.audit = AuditLog()
    }

    /** 注入用户持久化回调（AppContext 启动时调用）。 */
    public func setPersist(cb: UserPersist): Unit { this.onPersist = Some(cb) }
    /** 注入服务端会话存储（AppContext 启动时调用）。 */
    public func setSessionStore(store: SessionStore): Unit { this.sessionStore = Some(store) }
    /** 会话列表（供 /api/auth/sessions）。 */
    public func sessionsOf(username: String): String {
        match (this.sessionStore) { case Some(s) => return s.listOf(username); case None => return "[]" }
    }
    /** 远程踢出会话。 */
    public func revokeSession(username: String, sid: String): Unit {
        match (this.sessionStore) { case Some(s) => s.revokeSid(username, sid); case None => () }
    }
    private func persist(u: UserRec): Unit {
        match (this.onPersist) { case Some(cb) => cb(u); case None => () }
    }

    /** 注册：成功返回令牌。一个用户 = 一个租户。
     *  枚举防护：无论用户名是否已存在，对外统一返回模糊提示（AMS §5.3）。 */
    public func register(username: String, password: String, tenantName: String): AuthResult {
        return this.doRegister(username, password, tenantName, true, true, "sha256")
    }

    /** 国密注册：口令派生用 PBKDF2-HMAC-SM3（信创场景，向前兼容存量 sha256 用户）。 */
    public func registerSm3(username: String, password: String, tenantName: String): AuthResult {
        return this.doRegister(username, password, tenantName, true, true, "sm3")
    }

    /** 预置系统账户（如 demo）：跳过弱口令校验，用于启动种子，不是公开注册入口。 */
    public func seedAccount(username: String, password: String, tenantName: String): AuthResult {
        return this.doRegister(username, password, tenantName, false, false, "sha256")
    }

    private let vagueRegisterMsg = "若该用户名可用，账户已创建；请尝试登录"

    private func doRegister(username: String, password: String, tenantName: String,
                            checkWeak: Bool, fuzzy: Bool, algo: String): AuthResult {
        if (username.isEmpty() || password.size < 6) {
            return AuthResult(false, "", "用户名不能为空且密码至少 6 位")
        }
        if (checkWeak && isWeakPassword(password)) {
            return AuthResult(false, "", "密码强度不足：请勿使用常见弱口令，至少 8 位且含非数字字符")
        }
        if (this.store.userExists(username)) {
            // 枚举防护：不暴露"已存在"，仍跑一次 KDF 抹平时序差异
            let _ = pbkdf2(password.toArray(), this.dummySalt, 400000, 32)
            this.audit.append(username, "auth.register", "", "rejected_duplicate", "")
            let msg = if (fuzzy) { vagueRegisterMsg } else { "用户名已存在" }
            return AuthResult(false, "", msg)
        }
        let salt = randomBytes(16)
        let dk = if (algo == "sm3") { Pbkdf2.deriveSm3(password.toArray(), salt, 400000, 32) }
                 else { pbkdf2(password.toArray(), salt, 400000, 32) }
        let hash = toHex(salt) + ":" + toHex(dk)
        let u = UserRec(username, hash, tenantName)
        u.hashAlgo = algo
        this.store.addUser(u)
        this.persist(u)
        this.audit.append(username, "auth.register", "", "success", "")
        return AuthResult(true, this.issueToken(username), "")
    }

    /** 登录：失败统一文案（不区分用户是否存在 / 是否锁定）。
     *  时序防护：用户不存在时仍跑一次等价 PBKDF2（AMS §5.3 防撞库）。 */
    public func login(username: String, password: String, ip: String): AuthResult {
        let u = this.store.getUser(username)
        let now = nowMs()
        match (u) {
            case Some(user) =>
                if (user.lockedUntilMs > now) {
                    this.audit.append(username, "auth.login", ip, "rejected_locked", "")
                    return AuthResult(false, "", "用户名或密码错误")
                }
                if (user.tokenVersion < 1) {
                    this.audit.append(username, "auth.login", ip, "rejected_disabled", "")
                    return AuthResult(false, "", "用户名或密码错误")
                }
                let parts = user.passwordHash.split(":").toArray()
                if (parts.size != 2) { return AuthResult(false, "", "用户名或密码错误") }
                let salt = fromHex(parts[0])
                let dk = if (user.hashAlgo == "sm3") { Pbkdf2.deriveSm3(password.toArray(), salt, 400000, 32) }
                         else { pbkdf2(password.toArray(), salt, 400000, 32) }
                if (constantEq(toHex(dk), parts[1])) {
                    user.failedCount = 0
                    user.lockedUntilMs = 0
                    this.persist(user)
                    this.audit.append(username, "auth.login", ip, "success", "")
                    return AuthResult(true, this.issueToken(username), "")
                }
                user.failedCount += 1
                var outcome = "bad_password"
                if (user.failedCount >= this.maxFails) {
                    user.lockedUntilMs = now + this.lockSeconds * 1000
                    user.failedCount = 0
                    outcome = "locked"
                }
                this.persist(user)
                this.audit.append(username, "auth.login", ip, outcome, "")
                return AuthResult(false, "", "用户名或密码错误")
            case None =>
                // 等价 KDF 计算，抹平"用户不存在"与"口令错误"的响应时间差
                let _ = pbkdf2(password.toArray(), this.dummySalt, 400000, 32)
                this.audit.append(username, "auth.login", ip, "bad_credentials", "")
                return AuthResult(false, "", "用户名或密码错误")
        }
    }

    /** 签发令牌：hex(username).hex(HMAC).expireSec.ver.jti。
     *  jti 为随机 8 字节，避免同用户同秒签发的令牌完全相同（重放可区分）。 */
    public func issueToken(username: String, ip!: String = "", device!: String = ""): String {
        let now = nowMs()
        let exp = now / 1000 + this.tokenTtlSeconds
        let u = this.store.getUser(username)
        let ver = match (u) { case Some(user) => user.tokenVersion; case None => 1 }
        let jti = toHex(randomBytes(8))
        let payload = username + "|${exp}|${ver}|${jti}"
        let sig = toHex(hmacSha256(this.secret, payload.toArray()))
        let token = b64encode(username) + "." + sig + "." + "${exp}" + "." + "${ver}" + "." + jti
        // 登记服务端会话（未注入时无操作）
        match (this.sessionStore) {
            case Some(ss) =>
                // 并发会话上限：签发新会话前踢掉该用户最旧的会话（保留 maxSessions-1 个）
                if (this.maxSessions > 0) { ss.enforceSessionLimit(username, this.maxSessions - 1) }
                ss.save(jti, username, toHex(sha256(token.toArray())),
                        device, ip, now, exp * 1000)
            case None => ()
        }
        return token
    }

    /**
     * 签发令牌对：access（本 tokenTtlSeconds）+ refresh（30 天，一次性轮换）。
     * refresh 摘要存会话表；重放使用会触发该用户全部会话撤销。
     */
    public func issueTokenPair(username: String, ip: String): TokenPair {
        let access = this.issueToken(username, ip: ip)
        let now = nowMs()
        let exp = now / 1000 + 30 * 86400
        let jti = toHex(randomBytes(8))
        let payload = "R|" + username + "|${exp}|${jti}"
        let sig = toHex(hmacSha256(this.secret, payload.toArray()))
        let refresh = "r." + b64encode(username) + "." + sig + "." + "${exp}" + "." + jti
        match (this.sessionStore) {
            case Some(ss) => ss.saveWithRefresh(jti, username,
                toHex(sha256(access.toArray())), toHex(sha256(refresh.toArray())),
                ip, now, exp * 1000)
            case None => ()
        }
        return TokenPair(access, refresh)
    }

    /** 兑换 refresh：成功返回新令牌对；重放返回 None 并已撤销全部会话。 */
    public func rotateRefresh(refresh: String, ip: String): ?TokenPair {
        let parts = refresh.split(".").toArray()
        if (parts.size != 5 || parts[0] != "r") { return None }
        let username = b64decode(parts[1])
        let exp = parseInt(parts[3])
        let jti = parts[4]
        if (exp < nowMs() / 1000) { return None }
        let payload = "R|" + username + "|${exp}|${jti}"
        let expect = toHex(hmacSha256(this.secret, payload.toArray()))
        if (!constantEq(parts[2], expect)) { return None }
        match (this.sessionStore) {
            case Some(ss) =>
                let r = ss.redeemRefresh(toHex(sha256(refresh.toArray())), nowMs())
                if (r.size < 3 || r[0..3] != "ok|") { return None }
                return Some(this.issueTokenPair(username, ip))
            case None => return None
        }
    }

    /** 校验令牌：返回用户名（无效返回 None）。 */
    public func verify(token: String): ?String {
        let parts = token.split(".").toArray()
        if (parts.size != 5) { return None }
        let username = b64decode(parts[0])
        let exp = parseInt(parts[2])
        let ver = parseInt(parts[3])
        let jti = parts[4]
        if (exp < nowMs() / 1000) { return None }
        let payload = username + "|${exp}|${ver}|${jti}"
        let expect = toHex(hmacSha256(this.secret, payload.toArray()))
        if (!constantEq(parts[1], expect)) { return None }
        let u = this.store.getUser(username)
        match (u) {
            case Some(user) =>
                if (user.tokenVersion != ver) { return None }
                // 服务端会话存在性校验（即时吊销）：注入会话存储后，令牌必须在会话表且未撤销
                match (this.sessionStore) {
                    case Some(ss) =>
                        if (!ss.isActive(toHex(sha256(token.toArray())), nowMs())) { return None }
                    case None => ()
                }
                return username
            case None => return None
        }
    }

    /** 登出：自增 token_version，使所有已签发令牌失效，并写审计。 */
    public func logout(username: String): Unit {
        let u = this.store.getUser(username)
        match (u) {
            case Some(user) => user.tokenVersion += 1; this.persist(user)
            case None => ()
        }
        match (this.sessionStore) { case Some(ss) => ss.revokeAll(username); case None => () }
        this.audit.append(username, "auth.logout", "", "success", "")
    }

    /** 取用户信息（展示用）。 */
    public func userOf(username: String): ?UserRec { return this.store.getUser(username) }

    // ---------------- TOTP 二次验证 ----------------
    /** 生成新的 TOTP 密钥与 otpauth URI（尚未绑定，需 enable 确认）。返回 "secret|uri"。 */
    public func totpSetup(username: String, issuer: String): String {
        let secret = Totp.newSecret(randomBytes(20))
        let uri = Totp.otpauthUrl(issuer, username, secret)
        return secret + "|" + uri
    }

    /** 用一次性验证码确认绑定；成功写 secret 并落库。返回是否成功。 */
    public func totpEnable(username: String, secretB32: String, code: String): Bool {
        let now = nowMs()
        if (Totp.verify(secretB32, code, now, 1) < 0) { return false }
        let u = this.store.getUser(username)
        match (u) {
            case Some(user) => user.totpSecret = secretB32; this.persist(user)
                               this.audit.append(username, "auth.totp", "", "enabled", "")
                               return true
            case None => return false
        }
    }

    /** 校验 TOTP 验证码（登录二段 / 敏感操作）。用户未绑定返回 false。 */
    public func totpVerify(username: String, code: String): Bool {
        let u = this.store.getUser(username)
        match (u) {
            case Some(user) =>
                if (user.totpSecret.isEmpty()) { return false }
                let ok = Totp.verify(user.totpSecret, code, nowMs(), 1) >= 0
                this.audit.append(username, "auth.totp", "", if (ok) { "verified" } else { "failed" }, "")
                return ok
            case None => return false
        }
    }

    /** 用户是否已绑定 TOTP。 */
    public func totpEnabled(username: String): Bool {
        let u = this.store.getUser(username)
        return match (u) { case Some(user) => !user.totpSecret.isEmpty(); case None => false }
    }

    /** 关闭 TOTP（需先校验当前 code）。 */
    public func totpDisable(username: String, code: String): Bool {
        if (!this.totpVerify(username, code)) { return false }
        let u = this.store.getUser(username)
        match (u) {
            case Some(user) => user.totpSecret = ""; this.persist(user)
                               this.audit.append(username, "auth.totp", "", "disabled", "")
                               return true
            case None => return false
        }
    }

    private func fromHex(s: String): Array<Byte> {
        let bytes = s.toArray()
        let out = Array<Byte>(bytes.size / 2, repeat: 0u8)
        var i: Int64 = 0
        while (i + 1 < bytes.size) {
            let hi = hexVal(bytes[i])
            let lo = hexVal(bytes[i + 1])
            if (hi >= 0 && lo >= 0) { out[i / 2] = UInt8(hi * 16 + lo) }
            i += 2
        }
        return out
    }
    private func hexVal(c: Byte): Int64 {
        let v = Int64(c)
        if (v >= 48 && v <= 57) { return v - 48 }
        if (v >= 97 && v <= 102) { return v - 87 }
        if (v >= 65 && v <= 70) { return v - 55 }
        return -1
    }
    private func b64encode(s: String): String {
        // 简化：用户名通常是 ASCII 安全字符，直接用 hex 编码保证 URL/点号分隔安全。
        return toHex(s.toArray())
    }
    private func b64decode(s: String): String {
        let bytes = fromHex(s)
        return String.fromUtf8(bytes)
    }
}

/** 当前 Unix 毫秒。 */
private func nowMs(): Int64 {
    return DateTime.now().toUnixTimeStamp().toMilliseconds()
}

/** 字符串转 Int64（解析失败返回 0，避免依赖 std.convert）。 */
private func parseInt(s: String): Int64 {
    var acc: Int64 = 0
    for (b in s.toArray()) {
        if (b < 48 || b > 57) { return 0 }
        acc = acc * 10 + Int64(b - 48)
    }
    return acc
}
