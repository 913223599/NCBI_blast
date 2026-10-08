<script setup lang="ts">
import { ref } from 'vue'
import { useBlastStore } from '../../stores/blast'
import { useAppStore } from '../../stores/app'
import { getBridge, apiPost } from '../../bridge/electron-bridge'
import { useI18n } from '../../locales'
import UniversalUpload from '../common/UniversalUpload.vue'

const blast = useBlastStore()
const appStore = useAppStore()
const { t } = useI18n()

const emit = defineEmits<{
  (e: 'openDiversityModal', path?: string, openHistory?: boolean): void
}>()

const detectedZip = ref<string | null>(null)
const detectedPackageInfo = ref<any>(null)

/**
 * 处理单株模式上传成功的路径
 */
async function onUploadSuccess(filePaths: string[]) {
  const bridge = getBridge()
  appStore.showNotification(`正在处理 ${filePaths.length} 个导入项...`, 'info')
  
  // 检查是否包含测序交付 ZIP 包，若是则自动提示可切换到多样性鉴定
  const zipFile = filePaths.find(p => p.toLowerCase().endsWith('.zip'))
  if (zipFile) {
    try {
      const detectRes = await apiPost('/api/diversity/detect_package', { file_path: zipFile })
      if (detectRes && detectRes.is_amplicon_package) {
        detectedZip.value = zipFile
        detectedPackageInfo.value = detectRes
        appStore.showNotification(`检测到测序交付包 (包含 ${detectRes.fastq_count} 个样本)，可切换至“多样性鉴定”开启 rrnDB 校正！`, 'info')
      }
    } catch (e) {
      console.warn('Package detection error:', e)
    }
  }

  const res = await bridge.process_blast_files(filePaths)
  if (res && res.success && res.paths) {
    blast.addFiles(res.paths)
    appStore.showNotification(`成功导入 ${res.paths.length} 个序列文件`, 'success')
  } else {
    blast.addFiles(filePaths)
  }
}

/**
 * 处理多样性模式上传成功的路径
 */
async function onDiversityUploadSuccess(filePaths: string[]) {
  if (!filePaths || filePaths.length === 0) return
  const path = filePaths[0]
  if (!path) return
  
  detectedZip.value = path
  try {
    const detectRes = await apiPost('/api/diversity/detect_package', { file_path: path })
    if (detectRes && detectRes.is_amplicon_package) {
      detectedPackageInfo.value = detectRes
      appStore.showNotification(`已识别测序交付包，包含 ${detectRes.fastq_count} 个样本`, 'success')
    } else {
      detectedPackageInfo.value = { file_name: path.split(/[/\\]/).pop(), fastq_count: '多' }
    }
  } catch (e) {
    detectedPackageInfo.value = { file_name: path.split(/[/\\]/).pop(), fastq_count: '多' }
  }
}

/**
 * 智能显示文件名：剥离后端增加的 8位 UUID 前缀
 */
function getDisplayName(fullPath: string) {
  const fileName = fullPath.split(/[/\\]/).pop() || ''
  // 匹配格式: 8位16进制 + 下划线 (例如: a1b2c3d4_test.fasta)
  const uuidPattern = /^[0-9a-f]{8}_/
  if (uuidPattern.test(fileName)) {
    return fileName.substring(9)
  }
  return fileName
}
</script>

<template>
  <div class="panel-section">
    <!-- 单株鉴定 vs 多样性鉴定 模式切换开关 -->
    <div class="analysis-mode-selector">
      <button 
        class="mode-switch-btn" 
        :class="{ active: blast.analysisTarget === 'isolate' }" 
        @click="blast.setAnalysisTarget('isolate')"
      >
        <svg class="mode-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <circle cx="12" cy="12" r="8" stroke-width="2"/>
          <path d="M12 8v8M8 12h8" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span>单株鉴定</span>
      </button>
      <button 
        class="mode-switch-btn" 
        :class="{ active: blast.analysisTarget === 'diversity' }" 
        @click="blast.setAnalysisTarget('diversity')"
      >
        <svg class="mode-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M4 6c4 0 6 6 10 6s6-6 10-6M4 18c4 0 6-6 10-6s6 6 10 6" stroke-width="2" stroke-linecap="round"/>
          <path d="M8 8.5v7M16 8.5v7" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span>多样性鉴定</span>
      </button>
    </div>

    <!-- 模式 A: 单株菌株鉴定输入 -->
    <div v-if="blast.analysisTarget === 'isolate'">
      <h3 class="section-title">{{ t('blast.input.title') }}</h3>
      <div class="mode-tabs-neo">
        <button class="mode-tab" :class="{ active: blast.inputMode === 'file' }" @click="blast.switchInputMode('file')">{{ t('blast.input.file') }}</button>
        <button class="mode-tab" :class="{ active: blast.inputMode === 'text' }" @click="blast.switchInputMode('text')">{{ t('blast.input.text') }}</button>
      </div>
      
      <div v-if="blast.inputMode === 'file'" class="file-area">
        <UniversalUpload 
          type="fasta"
          accept=".fasta,.fas,.fa,.fna,.seq,.ab1,.abi,.zip"
          :label="t('blast.input.drop')"
          @success="onUploadSuccess"
        />
        <div class="file-list-neo">
           <div v-for="f in blast.files" :key="f" class="file-item-neo">
             <span class="name" :title="f">{{ getDisplayName(f) }}</span>
             <button class="del" @click="blast.removeFile(f)">✕</button>
           </div>
        </div>
      </div>
      <textarea v-else v-model="blast.queryText" class="neo-textarea" :placeholder="t('blast.input.text_placeholder')" />
    </div>

    <!-- 模式 B: 16S 混样多样性鉴定与 rrnDB 归一化输入 -->
    <div v-else class="diversity-input-container">
      <div class="diversity-header-box">
        <div class="div-title-row">
          <span class="div-badge">16S 混样专研</span>
          <span class="div-rrndb-tag">rrnDB v5.10 拷贝数校正</span>
        </div>
        <p class="div-tip">专用于未分菌纯化样本、环境混样与多采样重复点位，直接分类单分子 Reads 并消除 16S 拷贝数偏差。</p>
      </div>

      <div class="diversity-upload-box">
        <UniversalUpload 
          type="fasta"
          accept=".zip,.fastq,.fastq.gz,.fasta,.fa"
          label="拖入生工测序交付压缩包 (ZIP) 或 FASTQ 读长"
          @success="onDiversityUploadSuccess"
        />
      </div>

      <!-- 已识别的测序包状态卡片 -->
      <div v-if="detectedZip" class="package-status-card">
        <div class="pkg-card-top">
          <div class="pkg-status-badge">
            <svg class="check-icon" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
            </svg>
            <span>测序交付包已载入</span>
          </div>
        </div>
        <div class="pkg-filename" :title="detectedZip">
          {{ detectedPackageInfo?.file_name || getDisplayName(detectedZip) }}
        </div>
        <div class="pkg-meta-desc">
          包含 <strong>{{ detectedPackageInfo?.fastq_count || '多' }} 个</strong> 独立采样点位的原始 Reads，采用多核并行与分片落盘保护。
        </div>

        <button class="btn-open-diversity-board" @click="emit('openDiversityModal', detectedZip || undefined)">
          <span>已载入，在右侧看板查看分析</span>
          <svg class="arrow-svg" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>
      </div>

      <div v-else class="empty-diversity-hint">
        <button class="btn-open-diversity-board secondary" @click="emit('openDiversityModal', undefined, true)">
          <span>在右侧看板查看历史多样性归档</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-section { margin-bottom: 24px; }

/* 模式切换 Segmented Control */
.analysis-mode-selector {
  display: flex;
  background: #f1f5f9;
  padding: 4px;
  border-radius: 12px;
  margin-bottom: 20px;
  border: 1px solid #e2e8f0;
}
.mode-switch-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  border-radius: 9px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.mode-switch-btn:hover {
  color: #1e293b;
}
.mode-switch-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.12);
}
.mode-icon-svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.section-title { font-size: 0.9rem; font-weight: 700; color: #1e293b; margin-bottom: 16px; }

.mode-tabs-neo { display: flex; background: #f1f5f9; padding: 4px; border-radius: 10px; margin-bottom: 16px; }
.mode-tab { flex: 1; padding: 6px; border: none; background: none; font-size: 0.8rem; font-weight: 600; color: #64748b; cursor: pointer; border-radius: 7px; transition: all 0.2s; }
.mode-tab.active { background: white; color: #2563eb; box-shadow: 0 2px 6px rgba(0,0,0,0.05); }

.file-area { display: flex; flex-direction: column; gap: 12px; }

.file-list-neo { display: flex; flex-direction: column; gap: 6px; max-height: 600px; overflow-y: auto; padding-right: 4px; }
.file-item-neo { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; flex-shrink: 0; min-height: 36px; }
.file-item-neo .name { font-size: 0.75rem; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 8px; }
.file-item-neo .del { background: none; border: none; color: #94a3b8; cursor: pointer; padding: 2px 6px; }
.file-item-neo .del:hover { color: #ef4444; }

.neo-textarea { width: 100%; height: 350px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; color: #334155; resize: none; outline: none; transition: all 0.2s; }
.neo-textarea:focus { border-color: #2563eb; background: white; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }

/* 多样性模式面板定制样式 */
.diversity-input-container {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.diversity-header-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
}
.div-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.div-badge {
  background: #2563eb;
  color: white;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
.div-rrndb-tag {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
.div-tip {
  font-size: 0.74rem;
  color: #64748b;
  line-height: 1.4;
  margin: 0;
}

.diversity-upload-box {
  display: flex;
  flex-direction: column;
}

.package-status-card {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pkg-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #dbeafe;
  color: #1e40af;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
}
.check-icon {
  width: 14px;
  height: 14px;
}
.pkg-filename {
  font-size: 0.8rem;
  font-weight: 700;
  color: #1e3a8a;
  word-break: break-all;
}
.pkg-meta-desc {
  font-size: 0.74rem;
  color: #475569;
  line-height: 1.4;
}

.btn-open-diversity-board {
  margin-top: 6px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 9px 14px;
  border-radius: 9px;
  font-size: 0.8rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-open-diversity-board:hover {
  background: #1d4ed8;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
.btn-open-diversity-board.secondary {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}
.btn-open-diversity-board.secondary:hover {
  background: #e2e8f0;
  color: #1e293b;
}
.arrow-svg {
  width: 14px;
  height: 14px;
}
</style>
