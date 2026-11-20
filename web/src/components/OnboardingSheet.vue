<script setup lang="ts">
/**
 * 首次部署引导：① 创建账户 → ② AI 配置 → ③ 提示可查看演示账户。
 * 触发：localStorage 无 rg.onboarded 标志时自动弹出；完成后写标志，可从设置页重新打开。
 * 账户注册直接调后端 POST /api/auth/register（返回 token 即登录）；AI 配置复用 AiConfigForm。
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import AiConfigForm from './AiConfigForm.vue'
import { t } from '../i18n'
import { apiPost } from '../api/client'
import { setSession } from '../composables/useAuth'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const router = useRouter()

const step = ref(0)
const busy = ref(false)
const error = ref('')
const form = ref({ username: '', password: '', confirm: '', tenant: '' })
const fields = ref<Record<string, string>>({})
const DEMO = { username: 'demo', password: 'demo123' }

const steps = computed(() => [t('onb.step1'), t('onb.step2'), t('onb.step3')])

function validate(): boolean {
  const e: Record<string, string> = {}
  const u = form.value.username.trim()
  if (u.length < 3) e.username = t('onb.errUser')
  if (form.value.password.length < 8) e.password = t('onb.errPass')
  if (form.value.password !== form.value.confirm) e.confirm = t('onb.errConfirm')
  fields.value = e
  return Object.keys(e).length === 0
}

async function createAccount() {
  if (!validate() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await apiPost<{ ok: boolean; token: string; username: string }>('auth/register', {
      username: form.value.username.trim(), password: form.value.password,
      tenant_name: form.value.tenant.trim(),
    })
    setSession(r.token, r.username)
    form.value.password = ''
    form.value.confirm = ''
    step.value = 1
  } catch (e) {
    error.value = (e as Error).message || t('onb.errCreate')
  } finally { busy.value = false }
}

function finish() {
  try { localStorage.setItem('rg.onboarded', '1') } catch { /* 隐私模式忽略 */ }
  emit('close')
  router.push('/dashboard')
}

function skipAll() {
  try { localStorage.setItem('rg.onboarded', '1') } catch { /* 隐私模式忽略 */ }
  emit('close')
}
</script>

<template>
  <div v-if="open" class="onb-mask" role="presentation">
    <section class="onb" role="dialog" aria-modal="true" :aria-label="t('onb.title')">
      <header class="onb-head">
        <div class="onb-brand"><AppIcon name="shield" :size="24" /><span>{{ t('app.name') }}</span></div>
        <button class="btn btn-ghost" type="button" :aria-label="t('onb.skip')" @click="skipAll">
          <AppIcon name="close" :size="18" />
        </button>
      </header>

      <nav class="onb-steps" aria-label="progress">
        <div v-for="(s, i) in steps" :key="i" class="onb-step" :class="{ done: i < step, active: i === step }">
          <span class="onb-dot">{{ i < step ? '✓' : i + 1 }}</span>
          <span class="onb-step-label">{{ s }}</span>
        </div>
      </nav>

      <div class="onb-body">
        <!-- 步骤 1：创建账户 -->
        <template v-if="step === 0">
          <h2 class="onb-h2">{{ t('onb.createTitle') }}</h2>
          <p class="onb-desc">{{ t('onb.createDesc') }}</p>
          <form class="onb-form" @submit.prevent="createAccount">
            <label class="ai-field">
              <span class="field-label">{{ t('onb.user') }} <em>*</em></span>
              <input v-model="form.username" class="field field-block" type="text" autocomplete="username"
                     :placeholder="t('onb.userHint')" :disabled="busy" />
              <span v-if="fields.username" class="field-err">{{ fields.username }}</span>
            </label>
            <label class="ai-field">
              <span class="field-label">{{ t('onb.pass') }} <em>*</em></span>
              <input v-model="form.password" class="field field-block" type="password" autocomplete="new-password"
                     :placeholder="t('onb.passHint')" :disabled="busy" />
              <span v-if="fields.password" class="field-err">{{ fields.password }}</span>
            </label>
            <label class="ai-field">
              <span class="field-label">{{ t('onb.confirm') }} <em>*</em></span>
              <input v-model="form.confirm" class="field field-block" type="password" autocomplete="new-password"
                     :disabled="busy" />
              <span v-if="fields.confirm" class="field-err">{{ fields.confirm }}</span>
            </label>
            <label class="ai-field">
              <span class="field-label">{{ t('onb.tenant') }}</span>
              <input v-model="form.tenant" class="field field-block" type="text" :placeholder="t('onb.tenantHint')" :disabled="busy" />
            </label>
            <div v-if="error" class="onb-error" role="alert">{{ error }}</div>
            <div class="onb-actions">
              <button class="btn btn-primary" type="submit" :disabled="busy">
                {{ busy ? t('onb.creating') : t('onb.createBtn') }}
              </button>
              <button class="btn btn-ghost" type="button" @click="skipAll">{{ t('onb.skip') }}</button>
            </div>
          </form>
        </template>

        <!-- 步骤 2：AI 配置 -->
        <template v-else-if="step === 1">
          <h2 class="onb-h2">{{ t('onb.aiTitle') }}</h2>
          <p class="onb-desc">{{ t('onb.aiDesc') }}</p>
          <AiConfigForm />
          <div class="onb-actions">
            <button class="btn btn-secondary" type="button" @click="step = 0">{{ t('onb.back') }}</button>
            <button class="btn btn-primary" type="button" @click="step = 2">{{ t('onb.next') }}</button>
          </div>
        </template>

        <!-- 步骤 3：完成 + 演示账户提示 -->
        <template v-else>
          <div class="onb-ready"><AppIcon name="check" :size="32" /></div>
          <h2 class="onb-h2">{{ t('onb.doneTitle') }}</h2>
          <p class="onb-desc">{{ t('onb.doneDesc') }}</p>
          <div class="demo-card">
            <div class="demo-title"><AppIcon name="info" :size="16" /> {{ t('onb.demoTitle') }}</div>
            <p class="demo-desc">{{ t('onb.demoDesc') }}</p>
            <code class="demo-cred">{{ DEMO.username }} / {{ DEMO.password }}</code>
          </div>
          <div class="onb-actions">
            <button class="btn btn-primary" type="button" @click="finish">{{ t('onb.enter') }}</button>
          </div>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.onb-mask { position: fixed; inset: 0; z-index: 100; background: var(--material-scrim, rgba(0,0,0,.45)); display: flex; align-items: center; justify-content: center; padding: 20px; }
.onb { width: min(660px, 100%); max-height: calc(100vh - 40px); overflow-y: auto; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: var(--r-xl); box-shadow: var(--shadow-pop); }
.onb-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 24px; border-bottom: 1px solid var(--border-subtle); }
.onb-brand { display: flex; align-items: center; gap: 10px; color: var(--accent); font-weight: 700; }
.onb-brand span { color: var(--text-primary); }
.onb-steps { display: flex; gap: 8px; padding: 16px 24px; border-bottom: 1px solid var(--border-subtle); }
.onb-step { flex: 1; display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: var(--fs-xs); }
.onb-dot { width: 24px; height: 24px; flex: none; display: flex; align-items: center; justify-content: center; border: 1px solid var(--border-strong); border-radius: 50%; font-weight: 600; }
.onb-step.active { color: var(--accent); }
.onb-step.active .onb-dot { border-color: var(--accent); background: var(--accent-soft); }
.onb-step.done .onb-dot { border-color: var(--success); color: var(--success); }
.onb-body { padding: 24px; }
.onb-h2 { font-size: var(--fs-lg); font-weight: 700; }
.onb-desc { color: var(--text-secondary); font-size: var(--fs-sm); line-height: 1.7; margin-top: 6px; }
.onb-form { display: flex; flex-direction: column; gap: 14px; margin-top: 18px; }
.ai-field { display: block; }
.field-label { display: block; font-size: var(--fs-sm); color: var(--text-secondary); margin-bottom: 6px; font-weight: 600; }
.field-label em { color: var(--danger); font-style: normal; }
.field-err { display: block; color: var(--danger); font-size: var(--fs-xs); margin-top: 4px; }
.onb-error { color: var(--danger); font-size: var(--fs-sm); padding: 10px 12px; border-radius: var(--r-md); background: var(--danger-soft); }
.onb-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px; }
.onb-ready { width: 56px; height: 56px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--success-soft); color: var(--success); margin-bottom: 14px; }
.demo-card { margin-top: 18px; padding: 16px; border: 1px solid var(--border-subtle); border-radius: var(--r-md); background: var(--bg-inset); }
.demo-title { display: flex; align-items: center; gap: 8px; color: var(--accent); font-weight: 600; font-size: var(--fs-sm); }
.demo-desc { color: var(--text-secondary); font-size: var(--fs-sm); line-height: 1.6; margin-top: 8px; }
.demo-cred { display: inline-block; margin-top: 10px; padding: 6px 10px; border-radius: var(--r-sm); background: var(--bg-surface); font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-primary); }
@media (max-width: 480px) { .onb { padding: 0; } .onb-step-label { display: none; } }
</style>
