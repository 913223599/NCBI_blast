<script setup lang="ts">
import { computed } from 'vue'
import type { StructureQueueSnapshot, StructureTaskHistoryItem } from '../types'

const props = defineProps<{
  task: StructureTaskHistoryItem
  queueStatus: StructureQueueSnapshot
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'start-new'): void
  (e: 'view-task', taskId: string): void
}>()

const runningMeta = computed(() => props.queueStatus.running_tasks?.[0] || null)
const waitingList = computed(() => props.queueStatus.waiting_tasks || [])
</script>

<template>
  <div class="queue-card">
    <div class="queue-badge">自动队列排队等待中</div>
    <h3>{{ task.task_name }}</h3>
    <p class="queue-desc">
      当前后台结构预测队列正在依次自动处理（运行中: {{ queueStatus.running_count }}，等待中: {{ queueStatus.queued_count }}）。
      <span v-if="task.queue_position">本任务当前排在第 {{ task.queue_position }} 位，前序完成后将自动接续分析。</span>
    </p>

    <div v-if="runningMeta" class="running-preview">
      <div class="rp-info">
        <span class="rp-tag">正在运行</span>
        <span class="rp-name" :title="runningMeta.task_name">{{ runningMeta.task_name }}</span>
      </div>
      <button type="button" class="rp-link" @click="emit('view-task', runningMeta.task_id)">
        查看进度
      </button>
    </div>

    <div v-if="waitingList.length > 1" class="waiting-list-box">
      <div class="wl-head">待运行排队序列 ({{ waitingList.length }})</div>
      <div v-for="(w, idx) in waitingList.slice(0, 6)" :key="w.task_id" class="wl-row" :class="{ self: w.task_id === task.task_id }">
        <span class="wl-pos">#{{ w.position || idx + 1 }}</span>
        <span class="wl-name">{{ w.task_name }}</span>
        <span v-if="w.task_id === task.task_id" class="wl-self">当前查看</span>
      </div>
      <div v-if="waitingList.length > 6" class="wl-more">其余 {{ waitingList.length - 6 }} 项可在左侧记录栏随时切换查看</div>
    </div>

    <div class="queue-actions">
      <button type="button" class="btn-cancel" @click="emit('cancel')">取消排队</button>
      <button type="button" class="btn-new" @click="emit('start-new')">继续批量导入</button>
    </div>
  </div>
</template>

<style scoped>
.queue-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 30px 28px;
  text-align: center;
  max-width: 660px;
  margin: 24px auto;
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
  font-size: 1.12rem;
  color: #0f172a;
}

.queue-desc {
  color: #64748b;
  font-size: 0.88rem;
  line-height: 1.6;
  margin-bottom: 18px;
}

.running-preview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  margin-bottom: 14px;
  text-align: left;
}

.rp-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.rp-tag {
  font-size: 0.72rem;
  font-weight: 700;
  color: #1d4ed8;
  background: #dbeafe;
  padding: 2px 7px;
  border-radius: 999px;
  flex-shrink: 0;
}

.rp-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rp-link {
  padding: 4px 10px;
  border-radius: 6px;
  background: #2563eb;
  color: #ffffff;
  font-size: 0.78rem;
  font-weight: 600;
  flex-shrink: 0;
}

.waiting-list-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 20px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wl-head {
  font-size: 0.78rem;
  font-weight: 700;
  color: #475569;
  margin-bottom: 2px;
}

.wl-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  padding: 5px 8px;
  border-radius: 7px;
  background: #ffffff;
  border: 1px solid #f1f5f9;
}

.wl-row.self {
  border-color: #fcd34d;
  background: #fffbeb;
}

.wl-pos {
  font-family: ui-monospace, monospace;
  font-weight: 700;
  color: #b45309;
  min-width: 24px;
}

.wl-name {
  flex: 1;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wl-self {
  font-size: 0.72rem;
  color: #b45309;
  font-weight: 700;
}

.wl-more {
  font-size: 0.75rem;
  color: #64748b;
  padding-top: 2px;
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
