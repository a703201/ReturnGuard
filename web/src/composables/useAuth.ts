/**
 * 轻量会话状态（本批骨架）：令牌存 localStorage 'rg_token'，登出清空。
 * 后续批次账户系统重做时，在此接入后端签名令牌 + 刷新/失效逻辑。
 */
import { ref, computed } from 'vue'

const TOKEN_KEY = 'rg_token'
const USER_KEY = 'rg_user'

function readToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}
function readUser(): string {
  try { return localStorage.getItem(USER_KEY) || '' } catch { return '' }
}

export const token = ref<string>(readToken())
export const username = ref<string>(readUser())
export const isLoggedIn = computed(() => !!token.value)
export const isDemo = computed(() => username.value === 'demo')

export function setSession(newToken: string, newUser: string) {
  token.value = newToken
  username.value = newUser
  try {
    localStorage.setItem(TOKEN_KEY, newToken)
    localStorage.setItem(USER_KEY, newUser)
  } catch { /* ignore */ }
}

export function clearSession() {
  token.value = ''
  username.value = ''
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch { /* ignore */ }
}
