<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './components/AppIcon.vue'
import LoginSheet from './components/LoginSheet.vue'
import OnboardingSheet from './components/OnboardingSheet.vue'
import { t } from './i18n'
import { isLoggedIn, isDemo, username, clearSession } from './composables/useAuth'
import { loginSheetOpen } from './composables/useLoginSheet'
import { onboardingOpen, shouldShowOnboarding } from './composables/useOnboarding'
import { apiGet } from './api/client'

const route = useRoute()
const router = useRouter()
const appVersion = ref('—')
const loginOpen = loginSheetOpen  // 顶栏与设置页共用同一个登录 Sheet

const nav = [
  { key: 'dashboard', path: '/dashboard', icon: 'chart' },
  { key: 'platform', path: '/platform', icon: 'layers' },
  { key: 'supplier', path: '/supplier', icon: 'truck' },
  { key: 'forensic', path: '/forensic', icon: 'search' },
  { key: 'entry', path: '/entry', icon: 'upload' },
]

const activeNav = computed(() => {
  const name = route.name as string
  if (name === 'about' || name === 'settings') return name
  return nav.some((n) => n.key === name) ? name : 'dashboard'
})

function onLogin() { loginOpen.value = false }

function onLogout() {
  clearSession()
  router.push('/dashboard')
}

onMounted(async () => {
  if (shouldShowOnboarding()) onboardingOpen.value = true
  try {
    const cfg = await apiGet<{ version: string }>('config')
    if (cfg?.version) appVersion.value = `V${cfg.version}`
  } catch { appVersion.value = '—' }
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="toprow">
          <div class="brand">
            <AppIcon name="shield" :size="30" />
            <div style="min-width:0">
              <div class="brand-title">{{ t('app.name') }}</div>
              <div class="brand-sub">{{ t('app.tagline') }}</div>
            </div>
          </div>
          <span class="version-tag">{{ appVersion }}</span>
          <div class="spacer" />
          <span v-if="isDemo" class="pill pill-accent">
            <span class="dot" /> {{ t('demo.banner') }}
          </span>
          <span v-else-if="isLoggedIn" class="pill pill-success">
            <span class="dot" /> {{ username }}
          </span>
          <button class="btn btn-ghost" type="button" :title="t('nav.settings')" :aria-label="t('nav.settings')" @click="router.push('/settings')">
            <AppIcon name="settings" :size="18" />
          </button>
          <button v-if="!isLoggedIn" class="btn btn-primary" type="button" @click="loginOpen = true">
            <AppIcon name="user" :size="16" /> {{ t('action.login') }}
          </button>
          <button v-else class="btn btn-secondary" type="button" @click="onLogout">{{ t('action.logout') }}</button>
        </div>
      </div>
    </header>

    <div class="body-layout">
      <!-- 左侧导航（对齐档案管理系统：竖排图标+标签） -->
      <aside class="sidebar">
        <nav class="side-nav" role="navigation" :aria-label="t('app.name')">
          <button v-for="item in nav" :key="item.key" class="side-item" role="tab"
                  :class="{ active: activeNav === item.key }"
                  :aria-selected="activeNav === item.key"
                  type="button" @click="router.push(item.path)">
            <AppIcon :name="item.icon" :size="18" />
            <span>{{ t(`nav.${item.key}`) }}</span>
          </button>
        </nav>
        <div class="side-bottom">
          <button class="btn btn-ghost side-refresh" type="button" @click="router.push('/dashboard')">
            <AppIcon name="refresh" :size="16" /> {{ t('action.refresh') }}
          </button>
          <button class="btn btn-ghost side-refresh" type="button"
                  :class="{ active: activeNav === 'settings' }" :aria-current="activeNav === 'settings' ? 'page' : undefined"
                  @click="router.push('/settings')">
            <AppIcon name="settings" :size="16" /> {{ t('nav.settings') }}
          </button>
          <button class="btn btn-ghost side-refresh" type="button"
                  :class="{ active: activeNav === 'about' }" :aria-current="activeNav === 'about' ? 'page' : undefined"
                  @click="router.push('/about')">
            <AppIcon name="info" :size="16" /> {{ t('nav.about') }}
          </button>
        </div>
      </aside>

      <main class="main-area">
        <div v-if="isDemo" class="demo-strip">
          <AppIcon name="shield" :size="16" />
          <span>{{ t('demo.bannerSub') }}</span>
        </div>
        <div class="view view-enter-active" :key="activeNav">
          <RouterView />
        </div>
      </main>
    </div>

    <LoginSheet :open="loginOpen" @close="loginOpen = false" @logged-in="onLogin" />
    <OnboardingSheet :open="onboardingOpen" @close="onboardingOpen = false" />
  </div>
</template>

<style scoped>
.demo-strip {
  display: flex; align-items: center; gap: 10px;
  background: var(--accent-soft); color: var(--accent);
  border-radius: var(--r-md); padding: 10px 16px; margin-bottom: 16px;
  font-size: var(--fs-sm);
}
</style>
