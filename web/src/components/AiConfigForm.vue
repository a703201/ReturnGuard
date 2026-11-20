<script setup lang="ts">
/**
 * AI 功能配置表单（AMS AiConfigPanel 范式）：provider 下拉 + 端点/模型文本 + 密钥密码框。
 * 供设置页与首次引导共用。密钥脱敏回显、留空不改；校验后保存，重启生效。
 * 事件 saved：保存成功后抛出，供引导流程推进下一步。
 */
import { ref, onMounted } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '../i18n'
import { isLoggedIn } from '../composables/useAuth'
import { apiGet, apiPost } from '../api/client'

const emit = defineEmits<{ saved: [] }>()

interface ProviderSpec { label: string; supported: boolean; capabilities: Record<string, boolean> }
interface ProvidersData { current: string; configured: boolean; providers: Record<string, ProviderSpec> }
interface AiSettings {
  current: string; provider: string; baseUrl: string; model: string;
  enabled: boolean; onlineAllowed: boolean; apiKeySet: boolean; apiKeyMask: string;
  apiKey: string; pendingRestart: boolean; envOverride: boolean
}
const ai = ref<ProvidersData | null>(null)
const aiSettings = ref<AiSettings | null>(null)
const aiError = ref('')
const saving = ref(false)
const savedMsg = ref('')
const openProvider = ref('')
const showKey = ref(false)
const clearKey = ref(false)

const form = ref({ provider: 'tokenplan', apiKey: '', baseUrl: '', model: '', enabled: true, onlineAllowed: true })
const errors = ref<Record<string, string>>({})

const capKeys = ['text', 'vl', 'ocr', 'embed', 'rerank', 'tts']
const capLabel = (k: string) => t(`set.cap.${k}`)
function toggleProvider(key: string) { openProvider.value = openProvider.value === key ? '' : key }

const onlineKeys = ['tokenplan', 'official', 'dashscope', 'openai', 'deepseek', 'moonshot', 'zhipu',
  'siliconflow', 'openrouter', 'azure_openai', 'anthropic', 'gemini', 'custom']
const isOnline = (k: string) => onlineKeys.includes(k)
const visibleProviders = () => {
  const all = ai.value?.providers || {}
  return Object.entries(all).filter(([k]) => form.value.onlineAllowed || !isOnline(k))
}

function applySettings(s: AiSettings) {
  aiSettings.value = s
  clearKey.value = false
  form.value = {
    provider: s.provider || s.current, apiKey: '', baseUrl: s.baseUrl, model: s.model,
    enabled: s.enabled, onlineAllowed: s.onlineAllowed,
  }
}

async function loadAi() {
  aiError.value = ''
  try { ai.value = await apiGet<ProvidersData>('ai/providers') }
  catch (e) { aiError.value = (e as Error).message || '加载失败'; return }
  if (!isLoggedIn.value) { aiSettings.value = null; return }
  try { applySettings(await apiGet<AiSettings>('ai/settings')) }
  catch (e) { aiSettings.value = null; aiError.value = (e as Error).message || '设置加载失败' }
}

function validate(): boolean {
  const e: Record<string, string> = {}
  if (!form.value.provider) e.provider = t('set.errProvider')
  if (form.value.baseUrl && !/^https?:\/\//.test(form.value.baseUrl)) e.baseUrl = t('set.errBaseUrl')
  if (form.value.model && /\s/.test(form.value.model)) e.model = t('set.errModel')
  if (form.value.apiKey && /[\r\n]/.test(form.value.apiKey)) e.apiKey = t('set.errApiKey')
  errors.value = e
  return Object.keys(e).length === 0
}

const aiChanged = () => {
  const s = aiSettings.value
  if (!s) return false
  return form.value.provider !== s.provider || !!form.value.apiKey || form.value.baseUrl !== s.baseUrl
    || form.value.model !== s.model || form.value.enabled !== s.enabled || form.value.onlineAllowed !== s.onlineAllowed
    || clearKey.value
}

async function saveAi() {
  if (!validate() || saving.value) return
  saving.value = true
  savedMsg.value = ''
  try {
    const r = await apiPost<{ pendingRestart: boolean }>('ai/settings', {
      provider: form.value.provider, apiKey: form.value.apiKey, baseUrl: form.value.baseUrl,
      model: form.value.model, enabled: form.value.enabled, onlineAllowed: form.value.onlineAllowed,
      clearKey: String(clearKey.value),
    })
    clearKey.value = false
    await loadAi()
    savedMsg.value = r.pendingRestart ? t('set.aiSavedRestart') : t('set.aiSaved')
    emit('saved')
  } catch (e) {
    aiError.value = (e as Error).message || '保存失败'
  } finally { saving.value = false }
}

function onOnlineToggle() {
  if (!form.value.onlineAllowed && isOnline(form.value.provider)) form.value.provider = 'ollama'
}

onMounted(loadAi)
defineExpose({ load: loadAi })
</script>

<template>
  <div>
    <div v-if="aiError" class="err" style="margin-top:12px">{{ aiError }}</div>
    <div v-else-if="!ai" class="empty-state" style="margin-top:12px"><span class="spinner" aria-hidden="true" /></div>
    <template v-else>
      <div class="kv"><span>{{ t('set.aiCurrent') }}</span>
        <b>{{ ai.providers[ai.current]?.label || ai.current }}</b>
      </div>
      <div v-if="aiSettings?.pendingRestart" class="pending-note" role="status">
        <AppIcon name="info" :size="16" /> {{ t('set.aiPending') }}
      </div>

      <form class="ai-form" @submit.prevent="saveAi">
        <label class="ai-field">
          <span class="field-label">{{ t('set.aiEnable') }}</span>
          <span class="switch-line">
            <input v-model="form.enabled" type="checkbox" />
            <span>{{ t('set.aiEnableHint') }}</span>
          </span>
        </label>

        <label class="ai-field">
          <span class="field-label">{{ t('set.aiOnline') }}</span>
          <span class="switch-line">
            <input v-model="form.onlineAllowed" type="checkbox" @change="onOnlineToggle" />
            <span>{{ t('set.aiOnlineHint') }}</span>
          </span>
        </label>

        <label class="ai-field">
          <span class="field-label">{{ t('set.aiPickTitle') }} <em>*</em></span>
          <select v-model="form.provider" class="field field-block" :disabled="!aiSettings || saving">
            <option v-for="[key, p] in visibleProviders()" :key="key" :value="key">
              {{ p.label }}{{ !p.supported ? '（未适配）' : '' }}
            </option>
          </select>
          <span v-if="errors.provider" class="field-err">{{ errors.provider }}</span>
        </label>

        <label class="ai-field">
          <span class="field-label">{{ t('set.aiModel') }}</span>
          <input v-model="form.model" class="field field-block" type="text"
                 :placeholder="ai.providers[form.provider]?.supported ? t('set.aiModelHint') : ''"
                 :disabled="!aiSettings || saving" autocomplete="off" />
          <span v-if="errors.model" class="field-err">{{ errors.model }}</span>
        </label>

        <label class="ai-field">
          <span class="field-label">{{ t('set.aiEndpoint') }}</span>
          <input v-model="form.baseUrl" class="field field-block" type="url" inputmode="url"
                 placeholder="https://api.example.com/v1" :disabled="!aiSettings || saving" autocomplete="off" />
          <span class="field-hint">{{ t('set.aiEndpointHint') }}</span>
          <span v-if="errors.baseUrl" class="field-err">{{ errors.baseUrl }}</span>
        </label>

        <label class="ai-field">
          <span class="field-label">
            {{ t('set.aiApiKey') }}
              <em v-if="aiSettings?.apiKeySet" class="key-set">{{ t('set.aiKeySet') }} · {{ aiSettings.apiKeyMask }}</em>
              <button v-if="aiSettings?.apiKeySet" type="button" class="key-clear" @click="clearKey = true">
                {{ clearKey ? t('set.aiKeyCleared') : t('set.aiKeyClear') }}
              </button>
            </span>
          <span class="key-line">
            <input v-model="form.apiKey" class="field field-block" :type="showKey ? 'text' : 'password'"
                   :placeholder="aiSettings?.apiKeySet ? t('set.aiKeyKeep') : t('set.aiKeyPlaceholder')"
                   :disabled="!aiSettings || saving" autocomplete="off" />
            <button type="button" class="btn btn-ghost key-eye" :aria-label="t('set.aiKeyToggle')" @click="showKey = !showKey">
              <AppIcon :name="showKey ? 'refresh' : 'search'" :size="16" />
            </button>
          </span>
          <span class="field-hint">{{ t('set.aiKeyHint') }}</span>
          <span v-if="errors.apiKey" class="field-err">{{ errors.apiKey }}</span>
        </label>

        <div class="ai-actions">
          <button class="btn btn-primary" type="submit" :disabled="!aiSettings || !aiChanged() || saving">
            <AppIcon name="check" :size="16" /> {{ saving ? t('set.aiSaving') : t('set.aiSave') }}
          </button>
          <span v-if="savedMsg" class="saved-msg" role="status">{{ savedMsg }}</span>
        </div>
      </form>

      <div class="caps-block">
        <div class="sub-label">{{ t('set.aiCapsTitle') }}</div>
        <div class="ai-list">
          <div v-for="(p, key) in ai.providers" :key="key" class="ai-item" :class="{ open: openProvider === key }">
            <button type="button" class="ai-head" :aria-expanded="openProvider === key" @click="toggleProvider(key)">
              <span class="ai-name">{{ p.label }}</span>
              <span v-if="key === ai.current" class="pill pill-accent ai-cur">{{ t('set.aiActive') }}</span>
              <span v-if="!p.supported" class="pill ai-na">{{ t('set.aiUnsupported') }}</span>
              <span class="ai-arrow" aria-hidden="true">▸</span>
            </button>
            <div class="ai-body">
              <div class="caps">
                <span v-for="k in capKeys" :key="k" class="cap"
                      :class="{ on: p.capabilities?.[k], off: !p.capabilities?.[k] }">
                  {{ capLabel(k) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.err { color: var(--danger); font-size: var(--fs-sm); }
.spinner { width: 20px; height: 20px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv span { color: var(--text-muted); }
.kv b { color: var(--text-primary); font-weight: 600; text-align: right; }
.pending-note { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding: 10px 12px; border-radius: var(--r-md); background: var(--warning-soft); color: var(--warning); font-size: var(--fs-sm); }
.ai-form { margin-top: 16px; display: flex; flex-direction: column; gap: 14px; }
.ai-field { display: block; }
.switch-line { display: flex; align-items: center; gap: 10px; min-height: 40px; font-size: var(--fs-sm); color: var(--text-secondary); cursor: pointer; }
.switch-line input { width: 18px; height: 18px; accent-color: var(--accent); cursor: pointer; }
.field-label { display: block; font-size: var(--fs-sm); color: var(--text-secondary); margin-bottom: 6px; font-weight: 600; }
.field-label em { color: var(--danger); font-style: normal; }
.key-set { color: var(--success); font-style: normal; font-weight: 600; margin-left: 8px; font-size: var(--fs-xs); }
.key-clear { margin-left: 8px; padding: 2px 8px; border: 1px solid var(--border-strong); border-radius: var(--r-pill); background: transparent; color: var(--danger); font-size: var(--fs-xs); cursor: pointer; }
.key-clear:hover { background: var(--danger-soft); }
.key-line { display: flex; align-items: center; gap: 6px; }
.key-line .field { flex: 1; min-width: 0; }
.key-eye { flex: none; min-width: 40px; }
.field-hint { display: block; color: var(--text-muted); font-size: var(--fs-xs); margin-top: 4px; line-height: 1.5; }
.field-err { display: block; color: var(--danger); font-size: var(--fs-xs); margin-top: 4px; }
.caps-block { margin-top: 20px; border-top: 1px solid var(--border-subtle); padding-top: 14px; }
.sub-label { font-size: var(--fs-xs); color: var(--text-muted); font-weight: 600; margin-bottom: 8px; }
.ai-list { display: flex; flex-direction: column; gap: 6px; }
.ai-item { border: 1px solid var(--border-subtle); border-radius: var(--r-md); overflow: hidden; }
.ai-head { width: 100%; display: flex; align-items: center; gap: 10px; padding: 11px 14px; background: transparent; border: 0; cursor: pointer; text-align: left; font-size: var(--fs-sm); }
.ai-head:hover { background: var(--bg-hover); }
.ai-head:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.ai-name { font-weight: 600; color: var(--text-primary); min-width: 0; }
.ai-cur, .ai-na { margin-left: auto; }
.ai-na { color: var(--text-muted); background: var(--bg-inset); }
.ai-arrow { color: var(--text-muted); transition: transform 220ms cubic-bezier(.32,.72,0,1); }
.ai-item.open .ai-arrow { transform: rotate(90deg); }
.ai-body { max-height: 0; overflow: hidden; padding: 0 14px; transition: max-height 260ms cubic-bezier(.32,.72,0,1), padding 260ms; }
.ai-item.open .ai-body { max-height: 120px; padding: 4px 14px 14px; }
.ai-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 4px; }
.saved-msg { color: var(--success); font-size: var(--fs-sm); }
.caps { display: flex; flex-wrap: wrap; gap: 6px; }
.cap { font-size: var(--fs-xs); padding: 3px 8px; border-radius: var(--r-pill); border: 1px solid var(--border-subtle); }
.cap.on { color: var(--success); border-color: var(--success); background: var(--success-soft); }
.cap.off { color: var(--text-muted); opacity: .6; }
@media (prefers-reduced-motion: reduce) { .ai-body, .ai-arrow, .spinner { transition: none; animation: none; } }
</style>
