<template>
  <div class="history-panel">
    <h3 class="panel-title">导入历史</h3>

    <div v-if="strain.importTasks.length === 0" class="empty-state">
      <div class="empty-icon">📋</div>
      <p>暂无导入记录</p>
      <p class="empty-hint">导入数据后将在此显示历史记录</p>
    </div>

    <div v-else class="task-list">
      <div
        v-for="task in strain.importTasks"
        :key="task.taskId"
        class="task-card"
        :class="{ active: strain.activeTaskId === task.taskId }"
        @click="selectTask(task.taskId)"
      >
        <div class="task-header">
          <div class="task-name">{{ task.fileName }}</div>
          <button class="task-delete" @click.stop="deleteTask(task.taskId)">✕</button>
        </div>

        <div class="task-meta">
          <span class="task-status" :class="task.status">
            {{ getStatusLabel(task.status) }}
          </span>
          <span class="task-count">{{ task.recordCount }} 条记录</span>
        </div>

        <div v-if="['queued', 'running'].includes(task.status)" class="progress-container">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: task.progress + '%' }"></div>
          </div>
          <span class="progress-text">{{ task.progress }}%</span>
        </div>

        <div class="task-time">
          {{ formatTime(task.startTime) }}
        </div>
      </div>
    </div>

    <div v-if="strain.importTasks.length > 0" class="history-actions">
      <button class="btn-clear" @click="clearAllTasks">清空历史</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

const strain = useStrainStore()
const appStore = useAppStore()

function selectTask(taskId: string) {
  strain.activeTaskId = taskId
}

function deleteTask(taskId: string) {
  strain.removeTask(taskId)
  appStore.showNotification('已删除导入记录', 'success')
}

function clearAllTasks() {
  if (window.confirm('确定要清空所有导入历史吗？')) {
    strain.clearTasks()
    appStore.showNotification('已清空导入历史', 'success')
  }
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '导入中',
    done: '已完成',
    error: '失败',
    cancelled: '已取消'
  }
  return labels[status] || status
}

function formatTime(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (hours < 24) return `${hours} 小时前`
  return `${days} 天前`
}
</script>

<style scoped>
.history-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
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

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.task-card:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.task-card.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.task-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-delete {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 1rem;
  padding: 4px;
  border-radius: 4px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.task-delete:hover {
  color: #dc2626;
  background: #fee2e2;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.task-status {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}

.task-status.queued {
  background: #fef3c7;
  color: #92400e;
}

.task-status.running {
  background: #dbeafe;
  color: #1e40af;
}

.task-status.done {
  background: #d1fae5;
  color: #065f46;
}

.task-status.error,
.task-status.cancelled {
  background: #fee2e2;
  color: #991b1b;
}

.task-count {
  font-size: 0.75rem;
  color: #64748b;
}

.progress-container {
  margin-bottom: 8px;
}

.progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 4px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #3b82f6);
  border-radius: 3px;
  transition: transform 0.3s; backface-visibility: hidden; -webkit-backface-visibility: hidden; transform-origin: left; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.progress-text {
  font-size: 0.7rem;
  color: #64748b;
}

.task-time {
  font-size: 0.75rem;
  color: #94a3b8;
}

.history-actions {
  padding-top: 8px;
  border-top: 1px solid #e2e8f0;
}

.btn-clear {
  width: 100%;
  padding: 10px;
  background: #f1f5f9;
  border: none;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-clear:hover {
  background: #e2e8f0;
}
</style>