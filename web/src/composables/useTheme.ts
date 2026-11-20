/** 主题：system / light / dark，写入 localStorage 'rg.theme' 并同步 data-theme。 */
import { ref } from 'vue'

export type ThemeMode = 'system' | 'light' | 'dark'
const KEY = 'rg.theme'

function read(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY) as ThemeMode | null
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch { /* ignore */ }
  return 'system'
}

export const themeMode = ref<ThemeMode>(read())

function apply(mode: ThemeMode) {
  const dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
}

export function setTheme(mode: ThemeMode) {
  themeMode.value = mode
  try { localStorage.setItem(KEY, mode) } catch { /* ignore */ }
  apply(mode)
}

export function initTheme() {
  apply(themeMode.value)
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', () => { if (themeMode.value === 'system') apply('system') })
}
