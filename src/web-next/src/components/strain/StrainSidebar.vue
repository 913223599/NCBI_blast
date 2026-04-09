<template>
  <aside class="sidebar-with-search">
    <!-- 搜索栏 -->
    <div class="search-section">
      <div class="search-input-wrapper">
        <span class="search-icon"></span>
        <input
          v-model="searchKeyword"
          class="search-input"
          placeholder="搜索样本..."
          @input="handleSearch"
        />
        <button v-if="searchKeyword" class="clear-btn" @click="clearSearch">✕</button>
      </div>
    </div>

    <div class="sidebar-header">
      <h3 class="sidebar-title">🧊 保藏管理</h3>
      <button class="btn-add-freezer" @click="emit('addFreezer')">
        <span class="icon">+</span>
        <span>添加冰箱</span>
      </button>
    </div>

    <!-- 视图切换 -->
    <div class="view-toggle">
      <button
        class="toggle-btn"
        :class="{ active: viewMode === 'freezers' }"
        @click="viewMode = 'freezers'"
      >
        🧊 冰箱
      </button>
      <button
        class="toggle-btn"
        :class="{ active: viewMode === 'samples' }"
        @click="viewMode = 'samples'"
      >
        🧬 样本
      </button>
    </div>

    <!-- 冰箱列表 -->
    <div v-show="viewMode === 'freezers'" class="freezer-list">
      <div v-if="strain.freezers.length === 0" class="empty-state">
        <div class="empty-icon">❄️</div>
        <p>暂无冰箱</p>
        <p class="empty-hint">点击"添加冰箱"开始管理</p>
      </div>

      <div
        v-for="freezer in strain.freezers"
        :key="freezer.id"
        class="freezer-card"
        :class="{ active: strain.activeFreezerId === freezer.id }"
        @click="selectFreezer(freezer.id)"
      >
        <div class="freezer-icon"></div>
        <div class="freezer-info">
          <div class="freezer-name">{{ freezer.name }}</div>
          <div class="freezer-meta">
            <span class="meta-item">{{ freezer.model }}</span>
            <span class="meta-divider">·</span>
            <span class="meta-item">{{ freezer.location }}</span>
          </div>
          <div class="freezer-stats">
            {{ getTotalCabinets(freezer) }} 柜 · 
            {{ getTotalDrawers(freezer) }} 抽屉 · 
            {{ getTotalBoxes(freezer) }} 个存储位
          </div>
        </div>
        <button class="btn-delete" @click.stop="deleteFreezer(freezer.id)" title="删除冰箱">
          🗑️
        </button>
      </div>
    </div>

    <!-- 样本搜索结果 -->
    <div v-show="viewMode === 'samples'" class="sample-results">
      <div v-if="strain.filteredRecords.length === 0" class="empty-state">
        <div class="empty-icon">🔍</div>
        <p>没有找到匹配的样本</p>
        <p class="empty-hint">请输入关键词搜索</p>
      </div>

      <div
        v-for="group in groupedRecords"
        :key="group.main.id"
        class="sample-card"
        @click="handleSampleClick(group.main)"
      >
        <div class="sample-icon"></div>
        <div class="sample-info">
          <div class="sample-name text-with-badge">
            {{ group.main.name }}
            <span v-if="group.count > 1" class="aliquot-badge">x{{ group.count }} 分装</span>
          </div>
          <div class="sample-meta">
            <span class="meta-badge accession">{{ group.main.accession || 'N/A' }}</span>
            <span class="type-badge" :class="group.main.sequenceType ? group.main.sequenceType.toLowerCase() : ''">
              {{ group.main.sequenceType || '-' }}
            </span>
          </div>
          <div 
            class="sample-location tooltip-native" 
            v-if="group.count > 1"
            :title="`所有存放点:\n${group.positions.join('\n')}`"
          >
            📍 [多处存放] (悬停查看 {{ group.count }} 处位置)
          </div>
          <div class="sample-location" v-else>
            📍 {{ group.positions[0] }}
          </div>
        </div>
      </div>
    </div>

    <!-- 底部调试工具 (仅测试用) -->
    <div class="sidebar-footer">
      <button class="btn-mock" @click="runMockSeed">
        🧪 填充测试数据
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { StrainRecord } from '../../stores/strain'
import { seedMockData } from '../../utils/mockStrainData'
import { useCodeGenerator } from '../../composables/useCodeGenerator'

const strain = useStrainStore()
const appStore = useAppStore()
const codeGen = useCodeGenerator()

const emit = defineEmits(['addFreezer', 'sampleClick'])

const viewMode = ref<'freezers' | 'samples'>('freezers')
const searchKeyword = ref('')

const groupedRecords = computed(() => {
  const map = new Map<string, { main: StrainRecord, count: number, positions: string[] }>()
  for (const record of strain.filteredRecords) {
     const key = record.sampleCode || record.accession || record.id
     if (!map.has(key)) {
       map.set(key, { main: record, count: 1, positions: [getLocationPath(record)] })
     } else {
       const group = map.get(key)!
       group.count++
       group.positions.push(getLocationPath(record))
     }
  }
  return Array.from(map.values())
})

let searchTimer: number | null = null

function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    strain.setSearchFilter('keyword', searchKeyword.value)
    if (searchKeyword.value) {
      viewMode.value = 'samples'
    }
  }, 300)
}

function clearSearch() {
  searchKeyword.value = ''
  strain.resetFilters()
}

function selectFreezer(id: string) {
  strain.setActiveFreezer(id)
}

function deleteFreezer(id: string) {
  const freezer = strain.freezers.find(f => f.id === id)
  if (!freezer) return
  
  if (window.confirm(`确定要删除冰箱"${freezer.name}"吗？\n该操作将同时删除冰箱内的所有样本记录。`)) {
    strain.removeFreezer(id)
    appStore.showNotification('已删除冰箱', 'success')
  }
}

function handleSampleClick(record: StrainRecord) {
  emit('sampleClick', record)
}

function runMockSeed() {
  if (strain.freezers.length === 0) {
    appStore.showNotification('请先添加至少一个冰箱', 'warning')
    return
  }
  seedMockData(strain, codeGen)
  appStore.showNotification('已成功生成 6 条符合 v6 规范的测试样本', 'success')
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

function getTotalCabinets(freezer: any): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    total += shelf.cabinets.length
  }
  return total
}

function getTotalDrawers(freezer: any): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      total += cabinet.drawers.length
    }
  }
  return total
}

function getTotalBoxes(freezer: any): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      for (const drawer of cabinet.drawers) {
        for (const box of drawer.boxes) {
          total += box.rows * box.cols
        }
      }
    }
  }
  return total
}
</script>

<style scoped>
.sidebar-with-search {
  width: 320px;
  min-width: 320px;
  background: white;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 搜索栏 */
.search-section {
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.search-input-wrapper {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.9rem;
}

.search-icon::before {
  content: '🔍';
}

.search-input {
  width: 100%;
  padding: 10px 36px 10px 36px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.85rem;
  transition: all 0.2s;
  background: white;
}

.search-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.clear-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.clear-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

/* 头部 */
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.sidebar-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 12px 0;
}

.btn-add-freezer {
  width: 100%;
  padding: 10px 16px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}

.btn-add-freezer:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 15px rgba(37, 99, 235, 0.3);
}

.icon {
  font-size: 1.2rem;
  font-weight: 700;
}

/* 视图切换 */
.view-toggle {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.toggle-btn {
  flex: 1;
  padding: 8px 12px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-btn:hover {
  border-color: #cbd5e1;
  color: #1e293b;
}

.toggle-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

/* 列表区域 */
.freezer-list,
.sample-results {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state p {
  margin: 4px 0;
  font-size: 0.9rem;
}

.empty-hint {
  font-size: 0.8rem !important;
  color: #cbd5e1;
}

/* 冰箱卡片 */
.freezer-card {
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 10px;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  transition: all 0.2s;
  position: relative;
}

.freezer-card:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.freezer-card.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.15);
}

.freezer-icon {
  font-size: 2rem;
  flex-shrink: 0;
}

.freezer-icon::before {
  content: '🧊';
}

.freezer-info {
  flex: 1;
  min-width: 0;
}

.freezer-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.freezer-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 4px;
}

.meta-item {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-divider {
  color: #cbd5e1;
}

.freezer-stats {
  font-size: 0.7rem;
  color: #94a3b8;
  font-weight: 600;
}

.btn-delete {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  padding: 4px;
  opacity: 0.6;
  transition: all 0.2s;
  flex-shrink: 0;
}

.btn-delete:hover {
  opacity: 1;
  transform: scale(1.1);
}

/* 样本卡片 */
.sample-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 8px;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  transition: all 0.2s;
}

.sample-card:hover {
  border-color: #2563eb;
  background: #eff6ff;
  transform: translateX(2px);
}

.sample-icon {
  font-size: 1.5rem;
  flex-shrink: 0;
}

.sample-icon::before {
  content: '🧬';
}

.sample-info {
  flex: 1;
  min-width: 0;
}

.text-with-badge {
  display: flex;
  align-items: center;
  gap: 8px;
}

.aliquot-badge {
  background: #fdf2f8;
  color: #db2777;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  border: 1px solid #fbcfe8;
}

.tooltip-native {
  cursor: help;
  color: #2563eb !important;
  text-decoration: underline dashed;
  text-underline-offset: 3px;
}

.tt-header {
  font-size: 0.7rem;
  color: #94a3b8;
  margin-bottom: 4px;
  border-bottom: 1px solid #334155;
  padding-bottom: 4px;
}

.tt-row {
  white-space: nowrap;
  font-size: 0.75rem;
  line-height: 1.5;
}

.sample-name {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.meta-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.meta-badge.accession {
  background: #f1f5f9;
  color: #475569;
}

.type-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
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

.sample-location {
  font-size: 0.7rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 底部调试工具 */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.btn-mock {
  width: 100%;
  padding: 8px;
  background: white;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-mock:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
  color: #1e293b;
}
</style>
