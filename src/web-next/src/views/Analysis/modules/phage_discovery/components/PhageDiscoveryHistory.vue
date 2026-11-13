<script setup lang="ts">
import type { PhageTaskRecord } from '../types'

defineProps<{
  tasks: PhageTaskRecord[]
  activeTaskId?: string
}>()

const emit = defineEmits<{
  (e: 'select', task: PhageTaskRecord): void
  (e: 'delete', taskId: string): void
}>()

function formatDate(dateStr?: string): string {
  if (!dateStr) return '--'
  return dateStr.slice(5, 16)
}

function getStatusText(status: PhageTaskRecord['status']): string {
  const map: Record<PhageTaskRecord['status'], string> = {
    queued: '排队中',
    running: '扫描中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已中止',
  }
  return map[status] || status
}
</script>

<template>
  <div class="history-list-container">
    <div v-if="tasks.length === 0" class="empty-history">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="1.6">
        <circle cx="12" cy="12" r="9" />
        <path d="M9 12h6M12 9v6" />
      </svg>
      <p>暂无前噬菌体扫描记录</p>
      <span class="empty-sub">提交任务后历史将持久保存于本地</span>
    </div>

    <div
      v-for="item in tasks"
      :key="item.task_id"
      class="history-item"
      :class="{ active: item.task_id === activeTaskId }"
      @click="emit('select', item)"
    >
      <div class="item-main">
        <div class="item-top">
          <span class="item-title" :title="item.task_name">{{ item.task_name || item.task_id }}</span>
          <span class="status-pill" :class="item.status">{{ getStatusText(item.status) }}</span>
        </div>

        <div class="item-meta">
          <span class="tag-badge version">V4.2</span>
          <span class="tag-badge device">{{ String(item.device || 'cpu').toUpperCase() }}</span>
          <span v-if="item.apply_protein_gate" class="tag-badge gate">蛋白门控</span>
          <span v-if="item.status === 'completed' && item.summary?.region_count !== undefined" class="hit-badge">
            {{ item.summary.region_count }} 个前噬菌体
          </span>
        </div>

        <div v-if="item.status === 'running' || item.status === 'queued'" class="mini-progress-bar">
          <div class="mini-progress-fill" :style="{ width: `${Math.max(4, item.progress || 0)}%` }"></div>
        </div>

        <div class="item-footer">
          <span class="time-text">{{ formatDate(item.created_at) }}</span>
          <button
            type="button"
            class="delete-btn"
            title="删除扫描记录与输出文件"
            @click.stop="emit('delete', item.task_id)"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-list-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-history {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 28px 10px;
  color: #94a3b8;
  gap: 6px;
}

.empty-history p {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.empty-sub {
  font-size: 11px;
  color: #94a3b8;
}

.history-item {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  background: #ffffff;
  transition: all 0.16s ease;
}

.history-item:hover {
  border-color: #93c5fd;
  background: #f8fafc;
}

.history-item.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.08);
}

.item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 6px;
}

.item-title {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 99px;
}

.status-pill.completed {
  background: #dcfce7;
  color: #15803d;
}

.status-pill.running,
.status-pill.queued {
  background: #dbeafe;
  color: #1d4ed8;
}

.status-pill.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.status-pill.cancelled {
  background: #f1f5f9;
  color: #64748b;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.tag-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
}

.tag-badge.version {
  background: #eef2ff;
  color: #4338ca;
}

.tag-badge.device {
  background: #f1f5f9;
  color: #475569;
}

.tag-badge.gate {
  background: #ecfeff;
  color: #0e7490;
}

.hit-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: #fef3c7;
  color: #b45309;
}

.mini-progress-bar {
  height: 4px;
  background: #e2e8f0;
  border-radius: 99px;
  overflow: hidden;
  margin: 4px 0 6px;
}

.mini-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #0ea5e9);
  transition: width 0.3s ease;
}

.item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.time-text {
  font-size: 11px;
  color: #94a3b8;
}

.delete-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.delete-btn:hover {
  color: #dc2626;
  background: #fee2e2;
}
</style>

