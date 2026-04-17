
<script setup lang="ts">
import { ref } from 'vue';
import UniversalUpload from '../../../../../components/common/UniversalUpload.vue';

interface Props {
  isRunning: boolean;
}
defineProps<Props>();

const emit = defineEmits(['run']);

const refFile = ref<string[]>([]);
const queryFile = ref<string[]>([]);

function handleRun() {
  if (refFile.value.length && queryFile.value.length) {
    emit('run', refFile.value[0], queryFile.value[0]);
  }
}
</script>

<template>
  <div class="comparison-controller card-neo">
    <div class="controller-header">
      <span class="icon">🔍</span>
      <h3>共线性对比系统 3.0</h3>
    </div>

    <div class="upload-grid">
      <div class="upload-box">
        <label>参考序列 (Reference)</label>
        <UniversalUpload 
          type="fasta" 
          :multiple="false"
          @success="(paths) => refFile = paths"
        />
        <div v-if="refFile && refFile[0]" class="file-tag">
          {{ refFile[0].split(/[/\\]/).pop() }}
        </div>
      </div>

      <div class="swap-icon">↔</div>

      <div class="upload-box">
        <label>待测序列 (Query)</label>
        <UniversalUpload 
          type="fasta" 
          :multiple="false"
          @success="(paths) => queryFile = paths"
        />
        <div v-if="queryFile && queryFile[0]" class="file-tag">
          {{ queryFile[0].split(/[/\\]/).pop() }}
        </div>
      </div>
    </div>

    <div class="action-bar">
      <div class="params-summary">
        <span class="badge">MUMmer Engine</span>
        <span class="badge">Auto-Orientation</span>
      </div>
      <button 
        class="btn-primary-run" 
        :disabled="isRunning || !refFile.length || !queryFile.length"
        @click="handleRun"
      >
        {{ isRunning ? '正在分析...' : '启动高精度比对' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.comparison-controller { padding: 24px; background: white; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); }
.controller-header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.controller-header h3 { margin: 0; font-size: 1.1rem; color: #1e293b; }

.upload-grid { display: grid; grid-template-columns: 1fr 40px 1fr; align-items: center; gap: 16px; margin-bottom: 24px; }
.upload-box label { font-size: 0.8rem; font-weight: 700; color: #64748b; margin-bottom: 8px; display: block; }
.swap-icon { text-align: center; color: #cbd5e1; font-size: 1.5rem; }

.file-tag { margin-top: 8px; font-size: 0.75rem; color: #2563eb; background: #eff6ff; padding: 4px 10px; border-radius: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.action-bar { display: flex; align-items: center; justify-content: space-between; padding-top: 20px; border-top: 1px solid #f1f5f9; }
.params-summary { display: flex; gap: 8px; }
.badge { background: #f1f5f9; color: #475569; padding: 4px 12px; border-radius: 99px; font-size: 0.72rem; font-weight: 600; }

.btn-primary-run { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; border: none; padding: 10px 24px; border-radius: 10px; font-weight: 700; cursor: pointer; transition: all 0.2s; }
.btn-primary-run:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(37,99,235,0.2); }
.btn-primary-run:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
