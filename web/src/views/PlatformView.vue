<script setup lang="ts">
/**
 * 平台举证包：展示九大跨境平台的退货/纠纷举证规则对照表 + 可折叠举证模板。
 * 数据来自仓颉后端 /api/platforms（仓颉实现的单一事实来源）。
 * 只列客观政策要求与 ReturnGuard 可支撑能力，不做裁决结论（去 AI 味、守住边界）。
 */
import { ref, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet } from '../api/client'

interface PlatformSpec {
  key: string; label: string; region?: string
  return_window: string; response_window: string; shipping_payer: string; burden_bias: string
  required_evidence: string[]; common_loss_reasons: string[]; special_clauses: string[]
  capability_map: Record<string, string>
}

const platforms = ref<PlatformSpec[]>([])
const loading = ref(true)
const error = ref('')
const openKey = ref('')

const columns: { key: keyof PlatformSpec; label: string }[] = [
  { key: 'return_window', label: t('plat.returnWindow') },
  { key: 'response_window', label: t('plat.responseWindow') },
  { key: 'shipping_payer', label: t('plat.shippingPayer') },
  { key: 'burden_bias', label: t('plat.burdenBias') },
]

function toggle(key: string) { openKey.value = openKey.value === key ? '' : key }
function arr(v: unknown): string[] { return Array.isArray(v) ? (v as string[]) : [] }

onMounted(async () => {
  try {
    const d = await apiGet<{ platforms: PlatformSpec[] }>('platforms')
    platforms.value = d?.platforms || []
  } catch (e) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('plat.heading') }}</h1>
    <p class="page-intro">{{ t('plat.intro') }}</p>

    <div v-if="loading" class="card empty-state" style="margin-top:20px">
      <span class="spinner" aria-hidden="true" />
    </div>
    <div v-else-if="error" class="card empty-state" style="margin-top:20px">
      <p class="err">{{ error }}</p>
    </div>

    <template v-else>
      <div class="card" style="margin-top:20px">
        <div class="card-heading"><AppIcon name="layers" :size="18" /><h3 class="card-title">{{ t('plat.dim') }}</h3></div>
        <div class="table-scroll">
          <table class="cmp">
            <thead>
              <tr><th>{{ t('plat.dim') }}</th><th v-for="p in platforms" :key="p.key">{{ p.label }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in columns" :key="c.key">
                <th>{{ c.label }}</th>
                <td v-for="p in platforms" :key="p.key">{{ p[c.key] || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <div class="card-heading"><AppIcon name="file" :size="18" /><h3 class="card-title">{{ t('for.evidence') }}</h3></div>
        <div class="acc-list">
          <div v-for="p in platforms" :key="p.key" class="acc" :class="{ open: openKey === p.key }">
            <button type="button" class="acc-head" :aria-expanded="openKey === p.key" @click="toggle(p.key)">
              <span class="acc-name">{{ p.label }}</span>
              <span class="acc-hint">{{ t('plat.burdenBias') }}：{{ p.burden_bias || '-' }}</span>
              <span class="acc-arrow" aria-hidden="true">▸</span>
            </button>
            <div class="acc-body">
              <div class="kv"><span>{{ t('plat.returnWindow') }}</span><b>{{ p.return_window }}</b></div>
              <div class="kv"><span>{{ t('plat.responseWindow') }}</span><b>{{ p.response_window }}</b></div>
              <div class="kv"><span>{{ t('plat.shippingPayer') }}</span><b>{{ p.shipping_payer }}</b></div>
              <div class="kv"><span>{{ t('plat.burdenBias') }}</span><b>{{ p.burden_bias }}</b></div>
              <div class="sub-label">{{ t('plat.requiredEvidence') }}</div>
              <ul class="ev"><li v-for="(x, i) in arr(p.required_evidence)" :key="i">{{ x }}</li></ul>
              <div class="sub-label">{{ t('plat.lossReasons') }}</div>
              <ul class="ev bad"><li v-for="(x, i) in arr(p.common_loss_reasons)" :key="i">{{ x }}</li></ul>
              <div v-if="arr(p.special_clauses).length" class="sub-label">{{ t('plat.specialClauses') }}</div>
              <ul v-if="arr(p.special_clauses).length" class="ev dim">
                <li v-for="(x, i) in arr(p.special_clauses)" :key="i">{{ x }}</li>
              </ul>
              <div class="sub-label">{{ t('plat.howWeHelp') }}</div>
              <ul class="ev cap">
                <li v-for="(desc, k) in (p.capability_map || {})" :key="k"><b>{{ k }}</b>：{{ desc }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
      <p class="data-note">{{ t('footer.dataNote') }}</p>
    </template>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 760px; line-height: 1.6; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.table-scroll { overflow-x: auto; margin-top: 16px; }
.cmp { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); min-width: 760px; }
.cmp th, .cmp td { border: 1px solid var(--border-subtle); padding: 10px 12px; text-align: left; vertical-align: top; }
.cmp thead th { background: var(--bg-inset); font-weight: 600; }
.cmp tbody th { background: var(--bg-inset); font-weight: 600; white-space: nowrap; }
.acc-list { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.acc { border: 1px solid var(--border-subtle); border-radius: var(--r-md); overflow: hidden; }
.acc-head {
  width: 100%; display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: transparent; border: 0; cursor: pointer; text-align: left;
}
.acc-head:hover { background: var(--bg-inset); }
.acc-name { font-weight: 600; font-size: var(--fs-md); }
.acc-hint { color: var(--text-muted); font-size: var(--fs-sm); flex: 1; }
.acc-arrow { color: var(--text-muted); transition: transform 220ms cubic-bezier(.32,.72,0,1); }
.acc.open .acc-arrow { transform: rotate(90deg); }
.acc-body {
  max-height: 0; overflow: hidden; padding: 0 16px;
  transition: max-height 320ms cubic-bezier(.32,.72,0,1), padding 320ms;
}
.acc.open .acc-body { max-height: 1600px; padding: 8px 16px 20px; }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv span { color: var(--text-muted); }
.kv b { color: var(--text-primary); font-weight: 600; text-align: right; }
.sub-label { font-size: var(--fs-xs); color: var(--text-muted); margin-top: 14px; font-weight: 600; }
.ev { margin: 6px 0 0; padding-left: 18px; font-size: var(--fs-sm); color: var(--text-secondary); line-height: 1.7; }
.ev.bad { color: var(--bad, #ff3b30); }
.ev.dim { color: var(--text-muted); }
.ev.cap { color: var(--accent); }
.spinner { width: 22px; height: 22px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
@media (prefers-reduced-motion: reduce) {
  .acc-body, .acc-arrow { transition: none; }
}
</style>
