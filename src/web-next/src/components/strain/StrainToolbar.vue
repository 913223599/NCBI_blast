<template>
  <header class="strain-toolbar">
    <div class="toolbar-left">
      <div
        class="tool-btn"
        :class="{ active: activePanel === 'import' && isSidebarOpen }"
        @click="togglePanel('import')"
      >
        <span class="icon">📥</span>
        <span class="label">数据导入</span>
      </div>
      <div class="tool-divider"></div>
      <div
        class="tool-btn"
        :class="{ active: activePanel === 'filter' && isSidebarOpen }"
        @click="togglePanel('filter')"
      >
        <span class="icon">🔍</span>
        <span class="label">高级筛选</span>
      </div>
      <div class="tool-divider"></div>
      <div
        class="tool-btn"
        :class="{ active: activePanel === 'history' && isSidebarOpen }"
        @click="togglePanel('history')"
      >
        <span class="icon"></span>
        <span class="label">导入历史</span>
      </div>
    </div>

    <div class="toolbar-right">
      <div class="stats-badge">
        <span class="stat-label">总记录</span>
        <span class="stat-value">{{ strain.totalRecords }}</span>
      </div>
      <div class="stats-badge" v-if="strain.selectedCount > 0">
        <span class="stat-label">已选择</span>
        <span class="stat-value highlight">{{ strain.selectedCount }}</span>
      </div>
      <div class="toolbar-actions">
        <button class="btn-secondary" @click="handleExport" :disabled="strain.selectedCount === 0">
          📤 导出
        </button>
        <button class="btn-danger" @click="handleClear" :disabled="!strain.hasData">
          🗑️ 清空
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { getBridge } from '../../bridge/pyqt-bridge'

const strain = useStrainStore()
const appStore = useAppStore()

// 从父组件注入状态
const activePanel = inject('activePanel') as any
const isSidebarOpen = inject('isSidebarOpen') as any

function togglePanel(panel: 'import' | 'filter' | 'history') {
  if (activePanel.value === panel && isSidebarOpen.value) {
    isSidebarOpen.value = false
  } else {
    activePanel.value = panel
    isSidebarOpen.value = true
  }
}

function handleExport() {
  if (strain.selectedCount === 0) {
    appStore.showNotification('请先选择要导出的记录', 'warning')
    return
  }

  try {
    const csvData = strain.exportSelected('csv')
    if (csvData) {
      getBridge().save_file(csvData, 'strain_export.csv')
      appStore.showNotification(`已导出 ${strain.selectedCount} 条记录`, 'success')
    }
  } catch (error) {
    console.error('[Strain] Export failed:', error)
    appStore.showNotification('导出失败', 'error')
  }
}

function handleClear() {
  const input = window.prompt(
    '此操作将永久清空所有菌毒种库数据且不可撤销！\n\n如确认操作，请在下方输入 DELETE 后点击确定：'
  )
  if (input === null) return // 用户取消
  if (input.trim().toUpperCase() !== 'DELETE') {
    appStore.showNotification('校验码不匹配，操作已取消', 'warning')
    return
  }
  strain.clearAll()
  appStore.showNotification('已清空所有数据', 'success')
}
</script>

<style scoped>
.strain-toolbar {
  height: 60px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 100;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  cursor: pointer;
  border-radius: 10px;
  color: #64748b;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  font-weight: 600;
  font-size: 0.82rem;
}

.tool-btn:hover {
  background: #f8fafc;
  color: #1e293b;
}

.tool-btn.active {
  color: #2563eb;
  background: #eff6ff;
}

.tool-btn .icon {
  font-size: 1.2rem;
}

.tool-divider {
  width: 1px;
  height: 24px;
  background: #e2e8f0;
  margin: 0 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stats-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.stat-label {
  font-size: 0.65rem;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1e293b;
}

.stat-value.highlight {
  color: #2563eb;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.btn-secondary,
.btn-danger {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-secondary {
  background: #f1f5f9;
  color: #475569;
}

.btn-secondary:hover:not(:disabled) {
  background: #e2e8f0;
}

.btn-danger {
  background: #fee2e2;
  color: #dc2626;
}

.btn-danger:hover:not(:disabled) {
  background: #fecaca;
}

.btn-secondary:disabled,
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>