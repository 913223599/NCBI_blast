<script setup lang="ts">
import type { StructureQueueSnapshot, StructureTaskHistoryItem } from '../types'

defineProps<{
  task: StructureTaskHistoryItem
  queueStatus: StructureQueueSnapshot
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'start-new'): void
}>()
</script>

<template>
  <div class="queue-card">
    <div class="queue-badge">任务排队等待中</div>
    <h3>{{ task.task_name }}</h3>
    <p class="queue-desc">
      当前预测队列正在执行前置任务（运行中: {{ queueStatus.running_count }}，队列排队: {{ queueStatus.queued_count }}）。
      <span v-if="task.queue_position">您的排队序号为第 {{ task.queue_position }} 位。</span>
    </p>

    <div class="queue-actions">
      <button type="button" class="btn-cancel" @click="emit('cancel')">取消排队</button>
      <button type="button" class="btn-new" @click="emit('start-new')">继续提交新任务</button>
    </div>
  </div>
</template>

<style scoped>
.queue-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 36px 28px;
  text-align: center;
  max-width: 620px;
  margin: 40px auto;
}

.queue-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
  font-size: 0.8rem;
  font-weight: 700;
  margin-bottom: 12px;
}

h3 {
  margin: 0 0 10px 0;
  font-size: 1.15rem;
  color: #0f172a;
}

.queue-desc {
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.6;
  margin-bottom: 22px;
}

.queue-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}

.btn-cancel,
.btn-new {
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-cancel {
  background: #fff1f2;
  color: #e11d48;
  border: 1px solid #fecdd3;
}

.btn-new {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}
</style>
