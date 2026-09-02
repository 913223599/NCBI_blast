<script setup lang="ts">
/**
 * AssemblySetup - 基因组拼接配置与数据上传面板 (纯净智能识别版)
 */
import { ref, computed } from 'vue';
import { getBridge } from '../../../bridge';
import type { AssemblyRunParams } from '../types';

const props = defineProps<{
  isRunning: boolean;
  isBusy: boolean;
}>();

const emit = defineEmits<{
  (e: 'run', params: AssemblyRunParams): void;
}>();

// 基础参数
const taskName = ref<string>(`Assembly_${new Date().toISOString().slice(0,10).replace(/-/g,'')}`);
const sampleType = ref<'BACTERIA' | 'PHAGE' | 'VIRUS' | 'METAGENOME'>('BACTERIA');
const tech = ref<'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI'>('ILLUMINA');
const mode = ref<'isolate' | 'metagenome' | 'metagenome_deep' | 'unconstrained'>('isolate');
const threads = ref<number>(Math.max(2, (navigator.hardwareConcurrency || 8) - 2));

// 高级参数 (NGCS 官方支持可调参数)
const showAdvanced = ref<boolean>(false);
const minContigLength = ref<number>(500);
const minReadLength = ref<number>(1000);
const minContainmentIdentity = ref<number>(0.92);
const maxReads = ref<number | null>(null);
const enableQC = ref<boolean>(true);

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
  let detectedMode: 'isolate' | 'metagenome' | 'metagenome_deep' | 'unconstrained' = 'isolate';

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
async function handleFileDrop(e: DragEvent) {
  isDragging.value = false;
  if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
  
  const files = Array.from(e.dataTransfer.files);
  await processIncomingFiles(files);
}

// 通过点击上传区域
async function handleDropzoneClick() {
  const isElectron = !!(window as any).electronAPI;
  if (isElectron) {
    try {
      const bridge = getBridge();
      const paths = await bridge.request_file_load(['fastq', 'fq', 'gz', 'fasta', 'fa', 'fna'], true);
      if (paths && paths.length > 0) {
        processPathList(paths);
        return;
      }
    } catch (e) {
      console.warn('原生对话框调用失败，回退至 input 选择:', e);
    }
  }
  document.getElementById('assembly-file-input')?.click();
}

// 通过 input 选择文件
async function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement;
  if (!target || !target.files || target.files.length === 0) return;
  
  const files = Array.from(target.files);
  await processIncomingFiles(files);
  target.value = '';
}

// 统一解析 File 对象的物理路径 (优先 Electron 真实路径，次选自动上传)
async function resolveFileItem(file: File): Promise<{ name: string; path: string; size: number }> {
  const name = file.name;
  const size = file.size;

  // 1. Electron 桌面端原生获取真实路径
  const localPath = (window as any).electronAPI?.getPathForFile?.(file) || (file as any).path || '';
  if (localPath && (localPath.includes('/') || localPath.includes('\\'))) {
    return { name, path: localPath, size };
  }

  // 2. 纯 Web 环境或未能直接读取物理路径：自动上传至后端临时目录
  try {
    const bridge = getBridge();
    const res = await bridge.upload_file(file);
    if (res && res.success && res.path) {
      return { name, path: res.path, size };
    }
  } catch (err) {
    console.error('上传测序文件失败:', err);
  }

  return { name, path: localPath || name, size };
}

// 处理物理路径列表 (来自 Electron 原生文件选择对话框)
function processPathList(paths: string[]) {
  if (!paths || paths.length === 0) return;
  const fileItems = paths.map(p => {
    const name = p.split(/[/\\]/).pop() || p;
    return { name, path: p, size: 0 };
  });

  assignFileSlots(fileItems);
}

// 智能分析并分配 R1 / R2 文件 (从 File[] 解析)
async function processIncomingFiles(files: File[]) {
  if (!files || files.length === 0) return;

  const resolvedItems = await Promise.all(files.map(f => resolveFileItem(f)));
  assignFileSlots(resolvedItems);
}

// 分配槽位与推断
function assignFileSlots(items: Array<{ name: string; path: string; size: number }>) {
  if (!items || items.length === 0) return;

  // 1. 如果仅有 1 个文件
  if (items.length === 1) {
    const f = items[0];
    if (!f) return;
    r1File.value = f;
    r2File.value = null;

    const cleanName = extractCleanSampleName(f.name);
    taskName.value = `${cleanName}_asm`;

    const { detectedTech, detectedSampleType, detectedMode } = inferTechAndType([{ name: f.name } as any], f.name);
    tech.value = detectedTech;
    sampleType.value = detectedSampleType;
    mode.value = detectedMode;

    autoDetectedSummary.value = `已智能识别为: ${detectedTech === 'ILLUMINA' ? '二代短读长 (Illumina/MGI)' : detectedTech} · 样本名: ${cleanName} · 类型: ${detectedSampleType}`;
    return;
  }

  // 2. 如果有多个文件，尝试按 R1 / R2 或 1 / 2 自动配对
  let foundR1: any = null;
  let foundR2: any = null;

  for (const f of items) {
    if (!f) continue;
    const name = f.name.toLowerCase();

    if (
      name.includes('_r1') || name.includes('.r1.') || name.includes('_1.') || name.includes('.1.') ||
      name.endsWith('_1.fq.gz') || name.endsWith('_1.fastq.gz') || name.endsWith('_1.fq') || name.endsWith('_1.fastq') ||
      name.includes('read1') || name.includes('forward')
    ) {
      foundR1 = f;
    } else if (
      name.includes('_r2') || name.includes('.r2.') || name.includes('_2.') || name.includes('.2.') ||
      name.endsWith('_2.fq.gz') || name.endsWith('_2.fastq.gz') || name.endsWith('_2.fq') || name.endsWith('_2.fastq') ||
      name.includes('read2') || name.includes('reverse')
    ) {
      foundR2 = f;
    }
  }

  if (foundR1) {
    r1File.value = foundR1;
  } else if (items[0]) {
    r1File.value = items[0];
  }

  if (foundR2) {
    r2File.value = foundR2;
  } else if (items.length > 1 && !foundR1 && items[1]) {
    r2File.value = items[1];
  }

  // 自动更新任务名与识别类型
  if (r1File.value) {
    const cleanName = extractCleanSampleName(r1File.value.name);
    taskName.value = `${cleanName}_asm`;

    const { detectedTech, detectedSampleType, detectedMode } = inferTechAndType(items.map(f => ({ name: f.name } as any)), r1File.value.name, r2File.value?.name);
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
    threads: threads.value,
    min_contig_length: minContigLength.value,
    min_read_length: minReadLength.value,
    min_containment_identity: minContainmentIdentity.value,
    max_reads: maxReads.value || undefined,
    enable_qc: enableQC.value
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
      <div v-if="!r1File" class="dropzone-empty" @click="handleDropzoneClick">
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
            <button class="remove-btn" @click.stop="clearR1" title="移除该文件">×</button>
          </div>

          <!-- R2 卡片 -->
          <div v-if="tech === 'ILLUMINA'" class="file-slot-card" :class="{ 'is-empty-slot': !r2File }">
            <div class="slot-badge r2-badge">Read 2 (反向端 / Reverse)</div>
            <div v-if="r2File" class="slot-info">
              <span class="file-name" :title="r2File.path">{{ r2File.name }}</span>
              <span class="file-size">{{ formatBytes(r2File.size) }}</span>
            </div>
            <div v-else class="slot-empty-hint" @click.stop="handleDropzoneClick">
              <span>+ 选择或拖入 R2 双端文件</span>
            </div>
            <button v-if="r2File" class="remove-btn" @click.stop="clearR2" title="移除该文件">×</button>
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
          <button class="text-btn" @click="handleDropzoneClick">
            重新选择或添加文件
          </button>
        </div>
      </div>
    </div>

    <!-- 基础参数配置表单 -->
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

      <!-- NGCS 原生组装模式 -->
      <div class="form-group">
        <label class="form-label">NGCS 组装模式</label>
        <select v-model="mode" class="form-select">
          <option value="isolate">单菌分离株模式 (Isolate - 高深度单菌精修)</option>
          <option value="metagenome">宏基因组模式 (Metagenome - 复杂多丰度群落)</option>
          <option value="metagenome_deep">宏基因组深度模式 (Metagenome Deep - 超低丰度深度挖掘)</option>
          <option value="unconstrained">无约束模式 (Unconstrained - 极端复杂/微小环状结构)</option>
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

    <!-- 高级调优参数折叠面板 (NGCS 原生算法参数) -->
    <div class="advanced-panel-wrapper">
      <div class="advanced-toggle" @click="showAdvanced = !showAdvanced">
        <div class="adv-left">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span class="adv-title">NGCS 高级算法与产物过滤参数</span>
        </div>
        <span class="adv-arrow" :class="{ 'is-open': showAdvanced }">▼</span>
      </div>

      <div v-show="showAdvanced" class="advanced-form-grid">
        <!-- 最小 Contig 长度 -->
        <div class="form-group">
          <label class="form-label">最小 Contig 产物长度 (bp)</label>
          <input 
            v-model.number="minContigLength" 
            type="number" 
            min="100" 
            step="100" 
            class="form-input" 
            placeholder="默认: 500"
          />
          <span class="field-hint">过滤短于此长度的碎片 (--min-contig-len)</span>
        </div>

        <!-- 气泡去重相似度阈值 -->
        <div class="form-group">
          <label class="form-label">气泡冗余去重相似度阈值</label>
          <input 
            v-model.number="minContainmentIdentity" 
            type="number" 
            min="0.5" 
            max="1.0" 
            step="0.01" 
            class="form-input" 
            placeholder="默认: 0.92"
          />
          <span class="field-hint">净化杂合气泡相似度 (--min-containment-identity)</span>
        </div>

        <!-- 长读长最小长度过滤 -->
        <div v-if="tech !== 'ILLUMINA'" class="form-group">
          <label class="form-label">长读长过滤最小长度 (bp)</label>
          <input 
            v-model.number="minReadLength" 
            type="number" 
            min="200" 
            step="100" 
            class="form-input" 
            placeholder="默认: 1000"
          />
          <span class="field-hint">过滤超短读长 (--min-len)</span>
        </div>

        <!-- 最大读取 Reads 上限 -->
        <div class="form-group">
          <label class="form-label">最大读取 Reads 数量 (可选)</label>
          <input 
            v-model.number="maxReads" 
            type="number" 
            min="10000" 
            step="50000" 
            class="form-input" 
            placeholder="留空为全量 Reads"
          />
          <span class="field-hint">限制导入数量以加速测试 (--max-reads)</span>
        </div>

        <!-- Fastp 质控开关 -->
        <div class="form-group checkbox-group">
          <label class="checkbox-label">
            <input v-model="enableQC" type="checkbox" class="form-checkbox" />
            <span>启用 Fastp 自动接头修剪与低质量过滤</span>
          </label>
          <span class="field-hint">如已在上游完成严格质控可取消勾选以提升速度</span>
        </div>
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
  gap: 20px;
  width: 100%;
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
  padding: 20px;
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

.advanced-panel-wrapper {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}
.advanced-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  cursor: pointer;
  background: #f8fafc;
  user-select: none;
  transition: background 0.2s;
}
.advanced-toggle:hover {
  background: #f1f5f9;
}
.adv-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
}
.adv-title {
  font-size: 0.82rem;
  font-weight: 600;
}
.adv-arrow {
  font-size: 0.75rem;
  color: #94a3b8;
  transition: transform 0.2s;
}
.adv-arrow.is-open {
  transform: rotate(180deg);
}

.advanced-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  padding: 18px;
  border-top: 1px solid #f1f5f9;
}
.field-hint {
  font-size: 0.68rem;
  color: #94a3b8;
}

.checkbox-group {
  justify-content: center;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}
.form-checkbox {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
  cursor: pointer;
}

.setup-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  padding-bottom: 28px;
  width: 100%;
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
