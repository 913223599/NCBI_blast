<template>
  <aside class="freezer-sidebar">
    <div class="sidebar-header">
      <h3 class="sidebar-title">🧊 保藏管理</h3>
      <button class="btn-add-freezer" @click="emit('addFreezer')">
        <span class="icon">+</span>
        <span>添加冰箱</span>
      </button>
    </div>

    <div class="freezer-list">
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
        <div class="freezer-icon">🧊</div>
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
  </aside>
</template>

<script setup lang="ts">
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

const strain = useStrainStore()
const appStore = useAppStore()

const emit = defineEmits(['addFreezer'])

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
.freezer-sidebar {
  width: 320px;
  min-width: 320px;
  background: white;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #e2e8f0;
}

.sidebar-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 16px 0;
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
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-add-freezer:hover {
  transform: translateY(-1px);
}

.icon {
  font-size: 1.2rem;
  font-weight: 700;
}

.freezer-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
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

.freezer-card {
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 12px;
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  position: relative;
}

.freezer-card:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
  transform: translateY(-2px);
}

.freezer-card.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.freezer-icon {
  font-size: 2rem;
  flex-shrink: 0;
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
  font-size: 0.8rem;
  color: #64748b;
  margin-bottom: 4px;
}

.meta-divider {
  color: #cbd5e1;
}

.freezer-stats {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 600;
}

.btn-delete {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  padding: 4px;
  border-radius: 6px;
  opacity: 0;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.freezer-card:hover .btn-delete {
  opacity: 1;
}

.btn-delete:hover {
  background: #fee2e2;
}
</style>