// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// SEC-13 配额闸：全局日 / 租户日 / IP 小时三层计数，仅拦 live 模式。
// 0 = 关闭该层。超限返回 false（调用方回 429，不静默降级）。
// 计数存储可插拔：内存（单进程）/ DB（跨 worker 共享）。
package rg.security.quota

import std.collection.*
import std.time.*
import std.env.*

public class QuotaConfig {
    public let globalDay: Int64
    public let tenantDay: Int64
    public let ipHour: Int64
    public init(globalDay: Int64, tenantDay: Int64, ipHour: Int64) {
        this.globalDay = globalDay; this.tenantDay = tenantDay; this.ipHour = ipHour
    }
    public static func fromEnv(): QuotaConfig {
        return QuotaConfig(
            envInt("RG_LIVE_QUOTA_GLOBAL_DAY", 300),
            envInt("RG_LIVE_QUOTA_TENANT_DAY", 60),
            envInt("RG_LIVE_QUOTA_IP_HOUR", 20)
        )
    }
}

/** 配额计数器抽象：get 读取当前值，incr 原子 +1。由上层注入内存/DB 实现。 */
public class QuotaCounter {
    private let getter: (String, String) -> Int64
    private let increr: (String, String) -> Unit
    public init(getter: (String, String) -> Int64, increr: (String, String) -> Unit) {
        this.getter = getter; this.increr = increr
    }
    public func get(scope: String, bucket: String): Int64 { return this.getter(scope, bucket) }
    public func incr(scope: String, bucket: String): Unit { this.increr(scope, bucket) }

    /** 内存计数器（单进程，回退用）。 */
    public static func inMemory(): QuotaCounter {
        let store = HashMap<String, Int64>()
        return QuotaCounter(
            { scope, bucket => store.get(scope + "|" + bucket) ?? 0 },
            { scope, bucket =>
                let k = scope + "|" + bucket
                store.add(k, (store.get(k) ?? 0) + 1)
            }
        )
    }
}

/** 配额闸（三层窗口，存储可插拔）。 */
public class Quota {
    private let cfg: QuotaConfig
    private let counter: QuotaCounter
    public let backend: String              // "memory" / "opengauss"（如实呈现）

    public init(cfg: QuotaConfig, counter: QuotaCounter, backend: String) {
        this.cfg = cfg; this.counter = counter; this.backend = backend
    }

    /** 检查并计数。mode != "live" 直接放行（配额只拦付费链路）。 */
    public func allow(mode: String, tenant: String, ip: String): Bool {
        if (mode != "live") { return true }
        let now = DateTime.now().toUnixTimeStamp().toMilliseconds()
        let day = dayKey(now)
        let hour = hourKey(now)
        if (!this.checkAndInc("global", day, this.cfg.globalDay)) { return false }
        if (!this.checkAndInc("tenant", tenant + "|" + day, this.cfg.tenantDay)) { return false }
        if (!this.checkAndInc("ip", ip + "|" + hour, this.cfg.ipHour)) { return false }
        return true
    }

    private func checkAndInc(scope: String, bucket: String, limit: Int64): Bool {
        if (limit <= 0) { return true }  // 0 = 关闭该层
        let c = this.counter.get(scope, bucket)
        if (c >= limit) { return false }
        this.counter.incr(scope, bucket)
        return true
    }

    private func dayKey(ms: Int64): String { return "${ms / 86400000}" }
    private func hourKey(ms: Int64): String { return "${ms / 3600000}" }
}

private func envInt(name: String, def: Int64): Int64 {
    let v = getVariable(name) ?? ""
    if (v.isEmpty()) { return def }
    var acc: Int64 = 0
    var any = false
    for (b in v.toArray()) {
        if (b < 48 || b > 57) { return def }
        acc = acc * 10 + Int64(b - 48); any = true
    }
    return if (any) { acc } else { def }
}
