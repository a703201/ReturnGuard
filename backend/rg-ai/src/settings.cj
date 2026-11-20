// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// AI 配置持久化：provider / API Key / Base URL / Model / 能力开关，写入受保护文件。
// 对齐 AMS「保存配置 + 重启生效」：不在运行时重建 AiClient（密钥/基地址构造期绑定）。
// 安全性：密钥仅存服务端文件，绝不进任何 HTTP 响应/日志；文件由容器卷持久化。
package rg.ai

import std.fs.*
import std.env.*

/** 完整 AI 配置（内存表示）。apiKey 为空表示"未设置/留空不改"。 */
public class AiConfig {
    public var provider: String
    public var apiKey: String
    public var baseUrl: String
    public var model: String
    public var enabled: Bool
    public var onlineAllowed: Bool
    public init(provider: String, apiKey: String, baseUrl: String, model: String, enabled: Bool, onlineAllowed: Bool) {
        this.provider = provider; this.apiKey = apiKey; this.baseUrl = baseUrl
        this.model = model; this.enabled = enabled; this.onlineAllowed = onlineAllowed
    }
}

/** 配置存储：每行 `key=value`，值不换行（API Key/URL/模型名均不含换行）。 */
public class AiSettingsStore {
    private let path: String
    public init(path!: String = "") {
        if (path.isEmpty()) {
            this.path = getVariable("RG_AI_CONFIG_FILE") ?? "/app/data/ai_config.env"
        } else {
            this.path = path
        }
    }

    private func trim(s: String): String {
        var a = 0
        var b = s.size
        while (a < b && (s[a] == 0x20 || s[a] == 0x0a || s[a] == 0x0d)) { a += 1 }
        while (b > a && (s[b - 1] == 0x20 || s[b - 1] == 0x0a || s[b - 1] == 0x0d)) { b -= 1 }
        return s[a..b]
    }

    /** 读取一个 key 的值（无该文件返回空串）。 */
    private func readKey(lines: Array<String>, wanted: String): String {
        for (line in lines) {
            let eq = line.indexOf("=")
            match (eq) {
                case Some(i) =>
                    if (trim(line[0..i]) == wanted) { return trim(line[i + 1..line.size]) }
                case None => ()
            }
        }
        return ""
    }

    /** 读取完整配置（密钥也读入内存，但不对外暴露）。 */
    public func load(): AiConfig {
        var provider = ""
        var key = ""
        var base = ""
        var model = ""
        var enabled = true
        var online = true
        try {
            let s = String.fromUtf8(File.readFrom(this.path))
            let lines = s.split("\n").toArray()
            provider = this.readKey(lines, "AI_PROVIDER")
            key = this.readKey(lines, "AI_API_KEY")
            base = this.readKey(lines, "AI_BASE_URL")
            model = this.readKey(lines, "AI_MODEL")
            let en = this.readKey(lines, "AI_ENABLED")
            if (!en.isEmpty()) { enabled = (en == "true" || en == "1") }
            let on = this.readKey(lines, "AI_ONLINE_ALLOWED")
            if (!on.isEmpty()) { online = (on != "false" && on != "0") }
        } catch (e: Exception) { /* 文件不存在 = 未配置 */ }

        // 向后兼容旧的单值 provider 文件（若新配置里没有 provider）
        if (provider.isEmpty()) {
            let slash = this.path.lastIndexOf("/")
            let dir = match (slash) { case Some(i) => this.path[0..i]; case None => "." }
            let old = dir + "/ai_provider.txt"
            try {
                provider = trim(String.fromUtf8(File.readFrom(old)))
            } catch (e: Exception) { provider = "" }
        }
        return AiConfig(provider, key, base, model, enabled, online)
    }

    /** 读取已保存的 provider key（供 Registry.activeKey 使用，兼容旧文件）。 */
    public func loadProvider(): String { return this.load().provider }

    /** 保存配置。apiKey 为空时保留原密钥（留空不改，对齐 AMS）；clearKey=true 时强制清空。 */
    public func save(cfg: AiConfig, clearKey!: Bool = false): Bool {
        let prev = this.load()
        let effectiveKey = if (clearKey) { "" } else if (cfg.apiKey.isEmpty()) { prev.apiKey } else { cfg.apiKey }
        let sb = StringBuilder()
        sb.append("AI_PROVIDER=${cfg.provider}\n")
        sb.append("AI_API_KEY=${effectiveKey}\n")
        sb.append("AI_BASE_URL=${cfg.baseUrl}\n")
        sb.append("AI_MODEL=${cfg.model}\n")
        sb.append("AI_ENABLED=${if (cfg.enabled) { "true" } else { "false" }}\n")
        sb.append("AI_ONLINE_ALLOWED=${if (cfg.onlineAllowed) { "true" } else { "false" }}\n")
        let content = sb.toString()
        try {
            File.writeTo(this.path, content.toArray())
            return true
        } catch (e: Exception) { return false }
    }

    /** 兼容旧调用：只保存 provider key（保留其余字段）。 */
    public func saveProvider(key: String): Bool {
        let c = this.load()
        return this.save(AiConfig(key, "", c.baseUrl, c.model, c.enabled, c.onlineAllowed))
    }

    public func filePath(): String { return this.path }
}
