<script setup lang="ts">
/**
 * 单案取证：上传退货图 + 商品主图，调用 /api/analyze 生成举证材料。
 * 无 AI 密钥时诚实回退 mock（capabilities 标注），不伪装成功（守住「只取证不裁决」）。
 */
import { ref, reactive, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet, apiPost } from '../api/client'
import { isLoggedIn } from '../composables/useAuth'

interface AnalyzeResult {
  similarity: number; same_item: boolean; dossier: string; consistency: string
  defect_tags: string[]; priority_score: number; defect_boxes: unknown[]
  case_id: string; platform: string; mode: string
  platform_evidence: string[]; voice_text: string
  capabilities: Record<string, boolean>
}
interface Ev { name: string; value: string }

const form = reactive({
  sku: 'SKU-3C01', amount: 120, listing: '', mode: 'mock',
  platform: '', category: '', supplier: '', language: 'zh',
})
const returnedImg = ref('')
const productImg = ref('')
const busy = ref(false)
const error = ref('')
const result = ref<AnalyzeResult | null>(null)
const platforms = ref<{ key: string; label: string }[]>([])
const categories = ref<string[]>([])
const suppliers = ref<string[]>([])
const step = ref(1)

function readFile(file: File | undefined, target: 'returned' | 'product') {
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const url = String(reader.result || '')
    if (target === 'returned') returnedImg.value = url
    else productImg.value = url
  }
  reader.readAsDataURL(file)
}

async function submit() {
  if (!returnedImg.value || !productImg.value) {
    error.value = t('for.returnedImg') + ' / ' + t('for.productImg')
    return
  }
  busy.value = true
  error.value = ''
  result.value = null
  step.value = 2
  try {
    const r = await apiPost<AnalyzeResult>('analyze', {
      mode: form.mode, sku: form.sku, platform: form.platform,
      listing_text: form.listing, returned_image_url: returnedImg.value,
    })
    result.value = r
    step.value = 3
  } catch (e) {
    error.value = (e as Error).message || t('for.error')
    step.value = 1
  } finally {
    busy.value = false
  }
}

async function copyDossier() {
  if (!result.value) return
  try { await navigator.clipboard.writeText(result.value.dossier) } catch { /* 忽略：非安全上下文 */ }
}

function pct(v: number) { return ((v || 0) * 100).toFixed(1) + '%' }
function arr(v: unknown): string[] { return Array.isArray(v) ? (v as string[]) : [] }
function truthyCaps(c: Record<string, boolean> | undefined) {
  if (!c) return []
  return Object.entries(c).filter(([, v]) => v).map(([k]) => k)
}
function platformEvidence(v: unknown): Ev[] {
  if (!Array.isArray(v)) return []
  return (v as unknown[]).map((x) => {
    if (typeof x === 'string') return { name: x, value: '' }
    const o = x as Record<string, unknown>
    return { name: String(o.name || o.title || o.key || ''), value: String(o.value || o.detail || o.text || '') }
  })
}

onMounted(async () => {
  if (!isLoggedIn.value) return
  try {
    const [p, ins] = await Promise.all([
      apiGet<{ platforms: { key: string; label: string }[] }>('platforms'),
      apiGet<{ category_heatmap: { name: string }[]; supplier_scorecard: { name: string }[] }>('insights?mode=mock'),
    ])
    platforms.value = p?.platforms || []
    categories.value = (ins?.category_heatmap || []).map((x) => x.name)
    suppliers.value = (ins?.supplier_scorecard || []).map((x) => x.name)
  } catch { /* 下拉为空不阻断取证 */ }
})
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('for.heading') }}</h1>
    <p class="page-intro">{{ t('for.intro') }}</p>

    <div v-if="!isLoggedIn" class="card empty-state" style="margin-top:20px">
      <AppIcon name="user" :size="44" /><h3>{{ t('ent.needLogin') }}</h3>
    </div>

    <template v-else>
      <!-- 三步流程 -->
      <div class="steps" style="margin-top:20px">
        <span class="st" :class="{ cur: step === 1, done: step > 1 }"><b>1</b> {{ t('for.step1') }}</span><i></i>
        <span class="st" :class="{ cur: step === 2, done: step > 2 }"><b>2</b> {{ t('for.step2') }}</span><i></i>
        <span class="st" :class="{ cur: step === 3 }"><b>3</b> {{ t('for.step3') }}</span>
      </div>

      <div class="for-grid" style="margin-top:16px">
        <div class="card">
          <div class="card-heading"><AppIcon name="upload" :size="18" /><h3 class="card-title">{{ t('for.step1') }}</h3></div>
          <form class="for-form" @submit.prevent="submit">
            <label>{{ t('for.returnedImg') }}</label>
            <input type="file" accept="image/*" required @change="readFile(($event.target as HTMLInputElement).files?.[0], 'returned')" />
            <img v-if="returnedImg" :src="returnedImg" class="preview" alt="returned" />
            <label>{{ t('for.productImg') }}</label>
            <input type="file" accept="image/*" required @change="readFile(($event.target as HTMLInputElement).files?.[0], 'product')" />
            <img v-if="productImg" :src="productImg" class="preview" alt="product" />
            <label>{{ t('for.sku') }}</label>
            <input v-model="form.sku" type="text" />
            <label>{{ t('for.amount') }}</label>
            <input v-model.number="form.amount" type="number" step="0.01" />
            <label>{{ t('for.listing') }}</label>
            <textarea v-model="form.listing" rows="2" placeholder="如：全新未拆封，支持 30 天退换" />
            <label>{{ t('for.mode') }}</label>
            <select v-model="form.mode">
              <option value="mock">{{ t('for.modeMock') }}</option>
              <option value="live">{{ t('for.modeLive') }}</option>
            </select>
            <label>{{ t('for.platform') }}</label>
            <select v-model="form.platform">
              <option value="">{{ t('for.unspecified') }}</option>
              <option v-for="p in platforms" :key="p.key" :value="p.key">{{ p.label }}</option>
            </select>
            <label>{{ t('for.category') }}</label>
            <select v-model="form.category">
              <option value="">{{ t('for.unspecified') }}</option>
              <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
            </select>
            <label>{{ t('for.supplier') }}</label>
            <select v-model="form.supplier">
              <option value="">{{ t('for.unspecified') }}</option>
              <option v-for="s in suppliers" :key="s" :value="s">{{ s }}</option>
            </select>
            <button class="btn btn-primary field-block" type="submit" :disabled="busy">
              <span v-if="busy" class="spinner" aria-hidden="true" />
              {{ busy ? t('for.analyzing') : t('for.submit') }}
            </button>
          </form>
          <p v-if="error" class="err" style="margin-top:10px">{{ error }}</p>
        </div>

        <div class="card">
          <div class="card-heading"><AppIcon name="file" :size="18" /><h3 class="card-title">{{ t('for.resultTitle') }}</h3></div>
          <div v-if="result" class="result">
            <div class="mode-badge" :class="result.mode">{{ result.mode === 'live' ? 'AI 实算' : '演示模式（非 AI 结论）' }}</div>
            <div class="metric">
              <span>{{ t('for.similarity') }}</span><b>{{ pct(result.similarity) }}</b>
            </div>
            <div class="bar"><i :style="{ width: pct(result.similarity) }" /></div>
            <div class="kv"><span>{{ t('for.sameItem') }}</span><b>{{ result.same_item ? '疑似同款' : '疑似调包/非同款' }}</b></div>
            <div v-if="arr(result.defect_tags).length" class="kv"><span>{{ t('for.defects') }}</span><b>{{ arr(result.defect_tags).join('、') }}</b></div>
            <div v-if="result.consistency" class="kv"><span>{{ t('for.listing') }}</span><b>{{ result.consistency }}</b></div>
            <div class="kv"><span>{{ t('for.priority') }}</span><b>{{ (result.priority_score * 100).toFixed(0) }}</b></div>
            <div class="sub-label">{{ t('for.dossier') }}</div>
            <div class="dossier-head">
              <pre class="dossier">{{ result.dossier }}</pre>
              <button class="btn btn-ghost" type="button" @click="copyDossier">{{ t('for.copy') }}</button>
            </div>
            <div v-if="result.voice_text" class="sub-label">{{ t('for.voice') }}</div>
            <pre v-if="result.voice_text" class="dossier">{{ result.voice_text }}</pre>
            <div v-if="platformEvidence(result.platform_evidence).length" class="sub-label">{{ t('for.evidence') }} · {{ result.platform || '-' }}</div>
            <ul v-if="platformEvidence(result.platform_evidence).length" class="ev">
              <li v-for="(e, i) in platformEvidence(result.platform_evidence)" :key="i">
                <b>{{ e.name }}</b>{{ e.value ? '：' + e.value : '' }}
              </li>
            </ul>
            <div class="caps">
              <span>能力状态：</span>
              <span v-if="truthyCaps(result.capabilities).length" class="pill pill-success">
                真实：{{ truthyCaps(result.capabilities).join(' / ') }}
              </span>
              <span v-else class="pill">{{ t('for.modeMock') }}</span>
            </div>
            <div class="case-id">{{ result.case_id }}</div>
          </div>
          <div v-else class="empty-state" style="min-height:240px">
            <AppIcon name="search" :size="44" />
            <p>{{ t('for.resultEmpty') }}</p>
          </div>
        </div>
      </div>
      <p class="data-note">{{ t('footer.dataNote') }}</p>
    </template>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 780px; line-height: 1.6; }
.steps { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.st { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-sm); color: var(--text-muted); }
.st b { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--bg-inset); font-size: 11px; }
.st.cur { color: var(--accent); font-weight: 600; }
.st.cur b { background: var(--accent); color: #fff; }
.st.done b { background: var(--success-soft); color: var(--success); }
.steps i { width: 22px; height: 1px; background: var(--border-strong); }
.for-grid { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.2fr); gap: 16px; align-items: start; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.for-form { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; }
.for-form label { font-size: var(--fs-xs); color: var(--text-muted); margin-top: 8px; }
.for-form input, .for-form select, .for-form textarea {
  width: 100%; background: var(--bg-inset); border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm); padding: 9px 10px; font-size: var(--fs-sm);
}
.for-form .field-block { margin-top: 16px; }
.preview { width: 100%; max-height: 150px; object-fit: contain; border-radius: var(--r-sm); background: var(--bg-inset); margin-top: 6px; }
.result { margin-top: 14px; }
.mode-badge { display: inline-block; font-size: var(--fs-xs); padding: 3px 10px; border-radius: var(--r-pill); background: var(--bg-inset); color: var(--text-muted); }
.mode-badge.live { background: var(--success-soft); color: var(--success); }
.metric { display: flex; justify-content: space-between; margin-top: 16px; font-size: var(--fs-sm); }
.metric b { font-size: var(--fs-lg); }
.bar { height: 10px; border-radius: var(--r-pill); background: var(--bg-inset); overflow: hidden; margin-top: 6px; }
.bar i { display: block; height: 100%; background: var(--accent); border-radius: var(--r-pill); transition: width 500ms cubic-bezier(.32,.72,0,1); }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--fs-sm); }
.kv span { color: var(--text-muted); }
.kv b { font-weight: 600; text-align: right; }
.sub-label { font-size: var(--fs-xs); color: var(--text-muted); font-weight: 600; margin-top: 16px; }
.dossier-head { position: relative; }
.dossier { background: var(--bg-inset); border-radius: var(--r-sm); padding: 12px; font-size: var(--fs-xs); line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; margin-top: 6px; }
.dossier-head .btn { position: absolute; top: 10px; right: 10px; }
.ev { margin: 6px 0 0; padding-left: 18px; font-size: var(--fs-sm); color: var(--text-secondary); line-height: 1.7; }
.caps { display: flex; align-items: center; gap: 8px; margin-top: 16px; font-size: var(--fs-xs); color: var(--text-muted); flex-wrap: wrap; }
.case-id { margin-top: 14px; font-size: var(--fs-xs); color: var(--text-muted); font-variant-numeric: tabular-nums; }
.spinner { width: 14px; height: 14px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; display: inline-block; }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
@media (max-width: 900px) { .for-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .bar i { transition: none; } }
</style>
