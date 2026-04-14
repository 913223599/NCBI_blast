<template>
  <div class="list-view-container">
    <!-- 工具栏 -->
    <StrainListToolbar
      :selected-count="strainStore.selectedCount"
      :total-count="strainStore.totalRecords"
      :filtered-count="strainStore.filteredCount"
      :is-all-selected="isAllSelected"
      :show-advanced-search="showAdvancedSearch"
      :active-filter-count="activeFilterCount"
      @toggleSelectAll="handleToggleSelectAll"
      @deleteSelected="handleDeleteSelected"
      @exportSelected="handleExportSelected"
      @toggleSearch="showAdvancedSearch = !showAdvancedSearch"
    />

    <div class="main-content-layout">
      <!-- 数据表格区域 -->
      <div class="table-area">
        <StrainListTable
          :records="displayedRecords"
          :selected-ids="strainStore.selectedRecords"
          :active-id="strainStore.activeRecord?.id"
          :visibility="columnVisibility"
          :sort-key="strainStore.searchFilters.sortKey"
          :sort-order="strainStore.searchFilters.sortOrder"
          @rowClick="handleRowClick"
          @toggleSelect="handleToggleSelect"
          @viewDetail="handleViewDetail"
          @deleteRow="handleDeleteRow"
          @sort="key => strainStore.toggleSort(key)"
        />
        
        <!-- 性能截断提示 -->
        <div v-if="strainStore.filteredCount > RENDER_LIMIT" class="render-limit-notice">
          仅显示前 {{ RENDER_LIMIT }} 条结果 (共 {{ strainStore.filteredCount }} 条)
        </div>
      </div>

      <!-- 右侧高级搜索侧边栏 -->
      <Transition name="slide-right">
        <div v-if="showAdvancedSearch" class="sidebar-overlay">
          <StrainListAdvancedSearch 
            :stats="filterStats"
            :initial-columns="columnVisibility"
            @close="showAdvancedSearch = false" 
            @updateColumns="val => Object.assign(columnVisibility, val)"
          />
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { useStrainStore } from '../../../stores/strain'
import { useAppStore } from '../../../stores/app'
import StrainListAdvancedSearch from './StrainListAdvancedSearch.vue'
import StrainListToolbar from './StrainListToolbar.vue'
import StrainListTable from './StrainListTable.vue'

const RENDER_LIMIT = 500
const strainStore = useStrainStore()
const appStore = useAppStore()

const showAdvancedSearch = ref(false)

const columnVisibility = reactive({
  accession: true,
  species: true,
  strain: true,
  sequenceType: true,
  source: false, // 默认隐藏一些不常用的
  host: false,
  country: true,
  collectionDate: true
})

const activeFilterCount = computed(() => {
  const f = strainStore.searchFilters
  let count = 0
  if (f.keyword) count++
  if (f.species) count++
  if (f.sequenceType) count++
  if (f.country) count++
  if (f.dateFrom || f.dateTo) count++
  return count
})

const displayedRecords = computed(() => {
  return strainStore.filteredRecords.slice(0, RENDER_LIMIT)
})

const filterStats = computed(() => {
  const records = strainStore.filteredRecords
  const total = records.length
  if (total === 0) return null
  
  const typeMap: Record<string, number> = {}
  records.forEach(r => {
    const type = r.sequenceType || 'Unknown'
    typeMap[type] = (typeMap[type] || 0) + 1
  })
  
  return {
    total,
    types: Object.entries(typeMap).map(([name, count]) => ({
      name,
      count,
      percent: Math.round((count / total) * 100)
    })).sort((a, b) => b.count - a.count)
  }
})

const isAllSelected = computed(() => {
  return strainStore.selectedCount === strainStore.filteredCount && strainStore.filteredCount > 0
})

function handleToggleSelectAll(checked: boolean) {
  if (checked) strainStore.selectAll()
  else strainStore.clearSelection()
}

function handleToggleSelect(id: string) {
  strainStore.toggleSelect(id)
}

function handleRowClick(record: any) {
  strainStore.setActiveRecord(record)
}

function handleViewDetail(record: any) {
  strainStore.setActiveRecord(record)
}

function handleDeleteRow(id: string) {
  if (window.confirm('确定要删除这条记录吗？')) {
    strainStore.removeRecord(id)
    appStore.showNotification('已删除记录', 'success')
  }
}

function handleDeleteSelected() {
  const count = strainStore.selectedCount
  if (window.confirm(`确定要批量删除选中的 ${count} 条记录吗？`)) {
    const ids = Array.from(strainStore.selectedRecords)
    strainStore.removeRecordsBatch(ids)
    appStore.showNotification(`已批量删除 ${count} 条记录`, 'success')
  }
}

function handleExportSelected() {
  const count = strainStore.selectedCount
  if (count === 0) return
  
  const content = strainStore.exportSelected('csv')
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  
  link.setAttribute('href', url)
  link.setAttribute('download', `Strain_Export_${new Date().getTime()}.csv`)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  
  appStore.showNotification(`已成功导出 ${count} 条记录`, 'success')
}
</script>

<style scoped>
.list-view-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  contain: content;
}

.main-content-layout {
  flex: 1;
  display: flex;
  flex-direction: row;
  min-height: 0;
  position: relative; /* 为绝对定位的抽屉提供基准 */
  background: white;
}

.table-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  z-index: 10;
}

/* 抽屉式侧边栏动画 */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.slide-right-enter-from,
.slide-right-leave-to {
  transform: translateX(100%);
}

.sidebar-overlay {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 50;
  width: 320px;
  background: white;
  box-shadow: -5px 0 20px rgba(0,0,0,0.1);
}

.render-limit-notice {
  padding: 8px;
  background: #fffbeb;
  color: #b45309;
  font-size: 0.75rem;
  text-align: center;
  border-top: 1px solid #fef3c7;
}
</style>
