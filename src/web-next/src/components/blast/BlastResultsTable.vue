<script setup lang="ts">
import { computed } from 'vue'
import { useBlastStore } from '../../stores/blast'
import { useAppStore } from '../../stores/app'
import { useStrainStore } from '../../stores/strain'
import { useRouter } from 'vue-router'
import { getBridge } from '../../bridge'
import { useI18n } from '../../locales'
import TranslateSplicer from '../common/TranslateSplicer.vue'

const props = defineProps<{
  isTranslating: boolean
}>()

const emit = defineEmits<{
  (e: 'viewAllHits', csvFile: string, queryTitle: string): void
  (e: 'showAlignmentMap', hit: any): void
  (e: 'translateAll'): void
  (e: 'exportResults'): void
}>()

const blast = useBlastStore()
const appStore = useAppStore()
const strainStore = useStrainStore()
const router = useRouter()
const { t } = useI18n()

/**
 * 翻译切换逻辑
 */
const hasActiveTranslation = computed(() => {
  // 只有当有任意一项真正展示了译文时，才认为当前是“翻译状态”
  return blast.results.some(h => h.translatedName && h.showOriginal === false)
})

function toggleTranslateAll() {
  const isCurrentlyShowingTranslation = hasActiveTranslation.value
  
  if (isCurrentlyShowingTranslation) {
    // 切换回原文：让所有具有译文的项都强制显示原文
    blast.results.forEach(h => {
      if (h.translatedName) h.showOriginal = true
    })
  } else {
    // 准备显示译文
    const untranslatedItems = blast.results.filter(h => h.speciesName && h.speciesName !== 'Unknown' && !h.translatedName)
    
    // 如果存在尚未翻译的有效条目，触发批量翻译补充剩余部分
    if (untranslatedItems.length > 0) {
      emit('translateAll')
    }
    
    // 把已有译文的全部拉出来显示
    blast.results.forEach(h => {
      if (h.translatedName) h.showOriginal = false
    })
  }
}

function handleRowTranslate(h: any) {
  if (h.translatedName) {
    // 已经有翻译了，单纯在这两条之间切换
    h.showOriginal = h.showOriginal === false ? true : false
  } else if (h.speciesName && h.speciesName !== 'Unknown' && !h.isTranslating) {
    // 按需发起单条翻译
    h.isTranslating = true
    getBridge().translate_text?.(h.speciesName, 'species', (translated: string) => {
      h.isTranslating = false
      if (translated && translated !== h.speciesName) {
        // 使用 replace 替换掉原文中的这一项，保留百分比等格式
        const base = h.speciesName
        if (base.includes(h.speciesName)) { // 若是拼接结构则安全替换
           h.translatedName = base.replace(h.speciesName, translated)
        } else {
           h.translatedName = translated
        }
        h.showOriginal = false
      }
    })
  }
}

/**
 * 样本一键入库
 */
function saveToStore(hit: any) {
  // 核心工具：提取首选共识项，去除百分比和后续候选项
  const getTopItem = (s: any = '') => {
    const str = String(s || '')
    const firstPart = str.split(',')[0] || ''
    const secondPart = firstPart.split('(')[0] || ''
    const thirdPart = secondPart.split(';')[0] || ''
    return thirdPart.trim()
  }

  const topTranslated = getTopItem(hit.translatedName || '')
  const topOriginal = getTopItem(hit.speciesName || '')
  
  const hasTranslation = topTranslated && topTranslated !== topOriginal
  const splicedName = hasTranslation 
    ? `${topTranslated} (${topOriginal})` 
    : (topOriginal || hit.queryTitle)

  const draftRecord = {
    name: splicedName,
    species: splicedName,
    accession: hit.accession,
    strain: hit.genusStrain,
    sequence: hit.rawSequence || '', 
    metadata: {
      blast_identity: hit.identity,
      blast_evalue: hit.evalue,
      blast_task_id: blast.activeTaskId,
      blast_hit_title: hit.hitTitle,
      original_query_id: hit.queryTitle,
      full_identification: hit.translatedName
    }
  }

  strainStore.setPendingBlastDraft(draftRecord)
  router.push('/strain')
  appStore.showNotification(t('blast.notify.draft_saved'), 'success')
}

function openNcbi(accession: string): void {
  if (!accession || accession === '-' || accession === 'N/A') {
    appStore.showNotification(t('blast.notify.no_accession'), 'warning')
    return
  }
  const url = `https://www.ncbi.nlm.nih.gov/nuccore/${accession}`
  try {
    getBridge().open_external_url(url)
  } catch (e) {
    window.open(url, '_blank')
  }
}
</script>

<template>
  <div class="blast-results-container">
    <div class="results-header">
      <div class="title">📊 {{ blast.resultTitle }}</div>
      <div class="actions">
        <button class="btn-ai" @click="toggleTranslateAll" :disabled="isTranslating">
          {{ hasActiveTranslation ? '↩️ ' + t('label_source_en') : t('blast.btn.trans') }}
        </button>
        <button class="btn-export" @click="emit('exportResults')">{{ t('blast.btn.export') }}</button>
      </div>
    </div>
    <div class="table-wrapper scroll-v">
      <table v-if="blast.results.length > 0">
        <thead>
          <tr>
            <th>{{ t('blast.res.query') }}</th>
            <th>{{ t('blast.res.detail') }}</th>
            <th>{{ t('blast.res.id') }}</th>
            <th>{{ t('blast.res.eval') }}</th>
            <th>NCBI</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in blast.results" :key="h.accession" class="blast-row-neo" :class="{ 'translating-pulse': h.isTranslating }">
            <td class="mono">{{ h.queryTitle }}</td>
            <td class="detail-cell-neo" @click="handleRowTranslate(h)">
              <div class="sp">
                <TranslateSplicer :original="h.speciesName" :translated="h.translatedName" :showOriginal="h.showOriginal" />
              </div>
              <div class="st">{{ h.genusStrain }}</div>
              <div class="gs">{{ h.geneSource }}</div>
              <div v-if="h.csvFile" class="view-all-link" @click.stop="emit('viewAllHits', h.csvFile, h.queryTitle)">
                {{ t('blast.res.view_all') }} ({{ h.csvFile ? '更多' : '0' }}) →
              </div>
            </td>
            <td>
              <div class="id-val" :class="h.identity >= 97 ? 'high-id' : 'low-id'">
                {{ h.identity.toFixed(1) }}%
              </div>
            </td>
            <td class="mono">{{ h.evalue }}</td>
            <td>
              <button 
                v-if="h.accession && h.accession !== '-' && h.accession !== 'N/A'" 
                class="link-btn" 
                @click="openNcbi(h.accession)"
                title="NCBI"
              >🔗</button>
              <span v-else class="no-link">-</span>
            </td>
            <td>
              <button class="btn-action-vis" @click="emit('showAlignmentMap', h)">📊 {{ t('blast.btn.vis') }}</button>
              <button class="btn-action-save" @click="saveToStore(h)">📥 {{ t('blast.btn.save') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-hint">
        <div class="icon">🧬</div>
        <p>{{ t('blast.hist.empty') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.blast-results-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  overflow: hidden;
}
.results-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}
.results-header .title { font-weight: 700; color: #1e293b; }
.results-header .actions { display: flex; gap: 10px; }

.table-wrapper { flex: 1; overflow: auto; padding: 20px; }
table { width: 100%; border-collapse: separate; border-spacing: 0; }
th { text-align: left; padding: 12px 16px; background: #f8fafc; color: #64748b; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; border-bottom: 1px solid #e2e8f0; }
td { padding: 16px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }

.blast-row-neo:hover { background: #f8fafc; }
.mono { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8rem; color: #475569; }

.detail-cell-neo .sp { font-weight: 700; color: #111827; margin-bottom: 4px; }
.detail-cell-neo .st { font-size: 0.8rem; color: #2563eb; margin-bottom: 2px; }
.detail-cell-neo .gs { font-size: 0.75rem; color: #64748b; }
.view-all-link { margin-top: 8px; font-size: 0.75rem; color: #2563eb; cursor: pointer; font-weight: 600; }
.view-all-link:hover { text-decoration: underline; }

.id-val { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.95rem; }
.high-id { color: #059669; }
.low-id { color: #ea580c; }

.link-btn { background: #f1f5f9; border: none; padding: 6px; border-radius: 6px; cursor: pointer; transition: background 0.2s; }
.link-btn:hover { background: #e2e8f0; }

.btn-action-vis, .btn-action-save { border: none; border-radius: 6px; padding: 6px 12px; font-size: 0.75rem; font-weight: 600; cursor: pointer; margin-right: 6px; transition: transform 0.1s; }
.btn-action-vis { background: #eff6ff; color: #2563eb; }
.btn-action-save { background: #ecfdf5; color: #059669; }
.btn-action-vis:active, .btn-action-save:active { transform: scale(0.95); }

.empty-hint { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px; color: #94a3b8; }
.empty-hint .icon { font-size: 3rem; margin-bottom: 16px; opacity: 0.3; }

.btn-ai, .btn-export { padding: 8px 16px; border-radius: 8px; font-size: 0.8rem; font-weight: 600; cursor: pointer; border: 1px solid #e2e8f0; transition: all 0.2s; }
.btn-ai { background: linear-gradient(135deg, #2563eb, #7c3aed); color: white; border: none; }
.btn-ai:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-export { background: white; color: #475569; }
.btn-export:hover { background: #f8fafc; border-color: #cbd5e1; }

@keyframes pulse-opacity {
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
}
.translating-pulse { animation: pulse-opacity 1.5s infinite; pointer-events: none; }
</style>
