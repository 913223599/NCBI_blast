<template>
  <div class="advanced-search-sidebar">
    <!-- 固定表头 -->
    <div class="sidebar-header">
      <div class="header-title">
        <h3>高级筛选器</h3>
        <div class="match-badge" v-if="stats">{{ stats.total }} 结果</div>
      </div>
      <button class="btn-close-circle" @click="emit('close')">✕</button>
    </div>

    <!-- 可滚动主体 -->
    <div class="sidebar-body scrollable-area">
      <!-- 质量控制区 -->
      <section class="compact-section pink-mode">
        <label class="section-label">质量监控</label>
        <div class="integrity-toggle" @click="toggleIntegrityCheck">
          <div class="toggle-track" :class="{ active: integrityOnly }">
            <span class="toggle-thumb"></span>
          </div>
          <span class="text">仅查缺失项</span>
        </div>
      </section>

      <!-- 核心搜索区 -->
      <div class="divider-text">筛选条件</div>
      <section class="main-filters">
        <div class="input-item">
          <label>关键字</label>
          <input type="search" v-model="filters.keyword" placeholder="搜索名称、备注..." @input="handleInput" />
        </div>

        <div class="input-item">
          <label>物种分类</label>
          <SpeciesTreeSelector 
            v-model="filters.species" 
            @change="handleInput"
          />
        </div>

        <div class="input-item">
          <label>长度范围 (bp)</label>
          <div class="range-inputs">
            <input type="number" v-model="filters.minLength" placeholder="Min" @input="handleInput" />
            <span class="sep">-</span>
            <input type="number" v-model="filters.maxLength" placeholder="Max" @input="handleInput" />
          </div>
        </div>

        <div class="input-item">
          <label>采集时间范围</label>
          <div class="date-inputs">
            <input type="date" v-model="filters.dateFrom" @change="handleInput" />
            <input type="date" v-model="filters.dateTo" @change="handleInput" />
          </div>
        </div>
      </section>

      <div class="divider-text">表格显示项</div>
      <!-- 平铺式列管理 -->
      <section class="column-visibility-grid">
        <label v-for="(visible, key) in columnVisibility" :key="key" class="col-check-label">
          <input type="checkbox" v-model="columnVisibility[String(key)]" @change="emit('updateColumns', columnVisibility)" />
          <span>{{ getColumnLabel(String(key)) }}</span>
        </label>
      </section>
    </div>

    <!-- 固定底部操作 -->
    <div class="sidebar-footer">
      <button class="btn-action-primary" @click="handleExportFiltered" :disabled="!stats || stats.total === 0">
        导出当前结果 ({{ stats?.total || 0 }})
      </button>
      <button class="btn-action-ghost" @click="resetFilters">全部重置</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive } from 'vue'
import { useStrainStore } from '../../../stores/strain'
import { useAppStore } from '../../../stores/app'
import SpeciesTreeSelector from '../SpeciesTreeSelector.vue'
import { useCodeGenerator } from '../../../composables/useCodeGenerator'

const props = defineProps<{
  stats: { total: number } | null,
  initialColumns: Record<string, boolean>
}>()

const emit = defineEmits(['close', 'updateColumns'])

const strainStore = useStrainStore()
const appStore = useAppStore()
const filters = strainStore.searchFilters as any

const uniqueSpecies = computed(() => strainStore.uniqueSpecies)
const columnVisibility = reactive<Record<string, boolean>>({ ...props.initialColumns })

// 将编码对照表路径转换为显示名称的辅助函数
function speciesPathToDisplayName(fullPath: string): string {
  if (!fullPath) return ''
  // 尝试从对照表中获取名称
  const { lookup } = useCodeGenerator()
  const entry = lookup.findByFullPath(fullPath)
  if (entry) {
    let label = entry.name
    if (entry.latinName) {
      label += ` (${entry.latinName})`
    }
    return label
  }
  // 如果找不到，直接返回原值（兼容旧数据）
  return fullPath
}

const integrityOnly = ref(false)
function toggleIntegrityCheck() {
  integrityOnly.value = !integrityOnly.value
  filters.integrityOnly = integrityOnly.value
  strainStore.applyFilters()
}

let timer: number | null = null
function handleInput() {
  if (timer) clearTimeout(timer)
  timer = window.setTimeout(() => strainStore.applyFilters(), 300)
}

function resetFilters() {
  integrityOnly.value = false
  filters.integrityOnly = false
  filters.minLength = null
  filters.maxLength = null
  strainStore.resetFilters()
}

function getColumnLabel(key: string | number): string {
  const k = String(key)
  const labels: Record<string, string> = { accession: '登录号', species: '物种', strain: '菌株', sequenceType: '类型', source: '来源', host: '宿主', country: '地区', collectionDate: '采集时间', addedAt: '录入时间', location: '位置' }
  return labels[k] || k
}

function handleExportFiltered() {
  const content = strainStore.exportSelected('csv')
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.setAttribute('href', URL.createObjectURL(blob))
  link.setAttribute('download', 'Result_Filtered.csv')
  link.click()
  appStore.showNotification('已导出符合条件的全部数据', 'success')
}
</script>

<style scoped>
.advanced-search-sidebar {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: white;
}

.sidebar-header {
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px solid #f1f5f9;
}

.header-title h3 { font-size: 0.95rem; font-weight: 800; color: #1e293b; margin: 0; }
.match-badge { font-size: 0.7rem; color: #2563eb; font-weight: 800; background: #eff6ff; padding: 2px 8px; border-radius: 20px; margin-top: 4px; display: inline-block; width: fit-content; }

.btn-close-circle { width: 24px; height: 24px; border-radius: 50%; border: none; background: #f1f5f9; color: #64748b; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 0.8rem; }

.scrollable-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 滚动条美化 */
.scrollable-area::-webkit-scrollbar { width: 5px; }
.scrollable-area::-webkit-scrollbar-track { background: transparent; }
.scrollable-area::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 3px; }

.compact-section { padding: 12px; border-radius: 10px; }
.pink-mode { background: #fdf2f8; border: 1px solid #fce7f3; }
.section-label { font-size: 0.65rem; font-weight: 800; color: #db2777; text-transform: uppercase; margin-bottom: 8px; display: block; }

.integrity-toggle { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.toggle-track { width: 32px; height: 18px; background: #cbd5e1; border-radius: 10px; position: relative; transition: all 0.2s; }
.toggle-track.active { background: #db2777; }
.toggle-thumb { width: 14px; height: 14px; background: white; border-radius: 50%; position: absolute; top: 2px; left: 2px; transition: 0.2s; }
.toggle-track.active .toggle-thumb { transform: translateX(14px); }
.integrity-toggle .text { font-size: 0.8rem; font-weight: 700; color: #db2777; }

.divider-text { font-size: 0.7rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; }

.main-filters { display: flex; flex-direction: column; gap: 16px; }
.input-item { display: flex; flex-direction: column; gap: 5px; }
.input-item label { font-size: 0.7rem; font-weight: 800; color: #475569; }
.input-item input, .input-item select { padding: 10px; border: 1.5px solid #e2e8f0; border-radius: 8px; font-size: 0.85rem; background: #f8fafc; transition: all 0.2s; }
.input-item input:focus { border-color: #2563eb; background: white; outline: none; }

.range-inputs, .date-inputs { display: flex; align-items: center; gap: 8px; }
.range-inputs input, .date-inputs input { flex: 1; min-width: 0; }
.sep { color: #cbd5e1; }

.column-visibility-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.col-check-label { display: flex; align-items: center; gap: 8px; font-size: 0.75rem; font-weight: 600; color: #1e293b; cursor: pointer; }

.sidebar-footer { padding: 16px; border-top: 1px solid #f1f5f9; background: white; display: flex; flex-direction: column; gap: 10px; }
.btn-action-primary { width: 100%; padding: 12px; background: #2563eb; color: white; border: none; border-radius: 10px; font-size: 0.85rem; font-weight: 800; cursor: pointer; box-shadow: 0 4px 6px -1px rgba(37,99,235,0.2); }
.btn-action-ghost { width: 100%; padding: 10px; background: none; border: 1px solid #e2e8f0; color: #64748b; border-radius: 10px; font-size: 0.8rem; font-weight: 600; cursor: pointer; }
.btn-action-primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
