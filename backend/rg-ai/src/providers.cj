// Copyright 2026 何宇翔 (He Yuxiang) <https://github.com/a703201>
// SPDX-License-Identifier: Apache-2.0
// AI 平台注册表：仓颉实现的单一事实来源，14 平台 + 能力矩阵。
// 设计原则（对齐 docs/AI_PROVIDERS.md）：
//   - 按能力编程，不按厂商编程；新增平台 = 加一条声明，不改调用代码；
//   - 能力缺口如实声明（supported=false 不伪装）；
//   - 密钥只从环境变量读，注册表不含凭据；公开接口不泄露密钥状态。
package rg.ai

import std.env.*
import std.collection.*

/** 平台声明：基地址 / 密钥环境变量 / 默认模型 / 能力列表 / 鉴权风格 / 是否需密钥。 */
public class ProviderSpec {
    public let key: String
    public let label: String
    public let baseUrl: String
    public let baseUrlEnv: String
    public let keyEnv: String
    public let keyRequired: Bool
    public let authStyle: String        // bearer / api-key / none
    public let textModel: String
    public let vlModel: String
    public let capabilities: Array<String>   // text/vl/ocr/embed/rerank/tts
    public let supported: Bool          // false = 原生协议非 OpenAI 兼容，本适配层不直连

    public init(key: String, label: String, baseUrl: String, baseUrlEnv: String, keyEnv: String,
                keyRequired: Bool, authStyle: String, textModel: String, vlModel: String,
                capabilities: Array<String>, supported: Bool) {
        this.key = key; this.label = label; this.baseUrl = baseUrl
        this.baseUrlEnv = baseUrlEnv; this.keyEnv = keyEnv; this.keyRequired = keyRequired
        this.authStyle = authStyle; this.textModel = textModel; this.vlModel = vlModel
        this.capabilities = capabilities; this.supported = supported
    }

    /** 当前基地址：界面配置 > 环境变量 > 注册表默认。 */
    public func resolvedBaseUrl(): String {
        let saved = AiSettingsStore().load()
        if (!saved.baseUrl.isEmpty()) { return saved.baseUrl }
        if (!this.baseUrlEnv.isEmpty()) {
            let v = getVariable(this.baseUrlEnv) ?? ""
            if (!v.isEmpty()) { return v }
        }
        return this.baseUrl
    }
    /** 当前密钥：界面配置 > 环境变量（仅内存，不进日志/响应）。 */
    public func resolvedKey(): String {
        let saved = AiSettingsStore().load()
        if (!saved.apiKey.isEmpty()) { return saved.apiKey }
        if (this.keyEnv.isEmpty()) { return "" }
        return getVariable(this.keyEnv) ?? ""
    }
    /** 当前文本模型：界面配置 > 环境变量 > 注册表默认。 */
    public func resolvedModel(): String {
        let saved = AiSettingsStore().load()
        if (!saved.model.isEmpty()) { return saved.model }
        let v = getVariable("RG_AI_MODEL") ?? ""
        if (!v.isEmpty()) { return v }
        return this.textModel
    }
    public func supports(cap: String): Bool {
        for (c in this.capabilities) { if (c == cap) { return true } }
        return false
    }
}

/** 14 平台注册表（唯一事实来源，与 Python providers.py 对齐）。 */
public class ProviderRegistry {
    private let specs: HashMap<String, ProviderSpec>
    public let keys: Array<String>

    public init() {
        // 局部注册表：构造函数内所有成员初始化完前不能通过 this 调用方法（仓颉限制）
        let map = HashMap<String, ProviderSpec>()
        let add = { s: ProviderSpec => map.add(s.key, s) }
        let allCaps = ["text", "vl", "ocr", "embed", "rerank", "tts"]
        let textVl = ["text", "vl", "ocr"]
        // ---- OpenAI 兼容平台 ----
        add(ProviderSpec("tokenplan", "百炼 · Token Plan 网关",
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "MODEL_ROUTER_BASE_URL", "MODEL_ROUTER_API_KEY", true, "bearer",
            "qwen3.7-max", "qwen-vl-max", allCaps, true))
        add(ProviderSpec("official", "百炼 · 官方 Model Router",
            "https://model-router.edu-aliyun.com/v1",
            "MODEL_ROUTER_OFFICIAL_BASE_URL", "MODEL_ROUTER_OFFICIAL_KEY", true, "bearer",
            "qwen3.7-max", "qwen-vl-max", allCaps, true))
        add(ProviderSpec("dashscope", "百炼 · 国内站按量付费",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "DASHSCOPE_BASE_URL", "DASHSCOPE_API_KEY", true, "bearer",
            "qwen-plus", "qwen-vl-max", allCaps, true))
        add(ProviderSpec("openai", "OpenAI",
            "https://api.openai.com/v1", "OPENAI_BASE_URL", "OPENAI_API_KEY", true, "bearer",
            "gpt-4o-mini", "gpt-4o-mini", ["text", "vl", "ocr", "tts"], true))
        add(ProviderSpec("deepseek", "DeepSeek",
            "https://api.deepseek.com/v1", "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", true, "bearer",
            "deepseek-chat", "", ["text"], true))
        add(ProviderSpec("moonshot", "月之暗面 Kimi",
            "https://api.moonshot.cn/v1", "MOONSHOT_BASE_URL", "MOONSHOT_API_KEY", true, "bearer",
            "kimi-k2.6", "kimi-k2.6", ["text", "vl", "ocr"], true))
        add(ProviderSpec("zhipu", "智谱 GLM",
            "https://open.bigmodel.cn/api/paas/v4", "ZHIPU_BASE_URL", "ZHIPU_API_KEY", true, "bearer",
            "glm-5.2", "glm-5.2", ["text", "vl", "ocr"], true))
        add(ProviderSpec("siliconflow", "硅基流动",
            "https://api.siliconflow.cn/v1", "SILICONFLOW_BASE_URL", "SILICONFLOW_API_KEY", true, "bearer",
            "Qwen/Qwen3-8B", "Qwen/Qwen2.5-VL-72B-Instruct", ["text", "vl", "ocr"], true))
        add(ProviderSpec("openrouter", "OpenRouter 聚合",
            "https://openrouter.ai/api/v1", "OPENROUTER_BASE_URL", "OPENROUTER_API_KEY", true, "bearer",
            "openai/gpt-4o-mini", "openai/gpt-4o-mini", textVl, true))
        // ---- 本地 / 内网 ----
        add(ProviderSpec("ollama", "Ollama（本机/内网自托管）",
            "http://127.0.0.1:11434/v1", "OLLAMA_BASE_URL", "OLLAMA_API_KEY", false, "none",
            "qwen2.5:7b", "qwen2.5vl:7b", textVl, true))
        add(ProviderSpec("custom", "自定义 OpenAI 兼容端点",
            "", "RG_AI_BASE_URL", "RG_AI_KEY", false, "bearer",
            "qwen-plus", "qwen-vl-max", textVl, true))
        // ---- 原生协议（本适配层不直连，能力如实声明为不支持）----
        add(ProviderSpec("azure_openai", "Azure OpenAI（api-key 风格）",
            "", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", true, "api-key",
            "gpt-4o-mini", "gpt-4o-mini", ["text", "vl", "ocr", "tts"], false))
        add(ProviderSpec("anthropic", "Anthropic Claude（原生 Messages API）",
            "https://api.anthropic.com/v1", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", true, "bearer",
            "claude-sonnet-4-5", "claude-sonnet-4-5", ["text", "vl"], false))
        add(ProviderSpec("gemini", "Google Gemini（原生 API）",
            "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_BASE_URL", "GEMINI_API_KEY", true, "bearer",
            "gemini-2.5-flash", "gemini-2.5-flash", ["text", "vl"], false))
        this.specs = map
        // keys 按插入顺序稳定输出（HashMap 无序，单独维护）
        this.keys = ["tokenplan", "official", "dashscope", "openai", "deepseek", "moonshot", "zhipu",
                     "siliconflow", "openrouter", "ollama", "custom", "azure_openai", "anthropic", "gemini"]
    }

    public func get(key: String): ?ProviderSpec { return this.specs.get(key) }

    /**
     * 当前生效 provider。优先级：
     *   1) 环境变量 RG_AI_PROVIDER / MODEL_ROUTER_PROFILE（部署侧强制覆盖）
     *   2) 设置页保存的持久化文件（AiSettingsStore）
     *   3) 默认 tokenplan
     * 未知值一律回退默认，不伪造成功。
     */
    public func activeKey(): String {
        var k = getVariable("RG_AI_PROVIDER") ?? ""
        if (k.isEmpty()) { k = getVariable("MODEL_ROUTER_PROFILE") ?? "" }
        // 🔴 docker-compose 里 MODEL_ROUTER_PROFILE=tokenplan 是启动默认；
        //    若设置页已保存选择，应以文件为准（除非显式设了 RG_AI_PROVIDER）。
        let saved = AiSettingsStore().loadProvider()
        if (k.isEmpty() || (k == "tokenplan" && !saved.isEmpty())) { k = saved }
        if (k.isEmpty()) { return "tokenplan" }
        if (this.specs.contains(k)) { return k }
        return "tokenplan"
    }

    /** 生成对外能力矩阵 JSON（不含任何密钥 / 基地址）。 */
    public func capabilitiesJson(): String {
        let parts = ArrayList<String>()
        for (k in this.keys) {
            match (this.specs.get(k)) {
                case Some(s) =>
                    let caps = ArrayList<String>()
                    for (c in ["text", "vl", "ocr", "embed", "rerank", "tts"]) {
                        caps.add("\"" + c + "\":" + (if (s.supported && s.supports(c)) { "true" } else { "false" }))
                    }
                    parts.add("\"" + s.key + "\":{\"label\":\"" + s.label +
                        "\",\"supported\":" + (if (s.supported) { "true" } else { "false" }) +
                        ",\"capabilities\":{" + String.join(caps.toArray(), delimiter: ",") + "}}")
                case None => ()
            }
        }
        return "{" + String.join(parts.toArray(), delimiter: ",") + "}"
    }
}
