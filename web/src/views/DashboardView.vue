<script setup lang="ts">
/**
 * 市场洞察看板（核心页）。登录后从仓颉后端 /api/insights 拉取当前租户数据：
 * 演示账户看预置演示种子，普通账户看自身租户数据（单库 + 租户隔离，无 demo/real 切换）。
 * 未登录不展示数据，引导登录（可用演示账户）。
 */
import { ref, computed, watch, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet } from '../api/client'
import { isLoggedIn } from '../composables/useAuth'

interface ViewRow { name: string; cases: number; refund: number; win_rate: number; decided: number }
interface SkuInsight { sku: string; finding: string; action: string }
interface BlacklistRow { supplier: string; name: string; quality_score: number; level: string; reason: string }
interface Insights {
  total_cases: number; total_refund: number; win_rate: number; decided: number
  avg_dispute_rate: number; report: string; tenant: string
  category_heatmap: ViewRow[]; platform_view: ViewRow[]
  region_view: ViewRow[]; season_view: ViewRow[]; supplier_scorecard: ViewRow[]
  sourcing_advice?: string[]; recommendations?: string[]
  sku_insights?: SkuInsight[]; supplier_blacklist?: BlacklistRow[]
  root_cause?: string; total_return_cost?: number; logistics_cost?: number
  sku_ranking?: SkuRankRow[]; anomaly_alerts?: AnomalyRow[]
  root_cause_dist?: Record<string, number>
}
interface SkuRankRow {
  sku: string; category: string; supplier: string; cases: number; refund: number
  win_rate: number; top_defect: string; anomaly: boolean
}
interface AnomalyRow { sku: string; category: string; recent: number; prior: number; pct: number; reason: string }

const insights = ref<Insights | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  if (!isLoggedIn.value) { insights.value = null; return }
  loading.value = true
  loadError.value = ''
  try {
    insights.value = await apiGet<Insights>('insights?mode=mock')
  } catch (e) {
    loadError.value = (e as Error).message || '加载失败'
    insights.value = null
  } finally {
    loading.value = false
  }
}

const kpis = computed(() => {
  const d = insights.value
  if (!d) return []
  return [
    { label: t('kpi.total'), value: d.total_cases.toLocaleString('zh-CN'), hint: t('kpi.placeholder') },
    { label: t('kpi.refund'), value: '¥ ' + Math.round(d.total_refund).toLocaleString('zh-CN'), hint: t('kpi.placeholder') },
    { label: t('kpi.win'), value: (d.win_rate * 100).toFixed(1) + '%', hint: t('kpi.placeholder') },
    { label: t('kpi.defect'), value: (d.avg_dispute_rate * 100).toFixed(1) + '%', hint: t('kpi.placeholder') },
  ]
})

/** 卡片 → 对应聚合数组。 */
const cards: { key: string; icon: string; field: keyof Insights }[] = [
  { key: 'category', icon: 'chart', field: 'category_heatmap' },
  { key: 'platform', icon: 'layers', field: 'platform_view' },
  { key: 'region', icon: 'globe', field: 'region_view' },
  { key: 'supplier', icon: 'truck', field: 'supplier_scorecard' },
]

function rowsOf(field: keyof Insights): ViewRow[] {
  const v = insights.value?.[field]
  return Array.isArray(v) ? (v as ViewRow[]).slice(0, 6) : []
}
function pct(v: number): string { return (v * 100).toFixed(1) + '%' }
/** 胜诉率分色：<30% 高风险红 / <60% 中风险橙 / ≥60% 蓝。 */
function rateClass(v: number): string {
  if (v < 0.3) return 'rate-low'
  if (v < 0.6) return 'rate-mid'
  return 'rate-high'
}

const rootCauseRows = computed(() => {
  const d = insights.value
  if (!d?.root_cause_dist) return []
  return Object.entries(d.root_cause_dist)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
})
const rootCauseMax = computed(() => Math.max(1, ...rootCauseRows.value.map((r) => r.count)))
const rootCauseTotal = computed(() => Math.max(1, rootCauseRows.value.reduce((s, r) => s + r.count, 0)))

const adviceList = computed<string[]>(() => {
  const d = insights.value
  if (!d) return []
  const arr = d.sourcing_advice?.length ? d.sourcing_advice : (d.recommendations || [])
  return arr.filter(Boolean)
})

watch(isLoggedIn, () => { void load() })
onMounted(() => { void load() })
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('dash.heading') }}</h1>
    <p class="page-intro">{{ t('dash.intro') }}</p>

    <!-- 未登录：引导登录，不展示数据 -->
    <div v-if="!isLoggedIn" class="card empty-state" style="margin-top:24px">
      <AppIcon name="user" :size="44" />
      <h3>{{ t('dash.loginRequired') }}</h3>
      <p>{{ t('dash.loginRequiredDesc') }}</p>
    </div>

    <template v-else-if="insights">
      <div class="dash-meta">
        <span class="pill pill-accent"><span class="dot" /> {{ insights.tenant }}</span>
        <span class="pill">{{ t('kpi.placeholder') }}</span>
      </div>
      <div class="kpi-grid stagger" style="margin-top:16px">
        <div v-for="k in kpis" :key="k.label" class="kpi">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value">{{ k.value }}</div>
          <div class="kpi-hint">{{ k.hint }}</div>
        </div>
      </div>

      <div class="board-grid stagger" style="margin-top:16px">
        <div v-for="c in cards" :key="c.key" class="card insight-card">
          <div class="card-heading">
            <AppIcon :name="c.icon" :size="18" />
            <h3 class="card-title">{{ t(`dash.card.${c.key}`) }}</h3>
          </div>
          <div class="rows">
            <div v-for="row in rowsOf(c.field)" :key="row.name" class="row">
              <span class="row-name" :title="row.name">{{ row.name }}</span>
              <span class="row-track">
                <!-- 条长=胜诉率（有差异的趋势指标），案件数在右侧标注；按风险分色 -->
                <span class="row-fill" :class="rateClass(row.win_rate || 0)"
                      :style="{ width: ((row.win_rate || 0) * 100) + '%' }" />
              </span>
              <span class="row-val">{{ row.cases }}笔 · {{ pct(row.win_rate || 0) }}</span>
            </div>
          </div>
        </div>

        <div class="card insight-card">
          <div class="card-heading">
            <AppIcon name="inbox" :size="18" />
            <h3 class="card-title">{{ t('dash.card.report') }}</h3>
          </div>
          <p class="report-text">{{ insights.report }}</p>
          <p v-if="insights.root_cause" class="report-sub">{{ insights.root_cause }}</p>
        </div>

        <!-- ⑧ 建议清单：反哺选品与品控的具体动作 -->
        <div class="card insight-card">
          <div class="card-heading">
            <AppIcon name="spark" :size="18" />
            <h3 class="card-title">{{ t('dash.card.advice') }}</h3>
          </div>
          <ul v-if="adviceList.length" class="advice-list">
            <li v-for="(a, i) in adviceList" :key="i">{{ a }}</li>
          </ul>
          <p v-else class="muted-note">{{ t('empty.title') }}</p>
        </div>

        <!-- SKU 洞察：高发问题与对应动作 -->
        <div v-if="insights.sku_insights?.length" class="card insight-card">
          <div class="card-heading">
            <AppIcon name="chart" :size="18" />
            <h3 class="card-title">{{ t('dash.card.skuInsight') }}</h3>
          </div>
          <div v-for="s in insights.sku_insights" :key="s.sku" class="sku-item">
            <div class="sku-code">{{ s.sku }}</div>
            <div class="sku-finding">{{ s.finding }}</div>
            <div class="sku-action">→ {{ s.action }}</div>
          </div>
        </div>

        <!-- 供应商黑名单 -->
        <div v-if="insights.supplier_blacklist?.length" class="card insight-card">
          <div class="card-heading">
            <AppIcon name="truck" :size="18" />
            <h3 class="card-title">{{ t('dash.card.blacklist') }}</h3>
          </div>
          <div v-for="b in insights.supplier_blacklist" :key="b.supplier" class="blacklist-item">
            <span class="bl-name">{{ b.name || b.supplier }}</span>
            <span class="pill pill-bad">{{ b.quality_score }}</span>
            <div class="bl-reason">{{ b.reason }}</div>
          </div>
        </div>

        <!-- 退货成本 -->
        <div class="card insight-card">
          <div class="card-heading"><AppIcon name="chart" :size="18" /><h3 class="card-title">{{ t('dash.card.cost') }}</h3></div>
          <div class="cost-grid">
            <div><span>{{ t('dash.costLogistics') }}</span><b>¥ {{ Math.round(insights.logistics_cost || 0).toLocaleString('zh-CN') }}</b></div>
            <div><span>{{ t('dash.costTotal') }}</span><b>¥ {{ Math.round(insights.total_return_cost || 0).toLocaleString('zh-CN') }}</b></div>
            <div><span>{{ t('dash.costShare') }}</span><b>{{ (((insights.logistics_cost || 0) / Math.max(insights.total_return_cost || 1, 1)) * 100).toFixed(1) }}%</b></div>
          </div>
        </div>

        <!-- 根因分布 -->
        <div v-if="rootCauseRows.length" class="card insight-card">
          <div class="card-heading"><AppIcon name="inbox" :size="18" /><h3 class="card-title">{{ t('dash.card.rootCause') }}</h3></div>
          <div v-for="r in rootCauseRows" :key="r.name" class="row" style="margin-top:12px">
            <span class="row-name" :title="r.name">{{ r.name }}</span>
            <span class="row-track"><span class="row-fill" :style="{ width: (r.count / rootCauseMax * 100) + '%' }" /></span>
            <span class="row-val">{{ r.count }} · {{ (r.count / rootCauseTotal * 100).toFixed(0) }}%</span>
          </div>
        </div>

        <!-- 异常预警（无异常时也显示卡片，明确告知状态） -->
        <div class="card insight-card">
          <div class="card-heading"><AppIcon name="spark" :size="18" /><h3 class="card-title">{{ t('dash.card.anomaly') }}</h3></div>
          <p v-if="!insights.anomaly_alerts?.length" class="muted-note">{{ t('dash.noAnomaly') }}</p>
          <div v-for="(a, i) in insights.anomaly_alerts || []" :key="i" class="anomaly-item">
            <b>{{ a.sku }}</b> <span class="pill pill-bad">+{{ a.pct }}%</span>
            <div class="anomaly-reason">{{ a.reason }}</div>
          </div>
        </div>

        <!-- SKU 排名表 -->
        <div v-if="insights.sku_ranking?.length" class="card insight-card wide-card">
          <div class="card-heading"><AppIcon name="layers" :size="18" /><h3 class="card-title">{{ t('dash.card.skuRank') }}</h3></div>
          <div class="table-scroll">
            <table class="mini-table">
              <thead><tr><th>SKU</th><th>{{ t('ent.category') }}</th><th>{{ t('ent.supplier') }}</th><th>{{ t('ent.recent') }}</th><th>{{ t('kpi.refund') }}</th><th>{{ t('kpi.win') }}</th><th>{{ t('ent.defect') }}</th></tr></thead>
              <tbody>
                <tr v-for="r in insights.sku_ranking.slice(0, 10)" :key="r.sku">
                  <td>{{ r.sku }}<span v-if="r.anomaly" class="pill pill-bad">!</span></td>
                  <td>{{ r.category || '-' }}</td><td>{{ r.supplier || '-' }}</td>
                  <td>{{ r.cases }}</td><td>¥{{ Math.round(r.refund).toLocaleString('zh-CN') }}</td>
                  <td>{{ pct(r.win_rate) }}</td><td>{{ r.top_defect || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 地区 / 季节分布 -->
        <div class="card insight-card">
          <div class="card-heading"><AppIcon name="globe" :size="18" /><h3 class="card-title">{{ t('dash.card.region') }}</h3></div>
          <div class="table-scroll">
            <table class="mini-table">
              <thead><tr><th>{{ t('dash.colRegion') }}</th><th>{{ t('ent.recent') }}</th><th>{{ t('kpi.refund') }}</th><th>{{ t('kpi.win') }}</th></tr></thead>
              <tbody>
                <tr v-for="r in rowsOf('region_view')" :key="r.name">
                  <td>{{ r.name }}</td><td>{{ r.cases }}</td><td>¥{{ Math.round(r.refund).toLocaleString('zh-CN') }}</td><td>{{ pct(r.win_rate) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="card insight-card">
          <div class="card-heading"><AppIcon name="chart" :size="18" /><h3 class="card-title">{{ t('dash.card.season') }}</h3></div>
          <div class="table-scroll">
            <table class="mini-table">
              <thead><tr><th>{{ t('dash.colSeason') }}</th><th>{{ t('ent.recent') }}</th><th>{{ t('kpi.refund') }}</th><th>{{ t('kpi.win') }}</th></tr></thead>
              <tbody>
                <tr v-for="r in rowsOf('season_view')" :key="r.name">
                  <td>{{ r.name }}</td><td>{{ r.cases }}</td><td>¥{{ Math.round(r.refund).toLocaleString('zh-CN') }}</td><td>{{ pct(r.win_rate) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <p class="data-note">{{ t('footer.dataNote') }}</p>
    </template>

    <div v-else-if="loading" class="card empty-state" style="margin-top:24px">
      <span class="spinner" aria-hidden="true" />
      <p>{{ t('dash.loading') }}</p>
    </div>
    <div v-else class="card empty-state" style="margin-top:24px">
      <p class="err">{{ loadError || t('empty.title') }}</p>
      <button class="btn btn-secondary" type="button" @click="load">{{ t('action.refresh') }}</button>
    </div>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 720px; }
.dash-meta { display: flex; gap: 8px; margin-top: 20px; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.rows { display: flex; flex-direction: column; gap: 9px; margin-top: 18px; }
.row { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); }
.row-name { width: 92px; flex: none; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-track { flex: 1; height: 10px; border-radius: var(--r-pill); background: var(--bg-inset); overflow: hidden; }
.row-fill { display: block; height: 100%; border-radius: var(--r-pill); background: var(--accent); transform-origin: left; animation: rg-bar-grow 520ms cubic-bezier(0.32,0.72,0,1) both; }
.row-fill.rate-low { background: #ff3b30; }
.row-fill.rate-mid { background: #ff9f0a; }
.row-fill.rate-high { background: var(--accent); }
.row-val { width: 96px; flex: none; text-align: right; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.report-text { margin-top: 16px; font-size: var(--fs-md); line-height: 1.7; color: var(--text-secondary); }
.report-sub { margin-top: 10px; font-size: var(--fs-sm); line-height: 1.6; color: var(--text-muted); }
.advice-list { margin: 14px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.advice-list li {
  background: var(--bg-inset); border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm); padding: 10px 12px;
  font-size: var(--fs-sm); line-height: 1.6; color: var(--text-secondary);
}
.advice-list li::before { content: '▸ '; color: var(--accent); font-weight: 700; }
.muted-note { margin-top: 14px; color: var(--text-muted); font-size: var(--fs-sm); }
.sku-item { padding: 12px 0; border-bottom: 1px solid var(--border-subtle); }
.sku-item:last-child { border-bottom: 0; }
.sku-code { font-size: var(--fs-sm); font-weight: 700; color: var(--text-primary); }
.sku-finding { margin-top: 4px; font-size: var(--fs-sm); color: var(--text-secondary); line-height: 1.6; }
.sku-action { margin-top: 4px; font-size: var(--fs-xs); color: var(--accent); line-height: 1.6; }
.blacklist-item { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
.blacklist-item:last-child { border-bottom: 0; }
.bl-name { font-size: var(--fs-sm); font-weight: 600; }
.bl-reason { flex: 1 1 100%; font-size: var(--fs-xs); color: var(--text-muted); line-height: 1.5; }
.wide-card { grid-column: 1 / -1; }
.cost-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px; }
.cost-grid div { background: var(--bg-inset); border-radius: var(--r-sm); padding: 12px; }
.cost-grid span { display: block; font-size: var(--fs-xs); color: var(--text-muted); }
.cost-grid b { display: block; margin-top: 6px; font-size: var(--fs-md); }
.anomaly-item { padding: 10px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.anomaly-item:last-child { border-bottom: 0; }
.anomaly-reason { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 4px; line-height: 1.5; }
.table-scroll { overflow-x: auto; margin-top: 14px; }
.mini-table { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
.mini-table th, .mini-table td { border-bottom: 1px solid var(--border-subtle); padding: 8px 10px; text-align: left; white-space: nowrap; }
.mini-table th { color: var(--text-muted); font-weight: 600; }
.mini-table tbody tr:hover { background: var(--bg-inset); }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
.spinner { width: 22px; height: 22px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; }
</style>
