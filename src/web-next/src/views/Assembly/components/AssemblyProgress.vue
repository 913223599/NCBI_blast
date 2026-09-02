<script setup lang="ts">
/**
 * AssemblyProgress - 基因组组装实时运行进度与遥测日志控制台
 */
import { ref, watch, nextTick } from 'vue';
import type { AssemblyTaskItem } from '../types';

const props = defineProps<{
  task: AssemblyTaskItem;
  logs: string[];
}>();

const emit = defineEmits<{
  (e: 'cancel'): void;
}>();

const logContainer = ref<HTMLElement | null>(null);

// 自动滚动控制台到最新
watch(() => props.logs.length, async () => {
  await nextTick();
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight;
  }
});

// 计算阶段状态
const phases = [
  { id: 1, name: '数据加载', threshold: 10 },
  { id: 2, name: '欧拉残差流', threshold: 35 },
  { id: 3, name: '拓扑合并', threshold: 65 },
  { id: 4, name: 'SIMD-POA打磨', threshold: 85 },
  { id: 5, name: '产物收割', threshold: 98 }
];

function getPhaseClass(threshold: number, progress: number) {
  if (progress >= threshold) return 'is-done';
  if (progress >= threshold - 20) return 'is-current';
  return 'is-pending';
}
</script>

<template>
  <div class="assembly-progress-container">
    <div class="progress-main-card">
      <!-- 顶部任务状态摘要 -->
      <div class="header-row">
        <div class="task-meta">
          <span class="pulse-indicator"></span>
          <span class="task-title">NGCS 组装计算中: <b>{{ task.name }}</b></span>
        </div>
        <button class="stop-btn" @click="emit('cancel')" title="强制停止当前组装任务">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="4" y="4" width="16" height="16" rx="2" />
          </svg>
          <span>终止组装</span>
        </button>
      </div>

      <!-- 进度条与实时步骤 -->
      <div class="progress-section">
        <div class="progress-info">
          <span class="current-step-text">{{ task.last_step || '正在执行 NGCS 拓扑重构...' }}</span>
          <span class="percent-text">{{ Math.round(task.progress || 0) }}%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: `${Math.max(5, task.progress || 0)}%` }"></div>
        </div>
      </div>

      <!-- 阶段步骤指示器 -->
      <div class="phase-stepper">
        <div 
          v-for="p in phases" 
          :key="p.id" 
          class="phase-item"
          :class="getPhaseClass(p.threshold, task.progress || 0)"
        >
          <div class="phase-dot">
            <span v-if="(task.progress || 0) >= p.threshold">✓</span>
            <span v-else>{{ p.id }}</span>
          </div>
          <span class="phase-name">{{ p.name }}</span>
        </div>
      </div>

      <!-- 实时日志终端控制台 -->
      <div class="console-box">
        <div class="console-header">
          <div class="dots-group">
            <span class="c-dot red"></span>
            <span class="c-dot yellow"></span>
            <span class="c-dot green"></span>
          </div>
          <span class="console-title">NGCS Pipeline Telemetry Terminal</span>
          <span class="log-count">{{ logs.length }} lines</span>
        </div>
        <div ref="logContainer" class="console-body scroll-v">
          <div v-if="logs.length === 0" class="empty-log">
            等待底层组装引擎流式日志输出...
          </div>
          <div v-for="(line, idx) in logs" :key="idx" class="log-line">
            <span class="log-prefix">&gt;</span>
            <span class="log-text">{{ line }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assembly-progress-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px;
  overflow-y: auto;
}

.progress-main-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.task-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pulse-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
  animation: pulse-ring 1.5s infinite;
}
@keyframes pulse-ring {
  0% { transform: scale(0.9); opacity: 0.8; }
  50% { transform: scale(1.2); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.8; }
}
.task-title {
  font-size: 1rem;
  color: #1e293b;
}

.stop-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  background: #fee2e2;
  color: #ef4444;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.stop-btn:hover {
  background: #ef4444;
  color: white;
}

.progress-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.current-step-text {
  font-size: 0.85rem;
  font-weight: 600;
  color: #2563eb;
}
.percent-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.1rem;
  font-weight: 800;
  color: #1e293b;
}

.progress-bar-bg {
  height: 10px;
  background: #f1f5f9;
  border-radius: 5px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  border-radius: 5px;
  transition: width 0.3s ease;
}

.phase-stepper {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  padding: 12px 0;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}
.phase-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.phase-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  background: #f1f5f9;
  color: #94a3b8;
}
.phase-name {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 500;
}

.phase-item.is-done .phase-dot {
  background: #dcfce7;
  color: #16a34a;
}
.phase-item.is-done .phase-name {
  color: #15803d;
  font-weight: 600;
}
.phase-item.is-current .phase-dot {
  background: #dbeafe;
  color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37,99,235,0.2);
}
.phase-item.is-current .phase-name {
  color: #2563eb;
  font-weight: 700;
}

.console-box {
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 280px;
}
.console-header {
  height: 32px;
  background: #1e293b;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
}
.dots-group {
  display: flex;
  gap: 5px;
}
.c-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.c-dot.red { background: #ef4444; }
.c-dot.yellow { background: #eab308; }
.c-dot.green { background: #22c55e; }

.console-title {
  font-size: 0.72rem;
  color: #94a3b8;
  font-family: monospace;
}
.log-count {
  font-size: 0.68rem;
  color: #64748b;
}

.console-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  line-height: 1.6;
  color: #e2e8f0;
}
.empty-log {
  color: #64748b;
  font-style: italic;
}
.log-line {
  display: flex;
  gap: 6px;
  word-break: break-all;
}
.log-prefix {
  color: #3b82f6;
  user-select: none;
}
</style>
