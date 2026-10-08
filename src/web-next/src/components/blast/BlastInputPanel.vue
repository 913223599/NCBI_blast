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
  (e: 'openDiversityModal', path?: string): void
}>()

const detectedZip = ref<string | null>(null)

/**
 * 处理上传成功的路径
 */
async function onUploadSuccess(filePaths: string[]) {
  const bridge = getBridge()
  appStore.showNotification(`正在处理 ${filePaths.length} 个导入项...`, 'info')
  
  // 检查是否包含测序交付 ZIP 包
  const zipFile = filePaths.find(p => p.toLowerCase().endsWith('.zip'))
  if (zipFile) {
    try {
      const detectRes = await apiPost('/api/diversity/detect_package', { file_path: zipFile })
      if (detectRes && detectRes.is_amplicon_package) {
        detectedZip.value = zipFile
        appStore.showNotification(`检测到测序交付包 (包含 ${detectRes.fastq_count} 个样本)，可一键开启多样性还原与 rrnDB 归一化分析！`, 'info')
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
    <!-- 16S 扩增子混样多样性与 rrnDB 归一化入口 -->
    <div class="diversity-banner-neo" @click="emit('openDiversityModal', detectedZip || undefined)">
      <div class="banner-top">
        <span class="banner-badge">生工 16S 专研</span>
        <span class="banner-title">混样多样性与 rrnDB 校正</span>
      </div>
      <p class="banner-desc">直接解析测序压缩包底层 Reads，引入 rrnDB 消除多拷贝偏好，还原采样重复真实群落结构。</p>
      <div class="banner-btn">
        <span>{{ detectedZip ? '立即解析已识别的测序包 →' : '打开 16S 多样性还原看板 →' }}</span>
      </div>
    </div>

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
</template>

<style scoped>
.diversity-banner-neo {
  background: linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%);
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 18px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.05);
}
.diversity-banner-neo:hover {
  transform: translateY(-2px);
  border-color: #3b82f6;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.12);
}
.banner-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.banner-badge {
  background: #2563eb;
  color: white;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
.banner-title {
  font-size: 0.84rem;
  font-weight: 700;
  color: #1e3a8a;
}
.banner-desc {
  font-size: 0.74rem;
  color: #475569;
  line-height: 1.4;
  margin: 0 0 10px;
}
.banner-btn {
  font-size: 0.76rem;
  font-weight: 700;
  color: #2563eb;
  display: flex;
  align-items: center;
}
.diversity-banner-neo:hover .banner-btn {
  color: #1d4ed8;
  text-decoration: underline;
}

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
