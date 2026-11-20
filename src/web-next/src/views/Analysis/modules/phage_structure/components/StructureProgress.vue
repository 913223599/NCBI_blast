<script setup lang="ts">
import type { StructureLogLine } from '../composables/usePhageStructure'

defineProps<{
  progress: number
  currentStep?: string
  logs: StructureLogLine[]
  taskId: string
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'start-new'): void
}>()
</script>

<template>
  <div class="progress-panel">
    <div class="progress-head">
      <div>
        <h3>正在执行结构与尾部形态解析</h3>
        <div class="task-sub">任务编号: {{ taskId }}</div>
      </div>
      <div class="head-actions">
        <button type="button" class="btn-secondary" @click="emit('start-new')">提交新任务</button>
        <button type="button" class="btn-danger" @click="emit('cancel')">中止分析</button>
      </div>
    </div>

    <div class="bar-wrap">
      <div class="bar-track">
        <div class="bar-fill" :style="{ width: `${Math.min(100, Math.max(4, progress || 4))}%` }"></div>
      </div>
      <div class="bar-meta">
        <span>{{ currentStep || '正在协调 PHROGs 结构同源扫描与 TMP 标尺解析...' }}</span>
        <span class="pct">{{ progress || 0 }}%</span>
      </div>
    </div>

    <div class="log-box">
      <div class="log-title">执行追踪日志</div>
      <div class="log-lines">
        <div v-if="logs.length === 0" class="log-empty">等待计算节点回传进度...</div>
        <div v-for="(entry, i) in logs" :key="i" class="log-row">
          <span class="log-time">[{{ entry.time }}]</span>
          <span class="log-text">{{ entry.line }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 24px;
}

.progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

h3 {
  margin: 0;
  font-size: 1.12rem;
  color: #0f172a;
}

.task-sub {
  font-size: 0.8rem;
  color: #64748b;
  margin-top: 3px;
  font-family: monospace;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.btn-secondary,
.btn-danger {
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-secondary {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
}

.btn-danger {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
}

.bar-wrap {
  margin-bottom: 18px;
}

.bar-track {
  height: 10px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #0ea5e9);
  transition: width 0.35s ease;
}

.bar-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 0.86rem;
  color: #334155;
}

.pct {
  font-weight: 700;
  color: #2563eb;
}

.log-box {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
}

.log-title {
  font-size: 0.78rem;
  color: #94a3b8;
  margin-bottom: 8px;
  font-weight: 600;
}

.log-lines {
  max-height: 240px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.55;
}

.log-row {
  display: flex;
  gap: 8px;
}

.log-time {
  color: #60a5fa;
  flex-shrink: 0;
}

.log-empty {
  color: #64748b;
}
</style>
