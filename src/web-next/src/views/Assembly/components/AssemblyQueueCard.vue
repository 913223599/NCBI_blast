<script setup lang="ts">
/**
 * AssemblyQueueCard - 基因组拼接任务排队等待卡片
 */
import type { AssemblyTaskItem, AssemblyQueueStatus } from '../types';

defineProps<{
  task: AssemblyTaskItem;
  queueStatus: AssemblyQueueStatus | null;
}>();

const emit = defineEmits<{
  (e: 'cancel'): void;
  (e: 'start-new'): void;
}>();
</script>

<template>
  <div class="queue-card-container">
    <div class="queue-card">
      <!-- 顶部排队动画 -->
      <div class="queue-animation">
        <div class="pulse-ring"></div>
        <div class="queue-icon-circle">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </div>
      </div>

      <!-- 排队文案 -->
      <h3 class="queue-title">拼接任务正在排队中</h3>
      <p class="queue-subtitle">
        当前任务: <span class="highlight-name">{{ task.name }}</span>
      </p>

      <div class="queue-badge-row">
        <div class="queue-position-box">
          <span class="pos-label">当前队列位次</span>
          <span class="pos-number">#{{ task.queue_position || 1 }}</span>
        </div>
        <div v-if="queueStatus?.running_task" class="running-info-box">
          <span class="run-label">当前正在执行</span>
          <span class="run-name">{{ queueStatus.running_task.name || queueStatus.running_task.id }}</span>
        </div>
      </div>

      <p class="queue-desc">
        系统采用严格串行持久化调度以保障运算稳定性与显存安全。前置任务完成后将自动触发本任务计算。
      </p>

      <!-- 操作按钮 -->
      <div class="queue-actions">
        <button class="btn-cancel" @click="emit('cancel')">取消排队</button>
        <button class="btn-new" @click="emit('start-new')">创建其他任务</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.queue-card-container {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px 20px;
}

.queue-card {
  width: 100%;
  max-width: 520px;
  background: white;
  border: 1px solid #fde68a;
  border-radius: 16px;
  padding: 36px 28px;
  text-align: center;
  box-shadow: 0 10px 25px -5px rgba(217, 119, 6, 0.08);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.queue-animation {
  position: relative;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 6px;
}
.queue-icon-circle {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: #fef3c7;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
}
.pulse-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(245, 158, 11, 0.2);
  animation: pulse-wave 2s infinite ease-out;
}
@keyframes pulse-wave {
  0% { transform: scale(0.8); opacity: 0.8; }
  100% { transform: scale(1.4); opacity: 0; }
}

.queue-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #92400e;
  margin: 0;
}
.queue-subtitle {
  font-size: 0.85rem;
  color: #64748b;
  margin: 0;
}
.highlight-name {
  font-weight: 600;
  color: #1e293b;
}

.queue-badge-row {
  display: flex;
  gap: 12px;
  margin: 10px 0;
  width: 100%;
}
.queue-position-box, .running-info-box {
  flex: 1;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pos-label, .run-label {
  font-size: 0.7rem;
  color: #b45309;
  font-weight: 600;
}
.pos-number {
  font-size: 1.5rem;
  font-weight: 800;
  color: #d97706;
}
.run-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-desc {
  font-size: 0.78rem;
  color: #94a3b8;
  line-height: 1.5;
  margin: 0;
}

.queue-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  width: 100%;
}
.btn-cancel, .btn-new {
  flex: 1;
  height: 40px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-cancel {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #475569;
}
.btn-cancel:hover {
  background: #fee2e2;
  color: #ef4444;
  border-color: #fca5a5;
}
.btn-new {
  background: #2563eb;
  border: none;
  color: white;
}
.btn-new:hover {
  background: #1d4ed8;
}
</style>
