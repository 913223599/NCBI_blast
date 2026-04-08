<template>
  <div class="search-results-panel">
    <!-- 结果头部 -->
    <div class="results-header">
      <div class="header-left">
        <h3 class="title">🧬 搜索结果</h3>
        <span class="result-count">{{ strain.filteredCount }} 条记录</span>
      </div>
      <div class="header-actions">
        <button class="btn-export" @click="handleExport" :disabled="strain.filteredCount === 0">
          📥 导出
        </button>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="strain.filteredRecords.length === 0" class="empty-state">
      <div class="empty-icon">🔍</div>
      <h3>没有找到匹配的样本</h3>
      <p>请尝试调整搜索条件或筛选器</p>
    </div>

    <!-- 结果列表 -->
    <div v-else class="results-list">
      <div
        v-for="record in strain.filteredRecords"
        :key="record.id"
        class="result-card"
        :class="{ selected: strain.selectedRecords.has(record.id) }"
        @click="handleCardClick(record, $event)"
      >
        <!-- 复选框 -->
        <div class="card-checkbox" @click.stop="strain.toggleSelect(record.id)">
          <input
            type="checkbox"
            :checked="strain.selectedRecords.has(record.id)"
            class="checkbox-input"
          />
        </div>

        <!-- 样本信息 -->
        <div class="card-content">
          <div class="card-main">
            <div class="sample-name">{{ record.name }}</div>
            <div class="sample-meta">
              <span class="meta-badge accession">{{ record.accession || 'N/A' }}</span>
              <span class="type-badge" :class="record.sequenceType.toLowerCase()">
                {{ record.sequenceType }}
              </span>
            </div>
          </div>

          <div class="card-details">
            <div class="detail-item">
              <span class="detail-label">物种：</span>
              <span class="detail-value">{{ record.species || '-' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">菌株：</span>
              <span class="detail-value">{{ record.strain || '-' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">位置：</span>
              <span class="detail-value">{{ getLocationPath(record) }}</span>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="card-actions" @click.stop>
          <button class="action-btn" @click="handleView(record)" title="查看详情">
            👁️
          </button>
          <button class="action-btn" @click="handleLocate(record)" title="定位位置">
            📍
          </button>
        </div>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div v-if="strain.selectedCount > 0" class="selection-bar">
      <span class="selection-info">已选择 {{ strain.selectedCount }} 项</span>
      <div class="selection-actions">
        <button class="btn-action" @click="handleExportSelected">导出选中</button>
        <button class="btn-action btn-delete" @click="handleDeleteSelected">删除选中</button>
        <button class="btn-action" @click="strain.clearSelection">取消选择</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { StrainRecord } from '../../stores/strain'

const strain = useStrainStore()
const appStore = useAppStore()

const emit = defineEmits(['view', 'locate', 'export'])

function handleCardClick(record: StrainRecord, event: MouseEvent) {
  // 如果点击的是复选框区域，不触发展开
  if ((event.target as HTMLElement).closest('.card-checkbox')) return
  emit('view', record)
}

function handleView(record: StrainRecord) {
  emit('view', record)
}

function handleLocate(record: StrainRecord) {
  emit('locate', record)
}

function getLocationPath(record: StrainRecord): string {
  if (!record.freezerId || !record.position) return '-'
  
  const freezer = strain.freezers.find(f => f.id === record.freezerId)
  if (!freezer) return '-'
  
  const shelf = freezer.shelves.find(s => s.id === record.shelfId)
  const cabinet = shelf?.cabinets.find(c => c.id === record.cabinetId)
  const drawer = cabinet?.drawers.find(d => d.id === record.drawerId)
  const box = drawer?.boxes.find(b => b.id === record.boxId)
  
  const parts = [
    freezer.name,
    shelf?.name,
    cabinet?.name,
    drawer?.name,
    box?.name,
    record.position
  ].filter(Boolean)
  
  return parts.join(' → ')
}

function handleExport() {
  if (strain.filteredCount === 0) return
  const data = strain.exportSelected('csv')
  if (data) {
    downloadFile(data, 'strain_records.csv', 'text/csv')
    appStore.showNotification('导出成功', 'success')
  }
}

function handleExportSelected() {
  if (strain.selectedCount === 0) return
  const data = strain.exportSelected('csv')
  if (data) {
    downloadFile(data, 'selected_records.csv', 'text/csv')
    appStore.showNotification('导出成功', 'success')
  }
}

function handleDeleteSelected() {
  if (confirm(`确定要删除选中的 ${strain.selectedCount} 条记录吗？`)) {
    strain.selectedRecords.forEach(id => {
      strain.removeRecord(id)
    })
    strain.clearSelection()
    appStore.showNotification('删除成功', 'success')
  }
}

function downloadFile(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.search-results-panel {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.result-count {
  font-size: 0.8rem;
  color: #64748b;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 12px;
}

.btn-export {
  padding: 8px 16px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-export:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-export:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 空状态 */
.empty-state {
  padding: 60px 20px;
  text-align: center;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-state h3 {
  font-size: 1.1rem;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.empty-state p {
  font-size: 0.9rem;
  color: #64748b;
  margin: 0;
}

/* 结果列表 */
.results-list {
  max-height: 600px;
  overflow-y: auto;
}

.result-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: all 0.2s;
}

.result-card:hover {
  background: #f8fafc;
}

.result-card.selected {
  background: #eff6ff;
  border-left: 3px solid #2563eb;
}

.card-checkbox {
  flex-shrink: 0;
}

.checkbox-input {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #2563eb;
}

.card-content {
  flex: 1;
  min-width: 0;
}

.card-main {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.sample-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.meta-badge {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.meta-badge.accession {
  background: #f1f5f9;
  color: #475569;
}

.type-badge {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 700;
}

.type-badge.dna {
  background: #dbeafe;
  color: #1e40af;
}

.type-badge.rna {
  background: #fce7f3;
  color: #be185d;
}

.type-badge.protein {
  background: #fef3c7;
  color: #92400e;
}

.card-details {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.detail-item {
  font-size: 0.8rem;
  color: #64748b;
}

.detail-label {
  color: #94a3b8;
}

.detail-value {
  color: #475569;
  font-weight: 500;
}

.card-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.action-btn {
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

/* 底部操作栏 */
.selection-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #eff6ff;
  border-top: 1px solid #bfdbfe;
}

.selection-info {
  font-size: 0.85rem;
  color: #1e40af;
  font-weight: 600;
}

.selection-actions {
  display: flex;
  gap: 8px;
}

.btn-action {
  padding: 6px 14px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-action:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.btn-action.btn-delete {
  color: #ef4444;
  border-color: #fecaca;
}

.btn-action.btn-delete:hover {
  background: #fee2e2;
  border-color: #fca5a5;
}
</style>
