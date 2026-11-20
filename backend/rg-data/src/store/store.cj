// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 内存数据存储：用户表 + 案件表（按租户隔离）。
// 骨架阶段：纯内存，启动预置 demo 账户 + 确定性演示案件；
// 后续批次接 openGauss 持久化（对齐 AMS ams.data）。
package rg.data.store

import std.collection.*

/** 案件落库回调类型（由上层注入，避免 store 依赖 db 包造成循环依赖）。 */
public type CasePersist = (CaseRec) -> Unit
/** 案件删除落库回调：(caseId, tenant) -> Unit。 */
public type CaseRemove = (String, String) -> Unit

/** 用户记录（一个用户 = 一个租户）。 */
public class UserRec {
    public var username: String
    public var passwordHash: String      // hex(salt) : hex(pbkdf2)
    public var tenantName: String
    public var tokenVersion: Int64
    public var failedCount: Int64
    public var lockedUntilMs: Int64      // epoch ms，0 = 未锁定
    public var totpSecret: String        // TOTP 密钥（空=未绑定二次验证）
    public var hashAlgo: String          // 口令派生算法："sha256"（存量）/ "sm3"（国密）
    public init(username: String, passwordHash: String, tenantName: String) {
        this.username = username
        this.passwordHash = passwordHash
        this.tenantName = tenantName
        this.tokenVersion = 1
        this.failedCount = 0
        this.lockedUntilMs = 0
        this.totpSecret = ""
        this.hashAlgo = "sha256"
    }
}

/** 案件记录（洞察聚合的最小字段集）。 */
public class CaseRec {
    public var caseId: String
    public var tenant: String
    public var sku: String
    public var category: String
    public var supplier: String
    public var platform: String
    public var region: String
    public var season: String
    public var amount: Float64
    public var similarity: Float64
    public var outcome: String           // 赢 / 部分退款 / 输 / 待分析
    public var defect: String            // 头号缺陷标签
    public init(caseId: String, tenant: String, sku: String, category: String,
                supplier: String, platform: String, region: String, season: String,
                amount: Float64, similarity: Float64, outcome: String, defect: String) {
        this.caseId = caseId
        this.tenant = tenant
        this.sku = sku
        this.category = category
        this.supplier = supplier
        this.platform = platform
        this.region = region
        this.season = season
        this.amount = amount
        this.similarity = similarity
        this.outcome = outcome
        this.defect = defect
    }
}

/** 全局内存存储（进程内单例）。 */
public class Store {
    private let users = HashMap<String, UserRec>()
    private let cases = ArrayList<CaseRec>()
    private var onCaseAdded: ?CasePersist = None
    private var onCaseRemoved: ?CaseRemove = None

    public init() {}

    /** 案件落库回调（由 AppContext 用 CaseRepo.upsertBulk 注入；离线时为空）。 */
    public func setCasePersist(cb: CasePersist): Unit { this.onCaseAdded = Some(cb) }

    public func addUser(u: UserRec): Unit { this.users.add(u.username, u) }
    public func getUser(name: String): ?UserRec { return this.users.get(name) }
    public func userExists(name: String): Bool { return this.users.contains(name) }

    /** 新增案件：入内存并触发持久化回调（手动录入路径）。 */
    public func addCase(c: CaseRec): Unit {
        this.cases.add(c)
        match (this.onCaseAdded) {
            case Some(cb) => cb(c)
            case None => ()
        }
    }
    /** 静默加入内存（种子加载 / 从库恢复用，不触发落库回调）。 */
    public func addCaseQuiet(c: CaseRec): Unit { this.cases.add(c) }
    /** 单库租户隔离：严格只返回该租户的案件（无 demo/real 双源、无 public 旁路）。 */
    public func casesOf(tenant: String): Array<CaseRec> {
        let out = ArrayList<CaseRec>()
        for (c in this.cases) {
            if (c.tenant == tenant) { out.add(c) }
        }
        return out.toArray()
    }
    public func caseCount(): Int64 { return this.cases.size }
    public func userCount(): Int64 { return this.users.size }

    /** 删除某租户的一条案件（严格按 caseId + tenant 匹配，防止跨租户删除）。返回是否删到。 */
    public func removeCase(caseId: String, tenant: String): Bool {
        var i = 0
        while (i < this.cases.size) {
            let c = this.cases[i]
            if (c.caseId == caseId && c.tenant == tenant) {
                this.cases.remove(at: i)
                match (this.onCaseRemoved) {
                    case Some(cb) => cb(caseId, tenant)
                    case None => ()
                }
                return true
            }
            i += 1
        }
        return false
    }
    /** 案件删除落库回调（上层用 CaseRepo.delete 注入）。 */
    public func setCaseRemove(cb: CaseRemove): Unit { this.onCaseRemoved = Some(cb) }

    /** 预置确定性演示案件（供洞察聚合，非真实数据）。 */
    public func seedDemo(count: Int64): Unit {
        for (c in this.seedDemoCollect(count)) { this.addCaseQuiet(c) }
    }

    /** 生成确定性演示案件数组（不入库；供持久化模式批量落库）。 */
    public func seedDemoCollect(count: Int64): Array<CaseRec> {
        let out = ArrayList<CaseRec>()
        let CATS = ["3C数码", "服饰鞋包", "家居日用", "美妆个护", "户外运动"]
        let PLATS = ["Amazon", "AliExpress", "Temu", "SHEIN", "eBay", "Shopee"]
        let SUPS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
        let REGIONS = ["US", "UK", "DE", "FR", "ES", "BR"]
        let SEASONS = ["春", "夏", "秋", "冬"]
        let DEFECTS = ["外包装破损", "功能故障", "货不对板", "缺件少件", "色差明显"]
        let OUTCOMES = ["赢", "输", "部分退款", "待分析"]
        var i: Int64 = 0
        while (i < count) {
            let ci = i % CATS.size
            let pi = (i * 7) % PLATS.size
            let si = (i * 3) % SUPS.size
            let ri = (i * 5) % REGIONS.size
            let sei = (i / 12) % SEASONS.size
            let di = (i * 11) % DEFECTS.size
            // outcome 用确定性分布：约 60% 已判定（赢/输/部分），40% 待分析
            let oi = (i * 13) % 10
            let outcome = if (oi < 4) { OUTCOMES[0] } else if (oi < 6) { OUTCOMES[1] }
                          else if (oi < 7) { OUTCOMES[2] } else { OUTCOMES[3] }
            let amount = Float64(60 + (i * 37) % 500) + 0.5
            let sim = Float64(70 + (i * 17) % 30) / 100.0
            out.add(CaseRec(
                "DEMO-${i}", "demo",
                "SKU-${1000 + i}", CATS[ci], SUPS[si],
                PLATS[pi], REGIONS[ri], SEASONS[sei],
                amount, sim, outcome, DEFECTS[di]
            ))
            i += 1
        }
        return out.toArray()
    }
}
