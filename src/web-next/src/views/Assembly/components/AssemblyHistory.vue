<script setup lang="ts">
/**
 * AssemblyHistory - 基因组拼接历史任务与队列卡片列表
 */
import type { AssemblyTaskItem } from '../types';

defineProps<{
  tasks: AssemblyTaskItem[];
  activeId: string;
  isLoading: boolean;
}>();

const emit = defineEmits<{
  (e: 'select', item: AssemblyTaskItem): void;
  (e: 'delete', taskId: string): void;
  (e: 'refresh'): void;
}>();

function formatTime(timestamp: number): string {
  if (!timestamp) return '-';
  const d = new Date(timestamp * 1000);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const timeStr = d.toTimeString().slice(0, 8);
  if (isToday) return timeStr;
  return `${d.getMonth() + 1}-${d.getDate()} ${timeStr.slice(0, 5)}`;
}

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'completed': return 'badge-completed';
    case 'running': return 'badge-running';
    case 'queued':
    case 'pending': return 'badge-queued';
    case 'failed':
    case 'error': return 'badge-failed';
    case 'aborted': return 'badge-aborted';
    default: return 'badge-default';
  }
}

function getStatusText(status: string) {
  switch (status) {
    case 'completed': return '已完成';
    case 'running': return '组装中';
    case 'queued':
    case 'pending': return '排队中';
    case 'failed':
    case 'error': return '失败';
    case 'aborted': return '已取消';
    default: return status || '等待中';
  }
}
</script>

<template>
  <div class="assembly-history-container">
    <div class="history-header">
      <span class="total-count">共 {{ tasks.length }} 条记录</span>
      <button class="refresh-btn" :class="{ 'is-loading': isLoading }" @click="emit('refresh')" title="刷新记录">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M23 4v6h-6M1 20v-6h6" />
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
        </svg>
      </button>
    </div>

    <div v-if="tasks.length === 0" class="history-empty">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
        <rect x="2" y="3" width="20" height="18" rx="2" />
        <line x1="8" y1="12" x2="16" y2="12" />
      </svg>
      <p>暂无拼接历史</p>
    </div>

    <div v-else class="history-list scroll-v">
      <div 
        v-for="item in tasks" 
        :key="item.id" 
        class="history-card"
        :class="{ 'is-active': item.id === activeId }"
        @click="emit('select', item)"
      >
        <div class="card-top">
          <span class="task-name" :title="item.name || item.id">{{ item.name || item.id }}</span>
          <span class="status-badge" :class="getStatusBadgeClass(item.status)">
            <span v-if="item.status === 'running'" class="pulse-dot"></span>
            {{ getStatusText(item.status) }}
          </span>
        </div>

        <div class="card-tags">
          <span class="tech-tag">{{ item.tech || 'NGS' }}</span>
          <span v-if="item.sample_type" class="type-tag">{{ item.sample_type }}</span>
          <span class="time-text">{{ formatTime(item.created_at) }}</span>
        </div>

        <div v-if="item.results && item.results.contigs" class="card-stats">
          <span class="stat-pill">Contigs: <b>{{ item.results.contigs }}</b></span>
          <span class="stat-pill">N50: <b>{{ (item.results.n50 / 1000).toFixed(1) }}k</b></span>
          <span class="stat-pill">GC: <b>{{ item.results.gc_percent }}%</b></span>
        </div>

        <div class="card-actions" @click.stop>
          <button class="delete-btn" @click="emit('delete', item.id)" title="删除记录">
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
.assembly-history-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9;
}
.total-count {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
}
.refresh-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #94a3b8;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.refresh-btn:hover {
  color: #2563eb;
  background: #f1f5f9;
}
.refresh-btn.is-loading svg {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #94a3b8;
  font-size: 0.8rem;
  gap: 8px;
}

.history-card {
  position: relative;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.history-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0,0,0,0.03);
}
.history-card.is-active {
  border-color: #3b82f6;
  background: #f8faff;
  box-shadow: 0 0 0 1px #3b82f6;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.task-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.status-badge {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.badge-completed { background: #dcfce7; color: #15803d; }
.badge-running { background: #dbeafe; color: #1d4ed8; }
.badge-queued { background: #fef9c3; color: #a16207; }
.badge-failed { background: #fee2e2; color: #b91c1c; }
.badge-aborted { background: #f1f5f9; color: #64748b; }
.badge-default { background: #f8fafc; color: #64748b; }

.pulse-dot {
  width: 5px;
  height: 5px;
  background: #2563eb;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0% { transform: scale(0.9); opacity: 0.6; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.6; }
}

.card-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
}
.tech-tag {
  background: #f1f5f9;
  color: #475569;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}
.type-tag {
  background: #eff6ff;
  color: #2563eb;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 500;
}
.time-text {
  margin-left: auto;
  color: #94a3b8;
  font-size: 0.68rem;
}

.card-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
  color: #64748b;
  background: #f8fafc;
  padding: 4px 6px;
  border-radius: 4px;
}
.stat-pill b {
  color: #1e293b;
}

.card-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.history-card:hover .card-actions {
  opacity: 1;
}
.delete-btn {
  background: rgba(255,255,255,0.9);
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 3px 4px;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.delete-btn:hover {
  color: #ef4444;
  border-color: #fca5a5;
  background: #fee2e2;
}
</style>
