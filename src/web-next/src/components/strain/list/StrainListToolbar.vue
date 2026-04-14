<template>
  <div class="table-toolbar">
    <div class="toolbar-left">
      <label class="select-all-checkbox">
        <input
          type="checkbox"
          :checked="isAllSelected"
          @change="toggleSelectAll"
        />
        <span>全选当前页</span>
      </label>
      <div class="divider"></div>
      <span class="record-stats">
        已选 <strong class="highlight">{{ selectedCount }}</strong> / 共 {{ totalCount }} 条
      </span>
    </div>

    <div class="toolbar-right">
      <div class="action-group">
        <button 
          class="btn-action danger" 
          @click="emit('deleteSelected')" 
          :disabled="selectedCount === 0"
        >
          <span class="icon">🗑️</span>
          <span>批量删除</span>
        </button>
        <button 
          class="btn-action primary" 
          @click="emit('exportSelected')" 
          :disabled="selectedCount === 0"
        >
          <span class="icon">📤</span>
          <span>导出选中</span>
        </button>
      </div>
      
      <div class="divider"></div>
      
      <button 
        class="btn-action filter-toggle" 
        :class="{ active: showAdvancedSearch }"
        @click="emit('toggleSearch')"
      >
        <span class="icon">🏷️</span>
        <span>高级筛选</span>
        <span v-if="activeFilterCount > 0" class="filter-count">{{ activeFilterCount }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  selectedCount: number
  totalCount: number
  filteredCount: number
  isAllSelected: boolean
  showAdvancedSearch: boolean
  activeFilterCount: number
}>()

const emit = defineEmits(['toggleSelectAll', 'deleteSelected', 'exportSelected', 'toggleSearch'])

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  emit('toggleSelectAll', checked)
}
</script>

<style scoped>
.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.divider {
  width: 1px;
  height: 20px;
  background: #e2e8f0;
}

.select-all-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #475569;
  font-weight: 600;
}

.select-all-checkbox input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.record-stats {
  font-size: 0.85rem;
  color: #64748b;
}

.highlight {
  color: #2563eb;
}

.action-group {
  display: flex;
  gap: 8px;
}

.btn-action {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.btn-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  filter: grayscale(1);
}

.btn-action.danger {
  background: white;
  border-color: #fecaca;
  color: #dc2626;
}

.btn-action.danger:hover:not(:disabled) {
  background: #fef2f2;
  border-color: #dc2626;
}

.btn-action.primary {
  background: white;
  border-color: #dbeafe;
  color: #2563eb;
}

.btn-action.primary:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #2563eb;
}

.filter-toggle {
  background: white;
  border: 1px solid #e2e8f0;
  color: #64748b;
  position: relative;
}

.filter-toggle.active {
  background: #eff6ff;
  border-color: #2563eb;
  color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.filter-count {
  background: #2563eb;
  color: white;
  font-size: 0.65rem;
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  margin-left: 2px;
}

.btn-icon-only {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
}

.btn-icon-only:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}
</style>
