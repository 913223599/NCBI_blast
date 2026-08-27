<script setup lang="ts">
import { computed } from 'vue';
import type { AnnotationTaskItem, AnnotationQueueStatus } from '../types';

const props = defineProps<{
  task: AnnotationTaskItem;
  queueStatus?: AnnotationQueueStatus | null;
}>();

const emit = defineEmits<{
  (e: 'cancel', taskId: string): void;
  (e: 'start-new'): void;
}>();

const realPosition = computed(() => {
  if (props.queueStatus?.waiting_tasks) {
    const match = props.queueStatus.waiting_tasks.find(w => w.task_id === props.task.task_id);
    if (match && typeof match.position === 'number') {
      return match.position;
    }
  }
  return props.task.position || 1;
});
</script>

<template>
  <div class="annotation-queue-card">
    <div class="queue-card-inner">
      <div class="queue-icon-wrapper">
        <div class="pulse-ring"></div>
        <div class="queue-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </div>
      </div>

      <div class="queue-status-title">
        <h3>任务正在排队等待中</h3>
        <div class="queue-position-badge">
          排队位次 <span>#{{ realPosition }}</span>
        </div>
      </div>

      <p class="queue-tip">
        计算引擎当前正在处理前序分析任务。系统将在前序任务完成后按顺序自动启动该任务，无需停留在本页面。
      </p>

      <div class="task-details-grid">
        <div class="detail-item">
          <span class="label">任务名称</span>
          <span class="val">{{ task.task_name }}</span>
        </div>
        <div class="detail-item">
          <span class="label">任务 ID</span>
          <span class="val font-mono">{{ task.task_id }}</span>
        </div>
        <div class="detail-item">
          <span class="label">生物类型</span>
          <span class="val">{{ task.sample_type }}</span>
        </div>
        <div class="detail-item">
          <span class="label">注释引擎</span>
          <span class="val">{{ task.engine }}</span>
        </div>
        <div class="detail-item full-width">
          <span class="label">提交时间</span>
          <span class="val">{{ task.created_at }}</span>
        </div>
      </div>

      <div class="queue-actions">
        <button class="cancel-queue-btn" type="button" @click="emit('cancel', task.task_id)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          取消排队
        </button>

        <button class="new-more-btn" type="button" @click="emit('start-new')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          继续提交新任务
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotation-queue-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 40px 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 480px;
}

.queue-card-inner {
  max-width: 560px;
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.queue-icon-wrapper {
  position: relative;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.queue-icon {
  width: 64px;
  height: 64px;
  background: #eff6ff;
  border: 2px solid #bfdbfe;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 2;
}

.pulse-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(37, 99, 235, 0.15);
  animation: pulse-wave 2s infinite ease-out;
  z-index: 1;
}

@keyframes pulse-wave {
  0% {
    transform: scale(0.8);
    opacity: 1;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

.queue-status-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.queue-status-title h3 {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.queue-position-badge {
  background: #dbeafe;
  color: #1e40af;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid #bfdbfe;
}

.queue-position-badge span {
  font-size: 14px;
  font-weight: 800;
  color: #2563eb;
}

.queue-tip {
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
  margin-bottom: 24px;
  max-width: 480px;
}

.task-details-grid {
  width: 100%;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px 20px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 24px;
  text-align: left;
  margin-bottom: 28px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-item.full-width {
  grid-column: 1 / -1;
}

.detail-item .label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
}

.detail-item .val {
  font-size: 13px;
  color: #334155;
  font-weight: 600;
}

.font-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.queue-actions {
  display: flex;
  gap: 14px;
}

.cancel-queue-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  background: white;
  border: 1px solid #fca5a5;
  color: #dc2626;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.cancel-queue-btn:hover {
  background: #fef2f2;
  border-color: #f87171;
}

.new-more-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  background: #2563eb;
  border: 1px solid #2563eb;
  color: white;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.new-more-btn:hover {
  background: #1d4ed8;
}
</style>
