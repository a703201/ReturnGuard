<script setup lang="ts">
/**
 * 账户管理：个人资料修改、密码修改、TOTP 二次验证开关（可选，非强制）。
 * 后端端点：GET/PUT /api/auth/me、POST /api/auth/password、/api/auth/totp/*。
 * 二维码不引入第三方库：展示 otpauth_url 供用户复制到验证器；密钥可一键复制。
 */
import { ref, onMounted, watch } from 'vue'
import { t } from '../i18n'
import { apiGet, apiPost, apiPut } from '../api/client'
import { clearSession, isLoggedIn } from '../composables/useAuth'

interface Profile { username: string; tenant_name: string; display_name: string; email: string }
const profile = ref<Profile | null>(null)
const form = ref({ display_name: '', email: '' })
const pwd = ref({ old_password: '', new_password: '', confirm: '' })
const totpEnabled = ref(false)
const setup = ref<{ secret: string; otpauth_url: string } | null>(null)
const totpCode = ref('')
const disableCode = ref('')
const busy = ref(false)
const msg = ref('')
const err = ref('')
const fieldErr = ref<Record<string, string>>({})

async function load() {
  // 未登录不发需鉴权请求（避免 console 401 噪音）；登录后由父组件重新挂载或手动刷新
  if (!isLoggedIn.value) { profile.value = null; return }
  try {
    const [me, st] = await Promise.all([
      apiGet<{ user: Profile }>('auth/me'),
      apiGet<{ enabled: boolean }>('auth/totp/status'),
    ])
    profile.value = me.user
    form.value = { display_name: me.user.display_name || '', email: me.user.email || '' }
    totpEnabled.value = st.enabled
  } catch (e) { err.value = (e as Error).message || '加载失败' }
}
onMounted(load)
watch(isLoggedIn, (v) => { if (v) { void load() } })

function ok(text: string) { msg.value = text; err.value = '' }
function fail(e: unknown) { err.value = (e as { detail?: string }).detail || (e as Error).message || '操作失败'; msg.value = '' }

async function saveProfile() {
  fieldErr.value = {}
  if (form.value.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.value.email)) {
    fieldErr.value.email = t('acct.errEmail'); return
  }
  busy.value = true
  try {
    await apiPut('auth/me', { display_name: form.value.display_name, email: form.value.email })
    ok(t('acct.saved'))
    await load()
  } catch (e) { fail(e) } finally { busy.value = false }
}

async function savePassword() {
  fieldErr.value = {}
  if (pwd.value.new_password.length < 8) { fieldErr.value.new = t('acct.errPass'); return }
  if (pwd.value.new_password !== pwd.value.confirm) { fieldErr.value.confirm = t('acct.errConfirm'); return }
  busy.value = true
  try {
    const r = await apiPost<{ note: string }>('auth/password', {
      old_password: pwd.value.old_password, new_password: pwd.value.new_password,
    })
    ok(r.note || t('acct.saved'))
    pwd.value = { old_password: '', new_password: '', confirm: '' }
    // 密码修改后当前会话令牌已失效：提示重新登录
    clearSession()
  } catch (e) { fail(e) } finally { busy.value = false }
}

async function beginTotp() {
  busy.value = true
  try {
    setup.value = await apiGet<{ secret: string; otpauth_url: string }>('auth/totp/setup')
    totpCode.value = ''
    ok(t('acct.totpScanHint'))
  } catch (e) { fail(e) } finally { busy.value = false }
}

async function enableTotp() {
  if (!setup.value || totpCode.value.trim().length !== 6) { err.value = t('acct.totpNeedCode'); return }
  busy.value = true
  try {
    await apiPost('auth/totp/enable', { secret: setup.value.secret, code: totpCode.value.trim() })
    setup.value = null; totpCode.value = ''
    totpEnabled.value = true
    ok(t('acct.totpOn'))
  } catch (e) { fail(e) } finally { busy.value = false }
}

async function disableTotp() {
  if (disableCode.value.trim().length !== 6) { err.value = t('acct.totpNeedCode'); return }
  busy.value = true
  try {
    await apiPost('auth/totp/disable', { code: disableCode.value.trim() })
    disableCode.value = ''; totpEnabled.value = false
    ok(t('acct.totpOff'))
  } catch (e) { fail(e) } finally { busy.value = false }
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); ok(t('acct.copied')) }
  catch { err.value = t('acct.copyFail') }
}
</script>

<template>
  <div>
    <div v-if="err" class="msg err" role="alert">{{ err }}</div>
    <div v-if="msg" class="msg ok" role="status">{{ msg }}</div>

    <!-- 个人资料 -->
    <div class="sub-card">
      <div class="sub-title">{{ t('acct.profileTitle') }}</div>
      <div class="kv"><span>{{ t('acct.username') }}</span><b>{{ profile?.username || '—' }}</b></div>
      <div class="kv"><span>{{ t('acct.tenant') }}</span><b>{{ profile?.tenant_name || '—' }}</b></div>
      <label class="ai-field">
        <span class="field-label">{{ t('acct.displayName') }}</span>
        <input v-model="form.display_name" class="field field-block" type="text" maxlength="128" :disabled="busy" />
      </label>
      <label class="ai-field">
        <span class="field-label">{{ t('acct.email') }}</span>
        <input v-model="form.email" class="field field-block" type="email" maxlength="160" :disabled="busy" />
        <span v-if="fieldErr.email" class="field-err">{{ fieldErr.email }}</span>
      </label>
      <button class="btn btn-primary" type="button" :disabled="busy" @click="saveProfile">{{ t('acct.saveProfile') }}</button>
    </div>

    <!-- 修改密码 -->
    <div class="sub-card">
      <div class="sub-title">{{ t('acct.pwdTitle') }}</div>
      <p class="hint">{{ t('acct.pwdHint') }}</p>
      <label class="ai-field">
        <span class="field-label">{{ t('acct.oldPwd') }}</span>
        <input v-model="pwd.old_password" class="field field-block" type="password" autocomplete="current-password" :disabled="busy" />
      </label>
      <label class="ai-field">
        <span class="field-label">{{ t('acct.newPwd') }}</span>
        <input v-model="pwd.new_password" class="field field-block" type="password" autocomplete="new-password" :disabled="busy" />
        <span v-if="fieldErr.new" class="field-err">{{ fieldErr.new }}</span>
      </label>
      <label class="ai-field">
        <span class="field-label">{{ t('acct.confirmPwd') }}</span>
        <input v-model="pwd.confirm" class="field field-block" type="password" autocomplete="new-password" :disabled="busy" />
        <span v-if="fieldErr.confirm" class="field-err">{{ fieldErr.confirm }}</span>
      </label>
      <button class="btn btn-secondary" type="button" :disabled="busy" @click="savePassword">{{ t('acct.changePwd') }}</button>
    </div>

    <!-- TOTP 二次验证（可选） -->
    <div class="sub-card">
      <div class="sub-title">{{ t('acct.totpTitle') }}</div>
      <div class="kv"><span>{{ t('acct.totpStatus') }}</span>
        <b><span class="pill" :class="totpEnabled ? 'pill-success' : ''">{{ totpEnabled ? t('acct.totpOn') : t('acct.totpOffState') }}</span></b>
      </div>
      <p class="hint">{{ t('acct.totpDesc') }}</p>

      <template v-if="!totpEnabled && !setup">
        <button class="btn btn-secondary" type="button" :disabled="busy" @click="beginTotp">{{ t('acct.totpEnableBtn') }}</button>
      </template>
      <template v-else-if="setup && !totpEnabled">
        <div class="setup-box">
          <div class="field-label">{{ t('acct.totpSecret') }}</div>
          <code class="secret">{{ setup.secret }}</code>
          <button class="btn btn-ghost" type="button" @click="copy(setup.secret)">{{ t('acct.copy') }}</button>
          <div class="field-label" style="margin-top:10px">{{ t('acct.totpUri') }}</div>
          <code class="uri">{{ setup.otpauth_url }}</code>
          <button class="btn btn-ghost" type="button" @click="copy(setup.otpauth_url)">{{ t('acct.copy') }}</button>
          <p class="hint">{{ t('acct.totpScanHint') }}</p>
          <input v-model="totpCode" class="field field-block" type="text" inputmode="numeric" maxlength="6"
                 :placeholder="t('acct.totpCode')" style="margin-top:8px" />
          <div class="row">
            <button class="btn btn-primary" type="button" :disabled="busy" @click="enableTotp">{{ t('acct.totpConfirm') }}</button>
            <button class="btn btn-ghost" type="button" @click="setup = null">{{ t('action.cancel') }}</button>
          </div>
        </div>
      </template>
      <template v-else>
        <input v-model="disableCode" class="field field-block" type="text" inputmode="numeric" maxlength="6"
               :placeholder="t('acct.totpCode')" />
        <button class="btn btn-secondary" type="button" style="margin-top:8px" :disabled="busy" @click="disableTotp">
          {{ t('acct.totpDisableBtn') }}
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg { padding: 10px 12px; border-radius: var(--r-md); font-size: var(--fs-sm); margin-bottom: 12px; }
.msg.err { color: var(--danger); background: var(--danger-soft); }
.msg.ok { color: var(--success); background: var(--success-soft); }
.sub-card { border: 1px solid var(--border-subtle); border-radius: var(--r-md); padding: 16px; margin-bottom: 14px; }
.sub-title { font-weight: 600; font-size: var(--fs-sm); color: var(--text-primary); margin-bottom: 10px; }
.hint { color: var(--text-muted); font-size: var(--fs-xs); line-height: 1.6; margin: 6px 0 12px; }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv span { color: var(--text-muted); }
.kv b { color: var(--text-primary); font-weight: 600; }
.ai-field { display: block; margin-top: 10px; }
.field-label { display: block; font-size: var(--fs-sm); color: var(--text-secondary); margin-bottom: 6px; font-weight: 600; }
.field-err { display: block; color: var(--danger); font-size: var(--fs-xs); margin-top: 4px; }
.sub-card .btn { margin-top: 12px; }
.setup-box { background: var(--bg-inset); border-radius: var(--r-md); padding: 12px; margin-top: 10px; }
.secret, .uri { display: block; font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-primary); word-break: break-all; background: var(--bg-surface); padding: 8px; border-radius: var(--r-sm); }
.uri { margin-top: 4px; }
.row { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
