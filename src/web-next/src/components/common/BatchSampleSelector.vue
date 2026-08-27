<script setup lang="ts">
import { ref, computed } from 'vue'

export interface BatchSampleItem {
  sample_id: string
  sample_name: string
  source_type: 'task' | 'external_file' | string
  task_id?: string
  file_path?: string
  file_type?: string
  cds_count?: number
  annotated_count?: number
  sample_type?: string
}

interface Props {
  modelValue: BatchSampleItem[]
  availableSamples: BatchSampleItem[]
  identityThreshold?: number
  showThreshold?: boolean
  isRunning?: boolean
  runButtonText?: string
  minSelection?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: () => [],
  availableSamples: () => [],
  identityThreshold: 0.5,
  showThreshold: true,
  isRunning: false,
  runButtonText: '开始全景分析',
  minSelection: 2
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: BatchSampleItem[]): void
  (e: 'update:identityThreshold', value: number): void
  (e: 'import'): void
  (e: 'run'): void
}>()

// 状态管理
const searchQuery = ref('')
const selectedCategory = ref<string>('all')
const sortBy = ref<'default' | 'name' | 'cds_desc'>('default')
const isSelectedExpanded = ref(false)
const showModalSelector = ref(false)

// 模态框临时选中项
const modalSelectedIds = ref<Set<string>>(new Set())

// 已选 ID 集合用于极速比对
const selectedIdSet = computed(() => {
  return new Set(props.modelValue.map(s => s.sample_id))
})

// 分类与统计
const categoryStats = computed(() => {
  let phageCount = 0
  let hostCount = 0
  let extCount = 0

  for (const s of props.availableSamples) {
    const isExt = s.source_type === 'external_file' || s.sample_id.startsWith('EXT_')
    const t = (s.sample_type || '').toUpperCase()
    if (isExt) {
      extCount++
    } else if (t.includes('PHAGE') || t.includes('噬菌体') || s.sample_name.toLowerCase().includes('phage')) {
      phageCount++
    } else {
      hostCount++
    }
  }

  return {
    all: props.availableSamples.length,
    phage: phageCount,
    host: hostCount,
    ext: extCount
  }
})

// 过滤与排序后的样本列表
const filteredSamples = computed(() => {
  let list = [...props.availableSamples]

  // 1. 分类筛选
  if (selectedCategory.value === 'phage') {
    list = list.filter(s => {
      const isExt = s.source_type === 'external_file' || s.sample_id.startsWith('EXT_')
      const t = (s.sample_type || '').toUpperCase()
      return !isExt && (t.includes('PHAGE') || t.includes('噬菌体') || s.sample_name.toLowerCase().includes('phage'))
    })
  } else if (selectedCategory.value === 'host') {
    list = list.filter(s => {
      const isExt = s.source_type === 'external_file' || s.sample_id.startsWith('EXT_')
      const t = (s.sample_type || '').toUpperCase()
      return !isExt && !(t.includes('PHAGE') || t.includes('噬菌体') || s.sample_name.toLowerCase().includes('phage'))
    })
  } else if (selectedCategory.value === 'ext') {
    list = list.filter(s => s.source_type === 'external_file' || s.sample_id.startsWith('EXT_'))
  }

  // 2. 搜索关键词
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(s => {
      const matchName = s.sample_name.toLowerCase().includes(q)
      const matchId = s.sample_id.toLowerCase().includes(q)
      const matchCds = s.cds_count !== undefined && String(s.cds_count).includes(q)
      return matchName || matchId || matchCds
    })
  }

  // 3. 排序
  if (sortBy.value === 'name') {
    list.sort((a, b) => a.sample_name.localeCompare(b.sample_name, 'zh-Hans-CN', { numeric: true }))
  } else if (sortBy.value === 'cds_desc') {
    list.sort((a, b) => (b.cds_count || 0) - (a.cds_count || 0))
  }

  return list
})

// 单项勾选/取消
function toggleSample(sample: BatchSampleItem) {
  const current = [...props.modelValue]
  const idx = current.findIndex(s => s.sample_id === sample.sample_id)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    current.push(sample)
  }
  emit('update:modelValue', current)
}

function removeSelected(sampleId: string) {
  const next = props.modelValue.filter(s => s.sample_id !== sampleId)
  emit('update:modelValue', next)
}

// 批量操作：全选当前筛选结果
function selectAllFiltered() {
  const currentMap = new Map(props.modelValue.map(s => [s.sample_id, s]))
  for (const s of filteredSamples.value) {
    currentMap.set(s.sample_id, s)
  }
  emit('update:modelValue', Array.from(currentMap.values()))
}

// 批量操作：反选当前筛选结果
function invertFiltered() {
  const currentMap = new Map(props.modelValue.map(s => [s.sample_id, s]))
  for (const s of filteredSamples.value) {
    if (currentMap.has(s.sample_id)) {
      currentMap.delete(s.sample_id)
    } else {
      currentMap.set(s.sample_id, s)
    }
  }
  emit('update:modelValue', Array.from(currentMap.values()))
}

// 批量操作：清空全部已选
function clearAllSelected() {
  emit('update:modelValue', [])
}

// 模态选择器
function openModalSelector() {
  modalSelectedIds.value = new Set(props.modelValue.map(s => s.sample_id))
  showModalSelector.value = true
}

function toggleModalSample(id: string) {
  if (modalSelectedIds.value.has(id)) {
    modalSelectedIds.value.delete(id)
  } else {
    modalSelectedIds.value.add(id)
  }
}

function applyModalSelection() {
  const next: BatchSampleItem[] = []
  for (const s of props.availableSamples) {
    if (modalSelectedIds.value.has(s.sample_id)) {
      next.push(s)
    }
  }
  emit('update:modelValue', next)
  showModalSelector.value = false
}

function modalSelectAll() {
  for (const s of filteredSamples.value) {
    modalSelectedIds.value.add(s.sample_id)
  }
}

function modalClearAll() {
  modalSelectedIds.value.clear()
}
</script>

<template>
  <div class="batch-sample-selector">
    <!-- 1. 顶部控制行：已选摘要、阈值、外部导入与分析按钮 -->
    <div class="control-header-row">
      <div class="header-left-stat">
        <span class="stat-badge">
          已选样本: <strong>{{ modelValue.length }}</strong> / {{ availableSamples.length }}
        </span>
        
        <!-- 同源聚类阈值调节 -->
        <div class="threshold-field" v-if="showThreshold">
          <label class="threshold-label">同源聚类阈值:</label>
          <select 
            :value="identityThreshold" 
            @change="e => emit('update:identityThreshold', parseFloat((e.target as HTMLSelectElement).value))"
            class="threshold-select"
          >
            <option :value="0.3">30% (远源/结构域)</option>
            <option :value="0.5">50% (标准同源推荐)</option>
            <option :value="0.7">70% (中高同源)</option>
            <option :value="0.9">90% (近源亚型)</option>
          </select>
        </div>
      </div>

      <div class="header-right-actions">
        <button type="button" class="btn-import-ext" @click="emit('import')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导入外部文件 (GBK/FAA)
        </button>

        <button 
          type="button" 
          class="btn-run-action" 
          :disabled="isRunning || modelValue.length < minSelection" 
          @click="emit('run')"
        >
          <svg v-if="!isRunning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          <span v-if="isRunning" class="spinner-dot"></span>
          {{ isRunning ? '正在全景聚类计算中...' : `${runButtonText} (${modelValue.length} 样本)` }}
        </button>
      </div>
    </div>

    <!-- 2. 已选样本托盘 (Selected Tray) -->
    <div class="selected-tray-card" v-if="modelValue.length > 0">
      <div class="tray-header">
        <div class="tray-title-group">
          <span class="tray-title">已选分析清单 ({{ modelValue.length }})</span>
          <button 
            v-if="modelValue.length > 8" 
            type="button" 
            class="btn-toggle-expand" 
            @click="isSelectedExpanded = !isSelectedExpanded"
          >
            {{ isSelectedExpanded ? '收起列表 ▲' : '展开全部 ▼' }}
          </button>
        </div>
        <button type="button" class="btn-clear-tray" @click="clearAllSelected">
          清空已选
        </button>
      </div>

      <div class="selected-chips-box" :class="{ 'is-collapsed': !isSelectedExpanded && modelValue.length > 8 }">
        <div 
          v-for="s in modelValue" 
          :key="s.sample_id" 
          class="selected-item-chip"
          :title="`${s.sample_name} (${s.cds_count || 0} CDS)`"
        >
          <span class="chip-dot"></span>
          <span class="chip-name">{{ s.sample_name }}</span>
          <span class="chip-cds" v-if="s.cds_count !== undefined">{{ s.cds_count }} CDS</span>
          <button type="button" class="btn-remove-chip" @click="removeSelected(s.sample_id)">&times;</button>
        </div>
      </div>
    </div>
    <div v-else class="empty-tray-tip">
      <span>💡 暂未勾选样本，请在下方检索并挑选至少 {{ minSelection }} 个样本进行全景对比</span>
    </div>

    <!-- 3. 历史样本库挑选控制台 (Available Pool Workspace) -->
    <div class="available-pool-workspace">
      <!-- 过滤与批量操作工具栏 -->
      <div class="pool-toolbar">
        <div class="search-and-filter">
          <!-- 搜索框 -->
          <div class="search-input-box">
            <svg class="icon-search" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input 
              v-model="searchQuery" 
              type="text" 
              placeholder="搜索样本名称 / ID / CDS 数量..." 
              class="pool-search-input"
            />
            <button v-if="searchQuery" class="btn-clear-search" @click="searchQuery = ''">&times;</button>
          </div>

          <!-- 分类筛选器 -->
          <div class="category-filter-tabs">
            <button 
              type="button" 
              class="cat-tab" 
              :class="{ active: selectedCategory === 'all' }" 
              @click="selectedCategory = 'all'"
            >
              全部 ({{ categoryStats.all }})
            </button>
            <button 
              v-if="categoryStats.phage > 0"
              type="button" 
              class="cat-tab" 
              :class="{ active: selectedCategory === 'phage' }" 
              @click="selectedCategory = 'phage'"
            >
              噬菌体 ({{ categoryStats.phage }})
            </button>
            <button 
              v-if="categoryStats.host > 0"
              type="button" 
              class="cat-tab" 
              :class="{ active: selectedCategory === 'host' }" 
              @click="selectedCategory = 'host'"
            >
              宿主/细菌 ({{ categoryStats.host }})
            </button>
            <button 
              v-if="categoryStats.ext > 0"
              type="button" 
              class="cat-tab" 
              :class="{ active: selectedCategory === 'ext' }" 
              @click="selectedCategory = 'ext'"
            >
              外部导入 ({{ categoryStats.ext }})
            </button>
          </div>
        </div>

        <!-- 批量动作与排序 -->
        <div class="batch-action-bar">
          <div class="batch-btns">
            <button type="button" class="btn-batch" @click="selectAllFiltered" title="全选当前筛选结果">
              全选 ({{ filteredSamples.length }})
            </button>
            <button type="button" class="btn-batch" @click="invertFiltered" title="反选当前筛选列表">
              反选
            </button>
            <button type="button" class="btn-batch modal-trigger" @click="openModalSelector" title="打开高级大表穿梭挑选器">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </svg>
              高级挑选器
            </button>
          </div>

          <div class="sort-selector">
            <select v-model="sortBy" class="select-sort">
              <option value="default">默认排序</option>
              <option value="name">按名称 (A-Z)</option>
              <option value="cds_desc">按 CDS 数量 (高到低)</option>
            </select>
          </div>
        </div>
      </div>

      <!-- 样本胶囊标签滚动池 (固定限高，优雅滚动) -->
      <div class="samples-scroll-pool">
        <div 
          v-for="s in filteredSamples" 
          :key="s.sample_id" 
          :class="['pool-chip', { selected: selectedIdSet.has(s.sample_id) }]"
          @click="toggleSample(s)"
          :title="`${s.sample_name}\nID: ${s.sample_id}\nCDS: ${s.cds_count || 0}`"
        >
          <span class="chip-check">{{ selectedIdSet.has(s.sample_id) ? '✓' : '+' }}</span>
          <span class="chip-name">{{ s.sample_name }}</span>
          <span class="chip-cds" v-if="s.cds_count !== undefined">{{ s.cds_count }} CDS</span>
        </div>

        <!-- 无匹配结果 -->
        <div v-if="filteredSamples.length === 0" class="empty-pool-state">
          <p>未找到符合条件的样本</p>
          <button v-if="searchQuery" class="btn-reset-filter" @click="searchQuery = ''">清除搜索词</button>
        </div>
      </div>
    </div>

    <!-- 4. 高级大表选择器模态弹窗 (Modal Transfer) -->
    <div v-if="showModalSelector" class="modal-backdrop" @click.self="showModalSelector = false">
      <div class="modal-container">
        <div class="modal-header">
          <div class="modal-title-group">
            <h3>高级样本批量选择器</h3>
            <span class="modal-subtitle">支持在海量样本库中快速过滤、排序并批量组合对比样本群</span>
          </div>
          <button type="button" class="btn-close-modal" @click="showModalSelector = false">&times;</button>
        </div>

        <div class="modal-body">
          <div class="modal-toolbar">
            <input 
              v-model="searchQuery" 
              type="text" 
              placeholder="快速过滤名称 / ID..." 
              class="modal-search-input"
            />
            <div class="modal-quick-actions">
              <button type="button" class="modal-btn-action" @click="modalSelectAll">全选当前 ({{ filteredSamples.length }})</button>
              <button type="button" class="modal-btn-action" @click="modalClearAll">清空全部</button>
            </div>
          </div>

          <!-- 样本表格列表 -->
          <div class="modal-table-container">
            <table class="modal-samples-table">
              <thead>
                <tr>
                  <th style="width: 48px; text-align: center;">选择</th>
                  <th>样本名称</th>
                  <th>类型</th>
                  <th>CDS 数量</th>
                  <th>任务 / 来源 ID</th>
                </tr>
              </thead>
              <tbody>
                <tr 
                  v-for="s in filteredSamples" 
                  :key="s.sample_id"
                  :class="{ 'row-selected': modalSelectedIds.has(s.sample_id) }"
                  @click="toggleModalSample(s.sample_id)"
                >
                  <td style="text-align: center;">
                    <input 
                      type="checkbox" 
                      :checked="modalSelectedIds.has(s.sample_id)" 
                      @click.stop="toggleModalSample(s.sample_id)"
                    />
                  </td>
                  <td class="col-name">{{ s.sample_name }}</td>
                  <td>
                    <span class="table-type-badge">
                      {{ s.source_type === 'external_file' ? '外部导入' : (s.sample_type || 'PHAGE') }}
                    </span>
                  </td>
                  <td class="col-cds">{{ s.cds_count || '-' }}</td>
                  <td class="col-id">{{ s.sample_id }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="modal-footer">
          <div class="modal-footer-stat">
            已勾选 <strong>{{ modalSelectedIds.size }}</strong> 个样本
          </div>
          <div class="modal-footer-btns">
            <button type="button" class="btn-modal-cancel" @click="showModalSelector = false">取消</button>
            <button type="button" class="btn-modal-confirm" @click="applyModalSelection">
              应用并确认选择 ({{ modalSelectedIds.size }})
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.batch-sample-selector {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

/* 1. 顶部控制行 */
.control-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left-stat {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.stat-badge {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.stat-badge strong {
  color: #2563eb;
}

.threshold-field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.threshold-label {
  font-size: 12.5px;
  color: #64748b;
  font-weight: 500;
}

.threshold-select {
  height: 30px;
  padding: 0 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #1e293b;
  background: #ffffff;
  outline: none;
  cursor: pointer;
}

.header-right-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-import-ext {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  font-size: 12.5px;
  font-weight: 600;
  color: #3b82f6;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-import-ext:hover {
  background: #dbeafe;
  border-color: #93c5fd;
}

.btn-run-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 600;
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.btn-run-action:hover:not(:disabled) {
  background: linear-gradient(135deg, #1d4ed8, #1e40af);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.35);
}

.btn-run-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.spinner-dot {
  width: 12px;
  height: 12px;
  border: 2px solid #ffffff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 2. 已选托盘卡片 */
.selected-tray-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tray-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tray-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tray-title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn-toggle-expand {
  border: none;
  background: none;
  color: #3b82f6;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-toggle-expand:hover {
  background: #eff6ff;
}

.btn-clear-tray {
  border: none;
  background: none;
  color: #94a3b8;
  font-size: 11.5px;
  cursor: pointer;
  transition: color 0.15s ease;
}

.btn-clear-tray:hover {
  color: #ef4444;
}

.selected-chips-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  transition: max-height 0.2s ease;
}

.selected-chips-box.is-collapsed {
  max-height: 40px;
  overflow: hidden;
}

.selected-item-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  font-size: 12px;
  color: #1e40af;
  animation: fadeIn 0.15s ease;
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3b82f6;
}

.chip-name {
  font-weight: 600;
  max-width: 140px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chip-cds {
  font-size: 10.5px;
  color: #059669;
  background: #d1fae5;
  padding: 1px 4px;
  border-radius: 4px;
}

.btn-remove-chip {
  border: none;
  background: none;
  color: #93c5fd;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}

.btn-remove-chip:hover {
  color: #ef4444;
}

.empty-tray-tip {
  padding: 8px 12px;
  background: #fffbeb;
  border: 1px dashed #fde68a;
  border-radius: 6px;
  font-size: 12px;
  color: #b45309;
}

/* 3. 历史样本库工作台 */
.available-pool-workspace {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pool-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

.search-and-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}

.search-input-box {
  position: relative;
  min-width: 220px;
  display: flex;
  align-items: center;
}

.icon-search {
  position: absolute;
  left: 8px;
  color: #94a3b8;
  pointer-events: none;
}

.pool-search-input {
  width: 100%;
  height: 30px;
  padding: 0 24px 0 28px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #0f172a;
  outline: none;
}

.pool-search-input:focus {
  border-color: #3b82f6;
}

.btn-clear-search {
  position: absolute;
  right: 6px;
  border: none;
  background: none;
  color: #94a3b8;
  cursor: pointer;
}

.category-filter-tabs {
  display: flex;
  gap: 4px;
}

.cat-tab {
  border: none;
  background: #f1f5f9;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cat-tab:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.cat-tab.active {
  background: #3b82f6;
  color: #ffffff;
}

.batch-action-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-btns {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-batch {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
}

.btn-batch:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.btn-batch.modal-trigger {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.btn-batch.modal-trigger:hover {
  background: #dbeafe;
}

.select-sort {
  height: 28px;
  padding: 0 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11.5px;
  color: #475569;
  background: #ffffff;
  outline: none;
}

/* 胶囊标签滚动池 */
.samples-scroll-pool {
  max-height: 180px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px;
  align-content: flex-start;
}

.pool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 16px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.pool-chip:hover {
  border-color: #3b82f6;
  background: #eff6ff;
  color: #1e40af;
}

.pool-chip.selected {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.15);
}

.chip-check {
  font-weight: 700;
  font-size: 11px;
}

.chip-name {
  font-weight: 500;
  max-width: 180px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pool-chip.selected .chip-cds {
  background: rgba(255, 255, 255, 0.2);
  color: #93c5fd;
}

.chip-cds {
  font-size: 10px;
  color: #64748b;
  background: #e2e8f0;
  padding: 1px 4px;
  border-radius: 4px;
}

.empty-pool-state {
  width: 100%;
  padding: 24px;
  text-align: center;
  color: #94a3b8;
  font-size: 12.5px;
}

.btn-reset-filter {
  margin-top: 6px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #3b82f6;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
}

/* 4. 高级模态框 */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}

.modal-container {
  background: #ffffff;
  width: 800px;
  max-width: 92vw;
  max-height: 85vh;
  border-radius: 12px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: modalScaleUp 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes modalScaleUp {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
}

.modal-title-group h3 {
  margin: 0;
  font-size: 16px;
  color: #0f172a;
}

.modal-subtitle {
  font-size: 12px;
  color: #64748b;
}

.btn-close-modal {
  border: none;
  background: none;
  font-size: 20px;
  color: #94a3b8;
  cursor: pointer;
}

.btn-close-modal:hover {
  color: #ef4444;
}

.modal-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.modal-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.modal-search-input {
  width: 280px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12.5px;
}

.modal-quick-actions {
  display: flex;
  gap: 8px;
}

.modal-btn-action {
  border: 1px solid #cbd5e1;
  background: #f1f5f9;
  color: #334155;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.modal-btn-action:hover {
  background: #e2e8f0;
}

.modal-table-container {
  flex: 1;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.modal-samples-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.modal-samples-table th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #cbd5e1;
  color: #475569;
  font-weight: 600;
}

.modal-samples-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.modal-samples-table tr:hover {
  background: #f8fafc;
  cursor: pointer;
}

.modal-samples-table tr.row-selected {
  background: #eff6ff;
}

.col-name {
  font-weight: 600;
  color: #0f172a;
}

.col-cds {
  color: #059669;
  font-weight: 600;
}

.col-id {
  color: #64748b;
  font-family: monospace;
  font-size: 11px;
}

.table-type-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-footer-stat strong {
  color: #2563eb;
}

.modal-footer-btns {
  display: flex;
  gap: 10px;
}

.btn-modal-cancel {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
}

.btn-modal-confirm {
  border: none;
  background: #2563eb;
  color: #ffffff;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.btn-modal-confirm:hover {
  background: #1d4ed8;
}

@keyframes fadeIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
</style>
