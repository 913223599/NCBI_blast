<script setup lang="ts">
/**
 * SampleFilterPopover.vue - 样本显隐与高通量聚焦筛选浮层
 * 提供样本实时搜索、单株显隐切换、批量全选/反选/全不选及单株独立聚焦功能。
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  isOpen: boolean
  orderedSampleIds: string[]
  hiddenSampleIds: Set<string>
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'update:isOpen', val: boolean): void
  (e: 'toggle-sample', sampleId: string): void
  (e: 'show-all'): void
  (e: 'clear-all'): void
  (e: 'invert-selection'): void
  (e: 'focus-pair'): void
  (e: 'focus-single', sampleId: string): void
}>()

const searchKeyword = ref('')

function naturalSort(ids: string[]): string[] {
  return [...ids].sort((a, b) => {
    const nameA = props.sampleNames[a] || a
    const nameB = props.sampleNames[b] || b
    return nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' })
  })
}

const searchableSamples = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  const allIds = naturalSort(props.orderedSampleIds)
  return allIds
    .map(id => ({
      id,
      name: props.sampleNames[id] || id,
      visible: !props.hiddenSampleIds.has(id)
    }))
    .filter(item => {
      if (!kw) return true
      return item.name.toLowerCase().includes(kw) || item.id.toLowerCase().includes(kw)
    })
})
</script>

<template>
  <div class="sample-dropdown-wrapper">
    <button
      class="btn-sample-action btn-filter-dropdown"
      :class="{ active: isOpen }"
      @click="emit('update:isOpen', !isOpen)"
      title="勾选或搜索样本"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
      </svg>
      筛选样本
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <!-- 弹出浮层 -->
    <div class="sample-dropdown-panel" v-if="isOpen">
      <div class="sd-header">
        <input
          type="text"
          v-model="searchKeyword"
          placeholder="搜索样本名称或ID..."
          class="sd-search-input"
          @click.stop
        />
        <div class="sd-quick-actions">
          <button class="btn-sd-quick" @click.stop="emit('show-all')" title="勾选所有样本">全选</button>
          <button class="btn-sd-quick" @click.stop="emit('invert-selection')" title="反转勾选状态">反选</button>
          <button class="btn-sd-quick" @click.stop="emit('clear-all')" title="仅保留首株，取消其余勾选">全不选</button>
          <button class="btn-sd-close" @click.stop="emit('update:isOpen', false)">×</button>
        </div>
      </div>

      <div class="sd-sample-list">
        <div
          v-for="s in searchableSamples"
          :key="'sd-item-' + s.id"
          class="sd-sample-item"
          :class="{ active: s.visible }"
          @click="emit('toggle-sample', s.id)"
        >
          <input type="checkbox" :checked="s.visible" @click.stop="emit('toggle-sample', s.id)" />
          <span class="sd-name" :title="s.name">{{ s.name }}</span>
          <button class="btn-sd-only" @click.stop="emit('focus-single', s.id)" title="仅看这一株">
            仅看
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sample-dropdown-wrapper {
  position: relative;
}

.btn-sample-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  padding: 2px 7px;
  cursor: pointer;
  transition: all 0.15s ease;
  line-height: 1.2;
}

.btn-sample-action:hover {
  background: #e2e8f0;
  color: #0f172a;
  border-color: #94a3b8;
}

.btn-filter-dropdown.active {
  background: #2563eb;
  color: #ffffff;
  border-color: #1d4ed8;
}

.sample-dropdown-panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 50;
  width: 260px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sd-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sd-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  outline: none;
}

.sd-search-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.sd-quick-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.btn-sd-quick {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font-size: 9.5px;
  font-weight: 600;
  color: #475569;
  padding: 1px 6px;
  cursor: pointer;
}

.btn-sd-quick:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.btn-sd-close {
  background: transparent;
  border: none;
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

.btn-sd-close:hover {
  color: #dc2626;
}

.sd-sample-list {
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sd-sample-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  cursor: pointer;
  transition: background 0.1s ease;
}

.sd-sample-item:hover {
  background: #f1f5f9;
}

.sd-sample-item input[type="checkbox"] {
  margin: 0;
  cursor: pointer;
}

.sd-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #334155;
}

.sd-sample-item.active .sd-name {
  color: #0f172a;
  font-weight: 600;
}

.btn-sd-only {
  background: transparent;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font-size: 8.5px;
  color: #64748b;
  padding: 0 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.sd-sample-item:hover .btn-sd-only {
  opacity: 1;
}

.btn-sd-only:hover {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
}
</style>
