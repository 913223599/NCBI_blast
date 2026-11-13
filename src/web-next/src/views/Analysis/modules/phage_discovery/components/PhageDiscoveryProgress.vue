<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { PhageLogItem } from '../types'

const props = defineProps<{
  progress: number
  currentStep: string
  logs: PhageLogItem[]
  taskId: string
  status?: string
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'start-new'): void
}>()

const terminalRef = ref<HTMLElement | null>(null)

watch(
  () => props.logs.length,
  async () => {
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  }
)
</script>

<template>
  <div class="progress-card">
    <div class="progress-header">
      <div class="header-left">
        <div class="spinner-ring"></div>
        <div>
          <h3>Student V4.2 基因组前噬菌体识别与边界精修中</h3>
          <span class="task-id-label">任务编号: {{ taskId }}</span>
        </div>
      </div>
      <div class="header-actions">
        <button type="button" class="queue-new-btn" @click="emit('start-new')">新建排队</button>
        <button type="button" class="cancel-btn" @click="emit('cancel')">中止任务</button>
      </div>
    </div>

    <div class="bar-section">
      <div class="bar-meta">
        <span class="step-label">{{ currentStep || '正在调度计算引擎...' }}</span>
        <span class="pct-label">{{ Math.max(0, Math.min(100, progress || 0)) }}%</span>
      </div>
      <div class="progress-track">
        <div
          class="progress-fill"
          :style="{ width: `${Math.max(4, Math.min(100, progress || 0))}%` }"
        ></div>
      </div>
    </div>

    <div class="terminal-wrapper">
      <div class="terminal-title">实时推理与分割终端日志</div>
      <div ref="terminalRef" class="terminal-body">
        <div v-if="logs.length === 0" class="log-placeholder">
          正在等待引擎返回阶段输出...
        </div>
        <div v-for="(item, idx) in logs" :key="idx" class="log-line" :class="item.level">
          <span class="log-time">[{{ item.time }}]</span>
          <span class="log-text">{{ item.line }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.spinner-ring {
  width: 24px;
  height: 24px;
  border: 3px solid #dbeafe;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.header-left h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}

.task-id-label {
  font-size: 12px;
  color: #64748b;
  font-family: 'Consolas', monospace;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.queue-new-btn {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #2563eb;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.queue-new-btn:hover {
  background: #dbeafe;
}

.cancel-btn {
  border: 1px solid #fecaca;
  background: #fef2f2;
  color: #dc2626;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.cancel-btn:hover {
  background: #fee2e2;
}

.bar-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.step-label {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.pct-label {
  font-size: 14px;
  font-weight: 800;
  color: #2563eb;
}

.progress-track {
  height: 10px;
  background: #f1f5f9;
  border-radius: 99px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, #2563eb 0%, #0ea5e9 100%);
  transition: width 0.35s ease;
}

.terminal-wrapper {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  overflow: hidden;
}

.terminal-title {
  background: #1e293b;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 700;
  padding: 6px 12px;
  border-bottom: 1px solid #334155;
}

.terminal-body {
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.55;
  padding: 12px;
  height: 260px;
  overflow-y: auto;
}

.log-placeholder {
  color: #64748b;
}

.log-line {
  display: flex;
  gap: 8px;
}

.log-line.warning .log-text {
  color: #fbbf24;
}

.log-time {
  color: #64748b;
  flex-shrink: 0;
}

.log-text {
  word-break: break-all;
}
</style>

