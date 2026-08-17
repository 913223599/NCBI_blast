<script setup lang="ts">
/**
 * AnnotationHistory - 注释任务历史列表侧边栏
 */
import type { AnnotationTaskItem } from '../types';

defineProps<{
  tasks: AnnotationTaskItem[];
  activeId: string;
  isLoading: boolean;
}>();

const emit = defineEmits<{
  (e: 'select', task: AnnotationTaskItem): void;
  (e: 'delete', taskId: string): void;
  (e: 'refresh'): void;
}>();

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'completed': return 'badge-success';
    case 'running': return 'badge-running';
    case 'failed': return 'badge-failed';
    case 'cancelled': return 'badge-cancelled';
    default: return 'badge-pending';
  }
}

function getStatusText(status: string) {
  switch (status) {
    case 'completed': return '已完成';
    case 'running': return '分析中';
    case 'failed': return '失败';
    case 'cancelled': return '已取消';
    default: return '排队中';
  }
}
</script>

<template>
  <div class="annotation-history-panel">
    <div class="history-toolbar">
      <span class="history-count">共 {{ tasks.length }} 条记录</span>
      <button class="refresh-btn" @click="emit('refresh')" :title="'刷新列表'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
        </svg>
      </button>
    </div>

    <div v-if="isLoading" class="history-loading">
      <div class="mini-spinner"></div>
      <span>载入中...</span>
    </div>

    <div v-else-if="tasks.length === 0" class="history-empty">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
      <p>暂无历史注释记录</p>
    </div>

    <div v-else class="task-list">
      <div
        v-for="item in tasks"
        :key="item.task_id"
        :class="['task-card', { active: activeId === item.task_id }]"
        @click="emit('select', item)"
      >
        <div class="task-header">
          <span class="task-name" :title="item.task_name">{{ item.task_name }}</span>
          <span :class="['status-badge', getStatusBadgeClass(item.status)]">
            {{ getStatusText(item.status) }}
          </span>
        </div>

        <div class="task-meta">
          <span class="meta-tag">{{ item.sample_type }}</span>
          <span class="meta-time">{{ item.created_at?.split(' ')[1] || item.created_at }}</span>
        </div>

        <div v-if="item.status === 'running'" class="task-progress-mini">
          <div class="progress-bar-fill" :style="{ width: `${item.progress}%` }"></div>
        </div>

        <div v-if="item.summary && item.status === 'completed'" class="task-summary-mini">
          <span>CDS: {{ item.summary.cds_count }}</span>
          <span>GC: {{ item.summary.gc_content }}%</span>
        </div>

        <button 
          class="delete-btn" 
          @click.stop="emit('delete', item.task_id)" 
          title="删除该记录"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotation-history-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.history-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 0 4px;
}

.history-count {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.refresh-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #64748b;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: #f1f5f9;
  color: #3b82f6;
}

.history-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #94a3b8;
  padding: 20px 0;
  justify-content: center;
}

.mini-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.history-empty {
  text-align: center;
  padding: 36px 12px;
  color: #94a3b8;
}

.history-empty p {
  font-size: 12px;
  margin-top: 8px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.task-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-card:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.task-card.active {
  background: #eff6ff;
  border-color: #3b82f6;
  box-shadow: 0 0 0 1px #3b82f6;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.task-name {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.status-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.badge-success { background: #dcfce7; color: #166534; }
.badge-running { background: #dbeafe; color: #1e40af; }
.badge-failed { background: #fee2e2; color: #991b1b; }
.badge-cancelled { background: #f1f5f9; color: #64748b; }
.badge-pending { background: #fef3c7; color: #92400e; }

.task-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: #64748b;
}

.meta-tag {
  background: #e2e8f0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
}

.task-progress-mini {
  margin-top: 6px;
  height: 4px;
  background: #e2e8f0;
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: #3b82f6;
  transition: width 0.3s ease;
}

.task-summary-mini {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #475569;
  font-weight: 600;
}

.delete-btn {
  position: absolute;
  right: 6px;
  bottom: 6px;
  background: transparent;
  border: none;
  color: #94a3b8;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0;
  transition: all 0.2s;
}

.task-card:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
