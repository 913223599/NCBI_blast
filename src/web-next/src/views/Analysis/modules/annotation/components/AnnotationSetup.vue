<script setup lang="ts">
/**
 * AnnotationSetup - 功能注释输入与参数配置面板
 */
import { ref, reactive, watch, onMounted } from 'vue';
import { getBridge } from '../../../../../bridge';
import type { AnnotationRunParams, ContigMetaItem, FastaInspectResult } from '../types';
import ContigSelector from './ContigSelector.vue';

const props = defineProps<{
  isRunning: boolean;
}>();

const emit = defineEmits<{
  (e: 'run', params: AnnotationRunParams): void;
}>();

// 输入来源模式
const inputMode = ref<'upload' | 'paste' | 'assembly'>('upload');

// 表单状态
const form = reactive<AnnotationRunParams>({
  task_name: 'Annotation_' + new Date().toISOString().slice(0, 10).replace(/-/g, ''),
  sample_type: 'BACTERIA',
  engine: 'auto',
  fasta_path: '',
  fasta_content: '',
  prefix: 'ANNO',
  genetic_code: 11,
  min_contig_len: 200,
  threads: undefined,
  enable_waterfall: true,
  enable_homology: true,
  enable_phold: true,
  enable_safety_audit: true
});

// 文件上传状态
const uploadedFileName = ref<string>('');
const isUploading = ref<boolean>(false);
const isDragging = ref<boolean>(false);

// FASTA 预扫描与 Contig 选择状态
const inspectedContigs = ref<ContigMetaItem[]>([]);
const inspectTotalLength = ref<number>(0);
const inspectGc = ref<number>(0);
const isInspecting = ref<boolean>(false);
const selectedContigIds = ref<string[]>([]);

// 组装历史列表 (从拼接管线导入)
const assemblyHistory = ref<any[]>([]);
const selectedAssemblyTask = ref<string>('');
const isAssemblyLoading = ref<boolean>(false);

// 高级参数折叠开关
const showAdvanced = ref<boolean>(false);

// 预设示例数据
const SAMPLE_FASTA = `>NC_005816.1 Yersinia pestis KIM 10 plasmid pPCP1, complete sequence
ATGAAACGCATTAGCACCACCATTACCACCACCATCACCATTACCACAGGTAACGGTGCGGGCTGA
CGTATCGCGATCATGGCGATGCTGGCGTGCCTGGCTATCACCGTGATCGTCGCGATCCTGGTGCGT
AAACCGGTTCTGCCGAACAAAGTTGTTGGTGTGACCACCCTGACCGATGACATCCTGCTGCTGAAA
TAG`;

function loadSampleData() {
  inputMode.value = 'paste';
  form.fasta_content = SAMPLE_FASTA;
  form.task_name = 'Sample_Plasmid_Annotation';
  inspectCurrentFasta();
}

function clearPasteData() {
  form.fasta_content = '';
  inspectedContigs.value = [];
  selectedContigIds.value = [];
}

// 快速预扫描当前输入的 FASTA
async function inspectCurrentFasta() {
  const hasPath = (inputMode.value === 'upload' || inputMode.value === 'assembly') && !!form.fasta_path;
  const hasContent = inputMode.value === 'paste' && !!form.fasta_content && form.fasta_content.trim().length > 0;

  if (!hasPath && !hasContent) {
    inspectedContigs.value = [];
    selectedContigIds.value = [];
    return;
  }

  isInspecting.value = true;
  try {
    const bridge = getBridge();
    const payload = {
      fasta_path: hasPath ? form.fasta_path : undefined,
      fasta_content: hasContent ? form.fasta_content : undefined
    };
    const res: FastaInspectResult = await bridge.inspect_annotation_fasta(payload);
    if (res && res.success && res.contigs) {
      inspectedContigs.value = res.contigs;
      inspectTotalLength.value = res.total_length;
      inspectGc.value = res.gc_content;
      selectedContigIds.value = res.contigs.map(c => c.id);
    } else {
      inspectedContigs.value = [];
      selectedContigIds.value = [];
    }
  } catch (e) {
    console.warn('[AnnotationSetup] 预检查 FASTA 异常:', e);
    inspectedContigs.value = [];
    selectedContigIds.value = [];
  } finally {
    isInspecting.value = false;
  }
}

// 文件 input 引用
const fileInputRef = ref<HTMLInputElement | null>(null);

// 处理选择文件触发 (区分 Electron 原生对话框与 Web Input)
async function handleUploadClick() {
  const bridge = getBridge();
  const isElectron = !!(window as any).electronAPI;
  
  if (isElectron) {
    const paths = await bridge.request_file_load('fasta', false);
    if (paths && paths.length > 0) {
      setLocalFilePath(paths[0]);
    }
  } else {
    fileInputRef.value?.click();
  }
}

// 设置本地物理路径
function setLocalFilePath(filePath: string) {
  form.fasta_path = filePath;
  const baseName = filePath.split(/[/\\]/).pop() || filePath;
  uploadedFileName.value = baseName;
  if (!form.task_name || form.task_name.startsWith('Annotation_')) {
    form.task_name = baseName.replace(/\.[^/.]+$/, '') + '_Anno';
  }
  inspectCurrentFasta();
}

// 处理 HTML input 选择文件
async function handleFileSelected(e: any) {
  const file = e.target?.files?.[0];
  if (!file) return;
  await processFile(file);
  e.target.value = '';
}

// 处理拖拽文件
function handleFileDrop(e: DragEvent) {
  isDragging.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  processFile(file);
}

// 核心文件解析逻辑 (优先获取本地物理路径，纯 Web 下走 bridge.upload_file)
async function processFile(file: File) {
  const bridge = getBridge();
  const baseName = file.name;
  uploadedFileName.value = baseName;

  // 1. Electron 桌面端环境：直接获取物理绝对路径
  const localPath = bridge.get_path_for_file?.(file) || (file as any).path || '';
  if (localPath) {
    setLocalFilePath(localPath);
    return;
  }

  // 2. 纯 Web 浏览器环境：通过 bridge 执行上传
  isUploading.value = true;
  try {
    const res = await bridge.upload_file(file);
    if (res && res.success && res.path) {
      setLocalFilePath(res.path);
    } else {
      throw new Error(res?.error || '服务器暂存文件失败');
    }
  } catch (err: any) {
    alert(`文件上传失败: ${err.message}`);
    uploadedFileName.value = '';
    form.fasta_path = '';
  } finally {
    isUploading.value = false;
  }
}

// 获取组装历史
async function fetchAssemblyHistory() {
  isAssemblyLoading.value = true;
  try {
    const bridge = getBridge();
    let res: any = null;
    if (typeof bridge.fetchAssemblyHistory === 'function') {
      res = await bridge.fetchAssemblyHistory();
    } else if (typeof bridge.get_assembly_history === 'function') {
      res = await bridge.get_assembly_history();
    }
    if (res && res.data) {
      assemblyHistory.value = (res.data || []).filter((t: any) => 
        t.status === 'SUCCESS' || t.status === 'completed' || t.status === 'success'
      );
    }
  } catch (e) {
    console.warn('[AnnotationSetup] 获取组装历史失败:', e);
  } finally {
    isAssemblyLoading.value = false;
  }
}

function onAssemblyTaskSelected() {
  const task = assemblyHistory.value.find(t => t.task_id === selectedAssemblyTask.value);
  if (task) {
    // 自动寻找产物 FASTA 路径
    form.fasta_path = task.assembly_fasta || task.output_fasta || `results/assembly/${task.task_id}/final_assembly.fasta`;
    form.task_name = `${task.name || task.task_id}_Anno`;
    form.sample_type = task.sample_type || 'BACTERIA';
    inspectCurrentFasta();
  }
}

function onSubmit() {
  if (props.isRunning) return;

  if (inputMode.value === 'upload' && !form.fasta_path) {
    alert('请先上传或选择 FASTA 文件');
    return;
  }
  if (inputMode.value === 'paste' && (!form.fasta_content || !form.fasta_content.trim())) {
    alert('请在文本框中粘贴 FASTA 序列');
    return;
  }
  if (inputMode.value === 'assembly' && !form.fasta_path) {
    alert('请选择一个有效的组装历史任务');
    return;
  }

  // 检查 Contig 勾选
  if (inspectedContigs.value.length > 1 && selectedContigIds.value.length === 0) {
    alert('检测到多条 Contig，请在序列列表中至少勾选 1 条序列进行分析');
    return;
  }

  emit('run', {
    ...form,
    selected_contigs: inspectedContigs.value.length > 1 ? selectedContigIds.value : undefined
  });
}

onMounted(() => {
  fetchAssemblyHistory();
});
</script>

<template>
  <div class="annotation-setup-card">
    <div class="setup-header">
      <div class="title-with-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          <line x1="9" y1="7" x2="15" y2="7" />
          <line x1="9" y1="11" x2="13" y2="11" />
        </svg>
        <h2>基因组功能注释配置</h2>
      </div>
      <button class="sample-btn" type="button" @click="loadSampleData">
        载入质粒示例
      </button>
    </div>

    <!-- 1. 序列提交源切换 Tabs -->
    <div class="source-tabs">
      <button 
        type="button" 
        :class="['tab-btn', { active: inputMode === 'upload' }]"
        @click="inputMode = 'upload'"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        本地文件上传
      </button>
      <button 
        type="button" 
        :class="['tab-btn', { active: inputMode === 'paste' }]"
        @click="inputMode = 'paste'"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="4 7 4 4 20 4 20 7" />
          <line x1="9" y1="20" x2="15" y2="20" />
          <line x1="12" y1="4" x2="12" y2="20" />
        </svg>
        粘贴 FASTA 序列
      </button>
      <button 
        type="button" 
        :class="['tab-btn', { active: inputMode === 'assembly' }]"
        @click="inputMode = 'assembly'"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        </svg>
        从组装历史选择
      </button>
    </div>

    <!-- 2. 序列输入主体 -->
    <div class="source-content">
      <!-- 2.1 文件上传 / 本地选择 -->
      <div 
        v-if="inputMode === 'upload'" 
        class="drop-zone"
        :class="{ dragging: isDragging, 'has-file': !!uploadedFileName }"
        @click="handleUploadClick"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleFileDrop"
      >
        <input 
          type="file" 
          ref="fileInputRef" 
          hidden 
          accept=".fasta,.fa,.fna,.fsa,.seq,.txt" 
          @change="handleFileSelected" 
        />
        <div class="drop-label">
          <div class="drop-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="1.8">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <polyline points="9 15 12 12 15 15" />
            </svg>
          </div>
          <div class="drop-text">
            <template v-if="uploadedFileName">
              <span class="file-name-highlight">{{ uploadedFileName }}</span>
              <span v-if="form.fasta_path" class="file-path-hint" :title="form.fasta_path">{{ form.fasta_path }}</span>
              <span class="sub-tip">点击重新选择或拖拽替换文件</span>
            </template>
            <template v-else>
              <span class="main-tip">拖拽 FASTA 序列文件至此处，或 <span class="browse-link">点击选择文件</span></span>
              <span class="sub-tip">支持 .fasta / .fa / .fna / .fsa 格式（基因组 Contigs 或 Scaffolds）</span>
            </template>
          </div>
        </div>
      </div>

      <!-- 2.2 粘贴文本 -->
      <div v-else-if="inputMode === 'paste'" class="paste-zone">
        <div class="paste-header">
          <span class="paste-tip">请粘贴包含 > 头部或纯核酸的 FASTA 内容</span>
          <div class="paste-actions">
            <span class="char-count">{{ form.fasta_content?.length || 0 }} 字符</span>
            <button class="clear-btn" type="button" @click="clearPasteData">清空</button>
          </div>
        </div>
        <textarea
          v-model="form.fasta_content"
          placeholder=">Sequence_1&#10;ATGAAACGCATTAGCACCACCATTACCACCACCATCACCATT..."
          rows="6"
          class="fasta-textarea"
        ></textarea>
      </div>

      <!-- 2.3 组装历史选择 -->
      <div v-else class="assembly-zone">
        <div v-if="isAssemblyLoading" class="zone-loading">正在拉取组装历史...</div>
        <div v-else-if="assemblyHistory.length === 0" class="zone-empty">
          暂未发现已完成的组装拼接任务，请使用文件上传或直接粘贴。
        </div>
        <div v-else class="assembly-select-wrapper">
          <label class="select-label">选择组装任务产物:</label>
          <select v-model="selectedAssemblyTask" @change="onAssemblyTaskSelected" class="custom-select">
            <option value="">-- 请选择组装任务 --</option>
            <option v-for="t in assemblyHistory" :key="t.task_id" :value="t.task_id">
              [{{ t.sample_type }}] {{ t.name || t.task_id }} ({{ t.created_at?.slice(0, 16) }})
            </option>
          </select>
          <div v-if="form.fasta_path" class="selected-path-hint">
            产物路径: {{ form.fasta_path }}
          </div>
        </div>
      </div>
    </div>

    <!-- 2.5 序列筛选与包含配置 (当序列数 > 1 时呈现) -->
    <div v-if="isInspecting" class="inspect-loading-banner">
      <svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.5">
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
      <span>正在解析序列 Contig 列表与长度分布...</span>
    </div>
    
    <ContigSelector
      v-else-if="inspectedContigs.length > 1"
      :contigs="inspectedContigs"
      :total-length="inspectTotalLength"
      :overall-gc="inspectGc"
      @update:selection="val => selectedContigIds = val"
    />

    <!-- 3. 参数配置表单 -->
    <div class="params-grid">
      <div class="form-group">
        <label>任务名称</label>
        <input type="text" v-model="form.task_name" placeholder="请输入任务标识" class="text-input" />
      </div>

      <div class="form-group">
        <label>样本生物类型</label>
        <select v-model="form.sample_type" class="custom-select">
          <option value="PHAGE">噬菌体 (Bacteriophage - 优先 PHROGs & 3D结构)</option>
          <option value="BACTERIA">细菌 (Bacteria / Archaea - 优先 Prokka全特征)</option>
          <option value="VIRUS">病毒 / 质粒 (Viruses & Plasmids)</option>
          <option value="GENERAL">通用原核生物 (General)</option>
        </select>
      </div>

      <div class="form-group">
        <label>注释引擎模式</label>
        <select v-model="form.engine" class="custom-select">
          <option value="auto">全自动多引擎流式级联 (推荐: 主干预测 + 同源打捞 + 3D补漏)</option>
          <option value="pharokka">Pharokka 噬菌体专用引擎 (主干基准 + 级联互补)</option>
          <option value="prokka">Prokka 微生物标准注释引擎 (主干基准 + 级联互补)</option>
          <option value="prodigal">Prodigal 机器学习极速 CDS 识别 (主干基准 + 级联互补)</option>
          <option value="phold">Phold AI 3D 空间构象感知引擎 (结构折叠深度补漏)</option>
          <option value="builtin">内置高精度多核引擎 (零依赖纯 Python 极速模式)</option>
        </select>
      </div>

      <div class="form-group">
        <label>位点前缀 (Locus Prefix)</label>
        <input type="text" v-model="form.prefix" placeholder="如 ANNO / BUCT551" class="text-input" />
      </div>
    </div>

    <!-- 4. 高级参数抽屉 -->
    <div class="advanced-section">
      <button type="button" class="toggle-advanced-btn" @click="showAdvanced = !showAdvanced">
        <svg 
          width="14" 
          height="14" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          stroke-width="2"
          :style="{ transform: showAdvanced ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s' }"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
        高级算法调优参数 (密码子表 / 过滤长度 / 流式级联开关)
      </button>

      <div v-show="showAdvanced" class="advanced-body">
        <div class="params-grid">
          <div class="form-group">
            <label>遗传密码子表 (Genetic Code)</label>
            <select v-model.number="form.genetic_code" class="custom-select">
              <option :value="11">Code 11: 细菌、古菌、质粒与多数噬菌体标准</option>
              <option :value="1">Code 1: 标准通用密码子 (Standard)</option>
              <option :value="4">Code 4: 支原体/螺旋体密码子</option>
            </select>
          </div>

          <div class="form-group">
            <label>最小 Contig 过滤阈值 (bp)</label>
            <input type="number" v-model.number="form.min_contig_len" min="30" step="50" class="text-input" />
          </div>
        </div>

        <div class="waterfall-options-box">
          <div class="opt-box-title">多引擎流式级联与漏斗互补配置 (Streaming Waterfall Pipeline)</div>
          <div class="opt-checkbox-grid">
            <label class="checkbox-label" title="开启后将按顺序流经各引擎，自动补全前序引擎标记为 hypothetical protein 的未知基因">
              <input type="checkbox" v-model="form.enable_waterfall" />
              <span>启用多引擎流式级联互补 (推荐开启: 逐层漏斗式消除未知蛋白)</span>
            </label>
            <label class="checkbox-label" title="利用 105 万权威 PhageScope 蛋白库进行多核 BLASTP 并行比对打捞">
              <input type="checkbox" v-model="form.enable_homology" />
              <span>PhageScope 105万权威参考蛋白库同源打捞</span>
            </label>
            <label class="checkbox-label" title="基于 ESMFold 三维空间折叠与 Foldseek 空间构象识别，破解同源弱的结构蛋白">
              <input type="checkbox" v-model="form.enable_phold" />
              <span>Phold AI 蛋白质三维结构折叠与空间感知增强 (Foldseek 3D补漏)</span>
            </label>
            <label class="checkbox-label" title="针对耐药基因、毒力因子及 Anti-CRISPR 防御逃逸系统进行深度安全审计">
              <input type="checkbox" v-model="form.enable_safety_audit" />
              <span>CARD耐药 / VFDB毒力 / Anti-CRISPR 生物安全性与防御系统审计</span>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. 操作触发按钮 -->
    <div class="setup-actions">
      <button 
        type="button" 
        class="submit-btn" 
        :disabled="isRunning || isUploading"
        @click="onSubmit"
      >
        <svg v-if="!isRunning" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
        <span v-if="isRunning">正在执行功能注释...</span>
        <span v-else>启动功能注释分析</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.annotation-setup-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.setup-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.title-with-icon {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-with-icon h2 {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.sample-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.sample-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.source-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 10px;
  margin-bottom: 16px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  color: #1e293b;
  background: #f1f5f9;
}

.tab-btn.active {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
}

.source-content {
  margin-bottom: 20px;
}

.inspect-loading-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 10px 16px;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 16px;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 24px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s ease;
}

.drop-zone.dragging {
  border-color: #3b82f6;
  background: #eff6ff;
}

.drop-zone.has-file {
  border-color: #10b981;
  background: #f0fdf4;
}

.drop-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.drop-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-name-highlight {
  font-size: 14px;
  font-weight: 700;
  color: #065f46;
}

.file-path-hint {
  font-size: 11px;
  color: #047857;
  background: #d1fae5;
  padding: 2px 8px;
  border-radius: 4px;
  max-width: 460px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin: 2px auto 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.main-tip {
  font-size: 13px;
  color: #334155;
  font-weight: 500;
}

.browse-link {
  color: #2563eb;
  text-decoration: underline;
  font-weight: 600;
}

.sub-tip {
  font-size: 11px;
  color: #94a3b8;
}

.paste-zone {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.paste-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.paste-tip {
  font-size: 12px;
  color: #64748b;
}

.paste-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.char-count {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
}

.clear-btn {
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 11px;
  cursor: pointer;
  font-weight: 600;
}

.fasta-textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #1e293b;
  resize: vertical;
  outline: none;
}

.fasta-textarea:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.assembly-zone {
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.assembly-select-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.select-label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.selected-path-hint {
  font-size: 11px;
  color: #059669;
  background: #ecfdf5;
  padding: 4px 8px;
  border-radius: 4px;
}

.params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.text-input, .custom-select {
  height: 36px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  color: #1e293b;
  background: white;
  outline: none;
}

.text-input:focus, .custom-select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.advanced-section {
  margin-bottom: 20px;
  border-top: 1px dashed #e2e8f0;
  padding-top: 12px;
}

.toggle-advanced-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 0;
}

.toggle-advanced-btn:hover {
  color: #2563eb;
}

.advanced-body {
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.waterfall-options-box {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #cbd5e1;
}

.opt-box-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 8px;
}

.opt-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #475569;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  cursor: pointer;
  accent-color: #2563eb;
}

.setup-actions {
  display: flex;
  justify-content: flex-end;
}

.submit-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}

.submit-btn:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
