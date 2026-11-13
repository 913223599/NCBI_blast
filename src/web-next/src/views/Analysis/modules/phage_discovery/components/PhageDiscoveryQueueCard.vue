<script setup lang="ts">
import { computed } from 'vue'
import type { PhageQueueSnapshot, PhageTaskRecord } from '../types'

const props = defineProps<{
  task: PhageTaskRecord
  queueStatus: PhageQueueSnapshot
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'start-new'): void
}>()

const realPosition = computed(() => {
  const waitingList = props.queueStatus.waiting_tasks || []
  const matched = waitingList.find((item) => item.task_id === props.task.task_id)
  if (matched && typeof matched.position === 'number') {
    return matched.position
  }
  const idx = (props.queueStatus.queued || []).indexOf(props.task.task_id)
  if (idx >= 0) {
    return idx + 1
  }
  return props.task.queue_position || 1
})

const runningAheadTask = computed(() => {
  const runningTasks = props.queueStatus.running_tasks || []
  if (runningTasks.length > 0) {
    return runningTasks[0]
  }
  const runningIds = props.queueStatus.running || []
  if (runningIds.length > 0) {
    return { task_id: runningIds[0], task_name: runningIds[0] }
  }
  return null
})
</script>

<template>
  <div class="phage-queue-card">
    <div class="queue-card-inner">
      <div class="queue-icon-wrapper">
        <div class="pulse-ring"></div>
        <div class="queue-icon">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </div>
      </div>

      <div class="queue-title-block">
        <h3>前噬菌体扫描任务正在排队等待中</h3>
        <div class="queue-badge-row">
          <div class="queue-position-badge">
            当前队列位次 <span>#{{ realPosition }}</span>
          </div>
          <div v-if="runningAheadTask" class="running-ahead-badge">
            正在执行 <span>{{ runningAheadTask.task_name || runningAheadTask.task_id }}</span>
          </div>
        </div>
      </div>

      <p class="queue-tip">
        Student V4.2 引擎采用单任务严格串行调度以保障物理显存安全与识别稳定性。前序扫描任务完成后，系统将自动启动本任务。
      </p>

      <div class="task-details-grid">
        <div class="detail-item">
          <span class="label">任务名称</span>
          <span class="val" :title="task.task_name">{{ task.task_name }}</span>
        </div>
        <div class="detail-item">
          <span class="label">任务 ID</span>
          <span class="val font-mono">{{ task.task_id }}</span>
        </div>
        <div class="detail-item">
          <span class="label">计算设备</span>
          <span class="val">{{ String(task.device || 'auto').toUpperCase() }}</span>
        </div>
        <div class="detail-item">
          <span class="label">标志蛋白门控</span>
          <span class="val">{{ task.apply_protein_gate ? '已开启 (BLASTp)' : '未开启 (纯模型)' }}</span>
        </div>
        <div class="detail-item full-width">
          <span class="label">提交时间</span>
          <span class="val">{{ task.created_at }}</span>
        </div>
      </div>

      <div class="queue-actions">
        <button type="button" class="cancel-queue-btn" @click="emit('cancel')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          <span>取消排队</span>
        </button>

        <button type="button" class="new-more-btn" @click="emit('start-new')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>继续提交新任务</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.phage-queue-card {
  background: white;
  border: 1px solid #fde68a;
  border-radius: 12px;
  padding: 36px 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  box-shadow: 0 8px 20px -6px rgba(217, 119, 6, 0.1);
}

.queue-card-inner {
  width: 100%;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 16px;
}

.queue-icon-wrapper {
  position: relative;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pulse-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid #f59e0b;
  opacity: 0.45;
  animation: queuePulse 1.8s ease-out infinite;
}

@keyframes queuePulse {
  0% {
    transform: scale(0.85);
    opacity: 0.65;
  }
  100% {
    transform: scale(1.22);
    opacity: 0;
  }
}

.queue-icon {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: #fef3c7;
  display: flex;
  align-items: center;
  justify-content: center;
}

.queue-title-block h3 {
  margin: 0 0 10px;
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}

.queue-badge-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.queue-position-badge,
.running-ahead-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
}

.queue-position-badge {
  background: #fffbeb;
  border: 1px solid #fcd34d;
  color: #b45309;
}

.queue-position-badge span {
  font-weight: 800;
  font-size: 13px;
}

.running-ahead-badge {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
}

.running-ahead-badge span {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
}

.queue-tip {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
  max-width: 480px;
}

.task-details-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  text-align: left;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.detail-item.full-width {
  grid-column: 1 / -1;
}

.detail-item .label {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.detail-item .val {
  font-size: 13px;
  color: #1e293b;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.font-mono {
  font-family: 'Consolas', monospace;
}

.queue-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}

.cancel-queue-btn,
.new-more-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.cancel-queue-btn {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
}

.cancel-queue-btn:hover {
  background: #fee2e2;
}

.new-more-btn {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
}

.new-more-btn:hover {
  background: #dbeafe;
}
</style>
