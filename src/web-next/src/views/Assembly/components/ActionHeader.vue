
<script setup lang="ts">
const props = defineProps<{
  isRunning: boolean;
  onStop: () => void;
  onStart: () => void;
  onToggleHistory: () => void;
  canStart: boolean;
}>();
</script>

<template>
  <div class="action-bar">
    <div class="info-group">
      <h2>基因组拼接</h2>
      <p>面向高通量测序数据的一站式处理平台</p>
    </div>
    
    <div class="btn-group">
      <button class="history-btn" @click="onToggleHistory">
        📜 任务历史
      </button>

      <button v-if="isRunning" class="stop-btn" @click="onStop">
        <span class="pulse-dot"></span> 停止执行
      </button>
      <button v-else class="start-btn" :disabled="!canStart" @click="onStart">
        启动流水线
      </button>
    </div>
  </div>
</template>

<style scoped>
.action-bar { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.info-group h2 { font-size: 20px; color: #1e293b; margin: 0; font-weight: 700; letter-spacing: -0.5px; }
.info-group p { font-size: 12px; color: #64748b; margin: 0; opacity: 0.8; }

.btn-group { display: flex; gap: 10px; align-items: center; }

.history-btn {
  background: transparent; color: #64748b; border: 1px solid #e2e8f0; padding: 8px 16px; border-radius: 6px;
  font-weight: 600; font-size: 12px; cursor: pointer; transition: all 0.2s;
}
.history-btn:hover { background: #f8fafc; color: #3b82f6; border-color: #3b82f6; }

.start-btn {
  background: #3b82f6; color: white; border: none; padding: 10px 24px; border-radius: 6px;
  font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s;
}
.start-btn:hover:not(:disabled) { background: #2563eb; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2); }
.start-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.stop-btn {
  background: #fef2f2; color: #dc2626; border: 1px solid #fee2e2; padding: 12px 28px; border-radius: 8px;
  font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 10px; transition: all 0.2s;
}
.stop-btn:hover { background: #fee2e2; }

.pulse-dot { width: 8px; height: 8px; background: #dc2626; border-radius: 50%; animation: pulse 1.5s infinite; }
@keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.5); } 100% { opacity: 1; transform: scale(1); } }
</style>
