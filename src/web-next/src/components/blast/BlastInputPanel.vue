<script setup lang="ts">
import { useBlastStore } from '../../stores/blast'
import { useAppStore } from '../../stores/app'
import { getBridge } from '../../bridge'
import { useI18n } from '../../locales'

const blast = useBlastStore()
const appStore = useAppStore()
const { t } = useI18n()

function selectFiles(): void {
  try {
    getBridge().request_file_load('fasta')
  } catch (error) {
    console.warn('[Blast] Bridge not available:', error)
  }
}

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
}

async function handleDrop(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
  
  if (e.dataTransfer && e.dataTransfer.files.length > 0) {
    const filePaths: string[] = []
    const files = Array.from(e.dataTransfer.files)
    
    for (const f of files) {
      const path = getBridge().get_path_for_file(f)
      if (path) {
        filePaths.push(path)
      }
    }
    
    if (filePaths.length > 0) {
        appStore.showNotification(`正在处理 ${filePaths.length} 个导入项...`, 'info')
        const res = await getBridge().process_blast_files(filePaths)
        if (res && res.success && res.paths) {
            blast.addFiles(res.paths)
            appStore.showNotification(`成功导入 ${res.paths.length} 个序列文件`, 'success')
        } else {
            // Fallback
            blast.addFiles(filePaths)
        }
    }
  }
}
</script>

<template>
  <div class="panel-section">
    <h3 class="section-title">{{ t('blast.input.title') }}</h3>
    <div class="mode-tabs-neo">
      <button class="mode-tab" :class="{ active: blast.inputMode === 'file' }" @click="blast.switchInputMode('file')">{{ t('blast.input.file') }}</button>
      <button class="mode-tab" :class="{ active: blast.inputMode === 'text' }" @click="blast.switchInputMode('text')">{{ t('blast.input.text') }}</button>
    </div>
    
    <div v-if="blast.inputMode === 'file'" class="file-area">
      <div 
        class="drop-zone-neo" 
        @click="selectFiles"
        @dragover="handleDragOver"
        @drop="handleDrop"
      >
        <span class="dz-icon">📤</span>
        <span class="dz-text">{{ t('blast.input.drop') }}</span>
      </div>
      <div class="file-list-neo">
         <div v-for="f in blast.files" :key="f" class="file-item-neo">
           <span class="name">{{ f.split(/[/\\]/).pop() }}</span>
           <button class="del" @click="blast.removeFile(f)">✕</button>
         </div>
      </div>
    </div>
    <textarea v-else v-model="blast.queryText" class="neo-textarea" :placeholder="t('blast.input.text_placeholder')" />
  </div>
</template>

<style scoped>
.panel-section { margin-bottom: 24px; }
.section-title { font-size: 0.9rem; font-weight: 700; color: #1e293b; margin-bottom: 16px; }

.mode-tabs-neo { display: flex; background: #f1f5f9; padding: 4px; border-radius: 10px; margin-bottom: 16px; }
.mode-tab { flex: 1; padding: 6px; border: none; background: none; font-size: 0.8rem; font-weight: 600; color: #64748b; cursor: pointer; border-radius: 7px; transition: all 0.2s; }
.mode-tab.active { background: white; color: #2563eb; box-shadow: 0 2px 6px rgba(0,0,0,0.05); }

.file-area { display: flex; flex-direction: column; gap: 12px; }

.drop-zone-neo { border: 2px dashed #cbd5e1; border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; transition: all 0.2s; background: #f8fafc; }
.drop-zone-neo:hover { border-color: #2563eb; background: #f0f7ff; }
.dz-icon { font-size: 1.5rem; color: #2563eb; }
.dz-text { font-size: 0.75rem; color: #64748b; font-weight: 600; margin-top: 4px; display: block; }

.file-list-neo { display: flex; flex-direction: column; gap: 6px; max-height: 600px; overflow-y: auto; padding-right: 4px; }
.file-item-neo { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; flex-shrink: 0; min-height: 36px; }
.file-item-neo .name { font-size: 0.75rem; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 8px; }
.file-item-neo .del { background: none; border: none; color: #94a3b8; cursor: pointer; padding: 2px 6px; }
.file-item-neo .del:hover { color: #ef4444; }

.neo-textarea { width: 100%; height: 350px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; color: #334155; resize: none; outline: none; transition: all 0.2s; }
.neo-textarea:focus { border-color: #2563eb; background: white; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
</style>
