<script setup lang="ts">
import { ref } from 'vue';

const props = defineProps<{
  title: string;
  fileName: string;
  id: string;
}>();

const emit = defineEmits(['upload', 'clear']);

const inputRef = ref<HTMLInputElement | null>(null);

function handleUpload(e: Event) {
  emit('upload', e);
  if (inputRef.value) inputRef.value.value = ''; // 保证重复上传同名文件触发事件
}
</script>

<template>
  <div class="instant-file-card">
    <div class="card-header">
      <h2 class="title">
        <svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
        {{ title }}
      </h2>
      <button v-if="fileName" @click="emit('clear')" class="btn-clear">
        清空重置
      </button>
    </div>
    <div class="drop-zone" @click="inputRef?.click()">
      <svg class="upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      <p class="drop-text">点击或拖拽上传 FASTA 文件</p>
      <p class="drop-hint">支持多选文件自动拼接 (Multi-select)</p>
      <input 
        ref="inputRef"
        type="file" 
        multiple
        class="hidden-input"
        accept=".fasta,.fa,.txt"
        @change="handleUpload"
      />
    </div>
    <div v-if="fileName" class="file-badge">
      <div class="status-dot"></div>
      已加载: <span class="name">{{ fileName }}</span>
    </div>
  </div>
</template>

<style scoped>
.instant-file-card {
  background: white; padding: 16px; border-radius: 12px; border: 1px solid #f1f5f9;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: all 0.3s;
}
.instant-file-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.05); }

.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.title { font-size: 0.95rem; font-weight: 700; color: #334155; display: flex; align-items: center; gap: 8px; margin: 0; }
.icon { color: #3b82f6; width: 18px; height: 18px; }

.btn-clear {
  font-size: 11px; color: #f43f5e; background: #fff1f2; border: 1px solid #ffe4e6;
  padding: 2px 10px; border-radius: 99px; cursor: pointer; transition: all 0.2s;
}
.btn-clear:hover { background: #f43f5e; color: white; }

.drop-zone {
  border: 2px dashed #e2e8f0; border-radius: 10px; padding: 20px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: #f8fafc; cursor: pointer; transition: all 0.2s; position: relative;
}
.drop-zone:hover { background: #f1f5f9; border-color: #3b82f6; }
.upload-icon { color: #94a3b8; margin-bottom: 8px; width: 24px; height: 24px; }
.drop-zone:hover .upload-icon { color: #3b82f6; }

.drop-text { font-size: 13px; font-weight: 500; color: #475569; margin: 0; }
.drop-hint { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.hidden-input { display: none; }

.file-badge {
  margin-top: 12px; display: flex; align-items: center; gap: 8px; font-size: 12px;
  color: #059669; background: #ecfdf5; padding: 6px 10px; border-radius: 6px; border: 1px solid #d1fae5;
}
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; animation: pulse 2s infinite; }
.name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@keyframes pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
</style>
