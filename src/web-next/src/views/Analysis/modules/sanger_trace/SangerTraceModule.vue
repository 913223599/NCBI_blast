<script setup lang="ts">
/**
 * SangerTraceModule.vue
 * Sanger 测序色谱峰图质量分析与智能解峰工作台
 */
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { getBridge } from '../../../../bridge';
import { useAppStore } from '../../../../stores/app';
import { useBlastStore } from '../../../../stores/blast';
import type { SampleDeconvResult, BatchAnalysisResponse } from './types';
import TraceChromatogramViewer from './components/TraceChromatogramViewer.vue';
import DeconvResultsTable from './components/DeconvResultsTable.vue';

const appStore = useAppStore();
const blastStore = useBlastStore();
const router = useRouter();

// 状态管理
const isLoading = ref<boolean>(false);
const samples = ref<SampleDeconvResult[]>([]);
const selectedSample = ref<SampleDeconvResult | null>(null);
const isTraceCollapsed = ref<boolean>(false);
const trimThreshold = ref<number>(20);

function toggleTraceCollapse() {
  isTraceCollapsed.value = !isTraceCollapsed.value;
}

function handleSelectSample(sample: SampleDeconvResult) {
  selectedSample.value = sample;
  isTraceCollapsed.value = false;
}

// 文件拖拽状态
const isDragging = ref<boolean>(false);

function onDragOver(e: DragEvent) {
  e.preventDefault();
  isDragging.value = true;
}

function onDragLeave(e: DragEvent) {
  e.preventDefault();
  // 检查是否真正离开了容器
  const currentTarget = e.currentTarget as HTMLElement;
  const relatedTarget = e.relatedTarget as HTMLElement;
  if (!currentTarget || !currentTarget.contains(relatedTarget)) {
    isDragging.value = false;
  }
}

async function handleDrop(e: DragEvent) {
  e.preventDefault();
  isDragging.value = false;
  if (!e.dataTransfer?.files || e.dataTransfer.files.length === 0) return;

  const files = Array.from(e.dataTransfer.files);
  const bridge = getBridge();

  // 1. 尝试提取所有本地路径 (Electron 桌面端)
  const localPaths: string[] = [];
  for (const f of files) {
    const p = bridge.get_path_for_file?.(f) || (f as any).path;
    if (p) {
      localPaths.push(p);
    }
  }

  if (localPaths.length > 0) {
    // 桌面端：直接调用本地路径批量解析
    await analyzeFilePaths(localPaths);
  } else {
    // 浏览器端：执行文件上传解析
    await uploadFiles(files);
  }
}

// 统计指标
const stats = computed(() => {
  const total = samples.value.length;
  const indels = samples.value.filter(s => s.diagnosis?.category === 'HETERO_INDEL').length;
  const mixed = samples.value.filter(s => s.diagnosis?.category === 'MIXED_TEMPLATE').length;
  const clean = samples.value.filter(s => s.diagnosis?.category === 'CLEAN_SINGLE').length;
  const totalDiffs = samples.value.reduce((acc, s) => acc + (s.machine_diff_count || 0), 0);

  return { total, indels, mixed, clean, totalDiffs };
});

// 触发文件选择 (Electron 对话框或 Web 文件)
async function triggerFileImport() {
  const bridge = getBridge();
  if (bridge.request_file_load) {
    try {
      const paths = await bridge.request_file_load(['ab1', 'abi', 'zip'], true);
      if (paths && paths.length > 0) {
        await analyzeFilePaths(paths);
      }
    } catch (err: any) {
      console.warn('Native file load fallback:', err);
    }
  } else {
    // 浏览器环境兜底 input
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.ab1,.abi,.zip';
    input.onchange = async (e: any) => {
      const files: File[] = Array.from(e.target.files || []);
      if (files.length > 0) {
        await uploadFiles(files);
      }
    };
    input.click();
  }
}

// 自然排序辅助函数
function naturalSortSamples(list: SampleDeconvResult[]) {
  list.sort((a, b) => {
    const idA = a.sample_id || a.filename || '';
    const idB = b.sample_id || b.filename || '';
    return idA.localeCompare(idB, undefined, { numeric: true, sensitivity: 'base' });
  });
}

// 通过本地路径解析 (桌面端)
async function analyzeFilePaths(paths: string[]) {
  isLoading.value = true;
  try {
    const bridge = getBridge();
    const res: BatchAnalysisResponse = await bridge.analyze_sanger_traces?.(paths, trimThreshold.value);
    if (res && res.success) {
      const incoming = res.samples || [];
      naturalSortSamples(incoming);
      samples.value = incoming;
      if (samples.value.length > 0) {
        selectedSample.value = samples.value[0] || null;
      }
      appStore.showNotification(`成功解析 ${res.total_samples} 个 Sanger 样本`, 'success');
    } else {
      appStore.showNotification(res?.error || '解析失败', 'error');
    }
  } catch (err: any) {
    console.error('Analyze paths error:', err);
    appStore.showNotification(`解析失败: ${err.message}`, 'error');
  } finally {
    isLoading.value = false;
  }
}

// 通过上传解析 (Web端)
async function uploadFiles(files: File[]) {
  isLoading.value = true;
  try {
    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('trim_threshold', String(trimThreshold.value));

      const res = await fetch('/api/sanger/trace/upload', {
        method: 'POST',
        body: formData
      });
      const data: BatchAnalysisResponse = await res.json();
      if (data.success && data.samples) {
        samples.value.push(...data.samples);
      }
    }
    naturalSortSamples(samples.value);
    if (samples.value.length > 0 && !selectedSample.value) {
      selectedSample.value = samples.value[0] || null;
    }
    appStore.showNotification(`成功上传并解析 ${files.length} 个文件`, 'success');
  } catch (err: any) {
    appStore.showNotification(`上传失败: ${err.message}`, 'error');
  } finally {
    isLoading.value = false;
  }
}

// 导出 FASTA 序列
async function handleExportFasta(selectedSamples: SampleDeconvResult[], mode: string) {
  if (selectedSamples.length === 0) return;
  try {
    const bridge = getBridge();
    const res = await bridge.export_sanger_fasta?.(selectedSamples, mode);
    if (res && res.success && res.fasta_text) {
      const filename = `sanger_deconvoluted_${new Date().toISOString().slice(0, 10)}.fasta`;
      await bridge.save_file?.(res.fasta_text, filename);
      appStore.showNotification(`已成功导出 ${res.count} 条解峰序列`, 'success');
    }
  } catch (err: any) {
    appStore.showNotification(`导出失败: ${err.message}`, 'error');
  }
}

// 一键送入 BLAST 分析
async function handleSendToBlast(selectedSamples: SampleDeconvResult[]) {
  if (selectedSamples.length === 0) return;

  const seqList: { id: string; sequence: string }[] = [];
  for (const s of selectedSamples) {
    const alleles = s.sequences?.alleles || [];
    for (const a of alleles) {
      // 过滤 IUPAC 简并序列（含有大量非 ACGT 字符，NCBI blastn 无法建立 Hash 种子）
      if (a.allele_id === 'IUPAC_Consensus') continue;
      seqList.push({
        id: `${s.sample_id}_${a.allele_id}`,
        sequence: a.sequence
      });
    }
  }

  if (seqList.length === 0) {
    appStore.showNotification('没有可提交的比对序列', 'warning');
    return;
  }

  isLoading.value = true;
  try {
    const bridge = getBridge();
    const res = await bridge.create_blast_from_traces?.({
      task_name: `Deconv_${selectedSamples.length}_Samples_${new Date().toLocaleTimeString()}`,
      sequences: seqList,
      program: 'blastn',
      database: 'ncbi_16s',
      evalue: 0.05,
      max_hits: 50,
      threads: 4,
      filter_low_complexity: true,
      matrix: 'BLOSUM62',
      gap_open: 11,
      gap_extend: 1
    });

    if (res && res.status === 'started') {
      // 同步全局 BLAST 参数状态以对齐界面展示
      blastStore.params.database = 'ncbi_16s';
      blastStore.params.program = 'auto';
      blastStore.params.evalue = 0.05;
      blastStore.params.maxHits = 50;
      blastStore.params.threads = 4;
      blastStore.params.filterLowComplexity = true;
      blastStore.params.matrix = 'BLOSUM62';
      blastStore.params.gapOpen = 11;
      blastStore.params.gapExtend = 1;
      if (res.task_id) {
        blastStore.activeTaskId = res.task_id;
      }

      appStore.showNotification(`已创建 16S BLAST 任务，共 ${res.sequence_count} 条序列，正在跳转...`, 'success');
      setTimeout(() => {
        router.push('/blast');
      }, 500);
    } else {
      appStore.showNotification(res?.error || '创建 BLAST 任务失败', 'error');
    }
  } catch (err: any) {
    appStore.showNotification(`提交失败: ${err.message}`, 'error');
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div 
    class="sanger-trace-workbench"
    :class="{ 'is-dragover-active': isDragging }"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="handleDrop"
  >
    <!-- 全屏拖拽悬停遮罩 -->
    <div v-if="isDragging" class="drag-drop-overlay">
      <div class="overlay-box">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="12" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
        <h3>释放鼠标立即导入</h3>
        <p>支持批量拖入 .ab1、.abi 单文件或 .zip 压缩包</p>
      </div>
    </div>

    <!-- 顶部操作与统计面板 -->
    <div class="workbench-header">
      <div class="header-left">
        <div class="title-row">
          <h2>Sanger 峰图质量分析与智能解峰</h2>
          <span class="version-tag">PRO</span>
        </div>
        <p class="subtitle">针对 16S/目的基因测序中因 InDel 移码、多拷贝异质性或复合模板导致的“双峰”进行智能解卷积拆分与数据挽救。</p>
      </div>

      <div class="header-actions">
        <div class="trim-setting">
          <span class="label">质量裁剪 Q:</span>
          <input type="number" v-model.number="trimThreshold" min="10" max="40" class="input-num" />
        </div>
        <button class="btn-import-traces" @click="triggerFileImport" :disabled="isLoading">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          导入 AB1 / ZIP 压缩包
        </button>
      </div>
    </div>

    <!-- 统计卡片指标栏 -->
    <div v-if="samples.length > 0" class="stats-row">
      <div class="stat-card">
        <div class="stat-label">已载入样本</div>
        <div class="stat-value">{{ stats.total }} <span class="unit">个</span></div>
      </div>
      <div class="stat-card highlight-indel">
        <div class="stat-label">杂合 InDel 移码双峰</div>
        <div class="stat-value">{{ stats.indels }} <span class="unit">个</span></div>
        <div class="stat-desc">可完美拆分双单倍型</div>
      </div>
      <div class="stat-card highlight-mixed">
        <div class="stat-label">复合模板 / 混合菌</div>
        <div class="stat-value">{{ stats.mixed }} <span class="unit">个</span></div>
        <div class="stat-desc">已拆分出主优势菌与次要共存菌</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">单峰正常样本</div>
        <div class="stat-value">{{ stats.clean }} <span class="unit">个</span></div>
      </div>
      <div class="stat-card highlight-diff">
        <div class="stat-label">修正仪器误判碱基</div>
        <div class="stat-value">+{{ stats.totalDiffs }} <span class="unit">bp</span></div>
        <div class="stat-desc">大幅提升 BLAST 相似度</div>
      </div>
    </div>

    <!-- 主展示区：色谱图与诊断信息 (若有选中样本) -->
    <div v-if="selectedSample" class="trace-inspection-card" :class="{ 'is-collapsed': isTraceCollapsed }">
      <div class="inspection-header">
        <div class="header-main-info">
          <div class="sample-info-title">
            <span class="sample-badge">当前查看</span>
            <h3>{{ selectedSample.sample_id }}</h3>
            <span class="diag-badge" :class="selectedSample.diagnosis?.category">
              {{ selectedSample.diagnosis?.category }}
            </span>
            <span class="meta-tag mono">裁剪后长度: {{ selectedSample.trimmed_len }} bp (Q{{ selectedSample.avg_quality }})</span>
          </div>
          <div class="diagnosis-summary-text">
            {{ selectedSample.diagnosis?.description }}
          </div>
        </div>

        <div class="header-ctrl-actions">
          <button 
            class="btn-toggle-trace" 
            @click="toggleTraceCollapse"
            :title="isTraceCollapsed ? '展开色谱峰图' : '收起色谱峰图'"
          >
            <span v-if="isTraceCollapsed">▼ 展开峰图</span>
            <span v-else>▲ 收起峰图</span>
          </button>
          <button 
            class="btn-close-trace" 
            @click="selectedSample = null"
            title="关闭当前峰图查看"
          >
            ✕
          </button>
        </div>
      </div>

      <!-- 四通道色谱图 Canvas (支持收起/展开) -->
      <TraceChromatogramViewer v-show="!isTraceCollapsed" :sample="selectedSample" />
    </div>

    <!-- 空数据上传引导区 -->
    <div 
      v-else-if="!isLoading && samples.length === 0" 
      class="empty-workbench-dropzone"
      :class="{ 'is-dragging': isDragging }"
      @click="triggerFileImport"
    >
      <div class="drop-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="12" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
      </div>
      <h3>点击或拖拽上传 Sanger 测序原始文件 (.ab1 / .zip)</h3>
      <p>系统将自动解析四通道原始荧光信号、诊断双峰成因、执行 InDel 相位位移减法解卷积并输出纯净序列</p>
      <button class="btn-select-file">选择 AB1 文件或 ZIP 压缩包</button>
    </div>

    <!-- 下方结果列表 -->
    <div v-if="samples.length > 0" class="results-table-section">
      <DeconvResultsTable 
        :samples="samples"
        :selected-sample-id="selectedSample?.sample_id || ''"
        @select-sample="handleSelectSample"
        @export-fasta="handleExportFasta"
        @send-to-blast="handleSendToBlast"
      />
    </div>
  </div>
</template>

<style scoped>
.sanger-trace-workbench {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 20px;
  background: #f8fafc;
  gap: 16px;
  overflow-y: auto;
  box-sizing: border-box;
}

.workbench-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-row h2 {
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.version-tag {
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: white;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.subtitle {
  font-size: 0.78rem;
  color: #64748b;
  margin: 4px 0 0 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.trim-setting {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  color: #475569;
  font-weight: 600;
}

.input-num {
  width: 50px;
  padding: 4px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  text-align: center;
}

.btn-import-traces {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  font-weight: 700;
  font-size: 0.82rem;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
  transition: transform 0.1s;
}

.btn-import-traces:hover:not(:disabled) {
  transform: translateY(-1px);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.stat-card {
  background: white;
  border-radius: 10px;
  padding: 12px 16px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 0.72rem;
  color: #64748b;
  font-weight: 600;
}

.stat-value {
  font-size: 1.35rem;
  font-weight: 800;
  color: #1e293b;
  margin: 4px 0;
}

.stat-value .unit {
  font-size: 0.75rem;
  font-weight: normal;
  color: #94a3b8;
}

.stat-desc {
  font-size: 0.7rem;
  color: #94a3b8;
}

.highlight-indel { border-left: 4px solid #ea580c; }
.highlight-indel .stat-value { color: #c2410c; }

.highlight-mixed { border-left: 4px solid #7c3aed; }
.highlight-mixed .stat-value { color: #6d28d9; }

.highlight-diff { border-left: 4px solid #059669; }
.highlight-diff .stat-value { color: #047857; }

.trace-inspection-card {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inspection-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.header-main-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.header-ctrl-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-toggle-trace {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-toggle-trace:hover {
  background: #e2e8f0;
  color: #0f172a;
  border-color: #94a3b8;
}

.btn-close-trace {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-close-trace:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
}

.trace-inspection-card.is-collapsed {
  padding-bottom: 12px;
}

.results-table-section {
  display: flex;
  flex-direction: column;
  min-height: 550px;
}

.empty-workbench-dropzone {
  background: white;
  border: 2px dashed #cbd5e1;
  border-radius: 16px;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.empty-workbench-dropzone:hover,
.empty-workbench-dropzone.is-dragging {
  border-color: #2563eb;
  background: #eff6ff;
}

.empty-workbench-dropzone h3 {
  margin: 12px 0 6px 0;
  font-size: 1.05rem;
  color: #1e293b;
}

.empty-workbench-dropzone p {
  font-size: 0.8rem;
  color: #64748b;
  max-width: 500px;
  margin: 0 0 16px 0;
}

.btn-select-file {
  background: #2563eb;
  color: white;
  font-weight: 600;
  font-size: 0.8rem;
  padding: 8px 18px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
}

.drag-drop-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(37, 99, 235, 0.12);
  backdrop-filter: blur(4px);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.overlay-box {
  background: white;
  border: 2px dashed #2563eb;
  border-radius: 16px;
  padding: 40px 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

.overlay-box h3 {
  color: #1e293b;
  font-size: 1.2rem;
  margin: 16px 0 6px 0;
}

.overlay-box p {
  color: #64748b;
  font-size: 0.85rem;
  margin: 0;
}

.results-table-section {
  flex: 1;
  min-height: 350px;
  display: flex;
  flex-direction: column;
}
</style>
