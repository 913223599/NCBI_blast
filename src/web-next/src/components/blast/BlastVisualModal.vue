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
    <div class="visual-modal-content glass-card">
      <div class="modal-header">
        <h3>📊 序列比对内容图解</h3>
        <div class="modal-controls">
          <span class="label">排序方式:</span>
          <select 
            :value="sortMode" 
            @change="emit('update:sortMode', ($event.target as HTMLSelectElement).value); emit('fetchData')" 
            class="mini-select"
          >
            <option value="evalue">按 E-value</option>
            <option value="score">按 Score</option>
            <option value="start">按起始位置</option>
          </select>
          <button class="close-btn" @click="emit('close')">×</button>
        </div>
      </div>
      
      <div class="modal-body scroll-v">
        <div v-if="loading" class="visual-loading">
          <div class="spinner"></div>
          <p>正在拉取比对原始 XML 并解析...</p>
        </div>
        <AlignmentMap 
          v-else-if="data" 
          :query-name="data.query_name" 
          :query-length="data.query_length" 
          :hits="data.hits" 
        />
        <div v-else class="empty-hint">暂无数据</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay-neo { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 40px; }
.visual-modal-content { background: white; border-radius: 20px; width: 100%; max-width: 1200px; max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25); }
.modal-header { height: 70px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e2e8f0; }
.modal-header h3 { font-size: 1.1rem; font-weight: 700; color: #1e293b; }
.modal-controls { display: flex; align-items: center; gap: 15px; }
.modal-controls .label { font-size: 0.8rem; color: #64748b; font-weight: 600; }

.mini-select { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 8px; font-size: 0.8rem; color: #475569; outline: none; }
.close-btn { background: #f1f5f9; border: none; font-size: 1.5rem; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 8px; cursor: pointer; color: #64748b; }

.modal-body { flex: 1; padding: 30px; overflow: auto; background: #fcfdfe; }
.visual-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px; color: #64748b; gap: 20px; }
.spinner { width: 40px; height: 40px; border: 3px solid #f3f3f3; border-top: 3px solid #2563eb; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

.empty-hint { text-align: center; color: #94a3b8; padding: 40px; }
</style>
