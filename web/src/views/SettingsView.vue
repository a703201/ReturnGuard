<script setup lang="ts">
/**
 * 设置页：集中外观（主题）、语言、账户会话三类真实存在的偏好。
 * 不编造需后端支持的功能；所有改动即时生效并写入 localStorage（见 useTheme / i18n / useAuth）。
 * 无障碍：原生 radio 分组（fieldset/legend + visually-hidden input + label），方向键与读屏语义天然可用。
 */
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { t, locale, type Locale } from '../i18n'
import { themeMode, setTheme, type ThemeMode } from '../composables/useTheme'
import { isLoggedIn, isDemo, username, clearSession } from '../composables/useAuth'
import { openLoginSheet } from '../composables/useLoginSheet'
import { openOnboarding } from '../composables/useOnboarding'
import AiConfigForm from '../components/AiConfigForm.vue'

const router = useRouter()

const themeOptions: { value: ThemeMode; icon: string }[] = [
  { value: 'system', icon: 'globe' },
  { value: 'light', icon: 'sun' },
  { value: 'dark', icon: 'moon' },
]
const localeOptions: { value: Locale; label: string }[] = [
  { value: 'zh', label: '简体中文' },
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
]

function onLogout() {
  clearSession()
  router.push('/dashboard')
}
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('set.heading') }}</h1>
    <p class="page-intro">{{ t('set.intro') }}</p>

    <!-- 外观：主题 -->
    <div class="card" style="margin-top:20px">
      <div class="card-heading"><AppIcon name="sun" :size="18" /><h3 class="card-title">{{ t('set.themeTitle') }}</h3></div>
      <p class="card-desc">{{ t('set.themeDesc') }}</p>
      <fieldset class="choice-set">
        <legend class="sr-only">{{ t('set.themeTitle') }}</legend>
        <label v-for="opt in themeOptions" :key="opt.value" class="choice" :class="{ selected: themeMode === opt.value }">
          <input class="sr-only" type="radio" name="theme" :value="opt.value"
                 :checked="themeMode === opt.value" @change="setTheme(opt.value)" />
          <AppIcon :name="opt.icon" :size="20" />
          <span>{{ t(`theme.${opt.value}`) }}</span>
          <AppIcon v-if="themeMode === opt.value" name="check" :size="16" class="choice-check" />
        </label>
      </fieldset>
    </div>

    <!-- 语言 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="globe" :size="18" /><h3 class="card-title">{{ t('set.langTitle') }}</h3></div>
      <p class="card-desc">{{ t('set.langDesc') }}</p>
      <fieldset class="choice-set">
        <legend class="sr-only">{{ t('set.langTitle') }}</legend>
        <label v-for="opt in localeOptions" :key="opt.value" class="choice" :class="{ selected: locale === opt.value }">
          <input class="sr-only" type="radio" name="locale" :value="opt.value"
                 :checked="locale === opt.value" @change="locale = opt.value" />
          <span class="lang-code">{{ opt.value.toUpperCase() }}</span>
          <span>{{ opt.label }}</span>
          <AppIcon v-if="locale === opt.value" name="check" :size="16" class="choice-check" />
        </label>
      </fieldset>
    </div>

    <!-- 账户会话：真实状态，三态区分 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="user" :size="18" /><h3 class="card-title">{{ t('set.accountTitle') }}</h3></div>
      <div class="kv"><span>{{ t('set.accountStatus') }}</span>
        <b>
          <span v-if="!isLoggedIn" class="pill">{{ t('set.accountGuest') }}</span>
          <span v-else-if="isDemo" class="pill pill-accent">{{ t('set.accountDemo') }}</span>
          <span v-else class="pill pill-success">{{ username }}</span>
        </b>
      </div>
      <div v-if="isLoggedIn" class="kv"><span>{{ t('set.accountName') }}</span><b>{{ username }}</b></div>
      <p class="body-text">{{ t('set.accountDesc') }}</p>
      <button v-if="!isLoggedIn" class="btn btn-primary" type="button" @click="openLoginSheet">
        <AppIcon name="user" :size="16" /> {{ t('action.login') }}
      </button>
      <button v-else class="btn btn-secondary" type="button" @click="onLogout">
        <AppIcon name="close" :size="16" /> {{ t('action.logout') }}
      </button>
    </div>

    <!-- AI 功能配置：复用与首次引导相同的组件 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="spark" :size="18" /><h3 class="card-title">{{ t('set.aiTitle') }}</h3></div>
      <p class="card-desc">{{ t('set.aiDesc') }}</p>
      <AiConfigForm />
    </div>

    <!-- 引导入口：可重新查看首次部署引导（创建账户 / AI 配置 / 演示账户） -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="spark" :size="18" /><h3 class="card-title">{{ t('set.guideTitle') }}</h3></div>
      <p class="card-desc">{{ t('set.guideDesc') }}</p>
      <button class="btn btn-secondary" type="button" style="margin-top:12px" @click="openOnboarding">
        <AppIcon name="spark" :size="16" /> {{ t('set.guideBtn') }}
      </button>
    </div>

    <p class="data-note">{{ t('set.persistenceNote') }}</p>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 760px; line-height: 1.6; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.card-desc, .body-text { color: var(--text-secondary); font-size: var(--fs-sm); line-height: 1.7; margin-top: 6px; }
.body-text { margin-top: 14px; }
.choice-set { border: 0; padding: 0; margin: 16px 0 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.choice {
  min-height: 48px; display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border: 1px solid var(--border-subtle); border-radius: var(--r-md);
  color: var(--text-secondary); cursor: pointer; font-size: var(--fs-sm);
  transition: border-color 160ms ease, background 160ms ease;
}
.choice:hover { background: var(--bg-hover); }
.choice.selected { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.choice:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.choice-check { margin-left: auto; }
.lang-code { font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-muted); }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv span { color: var(--text-muted); }
.kv b { color: var(--text-primary); font-weight: 600; text-align: right; }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) { .choice { transition: none; } }
</style>
