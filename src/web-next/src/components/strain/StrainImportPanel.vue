<template>
  <div class="import-panel">
    <h3 class="panel-title">数据导入</h3>

    <!-- 导入模式切换 -->
    <div class="mode-tabs">
      <button class="mode-tab" :class="{ active: strain.inputMode === 'file' }" @click="strain.switchInputMode('file')">
        文件上传
      </button>
      <button class="mode-tab" :class="{ active: strain.inputMode === 'text' }" @click="strain.switchInputMode('text')">
        文本输入
      </button>
      <button class="mode-tab" :class="{ active: strain.inputMode === 'ncbi' }" @click="strain.switchInputMode('ncbi')">
        NCBI下载
      </button>
    </div>

    <!-- 文件上传模式 -->
    <div v-if="strain.inputMode === 'file'" class="input-section">
      <UniversalUpload type="fasta" accept=".fasta,.fas,.fa,.fna,.seq,.ab1,.abi,.zip,.gb,.gbk,.embl" label="上传或拖入新的菌种序列"
        @success="onFilesUploaded" />
    </div>

    <!-- 文本输入模式 -->
    <div v-if="strain.inputMode === 'text'" class="input-section">
      <textarea v-model="strain.importText" class="sequence-input"
        placeholder="粘贴FASTA格式序列...&#10;&#10;>Sequence1&#10;ATCGATCGATCG&#10;&#10;>Sequence2&#10;GCTAGCTAGCTA" />
      <button class="btn-primary" @click="handleImportText" :disabled="!strain.importText.trim()">
        导入序列
      </button>
    </div>

    <!-- NCBI下载模式 -->
    <div v-if="strain.inputMode === 'ncbi'" class="input-section">
      <div class="form-group">
        <label>NCBI Accession / 登录号</label>
        <input v-model="ncbiAccession" class="text-input" placeholder="例如：NC_045512.2, MN908947.3" />
      </div>
      <div class="form-group">
        <label>批量导入（每行一个）</label>
        <textarea v-model="ncbiBatchAccessions" class="sequence-input"
          placeholder="NC_045512.2&#10;MN908947.3&#10;MT019530.1" rows="6" />
      </div>
      <button class="btn-primary" @click="handleNCBIDownload" :disabled="!canDownloadNCBI">
        从NCBI下载
      </button>
    </div>

    <!-- 导入统计 -->
    <div v-if="strain.importTasks.length > 0" class="import-stats">
      <div class="stat-item">
        <span class="stat-label">待处理</span>
        <span class="stat-value">{{ pendingTasks }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">已完成</span>
        <span class="stat-value">{{ completedTasks }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { getBridge } from '../../bridge'
import UniversalUpload from '../common/UniversalUpload.vue'

const strain = useStrainStore()
const appStore = useAppStore()

const ncbiAccession = ref('')
const ncbiBatchAccessions = ref('')

const canDownloadNCBI = computed(() => {
  return ncbiAccession.value.trim() || ncbiBatchAccessions.value.trim()
})

const pendingTasks = computed(() => {
  return (strain.importTasks as any[]).filter(t => ['queued', 'running'].includes(t.status)).length
})

const completedTasks = computed(() => {
  return (strain.importTasks as any[]).filter(t => t.status === 'done').length
})

async function onFilesUploaded(filePaths: string[]) {
  if (filePaths.length === 0) return

  appStore.showNotification(`正在从 ${filePaths.length} 个文件中提取菌种信息...`, 'info')
  try {
    const bridge = getBridge()
    // 调用后端的导入逻辑（假设后端已有处理路径的接口）
    if (typeof bridge.import_sequences_to_strains === 'function') {
      const res = await bridge.import_sequences_to_strains(filePaths)
      if (res && res.success) {
        appStore.showNotification(`导入成功: 新增 ${res.count} 条记录`, 'success')
        // 刷新列表
        if (typeof (strain as any).fetchStrains === 'function') {
          (strain as any).fetchStrains()
        }
      } else {
        appStore.showNotification(`导入失败: ${res?.error || '处理异常'}`, 'error')
      }
    } else {
      // 临时方案：如果后端还没准备好批量路径接口，提示用户
      appStore.showNotification('后端批量导入接口对接中，请先使用文本模式', 'warning')
    }
  } catch (e) {
    appStore.showNotification('导入过程出错', 'error')
  }
}

function handleImportText() {
  if (!strain.importText.trim()) {
    appStore.showNotification('请输入序列数据', 'warning')
    return
  }

  // TODO: 实现文本序列解析和导入
  appStore.showNotification('序列导入功能开发中', 'info')
  strain.clearImportInput()
}

function handleNCBIDownload() {
  if (!canDownloadNCBI.value) {
    appStore.showNotification('请输入NCBI登录号', 'warning')
    return
  }

  // TODO: 实现NCBI下载逻辑
  appStore.showNotification('NCBI下载功能开发中', 'info')
  ncbiAccession.value = ''
  ncbiBatchAccessions.value = ''
}
</script>

<style scoped>
.import-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.mode-tabs {
  display: flex;
  gap: 4px;
  background: #f1f5f9;
  padding: 4px;
  border-radius: 10px;
}

.mode-tab {
  flex: 1;
  padding: 8px 12px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

.mode-tab:hover {
  color: #1e293b;
}

.mode-tab.active {
  background: white;
  color: #2563eb;

}

.input-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 32px 20px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  background: #f8fafc;
}

.drop-zone:hover {
  border-color: #2563eb;
  background: #eff6ff;
}

.drop-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 8px;
}

.drop-text {
  display: block;
  font-size: 0.9rem;
  font-weight: 600;
  color: #475569;
  margin-bottom: 4px;
}

.drop-hint {
  display: block;
  font-size: 0.75rem;
  color: #94a3b8;
}

.sequence-input {
  width: 100%;
  min-height: 200px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.85rem;
  line-height: 1.6;
  resize: vertical;
  transition: border-color 0.2s;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

.sequence-input:focus {
  outline: none;
  border-color: #2563eb;
}

.text-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.85rem;
  transition: border-color 0.2s;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.btn-primary {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  padding: 10px 20px;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;

}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);

}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.import-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 10px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-label {
  font-size: 0.7rem;
  color: #94a3b8;
  text-transform: uppercase;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
}
</style>