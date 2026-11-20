/**
 * 轻量多语言框架（沿用 AMS 设计取舍：不引入 vue-i18n，用 reactive locale + 文案目录）。
 * t() 只做静态查表 + {name} 占位符替换；缺键回退到传入的中文默认文案。
 */
import { ref, watch } from 'vue'
import zh from './catalog.zh'
import en from './catalog.en'
import fr from './catalog.fr'

export type Locale = 'zh' | 'en' | 'fr'
export const defaultLocale: Locale = 'zh'
export const supported: Locale[] = ['zh', 'en', 'fr']
const STORAGE_KEY = 'rg.locale'

function detectInitial(): Locale {
  let saved: Locale | null = null
  try {
    if (typeof localStorage !== 'undefined') saved = localStorage.getItem(STORAGE_KEY) as Locale | null
  } catch { saved = null }
  if (saved && supported.includes(saved)) return saved
  const nav = (typeof navigator !== 'undefined' && navigator.language ? navigator.language : 'zh').toLowerCase()
  if (nav.startsWith('fr')) return 'fr'
  if (nav.startsWith('en')) return 'en'
  return 'zh'
}

export const locale = ref<Locale>(detectInitial())

export const catalogs: Record<Locale, Record<string, string>> = { zh, en, fr }

export function t(key: string, fallback = '', vars?: Record<string, string | number>): string {
  let text = catalogs[locale.value]?.[key] ?? catalogs[defaultLocale]?.[key] ?? fallback ?? key
  if (vars) {
    for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v))
  }
  return text
}

try {
  watch(locale, (v) => localStorage.setItem(STORAGE_KEY, v))
} catch { /* 隐私模式：不持久化 */ }
