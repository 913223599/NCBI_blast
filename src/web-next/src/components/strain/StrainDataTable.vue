<template>
  <div class="data-table-container">
    <!-- 空状态 -->
    <div v-if="!strain.hasData" class="empty-state">
      <div class="empty-icon">🦠</div>
      <h2>菌毒种库为空</h2>
      <p>请从左侧面板导入数据开始使用</p>
      <div class="quick-actions">
        <button class="action-btn" @click="triggerImport">
          <span class="action-icon">📥</span>
          <span>导入FASTA</span>
        </button>
        <button class="action-btn" @click="triggerNCBI">
          <span class="action-icon">🌐</span>
          <span>从NCBI下载</span>
        </button>
        <button class="action-btn" @click="triggerManual">
          <span class="action-icon">✏️</span>
          <span>手动录入</span>
        </button>
      </div>
    </div>

    <!-- 数据表格 -->
    <div v-else class="table-wrapper">
      <!-- 表格工具栏 -->
      <div class="table-toolbar">
        <div class="toolbar-left">
          <label class="select-all-checkbox">
            <input
              type="checkbox"
              :checked="strain.selectedCount === strain.filteredCount && strain.filteredCount > 0"
              @change="toggleSelectAll"
            />
            <span>全选</span>
          </label>
          <span class="record-count">
            共 {{ strain.filteredCount }} 条记录
          </span>
        </div>

        <div class="toolbar-right">
          <button class="btn-icon" @click="handleDeleteSelected" :disabled="strain.selectedCount === 0">
            🗑️ 删除选中
          </button>
          <button class="btn-icon" @click="handleExportSelected">
            📤 导出选中
          </button>
        </div>
      </div>

      <!-- 数据表格 -->
      <table class="strain-table">
        <thead>
          <tr>
            <th class="col-checkbox"></th>
            <th class="col-accession">登录号</th>
            <th class="col-name">名称</th>
            <th class="col-species">物种</th>
            <th class="col-strain">菌株</th>
            <th class="col-type">类型</th>
            <th class="col-source">来源</th>
            <th class="col-host">宿主</th>
            <th class="col-country">地区</th>
            <th class="col-date">采集日期</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="record in displayedRecords"
            :key="record.id"
            class="table-row"
            :class="{
              selected: strain.selectedRecords.has(record.id),
              active: strain.activeRecord?.id === record.id
            }"
            @click="selectRecord(record)"
          >
            <td class="col-checkbox">
              <input
                type="checkbox"
                :checked="strain.selectedRecords.has(record.id)"
                @click.stop
                @change="strain.toggleSelect(record.id)"
              />
            </td>
            <td class="col-accession">
              <span class="accession-link" @click.stop="viewDetail(record)">
                {{ record.accession }}
              </span>
            </td>
            <td class="col-name">{{ record.name }}</td>
            <td class="col-species">
              <span class="species-badge">{{ record.species }}</span>
            </td>
            <td class="col-strain">{{ record.strain || '-' }}</td>
            <td class="col-type">
              <span class="type-badge" :class="record.sequenceType.toLowerCase()">
                {{ record.sequenceType }}
              </span>
            </td>
            <td class="col-source">{{ record.source || '-' }}</td>
            <td class="col-host">{{ record.host || '-' }}</td>
            <td class="col-country">{{ record.country || '-' }}</td>
            <td class="col-date">{{ record.collectionDate || '-' }}</td>
            <td class="col-actions">
              <button class="action-btn-small" @click.stop="viewDetail(record)" title="查看详情">
                👁️
              </button>
              <button class="action-btn-small" @click.stop="deleteRecord(record.id)" title="删除">
                🗑️
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      
      <!-- 渲染截断提示 -->
      <div v-if="strain.filteredRecords.length > 500" class="render-limit-notice">
        由于数据量极大，为确保性能，此处仅显示前 500 条数据。（共 {{ strain.filteredRecords.length }} 条）
        请使用左侧面板进行检索以查看更多。
      </div>
    </div>

    <!-- 详情面板（浮动） -->
    <StrainDetailPanel
      v-if="strain.activeRecord"
      :record="strain.activeRecord"
      @close="strain.setActiveRecord(null)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import StrainDetailPanel from './StrainDetailPanel.vue'

const strain = useStrainStore()
const appStore = useAppStore()

// 性能截断：最多渲染 500 行，否则几千几万行 DOM 会直接卡死浏览器
const displayedRecords = computed(() => {
  return strain.filteredRecords.slice(0, 500)
})

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    strain.selectAll()
  } else {
    strain.clearSelection()
  }
}

function selectRecord(record: any) {
  strain.setActiveRecord(record)
}

function viewDetail(record: any) {
  strain.setActiveRecord(record)
}

function deleteRecord(id: string) {
  if (window.confirm('确定要删除这条记录吗？')) {
    strain.removeRecord(id)
    appStore.showNotification('已删除记录', 'success')
  }
}

function handleDeleteSelected() {
  if (strain.selectedCount === 0) return
  if (window.confirm(`确定要删除选中的 ${strain.selectedCount} 条记录吗？`)) {
    strain.selectedRecords.forEach((id: string) => strain.removeRecord(id))
    appStore.showNotification(`已删除 ${strain.selectedCount} 条记录`, 'success')
  }
}

function handleExportSelected() {
  if (strain.selectedCount === 0) {
    appStore.showNotification('请先选择要导出的记录', 'warning')
    return
  }
  // TODO: 实现导出逻辑
  appStore.showNotification(`已导出 ${strain.selectedCount} 条记录`, 'success')
}

function triggerImport() {
  appStore.showNotification('导入功能开发中', 'info')
}

function triggerNCBI() {
  appStore.showNotification('NCBI下载功能开发中', 'info')
}

function triggerManual() {
  appStore.showNotification('手动录入功能开发中', 'info')
}
</script>

<style scoped>
.data-table-container {
  height: 100%;
  overflow: auto;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 16px;
  opacity: 0.6;
}

.empty-state h2 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.empty-state p {
  font-size: 0.95rem;
  color: #64748b;
  margin: 0 0 32px 0;
}

.quick-actions {
  display: flex;
  gap: 12px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.action-btn:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}

.action-icon {
  font-size: 1.2rem;
}

/* 表格包装 */
.table-wrapper {
  background: white;
  border-radius: 12px;
  overflow: hidden;
  /* 工业级渲染隔离：隔离布局计算，防止局部变动引起全局重排 */
  contain: content;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.select-all-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #475569;
}

.select-all-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.record-count {
  font-size: 0.85rem;
  color: #64748b;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

.btn-icon {
  padding: 8px 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-icon:hover:not(:disabled) {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 数据表格 */
.strain-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.strain-table thead {
  background: #f8fafc;
  position: sticky;
  top: 0;
  z-index: 10;
}

.strain-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 700;
  color: #64748b;
  border-bottom: 2px solid #e2e8f0;
  white-space: nowrap;
}

.strain-table tbody tr {
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  /* 现代工业级懒渲染：只渲染视口附近的行 */
  content-visibility: auto;
  contain-intrinsic-size: 0 45px; /* 预估行高，防止滚动条抖动 */
}

.strain-table tbody tr:hover {
  background: #f8fafc;
}

.strain-table tbody tr.selected {
  background: #eff6ff;
}

.strain-table tbody tr.active {
  background: #dbeafe;
}

.strain-table td {
  padding: 12px 16px;
  color: #1e293b;
}

.col-checkbox {
  width: 40px;
  text-align: center;
}

.col-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.col-accession {
  min-width: 120px;
}

.accession-link {
  color: #2563eb;
  font-weight: 600;
  cursor: pointer;
}

.accession-link:hover {
  text-decoration: underline;
}

.col-name {
  min-width: 150px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-species {
  min-width: 120px;
}

.species-badge {
  display: inline-block;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.col-strain {
  min-width: 100px;
}

.col-type {
  min-width: 80px;
}

.type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.type-badge.dna {
  background: #dbeafe;
  color: #1e40af;
}

.type-badge.rna {
  background: #fce7f3;
  color: #9d174d;
}

.type-badge.protein {
  background: #d1fae5;
  color: #065f46;
}

.col-source,
.col-host,
.col-country,
.col-date {
  min-width: 100px;
}

.col-actions {
  width: 80px;
  text-align: center;
}

.action-btn-small {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  padding: 4px;
  border-radius: 4px;
  transition: background 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.action-btn-small:hover {
  background: #f1f5f9;
}

.render-limit-notice {
  text-align: center;
  padding: 16px;
  background: #fffbeb;
  color: #b45309;
  font-size: 0.85rem;
  border-top: 1px solid #fef3c7;
}
</style>