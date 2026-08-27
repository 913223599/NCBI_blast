<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

export interface SampleOption {
  id: string
  name: string
  type?: string
  cdsCount?: number
  length?: number
  createdAt?: string
  isExternal?: boolean
  raw?: any
}

interface Props {
  modelValue?: string
  options?: SampleOption[]
  placeholder?: string
  disabled?: boolean
  showImportOption?: boolean
  importLabel?: string
  tagVariant?: 'a' | 'b' | 'default'
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  options: () => [],
  placeholder: '请选择样本或任务...',
  disabled: false,
  showImportOption: true,
  importLabel: '➕ 选择并导入本地外部文件 (.gbk / .gb / .faa)...',
  tagVariant: 'default'
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string, item?: SampleOption): void
  (e: 'import'): void
}>()

const isOpen = ref(false)
const searchQuery = ref('')
const selectedCategory = ref<string>('all')
const containerRef = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)

// 当前选中的选项对象
const selectedOption = computed(() => {
  if (!props.modelValue) return null
  return props.options.find(opt => opt.id === props.modelValue) || null
})

// 分类统计
const categoryStats = computed(() => {
  let phageCount = 0
  let hostCount = 0
  let extCount = 0

  for (const opt of props.options) {
    const t = (opt.type || '').toUpperCase()
    if (opt.isExternal || t.includes('EXT') || opt.id.startsWith('EXT_')) {
      extCount++
    } else if (t.includes('PHAGE') || t.includes('噬菌体')) {
      phageCount++
    } else {
      hostCount++
    }
  }

  return {
    all: props.options.length,
    phage: phageCount,
    host: hostCount,
    ext: extCount
  }
})

// 过滤后的选项列表
const filteredOptions = computed(() => {
  let list = props.options

  // 1. 分类筛选
  if (selectedCategory.value === 'phage') {
    list = list.filter(opt => {
      const t = (opt.type || '').toUpperCase()
      return !opt.isExternal && !opt.id.startsWith('EXT_') && (t.includes('PHAGE') || t.includes('噬菌体'))
    })
  } else if (selectedCategory.value === 'host') {
    list = list.filter(opt => {
      const t = (opt.type || '').toUpperCase()
      return !opt.isExternal && !opt.id.startsWith('EXT_') && !(t.includes('PHAGE') || t.includes('噬菌体'))
    })
  } else if (selectedCategory.value === 'ext') {
    list = list.filter(opt => opt.isExternal || opt.id.startsWith('EXT_') || (opt.type || '').toUpperCase().includes('EXT'))
  }

  // 2. 搜索关键词过滤
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return list

  return list.filter(opt => {
    const nameMatch = opt.name.toLowerCase().includes(q)
    const idMatch = opt.id.toLowerCase().includes(q)
    const typeMatch = (opt.type || '').toLowerCase().includes(q)
    return nameMatch || idMatch || typeMatch
  })
})

function toggleDropdown() {
  if (props.disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    nextTick(() => {
      searchInputRef.value?.focus()
    })
  }
}

function handleSelect(opt: SampleOption) {
  emit('update:modelValue', opt.id)
  emit('change', opt.id, opt)
  isOpen.value = false
}

function handleClear(e: Event) {
  e.stopPropagation()
  emit('update:modelValue', '')
  emit('change', '', undefined)
}

function handleImportClick() {
  isOpen.value = false
  emit('import')
}

function handleClickOutside(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isOpen.value) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="searchable-sample-select" ref="containerRef" :class="{ 'is-disabled': disabled }">
    <!-- 触发框 -->
    <div 
      class="select-trigger" 
      :class="[
        `variant-${tagVariant}`,
        { 'is-open': isOpen, 'has-selection': !!selectedOption }
      ]"
      @click="toggleDropdown"
    >
      <div class="trigger-content">
        <template v-if="selectedOption">
          <div class="selected-badge">
            <span class="badge-type" :class="(selectedOption.type || 'DEFAULT').toLowerCase()">
              {{ selectedOption.type || 'SAMPLE' }}
            </span>
            <span class="badge-name" :title="selectedOption.name">{{ selectedOption.name }}</span>
            <span class="badge-cds" v-if="selectedOption.cdsCount !== undefined">
              {{ selectedOption.cdsCount }} CDS
            </span>
          </div>
        </template>
        <template v-else>
          <span class="placeholder-text">{{ placeholder }}</span>
        </template>
      </div>

      <div class="trigger-actions">
        <button 
          v-if="selectedOption && !disabled" 
          type="button" 
          class="btn-clear" 
          title="清除选择" 
          @click="handleClear"
        >
          &times;
        </button>
        <div class="arrow-icon" :class="{ rotated: isOpen }">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </div>
    </div>

    <!-- 下拉弹出层 -->
    <transition name="popover-fade">
      <div v-if="isOpen" class="select-dropdown-popover">
        <!-- 搜索过滤栏 -->
        <div class="dropdown-header">
          <div class="search-input-wrap">
            <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input 
              ref="searchInputRef"
              v-model="searchQuery" 
              type="text" 
              class="search-input" 
              placeholder="搜索样本名称 / ID / 类型..." 
              @click.stop
            />
            <button 
              v-if="searchQuery" 
              class="clear-search-btn" 
              @click.stop="searchQuery = ''"
            >
              &times;
            </button>
          </div>

          <!-- 分类筛选 Tab -->
          <div class="category-tabs" @click.stop>
            <button 
              type="button" 
              class="tab-item" 
              :class="{ active: selectedCategory === 'all' }"
              @click="selectedCategory = 'all'"
            >
              全部 ({{ categoryStats.all }})
            </button>
            <button 
              v-if="categoryStats.phage > 0"
              type="button" 
              class="tab-item" 
              :class="{ active: selectedCategory === 'phage' }"
              @click="selectedCategory = 'phage'"
            >
              噬菌体 ({{ categoryStats.phage }})
            </button>
            <button 
              v-if="categoryStats.host > 0"
              type="button" 
              class="tab-item" 
              :class="{ active: selectedCategory === 'host' }"
              @click="selectedCategory = 'host'"
            >
              细菌/宿主 ({{ categoryStats.host }})
            </button>
            <button 
              v-if="categoryStats.ext > 0"
              type="button" 
              class="tab-item" 
              :class="{ active: selectedCategory === 'ext' }"
              @click="selectedCategory = 'ext'"
            >
              外部导入 ({{ categoryStats.ext }})
            </button>
          </div>
        </div>

        <!-- 置顶外部导入快捷按钮 -->
        <div v-if="showImportOption" class="import-quick-row" @click="handleImportClick">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <span>{{ importLabel }}</span>
        </div>

        <!-- 选项列表 -->
        <div class="options-list-scroll">
          <div 
            v-for="opt in filteredOptions" 
            :key="opt.id" 
            class="option-item"
            :class="{ 'is-selected': opt.id === modelValue }"
            @click="handleSelect(opt)"
          >
            <div class="option-main">
              <div class="option-title-row">
                <span class="opt-name">{{ opt.name }}</span>
                <span class="opt-type-tag" :class="(opt.type || 'DEFAULT').toLowerCase()">
                  {{ opt.type || 'SAMPLE' }}
                </span>
              </div>
              <div class="option-sub-row">
                <span class="opt-id" :title="opt.id">ID: {{ opt.id }}</span>
                <span class="opt-cds" v-if="opt.cdsCount !== undefined">{{ opt.cdsCount }} CDS</span>
                <span class="opt-date" v-if="opt.createdAt">{{ opt.createdAt }}</span>
              </div>
            </div>
            <div class="check-mark" v-if="opt.id === modelValue">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="filteredOptions.length === 0" class="empty-results">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p>未找到匹配的样本记录</p>
            <button v-if="searchQuery" class="reset-search-btn" @click.stop="searchQuery = ''">
              清除搜索条件
            </button>
          </div>
        </div>

        <!-- 底部汇总 -->
        <div class="dropdown-footer">
          <span>共 {{ filteredOptions.length }} 个可选样本</span>
          <span v-if="searchQuery">（已按关键字过滤）</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.searchable-sample-select {
  position: relative;
  width: 100%;
  font-family: inherit;
  user-select: none;
}

.searchable-sample-select.is-disabled {
  opacity: 0.6;
  pointer-events: none;
}

/* 触发器 */
.select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 42px;
  padding: 6px 12px;
  background: var(--bg-card, #ffffff);
  border: 1.5px solid var(--border-color, #cbd5e1);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.select-trigger:hover {
  border-color: #3b82f6;
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.12);
}

.select-trigger.is-open {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

/* 变体配色 */
.select-trigger.variant-a.has-selection {
  border-color: #3b82f6;
  background: #f0f7ff;
}

.select-trigger.variant-b.has-selection {
  border-color: #10b981;
  background: #f0fdf4;
}

.trigger-content {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.placeholder-text {
  color: var(--text-muted, #94a3b8);
  font-size: 13px;
}

/* 已选卡片徽章 */
.selected-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.badge-type {
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
  text-transform: uppercase;
  flex-shrink: 0;
}

.badge-type.phage {
  background: #dbeafe;
  color: #1d4ed8;
}

.badge-type.host, .badge-type.bacteria {
  background: #fef3c7;
  color: #b45309;
}

.badge-type.external, .badge-type.ext {
  background: #ede9fe;
  color: #6d28d9;
}

.badge-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-main, #0f172a);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge-cds {
  font-size: 11px;
  font-weight: 600;
  color: #059669;
  background: #d1fae5;
  padding: 2px 6px;
  border-radius: 10px;
  flex-shrink: 0;
}

.trigger-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
  flex-shrink: 0;
}

.btn-clear {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.15s ease;
}

.btn-clear:hover {
  color: #ef4444;
  background: #fee2e2;
}

.arrow-icon {
  color: #64748b;
  display: flex;
  align-items: center;
  transition: transform 0.2s ease;
}

.arrow-icon.rotated {
  transform: rotate(180deg);
}

/* 下拉弹窗容器 */
.select-dropdown-popover {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 1000;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-color, #cbd5e1);
  border-radius: 10px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: dropdownSlideDown 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes dropdownSlideDown {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 顶部搜索与分类 */
.dropdown-header {
  padding: 10px;
  border-bottom: 1px solid var(--border-color, #e2e8f0);
  background: var(--bg-header, #f8fafc);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  color: #94a3b8;
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 34px;
  padding: 0 28px 0 32px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12.5px;
  color: #0f172a;
  background: #ffffff;
  outline: none;
  transition: border-color 0.15s ease;
}

.search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.clear-search-btn {
  position: absolute;
  right: 6px;
  border: none;
  background: none;
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
  padding: 2px 4px;
}

.clear-search-btn:hover {
  color: #475569;
}

/* 分类 Tab */
.category-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
}

.tab-item {
  border: none;
  background: #e2e8f0;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.tab-item:hover {
  background: #cbd5e1;
  color: #0f172a;
}

.tab-item.active {
  background: #3b82f6;
  color: #ffffff;
}

/* 快捷导入行 */
.import-quick-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #eff6ff;
  border-bottom: 1px dashed #bfdbfe;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.import-quick-row:hover {
  background: #dbeafe;
}

/* 选项列表滚动区 */
.options-list-scroll {
  max-height: 260px;
  overflow-y: auto;
  padding: 4px 0;
}

.option-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s ease;
  border-bottom: 1px solid #f1f5f9;
}

.option-item:last-child {
  border-bottom: none;
}

.option-item:hover {
  background: #f8fafc;
}

.option-item.is-selected {
  background: #eff6ff;
}

.option-main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.option-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.opt-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.opt-type-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #64748b;
  flex-shrink: 0;
}

.opt-type-tag.phage {
  background: #e0e7ff;
  color: #3730a3;
}

.opt-type-tag.host, .opt-type-tag.bacteria {
  background: #fef3c7;
  color: #92400e;
}

.option-sub-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #64748b;
}

.opt-id {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 140px;
}

.opt-cds {
  color: #059669;
  font-weight: 600;
}

.check-mark {
  color: #2563eb;
  margin-left: 8px;
  flex-shrink: 0;
}

/* 空状态 */
.empty-results {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  color: #94a3b8;
  gap: 6px;
}

.empty-results p {
  margin: 0;
  font-size: 12.5px;
}

.reset-search-btn {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #3b82f6;
  font-size: 11.5px;
  padding: 3px 10px;
  border-radius: 4px;
  cursor: pointer;
  margin-top: 4px;
}

.reset-search-btn:hover {
  background: #f1f5f9;
}

/* 底部状态 */
.dropdown-footer {
  padding: 6px 12px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #64748b;
}

/* 动效 */
.popover-fade-enter-active,
.popover-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.popover-fade-enter-from,
.popover-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
