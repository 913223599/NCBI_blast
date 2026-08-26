<script setup lang="ts">
/**
 * AnnotationProgress - 注释执行实时进度与日志终端面板
 */
import { ref, watch, nextTick } from 'vue';

const props = defineProps<{
  progress: number;
  currentStep: string;
  logs: string[];
  taskId: string;
}>();

const emit = defineEmits<{
  (e: 'cancel'): void;
  (e: 'view-results'): void;
}>();

const logContainerRef = ref<HTMLDivElement | null>(null);

// 自动滚动到最新日志
watch(() => props.logs.length, () => {
  nextTick(() => {
    if (logContainerRef.value) {
      logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight;
    }
  });
});

function copyLogs() {
  const text = props.logs.join('\n');
  navigator.clipboard.writeText(text);
  alert('控制台日志已复制到剪贴板');
}
</script>

<template>
  <div class="annotation-progress-card">
    <div class="progress-header">
      <div class="header-left">
        <div class="pulsing-dot" :class="{ completed: progress >= 100 }"></div>
        <div class="header-text">
          <h3>{{ progress >= 100 ? '注释分析已全部完成' : '注释分析管线正在高速执行' }}</h3>
          <p class="step-desc">{{ currentStep || '正在调度生物信息学计算引擎...' }}</p>
        </div>
      </div>
      <div class="header-right">
        <span class="pct-badge" :class="{ completed: progress >= 100 }">{{ progress }}%</span>
        
        <button 
          v-if="progress >= 100" 
          class="view-result-btn" 
          @click="emit('view-results')" 
          title="点击直接切换并查看注释可视化成果"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          查看分析结果
        </button>

        <button 
          v-else 
          class="cancel-btn" 
          @click="emit('cancel')" 
          title="中止当前任务"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          取消任务
        </button>
      </div>
    </div>

    <!-- 进度条 -->
    <div class="progress-bar-bg">
      <div class="progress-bar-inner" :style="{ width: `${progress}%` }">
        <div class="bar-shine"></div>
      </div>
    </div>

    <!-- 实时终端日志 -->
    <div class="console-box">
      <div class="console-topbar">
        <div class="console-title">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" y1="19" x2="20" y2="19" />
          </svg>
          <span>实时日志终端 [Task: {{ taskId }}]</span>
        </div>
        <button class="copy-log-btn" @click="copyLogs">复制日志</button>
      </div>
      <div class="log-scroll-area" ref="logContainerRef">
        <div v-if="logs.length === 0" class="log-empty">等待日志输出...</div>
        <div v-for="(line, idx) in logs" :key="idx" class="log-line">
          <span class="log-idx">{{ idx + 1 }}</span>
          <span class="log-text">{{ line }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotation-progress-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.05);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pulsing-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #3b82f6;
  box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7);
  animation: pulse-ring 1.5s infinite;
}

.header-text h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.step-desc {
  margin: 2px 0 0;
  font-size: 12px;
  color: #64748b;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pct-badge {
  font-size: 18px;
  font-weight: 800;
  color: #2563eb;
}

.pct-badge.completed {
  color: #16a34a;
}

.pulsing-dot.completed {
  background: #16a34a;
  box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.7);
  animation: none;
}

.view-result-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border: 1px solid #047857;
  color: white;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
  transition: all 0.2s ease;
}

.view-result-btn:hover {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(16, 185, 129, 0.4);
}

.cancel-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #fee2e2;
  border: 1px solid #fecaca;
  color: #dc2626;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.cancel-btn:hover {
  background: #fca5a5;
  color: #991b1b;
}

.progress-bar-bg {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 20px;
}

.progress-bar-inner {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  position: relative;
  transition: width 0.3s ease;
}

.bar-shine {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.4) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  animation: shine-sweep 2s infinite;
}

.console-box {
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #1e293b;
}

.console-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #1e293b;
  color: #94a3b8;
  font-size: 11px;
}

.console-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.copy-log-btn {
  background: transparent;
  border: 1px solid #334155;
  color: #cbd5e1;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.copy-log-btn:hover {
  background: #334155;
  color: white;
}

.log-scroll-area {
  height: 180px;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
}

.log-empty {
  color: #64748b;
  font-style: italic;
}

.log-line {
  display: flex;
  gap: 10px;
  color: #e2e8f0;
}

.log-idx {
  color: #64748b;
  user-select: none;
  min-width: 24px;
  text-align: right;
}

.log-text {
  word-break: break-all;
  white-space: pre-wrap;
}

@keyframes pulse-ring {
  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7); }
  70% { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}

@keyframes shine-sweep {
  from { transform: translateX(-100%); }
  to { transform: translateX(100%); }
}
</style>
