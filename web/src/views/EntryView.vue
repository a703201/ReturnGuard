<script setup lang="ts">
/**
 * 数据录入：手动录入一条案件（真实写入当前租户 + 落库），并展示最近案件。
 * 文件导入：后端未提供批量导入端点，此处诚实提示，不伪装成功。
 */
import { ref, reactive, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { t } from '../i18n'
import { apiGet, apiPost, apiDelete } from '../api/client'
import { isLoggedIn } from '../composables/useAuth'

interface CaseRow {
  case_id: string; sku: string; category: string; supplier: string
  platform: string; region: string; season: string
  amount: number; similarity: number; outcome: string; defect: string
}
const rows = ref<CaseRow[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const okMsg = ref('')
const importFile = ref<File | null>(null)
const form = reactive({
  sku: '', category: '', supplier: '', platform: '',
  region: '', season: '', amount: 0, similarity: 0.8, outcome: '待分析', defect: '',
})

async function load() {
  if (!isLoggedIn.value) { rows.value = []; return }
  loading.value = true
  error.value = ''
  try {
    const d = await apiGet<{ total: number; cases: CaseRow[] }>('cases')
    rows.value = d?.cases || []
    total.value = d?.total || 0
  } catch (e) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function add() {
  if (!form.sku.trim()) { error.value = t('ent.sku'); return }
  saving.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const r = await apiPost<{ ok: boolean; case_id: string }>('cases', { ...form })
    if (r?.ok) {
      okMsg.value = r.case_id
      form.sku = ''; form.category = ''; form.supplier = ''
      form.amount = 0; form.defect = ''
      await load()
    }
  } catch (e) {
    error.value = (e as Error).message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function removeCase(c: CaseRow) {
  if (!window.confirm(`${t('ent.confirmDelete')} ${c.sku} (${c.case_id})?`)) return
  error.value = ''
  okMsg.value = ''
  try {
    await apiDelete(`cases/${encodeURIComponent(c.case_id)}`)
    okMsg.value = c.case_id
    await load()
  } catch (e) {
    error.value = (e as Error).message || '删除失败'
  }
}

function onFile(e: Event) {
  importFile.value = (e.target as HTMLInputElement).files?.[0] || null
}

async function importCsv() {
  const f = importFile.value
  if (!f) { error.value = t('ent.file'); return }
  if (!f.name.toLowerCase().endsWith('.csv')) {
    error.value = 'XLSX 需先另存为 CSV（后端未内置 ZIP/XML 解析，不伪装成功）'
    return
  }
  saving.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const text = await f.text()
    const r = await apiPost<{ ok: boolean; imported: number; skipped: number; errors: string[] }>(
      'cases/import', { csv: text, source: 'csv' })
    okMsg.value = `${t('ent.imported')}: ${r.imported} · ${t('ent.skipped')}: ${r.skipped}`
    importFile.value = null
    await load()
  } catch (e) {
    error.value = (e as Error).message || '导入失败'
  } finally {
    saving.value = false
  }
}
function money(v: number) { return '¥' + Number(v || 0).toLocaleString('zh-CN') }

onMounted(() => { void load() })
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t('ent.heading') }}</h1>
    <p class="page-intro">{{ t('ent.intro') }}</p>

    <div v-if="!isLoggedIn" class="card empty-state" style="margin-top:20px">
      <AppIcon name="user" :size="44" /><h3>{{ t('ent.needLogin') }}</h3>
    </div>

    <template v-else>
      <div class="ent-grid" style="margin-top:20px">
        <!-- 手动录入（真实写入） -->
        <div class="card">
          <div class="card-heading"><AppIcon name="file" :size="18" /><h3 class="card-title">{{ t('ent.manual') }}</h3></div>
          <form class="ent-form" @submit.prevent="add">
            <label>{{ t('ent.sku') }} *</label>
            <input v-model="form.sku" type="text" required />
            <div class="two">
              <div><label>{{ t('ent.category') }}</label><input v-model="form.category" type="text" /></div>
              <div><label>{{ t('ent.supplier') }}</label><input v-model="form.supplier" type="text" /></div>
            </div>
            <div class="two">
              <div><label>{{ t('ent.platform') }}</label><input v-model="form.platform" type="text" /></div>
              <div><label>{{ t('ent.region') }}</label><input v-model="form.region" type="text" /></div>
            </div>
            <div class="two">
              <div><label>{{ t('ent.season') }}</label><input v-model="form.season" type="text" /></div>
              <div><label>{{ t('ent.amount') }}</label><input v-model.number="form.amount" type="number" step="0.01" /></div>
            </div>
            <div class="two">
              <div><label>{{ t('ent.similarity') }}</label><input v-model.number="form.similarity" type="number" step="0.01" min="0" max="1" /></div>
              <div><label>{{ t('ent.outcome') }}</label>
                <select v-model="form.outcome">
                  <option>待分析</option><option>赢</option><option>部分退款</option><option>输</option>
                </select>
              </div>
            </div>
            <label>{{ t('ent.defect') }}</label>
            <input v-model="form.defect" type="text" />
            <button class="btn btn-primary field-block" type="submit" :disabled="saving">{{ t('ent.add') }}</button>
          </form>
          <p v-if="okMsg" class="ok">✓ {{ okMsg }}</p>
          <p v-if="error" class="err" style="margin-top:10px">{{ error }}</p>
        </div>

        <!-- 文件导入：CSV 真实导入，XLSX 如实提示需另存为 -->
        <div class="card">
          <div class="card-heading"><AppIcon name="upload" :size="18" /><h3 class="card-title">{{ t('ent.import') }}</h3></div>
          <div class="import-zone">
            <AppIcon name="upload" :size="32" />
            <p>{{ t('ent.file') }}</p>
            <input type="file" accept=".csv" @change="onFile" />
            <p v-if="importFile" class="chosen">{{ importFile.name }}</p>
            <button class="btn btn-secondary" type="button" :disabled="saving || !importFile" @click="importCsv">
              {{ saving ? t('dash.loading') : t('ent.upload') }}
            </button>
            <p class="hint">{{ t('ent.uploadHint') }}</p>
          </div>
        </div>
      </div>

      <!-- 最近案件 -->
      <div class="card" style="margin-top:16px">
        <div class="card-heading">
          <AppIcon name="inbox" :size="18" /><h3 class="card-title">{{ t('ent.recent') }}</h3>
          <span class="pill">{{ total }}</span>
        </div>
        <div v-if="loading" class="empty-state"><span class="spinner" aria-hidden="true" /></div>
        <div v-else-if="!rows.length" class="empty-state"><p>{{ t('ent.noData') }}</p></div>
        <div v-else class="table-scroll">
          <table class="case-table">
            <thead><tr>
              <th>SKU</th><th>{{ t('ent.category') }}</th><th>{{ t('ent.supplier') }}</th>
              <th>{{ t('ent.platform') }}</th><th>{{ t('ent.amount') }}</th>
              <th>{{ t('ent.similarity') }}</th><th>{{ t('ent.outcome') }}</th><th>{{ t('ent.defect') }}</th>
              <th>{{ t('action.delete') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="c in rows" :key="c.case_id">
                <td>{{ c.sku }}</td><td>{{ c.category || '-' }}</td><td>{{ c.supplier || '-' }}</td>
                <td>{{ c.platform || '-' }}</td><td>{{ money(c.amount) }}</td>
                <td>{{ c.similarity.toFixed(2) }}</td><td>{{ c.outcome }}</td><td>{{ c.defect || '-' }}</td>
                <td><button class="btn btn-ghost row-del" type="button" :aria-label="t('action.delete')" @click="removeCase(c)">
                  <AppIcon name="close" :size="15" />
                </button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p class="data-note">{{ t('footer.dataNote') }}</p>
    </template>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
.page-intro { color: var(--text-secondary); margin-top: 8px; max-width: 780px; line-height: 1.6; }
.ent-grid { display: grid; grid-template-columns: minmax(340px, 1.3fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
.card-heading { display: flex; align-items: center; gap: 10px; color: var(--accent); }
.card-heading .card-title { color: var(--text-primary); }
.ent-form { display: flex; flex-direction: column; gap: 5px; margin-top: 14px; }
.ent-form label { font-size: var(--fs-xs); color: var(--text-muted); margin-top: 7px; }
.ent-form input, .ent-form select {
  width: 100%; background: var(--bg-inset); border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm); padding: 9px 10px; font-size: var(--fs-sm);
}
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.field-block { margin-top: 16px; }
.ok { color: var(--success); font-size: var(--fs-sm); margin-top: 10px; }
.import-zone { display: flex; flex-direction: column; align-items: center; gap: 10px; margin-top: 18px; padding: 24px 16px; border: 1px dashed var(--border-strong); border-radius: var(--r-md); color: var(--text-muted); text-align: center; }
.import-zone input { font-size: var(--fs-sm); max-width: 100%; }
.chosen { color: var(--text-primary); font-size: var(--fs-sm); }
.hint { font-size: var(--fs-xs); line-height: 1.6; }
.table-scroll { overflow-x: auto; margin-top: 14px; }
.case-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); min-width: 720px; }
.case-table th, .case-table td { border-bottom: 1px solid var(--border-subtle); padding: 9px 10px; text-align: left; white-space: nowrap; }
.case-table th { color: var(--text-muted); font-weight: 600; font-size: var(--fs-xs); }
.case-table tbody tr:hover { background: var(--bg-inset); }
.row-del { padding: 4px 8px; min-height: 0; color: var(--text-muted); }
.row-del:hover { color: var(--bad, #ff3b30); background: var(--bg-inset); }
.spinner { width: 22px; height: 22px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: rg-spin 900ms linear infinite; }
.data-note { color: var(--text-muted); font-size: var(--fs-xs); margin-top: 24px; }
@media (max-width: 900px) { .ent-grid { grid-template-columns: 1fr; } }
</style>
