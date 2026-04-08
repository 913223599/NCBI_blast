<template>
  <div class="strain-workspace-container">
    <!-- 左侧冰箱列表（集成搜索） -->
    <StrainSidebar 
      @addFreezer="showAddDialog = true" 
      @sampleClick="handleSampleClick"
    />

    <!-- 右侧详情区 -->
    <main class="strain-content">
      <!-- 顶部工具栏 -->
      <div class="top-toolbar">
        <div class="toolbar-left">
          <button
            class="toolbar-btn"
            :class="{ active: currentView === 'freezer' }"
            @click="currentView = 'freezer'"
          >
            📋 平铺视图
          </button>
          <button
            class="toolbar-btn"
            :class="{ active: currentView === 'stats' }"
            @click="currentView = 'stats'"
          >
            📊 统计分析
          </button>
        </div>
        <div class="toolbar-right">
          <span class="shortcuts-hint">Ctrl+N: 添加冰箱 | Ctrl+I: 批量导入 | Ctrl+H: 帮助</span>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="content-area">
        <!-- 冰箱详情 -->
        <FreezerDetailPanel
          v-if="currentView === 'freezer'"
          @showSampleDetail="handleShowSampleDetail"
        />

        <!-- 统计面板 -->
        <StatisticsPanel v-if="currentView === 'stats'" />
      </div>
    </main>

    <!-- 添加冰箱对话框 -->
    <AddFreezerDialog 
      v-if="showAddDialog" 
      @close="showAddDialog = false"
      @added="handleFreezerAdded"
    />

    <!-- 批量导入对话框 -->
    <BatchImportDialog
      v-if="showBatchImport"
      @close="showBatchImport = false"
      @imported="handleBatchImported()"
    />

    <!-- 样本详情对话框 -->
    <SampleDetailDialog
      v-if="showSampleDetail && selectedSample"
      :record="selectedSample"
      @close="showSampleDetail = false"
      @deleted="handleSampleDeleted"
    />

    <!-- 快捷键帮助对话框 -->
    <KeyboardShortcutsHelp
      :visible="showShortcutsHelp"
      @close="showShortcutsHelp = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import StrainSidebar from '../components/strain/StrainSidebar.vue'
import FreezerDetailPanel from '../components/strain/FreezerDetailPanel.vue'
import StatisticsPanel from '../components/strain/StatisticsPanel.vue'
import AddFreezerDialog from '../components/strain/AddFreezerDialog.vue'
import BatchImportDialog from '../components/strain/BatchImportDialog.vue'
import SampleDetailDialog from '../components/strain/SampleDetailDialog.vue'
import KeyboardShortcutsHelp from '../components/strain/KeyboardShortcutsHelp.vue'
import { useStrainStore } from '../stores/strain'
import type { StrainRecord } from '../stores/strain'

const strain = useStrainStore()
const showAddDialog = ref(false)
const showBatchImport = ref(false)
const showShortcutsHelp = ref(false)
const currentView = ref<'freezer' | 'stats'>('freezer')

// 样本详情
const showSampleDetail = ref(false)
const selectedSample = ref<StrainRecord | null>(null)

function handleFreezerAdded(freezerId: string) {
  strain.setActiveFreezer(freezerId)
}

function handleSampleClick(record: StrainRecord) {
  selectedSample.value = record
  showSampleDetail.value = true
}

function handleShowSampleDetail(record: StrainRecord) {
  selectedSample.value = record
  showSampleDetail.value = true
}

function handleSampleDeleted() {
  showSampleDetail.value = false
  selectedSample.value = null
}

function handleBatchImported() {
  // 刷新统计
  if (currentView.value === 'stats') {
    // 触发重新计算
  }
}

// 快捷键支持
function handleKeyboard(e: KeyboardEvent) {
  // 忽略输入框中的按键
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
    return
  }

  // Ctrl+N: 添加冰箱
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault()
    showAddDialog.value = true
  }
  // Ctrl+I: 批量导入
  if (e.ctrlKey && e.key === 'i') {
    e.preventDefault()
    showBatchImport.value = true
  }
  // Ctrl+H: 显示快捷键帮助
  if (e.ctrlKey && e.key === 'h') {
    e.preventDefault()
    showShortcutsHelp.value = true
  }
  // Ctrl+S: 保存（浏览器默认行为）
  if (e.ctrlKey && e.key === 's') {
    e.preventDefault()
    // 数据已自动保存到 localStorage
  }
  // Esc: 关闭对话框
  if (e.key === 'Escape') {
    showAddDialog.value = false
    showBatchImport.value = false
    showSampleDetail.value = false
    showShortcutsHelp.value = false
  }
  // 数字键切换视图
  if (e.key === '1') {
    currentView.value = 'freezer'
  }
  if (e.key === '2') {
    currentView.value = 'stats'
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeyboard)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyboard)
})
</script>

<style scoped>
.strain-workspace-container {
  display: flex;
  height: 100%;
  background: #f8fafc;
  overflow: hidden;
}

.strain-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* 顶部工具栏 */
.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  padding: 12px 20px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
  z-index: 10;
}

/* 内容区域 */
.content-area {
  flex: 1;
  overflow: auto;
  background: #f8fafc;
  padding: 20px;
}

.toolbar-left {
  display: flex;
  gap: 12px;
}

.toolbar-btn {
  padding: 8px 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.toolbar-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.toolbar-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
}

.toolbar-right {
  flex: 1;
  display: flex;
  justify-content: flex-end;
}

/* 快捷键提示 */
.shortcuts-hint {
  background: rgba(15, 23, 42, 0.8);
  color: white;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 0.7rem;
  backdrop-filter: blur(8px);
  white-space: nowrap;
}

.hint-text {
  font-weight: 500;
  letter-spacing: 0.02em;
}
</style>
