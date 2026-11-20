<script setup lang="ts">
/**
 * 供应商透视：质量分排序（黑榜在前），多维标签 + 缺陷构成，点击卡片下钻
 * SKU 清单 / 平台分布 / 缺陷明细。数据来自 /api/insights 的 supplier_scorecard。
 */
import { ref, computed, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet } from '../api/client'
import { isLoggedIn } from '../composables/useAuth'

interface Drill { name: string; cases: number }
interface Supplier {
  name: string; supplier: string; cases: number; decided: number
  refund: number; avg_refund: number; quality_score: number; level: string
  defect_rate: number; win_rate: number; sku_count: number; platform_count: number
  sku_drill: Drill[]; platform_drill: Drill[]; defect_drill: Drill[]
}
const list = ref<Supplier[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref<Supplier | null>(null)

const sorted = computed(() => [...list.value].sort((a, b) => a.quality_score - b.quality_score))

function pct(v: number) { return ((v || 0) * 100).toFixed(1) + '%' }
function money(v: number) { return '¥' + Math.round(v || 0).toLocaleString('zh-CN') }
function levelClass(level: string) {
  return level === '黑名单' ? 'pill-bad' : level === '观察' ? 'pill' : 'pill-success'
}
function parse(v: unknown): Drill[] { return Array.isArray(v) ? (v as Drill[]) : [] }

async function load() {
  if (!isLoggedIn.value) { list.value = []; return }
  loading.value = true
  error.value = ''
  try {
    const d = await apiGet<{ supplier_scorecard: Supplier[] }>('insights?mode=mock')
    list.value = (d?.supplier_scorecard || []).map((s) => ({
      ...s,
      sku_drill: parse(s.sku_drill), platform_drill: parse(s.platform_drill), defect_drill: parse(s.defect_drill),
    }))
  } catch (e) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => { void load() })
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('sup.heading') }}</h1>
    <p class="page-intro">{{ t('sup.intro') }}</p>

    <div v-if="!isLoggedIn" class="card empty-state" style="margin-top:20px">
      <AppIcon name="user" :size="44" /><h3>{{ t('ent.needLogin') }}</h3>
    </div>
    <div v-else-if="loading" class="card empty-state" style="margin-top:20px">
      <span class="spinner" aria-hidden="true" />
    </div>
    <div v-else-if="error" class="card empty-state" style="margin-top:20px"><p class="err">{{ error }}</p></div>
    <div v-else-if="!sorted.length" class="card empty-state" style="margin-top:20px">
      <AppIcon name="truck" :size="44" /><p>{{ t('ent.noData') }}</p>
    </div>

    <div v-else class="sup-grid" style="margin-top:20px">
      <button v-for="s in sorted" :key="s.supplier" type="button" class="card sup-card" @click="selected = s">
        <div class="sup-top">
          <span class="sup-name">{{ s.name }}</span>
          <span class="pill" :class="levelClass(s.level)">{{ s.quality_score }}</span>
        </div>
        <div class="sup-tags">
          <span>{{ t('sup.defectRate') }} <b>{{ pct(s.defect_rate) }}</b></span>
          <span>{{ t('sup.winRate') }} <b>{{ pct(s.win_rate) }}</b></span>
          <span>{{ t('sup.avgRefund') }} <b>{{ money(s.avg_refund) }}</b></span>
          <span>{{ t('sup.skuCount') }} <b>{{ s.sku_count }}</b></span>
          <span>{{ t('sup.platformCount') }} <b>{{ s.platform_count }}</b></span>
        </div>
        <div class="mix-track" :title="t('sup.defectDist')">
          <span v-for="(d, i) in parse(s.defect_drill)" :key="i"
                class="mix-seg" :style="{ flex: String(d.cases || 1) }" />
        </div>
      </button>
    </div>

    <!-- 下钻 Sheet -->
    <div v-if="selected" class="overlay" @click.self="selected = null">
      <div class="sheet sheet-wide" role="dialog" :aria-label="selected.name">
        <div class="sheet-head">
          <h3>{{ selected.name }}</h3>
          <button class="btn btn-ghost" type="button" :aria-label="t('sup.close')" @click="selected = null">
            <AppIcon name="close" :size="18" />
          </button>
        </div>
        <div class="drill-grid">
          <div>
            <div class="sub-label">{{ t('sup.drillSku') }}</div>
            <div v-for="(d, i) in selected.sku_drill" :key="i" class="drill-row">
              <span>{{ d.name }}</span><b>{{ d.cases }}</b>
            </div>
            <p v-if="!selected.sku_drill.length" class="muted">{{ t('ent.noData') }}</p>
          </div>
          <div>
            <div class="sub-label">{{ t('sup.drillPlat') }}</div>
            <div v-for="(d, i) in selected.platform_drill" :key="i" class="drill-row">
              <span>{{ d.name }}</span><b>{{ d.cases }}</b>
            </div>
            <p v-if="!selected.platform_drill.length" class="muted">{{ t('ent.noData') }}</p>
          </div>
          <div>
            <div class="sub-label">{{ t('sup.drillDefect') }}</div>
            <div v-for="(d, i) in selected.defect_drill" :key="i" class="drill-row">
              <span>{{ d.name }}</span><b>{{ d.cases }}</b>
            </div>
            <p v-if="!selected.defect_drill.length" class="muted">{{ t('ent.noData') }}</p>
          </div>
        </div>
      </div>
    </div>
    <p class="data-note">{{ t('footer.dataNote') }}</p>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 780px; line-height: 1.6; }
.sup-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.sup-card { text-align: left; cursor: pointer; transition: transform 200ms cubic-bezier(.32,.72,0,1), border-color 200ms; }
.sup-card:hover { transform: translateY(-2px); border-color: var(--accent); }
.sup-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.sup-name { font-size: var(--fs-md); font-weight: 600; }
.sup-tags { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 12px; font-size: var(--fs-xs); color: var(--text-muted); }
.sup-tags b { color: var(--text-primary); font-weight: 600; margin-left: 3px; }
.mix-track { display: flex; gap: 2px; height: 8px; margin-top: 14px; border-radius: var(--r-pill); overflow: hidden; }
.mix-seg { background: var(--accent); opacity: .75; }
.mix-seg:nth-child(2n) { opacity: .5; }
.mix-seg:nth-child(3n) { opacity: .35; }
.sub-label { font-size: var(--fs-xs); color: var(--text-muted); font-weight: 600; margin-bottom: 8px; }
.drill-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 16px; }
.drill-row { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.drill-row span { color: var(--text-secondary); }
.muted { color: var(--text-muted); font-size: var(--fs-sm); }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
.spinner { width: 22px; height: 22px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; }
@media (prefers-reduced-motion: reduce) { .sup-card { transition: none; } }
</style>
