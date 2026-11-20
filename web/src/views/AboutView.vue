<script setup lang="ts">
/**
 * 关于页：产品定位、版本与技术事实、数据口径、开源许可。
 * 事实来自 README / VERSION / /api/config，不编造；版本运行时读取，避免发版漏改。
 * 三语由 i18n 目录提供；键盘可达（所有链接为原生 <a>，焦点样式沿用全局令牌）。
 */
import { ref, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet } from '../api/client'

const version = ref('—')
const REPO_URL = 'https://github.com/a703201/ReturnGuard'

onMounted(async () => {
  try {
    const cfg = await apiGet<{ version: string }>('config')
    version.value = cfg?.version ? `V${cfg.version}` : '—'
  } catch { version.value = '—' } // 静态内容仍可见；不伪装成功
})
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('about.heading') }}</h1>
    <p class="page-intro">{{ t('about.intro') }}</p>

    <!-- 品牌标识 + 版本（版本拉取失败时显示 —，不影响其余内容） -->
    <div class="hero card" style="margin-top:20px">
      <div class="hero-mark"><AppIcon name="shield" :size="40" :stroke="1.5" /></div>
      <div class="hero-text">
        <div class="hero-name">{{ t('app.name') }} <span class="version-tag">{{ version }}</span></div>
        <div class="hero-tagline">{{ t('app.tagline') }}</div>
      </div>
    </div>

    <!-- 定位：市场洞察为主、单案取证为辅 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="chart" :size="18" /><h3 class="card-title">{{ t('about.positionTitle') }}</h3></div>
      <p class="body-text">{{ t('about.positionBody') }}</p>
      <div class="facts">
        <div class="fact">
          <span class="fact-label">{{ t('about.casesLabel') }}</span>
          <b class="fact-value">{{ t('about.casesValue') }}</b>
          <span class="fact-note">{{ t('about.casesNote') }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">{{ t('about.platformsLabel') }}</span>
          <b class="fact-value">{{ t('about.platformsValue') }}</b>
          <span class="fact-note">{{ t('about.platformsNote') }}</span>
        </div>
        <div class="fact">
          <span class="fact-label">{{ t('about.aiLabel') }}</span>
          <b class="fact-value">{{ t('about.aiValue') }}</b>
          <span class="fact-note">{{ t('about.aiNote') }}</span>
        </div>
      </div>
    </div>

    <!-- 数据口径：诚实标注，不隐瞒来源 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="file" :size="18" /><h3 class="card-title">{{ t('about.dataTitle') }}</h3></div>
      <p class="body-text">{{ t('about.dataBody') }}</p>
    </div>

    <!-- 技术事实 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="layers" :size="18" /><h3 class="card-title">{{ t('about.stackTitle') }}</h3></div>
      <div class="kv"><span>{{ t('about.stackBackend') }}</span><b>{{ t('about.stackBackendVal') }}</b></div>
      <div class="kv"><span>{{ t('about.stackFrontend') }}</span><b>{{ t('about.stackFrontendVal') }}</b></div>
      <div class="kv"><span>{{ t('about.stackDb') }}</span><b>{{ t('about.stackDbVal') }}</b></div>
      <div class="kv"><span>{{ t('about.stackI18n') }}</span><b>{{ t('about.stackI18nVal') }}</b></div>
    </div>

    <!-- 开源与许可 -->
    <div class="card" style="margin-top:16px">
      <div class="card-heading"><AppIcon name="info" :size="18" /><h3 class="card-title">{{ t('about.licenseTitle') }}</h3></div>
      <p class="body-text">{{ t('about.licenseBody') }}</p>
      <a class="link" :href="REPO_URL" target="_blank" rel="noopener noreferrer">
        {{ t('about.repoLink') }} <span aria-hidden="true">↗</span>
      </a>
    </div>

    <p class="data-note">{{ t('footer.dataNote') }}</p>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 760px; line-height: 1.6; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.body-text { color: var(--text-secondary); font-size: var(--fs-sm); line-height: 1.75; margin-top: 12px; max-width: 860px; }
.hero { display: flex; align-items: center; gap: 18px; padding: 24px; }
.hero-mark {
  width: 64px; height: 64px; flex: none; border-radius: var(--r-lg);
  background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center;
}
.hero-text { min-width: 0; }
.hero-name { font-size: var(--fs-xl); font-weight: 700; letter-spacing: var(--tr-heading); display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.hero-tagline { color: var(--text-secondary); font-size: var(--fs-sm); margin-top: 6px; }
.version-tag {
  font-family: var(--font-mono); font-size: var(--fs-xs); font-weight: 600;
  color: var(--accent); background: var(--accent-soft);
  padding: 3px 9px; border-radius: var(--r-pill); white-space: nowrap;
}
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 20px; }
.fact { display: flex; flex-direction: column; gap: 4px; padding: 16px; background: var(--bg-inset); border-radius: var(--r-md); }
.fact-label { font-size: var(--fs-xs); color: var(--text-muted); font-weight: 600; }
.fact-value { font-size: var(--fs-xl); font-weight: 700; color: var(--text-primary); letter-spacing: var(--tr-heading); }
.fact-note { font-size: var(--fs-xs); color: var(--text-secondary); line-height: 1.5; }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv:last-child { border-bottom: 0; }
.kv span { color: var(--text-muted); }
.kv b { color: var(--text-primary); font-weight: 600; text-align: right; }
.link { display: inline-flex; align-items: center; gap: 6px; margin-top: 14px; color: var(--link); font-size: var(--fs-sm); }
.link:hover { text-decoration: underline; }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
</style>
