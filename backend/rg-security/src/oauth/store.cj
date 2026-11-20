// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// OAuth2 客户端与令牌 scope 的本地持久化（字段以 | 分隔，内容受控：不含 |）。
// 文件存于容器卷 /app/data，重启不丢；只存 secret 摘要与令牌摘要，不存明文。
package rg.security.oauth

import std.fs.*
import std.env.*
import std.collection.*

/** 客户端注册表存储（clientId|name|secretHash|scope|owner|createdMs）。 */
public class OAuthStore {
    private let clientPath: String
    private let scopePath: String
    public init() {
        let base = getVariable("RG_OAUTH_FILE") ?? "/app/data/oauth_clients.txt"
        this.clientPath = base
        let slash = base.lastIndexOf("/")
        let dir = match (slash) { case Some(i) => base[0..i]; case None => "." }
        this.scopePath = dir + "/oauth_scopes.txt"
    }

    private func readLines(path: String): Array<String> {
        try {
            let s = String.fromUtf8(File.readFrom(path))
            return s.split("\n").toArray()
        } catch (e: Exception) { return Array<String>() }
    }

    private func field(v: String): String {
        // 转义分隔符与换行（参数化字段，避免错列）
        return v.replace("\n", "%0A").replace("|", "%7C")
    }
    private func unfield(v: String): String {
        return v.replace("%7C", "|").replace("%0A", "\n")
    }

    /** 加载全部客户端。 */
    public func loadClients(): Array<Array<String>> {
        let out = ArrayList<Array<String>>()
        for (line in this.readLines(this.clientPath)) {
            if (line.size == 0) { continue }
            let parts = line.split("|").toArray()
            if (parts.size >= 6) { out.add(parts) }
        }
        return out.toArray()
    }

    /** 整表写回（调用方保证已合并）。 */
    public func saveClients(rows: Array<Array<String>>): Bool {
        let sb = StringBuilder()
        for (r in rows) {
            if (r.size < 6) { continue }
            sb.append("${field(r[0])}|${field(r[1])}|${field(r[2])}|${field(r[3])}|${field(r[4])}|${field(r[5])}\n")
        }
        try { File.writeTo(this.clientPath, sb.toString().toArray()); return true }
        catch (e: Exception) { return false }
    }

    /** 记录令牌摘要 → scope（追加；过期记录由调用方按需清理）。 */
    public func addScope(tokenHash: String, scope: String, expiresMs: Int64): Bool {
        let sb = StringBuilder()
        for (line in this.readLines(this.scopePath)) {
            if (line.size > 0) { sb.append(line); sb.append("\n") }
        }
        sb.append("${tokenHash}|${field(scope)}|${expiresMs}\n")
        try { File.writeTo(this.scopePath, sb.toString().toArray()); return true }
        catch (e: Exception) { return false }
    }

    /** 查询令牌摘要的 scope；无记录返回空串。 */
    public func scopeOf(tokenHash: String): String {
        for (line in this.readLines(this.scopePath)) {
            let parts = line.split("|").toArray()
            if (parts.size >= 2 && parts[0] == tokenHash) { return unfield(parts[1]) }
        }
        return ""
    }

}
