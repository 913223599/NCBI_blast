<script setup lang="ts">
/**
 * AssemblySetup - 基因组拼接配置与数据上传面板 (纯净智能识别版)
 */
import { ref, computed } from 'vue';
import type { AssemblyRunParams } from '../types';

const props = defineProps<{
  isRunning: boolean;
  isBusy: boolean;
}>();

const emit = defineEmits<{
  (e: 'run', params: AssemblyRunParams): void;
}>();

const taskName = ref<string>(`Assembly_${new Date().toISOString().slice(0,10).replace(/-/g,'')}`);
const sampleType = ref<'BACTERIA' | 'PHAGE' | 'VIRUS' | 'METAGENOME'>('BACTERIA');
const tech = ref<'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI'>('ILLUMINA');
const mode = ref<'isolate' | 'metagenome'>('isolate');
const threads = ref<number>(Math.max(2, (navigator.hardwareConcurrency || 8) - 2));

// 测序文件状态
const r1File = ref<{ name: string; path: string; size?: number } | null>(null);
const r2File = ref<{ name: string; path: string; size?: number } | null>(null);
const isDragging = ref<boolean>(false);
const autoDetectedSummary = ref<string | null>(null);

// 是否可以提交
const canSubmit = computed(() => {
  return !props.isRunning && !!r1File.value && !!taskName.value.trim();
});

// 核心函数：深度剥离扩展名与读长修饰词，提取纯净样本名
function extractCleanSampleName(filename: string): string {
  let name = filename;
  // 1. 循环剥离连续已知扩展名
  while (true) {
    const nextName = name.replace(/\.(fastq|fq|fasta|fa|fna|gz|tar|ab1|txt|bz2|zip)$/i, '');
    if (nextName === name) break;
    name = nextName;
  }
  // 2. 循环剥离末尾读长修饰与清洗标记
  while (true) {
    const nextName = name.replace(/[._-](R1|R2|1|2|read1|read2|forward|reverse|clean|raw|filtered|trimmed|val_1|val_2|subsample|pass|paired|ont|nanopore|hifi|pacbio|mgi|illumina|ngs)$/i, '');
    if (nextName === name) break;
    name = nextName;
  }
  return name.trim() || filename;
}

// 智能分析测序技术平台与生物类型
function inferTechAndType(files: File[], r1Name: string, r2Name?: string) {
  const combinedNames = [r1Name, r2Name || '', ...files.map(f => f.name)].join(' ').toLowerCase();

  // 1. 测序技术平台推断
  let detectedTech: 'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI' = 'ILLUMINA';
  if (combinedNames.includes('hifi') || combinedNames.includes('pacbio') || combinedNames.includes('ccs') || combinedNames.includes('sequel') || combinedNames.includes('revio')) {
    detectedTech = 'PACBIO_HIFI';
  } else if (combinedNames.includes('ont') || combinedNames.includes('nanopore') || combinedNames.includes('minion') || combinedNames.includes('promethion') || combinedNames.includes('gridion') || combinedNames.includes('dorado') || combinedNames.includes('guppy')) {
    detectedTech = 'NANOPORE';
  } else if (files.length >= 2 || r2Name || combinedNames.includes('_1.') || combinedNames.includes('_2.') || combinedNames.includes('_r1') || combinedNames.includes('_r2') || combinedNames.includes('illumina') || combinedNames.includes('mgi')) {
    detectedTech = 'ILLUMINA';
  }

  // 2. 样本生物类型推断
  let detectedSampleType: 'BACTERIA' | 'PHAGE' | 'VIRUS' | 'METAGENOME' = 'BACTERIA';
  let detectedMode: 'isolate' | 'metagenome' = 'isolate';

  if (combinedNames.includes('phage') || combinedNames.includes('bacteriophage') || combinedNames.includes('噬菌体') || combinedNames.includes('phi')) {
    detectedSampleType = 'PHAGE';
    detectedMode = 'isolate';
  } else if (combinedNames.includes('virus') || combinedNames.includes('viral') || combinedNames.includes('病毒')) {
    detectedSampleType = 'VIRUS';
    detectedMode = 'isolate';
  } else if (combinedNames.includes('meta') || combinedNames.includes('metagenome') || combinedNames.includes('宏基因组') || combinedNames.includes('microbiome') || combinedNames.includes('env')) {
    detectedSampleType = 'METAGENOME';
    detectedMode = 'metagenome';
  }

  return { detectedTech, detectedSampleType, detectedMode };
}

// 处理文件拖拽放置
function handleFileDrop(e: DragEvent) {
  isDragging.value = false;
  if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
  
  const files = Array.from(e.dataTransfer.files);
  processIncomingFiles(files);
}

// 通过 input 选择文件
function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement;
  if (!target || !target.files || target.files.length === 0) return;
  
  const files = Array.from(target.files);
  processIncomingFiles(files);
  target.value = '';
}

// 智能分析并分配 R1 / R2 文件
function processIncomingFiles(files: File[]) {
  if (!files || files.length === 0) return;

  // 1. 如果仅有 1 个文件
  if (files.length === 1) {
    const f = files[0];
    if (!f) return;
    const filePath = (f as any).path || f.name;
    r1File.value = { name: f.name, path: filePath, size: f.size };
    r2File.value = null;

    const cleanName = extractCleanSampleName(f.name);
    taskName.value = `${cleanName}_asm`;

    const { detectedTech, detectedSampleType, detectedMode } = inferTechAndType(files, f.name);
    tech.value = detectedTech;
    sampleType.value = detectedSampleType;
    mode.value = detectedMode;

    autoDetectedSummary.value = `已识别: ${detectedTech === 'ILLUMINA' ? '二代单端/双端' : detectedTech} · 纯净样本名: ${cleanName}`;
    return;
  }

  // 2. 如果有多个文件，尝试按 R1 / R2 或 1 / 2 自动配对
  let foundR1: any = null;
  let foundR2: any = null;

  for (const f of files) {
    if (!f) continue;
    const name = f.name.toLowerCase();
    const filePath = (f as any).path || f.name;

    if (
      name.includes('_r1') || name.includes('.r1.') || name.includes('_1.') || name.includes('.1.') ||
      name.endsWith('_1.fq.gz') || name.endsWith('_1.fastq.gz') || name.endsWith('_1.fq') || name.endsWith('_1.fastq') ||
      name.includes('read1') || name.includes('forward')
    ) {
      foundR1 = { name: f.name, path: filePath, size: f.size };
    } else if (
      name.includes('_r2') || name.includes('.r2.') || name.includes('_2.') || name.includes('.2.') ||
      name.endsWith('_2.fq.gz') || name.endsWith('_2.fastq.gz') || name.endsWith('_2.fq') || name.endsWith('_2.fastq') ||
      name.includes('read2') || name.includes('reverse')
    ) {
      foundR2 = { name: f.name, path: filePath, size: f.size };
    }
  }

  if (foundR1) {
    r1File.value = foundR1;
  } else if (files[0]) {
    const f0 = files[0];
    r1File.value = { name: f0.name, path: (f0 as any).path || f0.name, size: f0.size };
  }

  if (foundR2) {
    r2File.value = foundR2;
  } else if (files.length > 1 && !foundR1 && files[1]) {
    const f1 = files[1];
    r2File.value = { name: f1.name, path: (f1 as any).path || f1.name, size: f1.size };
  }

  // 自动更新任务名与识别类型
  if (r1File.value) {
    const cleanName = extractCleanSampleName(r1File.value.name);
    taskName.value = `${cleanName}_asm`;

    const { detectedTech, detectedSampleType, detectedMode } = inferTechAndType(files, r1File.value.name, r2File.value?.name);
    tech.value = detectedTech;
    sampleType.value = detectedSampleType;
    mode.value = detectedMode;

    const techLabel = detectedTech === 'ILLUMINA' ? '二代短读长双端 (Illumina / MGI NGS)' : (detectedTech === 'NANOPORE' ? '三代长读长 (Nanopore ONT)' : '三代 PacBio HiFi');
    autoDetectedSummary.value = `已智能识别为: ${techLabel} · 样本名: ${cleanName} · 类型: ${detectedSampleType}`;
  }
}

function clearR1() { 
  r1File.value = null; 
  autoDetectedSummary.value = null;
}
function clearR2() { 
  r2File.value = null; 
}

function formatBytes(bytes?: number): string {
  if (!bytes) return '';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function onStartAssembly() {
  if (!canSubmit.value || !r1File.value) return;

  const params: AssemblyRunParams = {
    name: taskName.value.trim(),
    sample_type: sampleType.value,
    tech: tech.value,
    mode: mode.value,
    r1_path: r1File.value.path,
    r2_path: r2File.value ? r2File.value.path : undefined,
    r1_name: r1File.value.name,
    r2_name: r2File.value ? r2File.value.name : undefined,
    threads: threads.value
  };

  emit('run', params);
}
</script>

<template>
  <div class="assembly-setup-container">
    <!-- 顶部标题 -->
    <div class="setup-header">
      <div class="title-row">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.2">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
        <span class="main-title">基因组组装配置 (NGCS Engine)</span>
      </div>
      <p class="sub-title">基于神经网络坐标系统 (NGCS) 的高保真从头组装，支持二代短读长残差流与三代长读长连续谱流形。</p>
    </div>

    <!-- 上传区域 -->
    <div 
      class="upload-dropzone" 
      :class="{ 'is-dragging': isDragging, 'has-files': r1File }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleFileDrop"
    >
      <input 
        id="assembly-file-input" 
        type="file" 
        multiple 
        accept=".fastq,.fq,.gz,.fasta,.fa,.fna" 
        class="hidden-file-input" 
        @change="handleFileSelect"
      />

      <!-- 未选择文件时的空状态 -->
      <div v-if="!r1File" class="dropzone-empty" onclick="document.getElementById('assembly-file-input').click()">
        <div class="icon-circle">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p class="primary-hint">拖拽测序数据文件至此处，或 <span class="click-link">点击选择文件</span></p>
        <p class="secondary-hint">支持二代双端 FASTQ (R1/R2) 及三代单端 FASTQ/FASTA (.fq.gz, .fastq, .fasta)</p>
      </div>

      <!-- 已选择文件时的卡片展示 -->
      <div v-else class="dropzone-filled">
        <div class="file-slots-row">
          <!-- R1 卡片 -->
          <div class="file-slot-card">
            <div class="slot-badge r1-badge">{{ tech === 'ILLUMINA' ? 'Read 1 (正向端 / Forward)' : '长读长数据 (Long Reads)' }}</div>
            <div class="slot-info">
              <span class="file-name" :title="r1File.path">{{ r1File.name }}</span>
              <span class="file-size">{{ formatBytes(r1File.size) }}</span>
            </div>
            <button class="remove-btn" @click="clearR1" title="移除该文件">×</button>
          </div>

          <!-- R2 卡片 -->
          <div v-if="tech === 'ILLUMINA'" class="file-slot-card" :class="{ 'is-empty-slot': !r2File }">
            <div class="slot-badge r2-badge">Read 2 (反向端 / Reverse)</div>
            <div v-if="r2File" class="slot-info">
              <span class="file-name" :title="r2File.path">{{ r2File.name }}</span>
              <span class="file-size">{{ formatBytes(r2File.size) }}</span>
            </div>
            <div v-else class="slot-empty-hint" onclick="document.getElementById('assembly-file-input').click()">
              <span>+ 选择或拖入 R2 双端文件</span>
            </div>
            <button v-if="r2File" class="remove-btn" @click="clearR2" title="移除该文件">×</button>
          </div>
        </div>

        <!-- 智能识别提示徽章 -->
        <div v-if="autoDetectedSummary" class="auto-detected-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span>{{ autoDetectedSummary }}</span>
        </div>

        <div class="replace-actions">
          <button class="text-btn" onclick="document.getElementById('assembly-file-input').click()">
            重新选择或添加文件
          </button>
        </div>
      </div>
    </div>

    <!-- 参数配置表单 -->
    <div class="form-grid">
      <!-- 任务名称 -->
      <div class="form-group">
        <label class="form-label">任务名称</label>
        <input 
          v-model="taskName" 
          type="text" 
          class="form-input" 
          placeholder="例如: Sample_01_Assembly"
        />
      </div>

      <!-- 测序平台 -->
      <div class="form-group">
        <label class="form-label">测序技术平台</label>
        <select v-model="tech" class="form-select">
          <option value="ILLUMINA">二代短读长双端 (Illumina / MGI NGS)</option>
          <option value="NANOPORE">三代长读长 (Oxford Nanopore ONT)</option>
          <option value="PACBIO_HIFI">三代高精度长读长 (PacBio HiFi)</option>
        </select>
      </div>

      <!-- 样本生物类型 -->
      <div class="form-group">
        <label class="form-label">样本生物类型</label>
        <select v-model="sampleType" class="form-select">
          <option value="BACTERIA">细菌 (Bacteria / Archaea)</option>
          <option value="PHAGE">噬菌体 (Bacteriophage)</option>
          <option value="VIRUS">病毒 (Virus)</option>
          <option value="METAGENOME">宏基因组 (Metagenome)</option>
        </select>
      </div>

      <!-- 组装模式 -->
      <div class="form-group">
        <label class="form-label">组装模式</label>
        <select v-model="mode" class="form-select">
          <option value="isolate">单菌分离株模式 (Isolate - 高深度精修)</option>
          <option value="metagenome">宏基因组模式 (Metagenome - 复杂多丰度)</option>
        </select>
      </div>

      <!-- 线程数 -->
      <div class="form-group">
        <label class="form-label">并行计算线程数</label>
        <input 
          v-model.number="threads" 
          type="number" 
          min="1" 
          max="64" 
          class="form-input"
        />
      </div>
    </div>

    <!-- 底部操作按钮 -->
    <div class="setup-footer">
      <div class="status-tip">
        <span v-if="isBusy" class="busy-pill">
          <span class="busy-dot"></span>
          当前引擎有任务正在运行，新任务将进入排队队列
        </span>
      </div>

      <button 
        class="submit-btn" 
        :disabled="!canSubmit || isRunning" 
        @click="onStartAssembly"
      >
        <svg v-if="isRunning" class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="12" />
        </svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
        <span>{{ isRunning ? '正在启动...' : '启动基因组拼接' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.assembly-setup-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px;
  overflow-y: auto;
  gap: 20px;
}

.setup-header .title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.main-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
}
.sub-title {
  font-size: 0.8rem;
  color: #64748b;
  margin-top: 4px;
}

.upload-dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  background: #f8fafc;
  padding: 30px 20px;
  text-align: center;
  transition: all 0.2s ease;
  cursor: pointer;
}
.upload-dropzone:hover, .upload-dropzone.is-dragging {
  border-color: #3b82f6;
  background: #eff6ff;
}
.upload-dropzone.has-files {
  cursor: default;
  padding: 16px;
  border-style: solid;
  border-color: #e2e8f0;
  background: #ffffff;
}

.hidden-file-input { display: none; }

.dropzone-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.icon-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: #eff6ff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.primary-hint {
  font-size: 0.9rem;
  font-weight: 600;
  color: #1e293b;
}
.click-link {
  color: #2563eb;
  text-decoration: underline;
}
.secondary-hint {
  font-size: 0.75rem;
  color: #94a3b8;
}

.dropzone-filled {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.file-slots-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.file-slot-card {
  position: relative;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
}
.file-slot-card.is-empty-slot {
  border-style: dashed;
  cursor: pointer;
  background: transparent;
}
.slot-badge {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  align-self: flex-start;
}
.r1-badge { background: #dbeafe; color: #1e40af; }
.r2-badge { background: #e0e7ff; color: #3730a3; }

.slot-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.file-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-size {
  font-size: 0.7rem;
  color: #64748b;
  white-space: nowrap;
}
.slot-empty-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  padding: 6px 0;
}
.remove-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  background: none;
  border: none;
  font-size: 1.1rem;
  color: #94a3b8;
  cursor: pointer;
  line-height: 1;
}
.remove-btn:hover { color: #ef4444; }

.auto-detected-banner {
  background: #eff6ff;
  border: 1px solid #dbeafe;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 0.75rem;
  color: #1d4ed8;
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.replace-actions {
  display: flex;
  justify-content: flex-end;
}
.text-btn {
  background: none;
  border: none;
  font-size: 0.75rem;
  color: #2563eb;
  cursor: pointer;
}
.text-btn:hover { text-decoration: underline; }

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #475569;
}
.form-input, .form-select {
  height: 38px;
  padding: 0 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.85rem;
  color: #1e293b;
  background: #ffffff;
  outline: none;
  transition: border-color 0.2s;
}
.form-input:focus, .form-select:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37,99,235,0.1);
}

.setup-footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 16px;
}

.busy-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #b45309;
  background: #fef3c7;
  padding: 4px 10px;
  border-radius: 20px;
}
.busy-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d97706;
  animation: pulse 1.5s infinite;
}

.submit-btn {
  height: 44px;
  padding: 0 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  border: none;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 4px 12px rgba(37,99,235,0.25);
  transition: all 0.2s;
}
.submit-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #1d4ed8, #1e40af);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(37,99,235,0.35);
}
.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}
.spin-icon { animation: spin 1s linear infinite; }
</style>
