// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// 审计链：认证等敏感事件 append-only 写入，每条含 prev_hash 形成哈希链，
// 可用 verifyChain() 自证未被篡改（参考 AMS ams.app.audit + docs/03 §7）。
// 本批为内存实现；后续批次接 openGauss 审计表（应用账号仅 INSERT/SELECT）。
package rg.security.audit

import std.collection.*
import std.time.*
import stdx.crypto.digest.*
import rg.kernel.json.*

// 内联摘要原语，避免与 authn 包循环依赖（authn 依赖本包的 AuditLog）。
private func sha256Hex(data: Array<Byte>): String {
    let h = SHA256()
    h.write(data)
    let bytes = h.finish()
    let hex = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"]
    let sb = StringBuilder()
    for (b in bytes) {
        let v = Int64(b)
        sb.append(hex[(v >> 4) & 0xf])
        sb.append(hex[v & 0xf])
    }
    return sb.toString()
}

/** 审计事件（值对象）。 */
public class AuditEvent {
    public let seq: Int64
    public let tsMs: Int64
    public let actor: String
    public let action: String
    public let ip: String
    public let outcome: String
    public let detail: String
    public let prevHash: String
    public let hash: String

    public init(seq: Int64, tsMs: Int64, actor: String, action: String,
                ip: String, outcome: String, detail: String, prevHash: String, hash: String) {
        this.seq = seq; this.tsMs = tsMs; this.actor = actor; this.action = action
        this.ip = ip; this.outcome = outcome; this.detail = detail
        this.prevHash = prevHash; this.hash = hash
    }

    /** 参与哈希的规范化载荷（字段顺序固定，避免序列化漂移）。 */
    public func payload(): String {
        return "${seq}|${tsMs}|${actor}|${action}|${ip}|${outcome}|${detail}|${prevHash}"
    }
    public func toJson(): String {
        return Obj().i64("seq", seq).i64("ts_ms", tsMs).str("actor", actor)
            .str("action", action).str("ip", ip).str("outcome", outcome)
            .str("detail", detail).str("prev_hash", prevHash).str("hash", hash)
            .build()
    }
}

/** 审计事件持久化回调（由上层用 AuditRepo.insert 注入；避免 audit 包依赖 db 包）。 */
public type AuditPersist = (AuditEvent) -> Unit

/** 追加式审计日志（哈希链；可选持久化到 openGauss）。 */
public class AuditLog {
    private let events = ArrayList<AuditEvent>()
    private var headHash: String = "0000000000000000000000000000000000000000000000000000000000000000"
    private var persist: ?AuditPersist = None

    public init() {}

    /** 注入持久化回调（AppContext 启动时调用）。 */
    public func setPersist(cb: AuditPersist): Unit { this.persist = Some(cb) }

    /** 从持久化加载历史事件（保持哈希链顺序，重建 head）。ts/seq 用库中原值以自证。 */
    public func restore(seq: Int64, tsMs: Int64, actor: String, action: String, ip: String,
                        outcome: String, detail: String, prevHash: String, hash: String): Unit {
        let ev = AuditEvent(seq, tsMs, actor, action, ip, outcome, detail, prevHash, hash)
        this.events.add(ev)
        this.headHash = hash
    }

    /** 追加一条事件，返回其哈希。 */
    public func append(actor: String, action: String, ip: String, outcome: String, detail: String): String {
        let seq = this.events.size + 1
        let ts = DateTime.now().toUnixTimeStamp().toMilliseconds()
        let hash = sha256Hex(("${seq}|${ts}|${actor}|${action}|${ip}|${outcome}|${detail}|${this.headHash}").toArray())
        let ev = AuditEvent(seq, ts, actor, action, ip, outcome, detail, this.headHash, hash)
        this.events.add(ev)
        this.headHash = hash
        match (this.persist) { case Some(cb) => cb(ev); case None => () }
        return hash
    }

    /** 自证哈希链完整：逐条重算，返回首条不一致的 seq（0 = 全通过）。 */
    public func verifyChain(): Int64 {
        var prev = "0000000000000000000000000000000000000000000000000000000000000000"
        for (ev in this.events) {
            let expect = sha256Hex(ev.payload().toArray())
            if (expect != ev.hash || ev.prevHash != prev) { return ev.seq }
            prev = ev.hash
        }
        return 0
    }

    public func size(): Int64 { return this.events.size }
    public func head(): String { return this.headHash }
    /** 最近 n 条（含全部字段），供 /api/audit 管理端点读取。 */
    public func tail(n: Int64): String {
        let arr = Arr()
        let total = this.events.size
        let start = if (total > n) { total - n } else { 0 }
        var i = start
        while (i < total) { arr.raw(this.events[i].toJson()); i += 1 }
        return arr.build()
    }
}
