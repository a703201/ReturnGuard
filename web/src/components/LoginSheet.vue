<script setup lang="ts">
/**
 * 登录 Sheet。
 * - 真实登录：调用后端 /api/auth/login。
 * - 演示账户：用 demo / demo123 走同一登录端点真正登录（不再是本地假会话），
 *   登录后按租户拉取演示种子数据，取消 demo/real 双源切换。
 */
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '../i18n'
import { setSession } from '../composables/useAuth'
import { apiPost } from '../api/client'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; loggedIn: [] }>()

const user = ref('')
const pass = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const res = await apiPost<{ token: string; username: string }>('auth/login', { username: user.value, password: pass.value })
    setSession(res.token, res.username)
    emit('loggedIn')
  } catch {
    error.value = t('login.error')
  } finally {
    busy.value = false
  }
}

async function enterDemo() {
  // 演示账户：走真实登录端点，拿到后端签发的租户令牌（与手工登录同一路径）。
  error.value = ''
  busy.value = true
  try {
    const res = await apiPost<{ token: string; username: string }>('auth/login', { username: 'demo', password: 'demo123' })
    setSession(res.token, res.username)
    emit('loggedIn')
  } catch {
    error.value = t('login.error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Transition name="overlay">
    <div v-if="open" class="overlay" @click.self="emit('close')">
      <div class="sheet" role="dialog" aria-modal="true" :aria-label="t('login.title')">
        <div class="sheet-head">
          <h2 class="sheet-title">{{ t('login.title') }}</h2>
          <div class="spacer" />
          <button class="icon-btn" type="button" :aria-label="t('action.logout')" @click="emit('close')">
            <AppIcon name="close" :size="20" />
          </button>
        </div>
        <p class="card-desc" style="margin-bottom:8px">{{ t('login.subtitle') }}</p>

        <form @submit.prevent="submit">
          <label class="field-label" for="lg-user">{{ t('login.user') }}</label>
          <input id="lg-user" v-model="user" class="field field-block" autocomplete="username" required />
          <label class="field-label" for="lg-pass">{{ t('login.password') }}</label>
          <input id="lg-pass" v-model="pass" class="field field-block" type="password" autocomplete="current-password" required />
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="btn btn-primary field-block" type="submit" style="margin-top:20px" :disabled="busy">
            {{ busy ? '…' : t('login.submit') }}
          </button>
        </form>

        <div class="divider"><span>{{ t('login.demoHint') }}</span></div>
        <button class="btn btn-secondary field-block" type="button" @click="enterDemo">
          <AppIcon name="check" :size="16" /> {{ t('action.demo') }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.divider {
  display: flex; align-items: center; gap: 12px;
  color: var(--text-muted); font-size: var(--fs-xs); margin: 22px 0 14px;
}
.divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--border-subtle); }
</style>
