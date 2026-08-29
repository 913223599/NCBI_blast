<script setup lang="ts">
import AlignmentMap from './AlignmentMap.vue'

const props = defineProps<{
  show: boolean
  loading: boolean
  data: any
  sortMode: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:sortMode', mode: string): void
  (e: 'fetchData'): void
}>()
</script>

<template>
  <div v-if="show" class="modal-overlay-neo" @click.self="emit('close')">
    <div class="visual-modal-content">
      <div class="modal-header">
        <div class="header-title-group">
          <div class="header-icon-box">
            <svg class="header-svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <div>
            <h3>序列比对与变异指纹图谱</h3>
            <p class="header-sub">BLAST 多序列比对覆盖度、单碱基突变 (SNP) 与逐位对齐分析</p>
          </div>
        </div>

        <div class="modal-controls">
          <span class="label">排序规则:</span>
          <select 
            :value="sortMode" 
            @change="emit('update:sortMode', ($event.target as HTMLSelectElement).value); emit('fetchData')" 
            class="mini-select"
          >
            <option value="evalue">按 E-value (显著性)</option>
            <option value="score">按 Bit-Score (得分)</option>
            <option value="start">按起始位点 (坐标)</option>
          </select>
          <button class="close-btn" title="关闭" @click="emit('close')">✕</button>
        </div>
      </div>
      
      <div class="modal-body">
        <div v-if="loading" class="visual-loading">
          <div class="spinner"></div>
          <p>正在精准解析原始 XML 与变异位点指纹...</p>
        </div>
        <AlignmentMap 
          v-else-if="data" 
          :query-name="data.query_name" 
          :query-length="data.query_length" 
          :hits="data.hits" 
        />
        <div v-else class="empty-hint">未找到有效的比对记录</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay-neo { 
  position: fixed; 
  inset: 0; 
  background: rgba(15, 23, 42, 0.6); 
  backdrop-filter: blur(4px);
  z-index: 2000; 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  padding: 30px; 
}
.visual-modal-content { 
  background: #f8fafc; 
  border-radius: 16px; 
  width: 100%; 
  max-width: 1300px; 
  height: 88vh; 
  display: flex; 
  flex-direction: column; 
  overflow: hidden; 
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35); 
  border: 1px solid #e2e8f0;
}
.modal-header { 
  height: 72px; 
  padding: 0 24px; 
  display: flex; 
  align-items: center; 
  justify-content: space-between; 
  border-bottom: 1px solid #e2e8f0; 
  background: white;
}
.header-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-icon-box {
  width: 38px;
  height: 38px;
  background: #eff6ff;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
}
.header-svg-icon {
  width: 22px;
  height: 22px;
}
.modal-header h3 { 
  font-size: 1.05rem; 
  font-weight: 700; 
  color: #0f172a; 
  margin: 0;
}
.header-sub {
  font-size: 0.72rem;
  color: #64748b;
  margin: 2px 0 0 0;
}
.modal-controls { 
  display: flex; 
  align-items: center; 
  gap: 12px; 
}
.modal-controls .label { 
  font-size: 0.78rem; 
  color: #64748b; 
  font-weight: 600; 
}

.mini-select { 
  background: #f1f5f9; 
  border: 1px solid #cbd5e1; 
  border-radius: 8px; 
  padding: 6px 12px; 
  font-size: 0.78rem; 
  color: #1e293b; 
  font-weight: 600;
  outline: none; 
  cursor: pointer;
}
.close-btn { 
  background: #f1f5f9; 
  border: none; 
  font-size: 0.9rem; 
  width: 32px; 
  height: 32px; 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  border-radius: 8px; 
  cursor: pointer; 
  color: #64748b; 
  transition: all 0.2s;
}
.close-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

.modal-body { 
  flex: 1; 
  padding: 16px; 
  overflow: hidden; 
  background: #f1f5f9; 
  display: flex;
  flex-direction: column;
}
.visual-loading { 
  display: flex; 
  flex-direction: column; 
  align-items: center; 
  justify-content: center; 
  height: 100%; 
  color: #64748b; 
  gap: 16px; 
}
.spinner { 
  width: 44px; 
  height: 44px; 
  border: 3px solid #e2e8f0; 
  border-top: 3px solid #2563eb; 
  border-radius: 50%; 
  animation: spin 1s linear infinite; 
}
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

.empty-hint { 
  text-align: center; 
  color: #94a3b8; 
  padding: 60px; 
  font-size: 0.9rem;
}
</style>
