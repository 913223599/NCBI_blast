
<script setup lang="ts">
import { ref } from 'vue';
import { getBridge } from '../../../bridge';

const props = defineProps<{
  selectedFiles: string[];
  disabled: boolean;
}>();

const emit = defineEmits(['update:selectedFiles']);

const isDragging = ref(false);

const handleFileDrop = async (e: DragEvent) => {
  if (props.disabled) return;
  isDragging.value = false;
  const files = e.dataTransfer?.files;
  if (files && files.length > 0) {
     const paths = Array.from(files).map(f => (f as any).path);
     emit('update:selectedFiles', [...props.selectedFiles, ...paths]);
  }
};

const selectFilesManually = async () => {
  if (props.disabled) return;
  const paths = await getBridge().request_file_load(['fastq', 'gz', 'ab1', 'fa'], true);
  if (paths) {
    emit('update:selectedFiles', [...props.selectedFiles, ...paths]);
  }
};

const removeFile = (index: number) => {
  if (props.disabled) return;
  const newFiles = [...props.selectedFiles];
  newFiles.splice(index, 1);
  emit('update:selectedFiles', newFiles);
};

const getFileIcon = (path: string) => {
  if (path.endsWith('.ab1')) return '📝';
  if (path.endsWith('.gz') || path.endsWith('.fastq')) return '🧬';
  return '📄';
};
</script>

<template>
  <div class="upload-section card">
    <div class="card-header">
      <h3>测序数据上传</h3>
      <span class="status-badge" :class="selectedFiles.length > 0 ? 'ready' : 'empty'">
        {{ selectedFiles.length > 0 ? '准备就绪' : '等待上传' }}
      </span>
    </div>

    <div 
      class="dropzone"
      :class="{ 
        'dragging': isDragging, 
        'disabled': disabled,
        'has-files': selectedFiles.length > 0 
      }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleFileDrop"
      @click="selectedFiles.length === 0 ? selectFilesManually() : null"
    >
      <div v-if="selectedFiles.length === 0" class="upload-prompt">
        <div class="upload-icon">📤</div>
        <p><strong>拖拽 FASTQ/AB1 文件到此处，或 <span>点击选择</span></strong></p>
        <p class="sub-hint">支持 Illumina, Nanopore, PacBio 及 Sanger (AB1) 格式</p>
      </div>

      <div v-else class="file-list">
        <div v-for="(file, idx) in selectedFiles" :key="idx" class="file-item" @click.stop>
          <span class="file-icon">{{ getFileIcon(file) }}</span>
          <span class="file-name" :title="file">{{ file.split(/[\\/]/).pop() }}</span>
          <button @click.stop="removeFile(idx)" class="remove-btn" v-if="!disabled">×</button>
        </div>
        <div class="add-more" v-if="!disabled" @click.stop="selectFilesManually">+ 继续添加文件</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-section { flex: 1.2; display: flex; flex-direction: column; }
.card { background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.03); padding: 24px; border: 1px solid #f1f5f9; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.card-header h3 { font-size: 16px; color: #1e293b; margin: 0; }

.status-badge { font-size: 11px; padding: 4px 10px; border-radius: 20px; font-weight: 600; }
.status-badge.empty { background: #f1f5f9; color: #94a3b8; }
.status-badge.ready { background: #ecfdf5; color: #059669; }

.dropzone {
  flex: 1;
  border: 2px dashed #e2e8f0;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  min-height: 160px;
  position: relative;
  margin-bottom: 0;
  overflow: hidden;
}

.dropzone.has-files {
  align-items: flex-start;
  justify-content: flex-start;
  border-style: solid;
  border-color: #e2e8f0;
  background: white;
  cursor: default;
}

.dropzone:hover:not(.disabled):not(.has-files) {
  border-color: #3b82f6;
  background: #f0f7ff;
}

.dropzone.dragging { border-color: #3b82f6; background: #eff6ff; }
.dropzone.disabled { cursor: not-allowed; opacity: 0.7; }

.upload-prompt { text-align: center; color: #64748b; padding: 20px; }
.upload-icon { font-size: 28px; margin-bottom: 8px; opacity: 0.5; }
.upload-prompt p { margin: 4px 0; font-size: 13px; }
.upload-prompt span { color: #3b82f6; text-decoration: underline; }
.sub-hint { font-size: 11px; opacity: 0.7; }

.file-list { 
  width: 100%; 
  padding: 16px; 
  display: flex; 
  flex-direction: column; 
  gap: 8px; 
  align-self: flex-start; 
}
.file-item {
  background: #f8fafc; 
  border: 1px solid #e2e8f0; 
  border-radius: 10px; 
  padding: 12px 16px;
  display: flex; 
  align-items: center; 
  gap: 12px; 
  position: relative; 
  transition: all 0.2s ease;
  animation: slideIn 0.3s ease forwards;
}

.file-item:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
  transform: translateX(4px);
}

.file-icon { font-size: 20px; }
.file-name { 
  font-size: 13px; 
  color: #334155; 
  flex: 1; 
  white-space: nowrap; 
  overflow: hidden; 
  text-overflow: ellipsis; 
  font-weight: 500;
}
.remove-btn { 
  background: white; 
  border: 1px solid #e2e8f0; 
  color: #94a3b8; 
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px; 
  cursor: pointer; 
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(0,0,0,0.02);
}
.remove-btn:hover { 
  color: #ef4444; 
  border-color: #fee2e2;
  background: #fef2f2;
}

.add-more { 
  text-align: center; 
  font-size: 13px; 
  color: #3b82f6; 
  font-weight: 600; 
  padding: 12px; 
  cursor: pointer; 
  border: 2px dashed #dbeafe; 
  background: #eff6ff;
  border-radius: 10px; 
  margin-top: 8px; 
  transition: all 0.2s ease;
}

.add-more:hover {
  background: #dbeafe;
  border-color: #3b82f6;
}

@keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
