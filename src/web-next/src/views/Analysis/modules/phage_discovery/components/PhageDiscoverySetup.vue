<script setup lang="ts">
import ContigSelector from '../../annotation/components/ContigSelector.vue'
import type { PhageCapabilities, PhageContigInspectItem, PhageScanForm } from '../types'
import { usePhageDiscoverySetup } from '../composables/usePhageDiscoverySetup'

const props = defineProps<{
  capabilities: PhageCapabilities | null
  isCapabilitiesLoading: boolean
  isInspecting: boolean
  isSubmitting: boolean
  isQueueBusy: boolean
  inspectedContigs: PhageContigInspectItem[]
  inspectTotalBp: number
}>()

const emit = defineEmits<{
  (e: 'submit', form: PhageScanForm): void
  (e: 'inspect', payload: { fasta_path?: string; fasta_content?: string }): void
  (e: 'save-config', payload: { default_model_dir?: string; blast_db?: string }): void
  (e: 'refresh-capabilities'): void
}>()

const {
  inputMode,
  uploadedFileName,
  isUploading,
  isDragging,
  fileInputRef,
  assemblyHistory,
  isAssemblyLoading,
  selectedAssemblyTask,
  showAdvanced,
  showPathConfig,
  configModelDir,
  configBlastDb,
  form,
  availableModels,
  activeV42Model,
  activeModelBadge,
  computeEnv,
  gateStatus,
  overallGcPercent,
  selectorContigs,
  singleContig,
  switchMode,
  getAssemblyTaskId,
  formatAssemblyTime,
  onAssemblyTaskSelected,
  triggerFileSelect,
  onBrowserFileChange,
  onDropFile,
  loadDemoSequence,
  clearPasteData,
  browseCustomModelDir,
  browseBlastDbFile,
  applySavedPaths,
  resetThresholds,
  formatParamsCount,
  onSubmit,
} = usePhageDiscoverySetup(props, emit)

void fileInputRef
</script>

<template>
  <div class="wb-card setup-card">
    <div class="setup-header">
      <div class="title-block">
        <h2>前噬菌体与噬菌体边界精细扫描</h2>
        <p class="subtitle">基于多尺度 DNA 序列与 ORF 语义上下文模型，结合 200bp SubBinRefiner 实现精确切割</p>
      </div>
      <div class="header-actions">
        <button type="button" class="wb-btn-outline sample-btn" @click="loadDemoSequence">载入验证样本</button>
      </div>
    </div>

    <div v-if="isQueueBusy" class="queue-busy-banner">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      <span>当前已有扫描任务正在执行或等待中：本次提交将严格串行加入等待队列，前序完成后自动启动。</span>
    </div>

    <div class="wb-tabs-bar source-tabs">
      <button type="button" class="wb-tab-btn soft" :class="{ active: inputMode === 'upload' }" @click="switchMode('upload')">
        本地基因组文件
      </button>
      <button type="button" class="wb-tab-btn soft" :class="{ active: inputMode === 'paste' }" @click="switchMode('paste')">
        直接粘贴 FASTA / GBK
      </button>
      <button type="button" class="wb-tab-btn soft" :class="{ active: inputMode === 'assembly' }" @click="switchMode('assembly')">
        从组装拼接历史导入
      </button>
    </div>

    <div class="source-content">
      <div v-if="inputMode === 'upload'">
        <input
          ref="fileInputRef"
          type="file"
          accept=".fasta,.fa,.fna,.fsa,.gbk,.gb,.genbank,.gz"
          style="display: none"
          @change="onBrowserFileChange"
        />
        <div
          class="wb-drop-zone drop-col"
          :class="{ dragging: isDragging }"
          @click="triggerFileSelect"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDropFile"
        >
          <div class="drop-icon">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <polyline points="9 15 12 12 15 15" />
            </svg>
          </div>
          <div class="drop-text">
            <template v-if="isUploading">
              <span class="file-name-highlight">正在上传序列文件至服务端...</span>
            </template>
            <template v-else-if="uploadedFileName">
              <span class="file-name-highlight">{{ uploadedFileName }}</span>
              <span v-if="form.fasta_path" class="file-path-hint" :title="form.fasta_path">{{ form.fasta_path }}</span>
              <span class="sub-tip">点击重新选择或拖拽替换基因组文件</span>
            </template>
            <template v-else>
              <span>拖拽细菌全基因组或拼接 Contigs 至此，或 <span class="browse-link">点击浏览文件</span></span>
              <span class="sub-tip">支持 .fasta / .fa / .fna / .fasta.gz / .gbk / .gbff 格式</span>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="inputMode === 'paste'" class="paste-zone">
        <div class="paste-header">
          <span>粘贴完整 FASTA 或 GenBank 核酸序列文本</span>
          <div class="paste-actions">
            <span>{{ form.fasta_content.length }} 字符</span>
            <button type="button" class="wb-btn-outline" @click="clearPasteData">清空</button>
          </div>
        </div>
        <textarea
          v-model="form.fasta_content"
          rows="5"
          class="wb-textarea"
          placeholder=">Chromosome_1&#10;ATGCGTACGTAGCTAGCTAG..."
        ></textarea>
      </div>

      <div v-else class="wb-surface-muted">
        <div v-if="isAssemblyLoading" class="zone-msg">正在获取已完成的基因组拼接任务...</div>
        <div v-else-if="assemblyHistory.length === 0" class="zone-msg">
          暂未检测到已完成的拼接产物，请通过文件选择或直接粘贴输入。
        </div>
        <div v-else class="form-group">
          <label>选择已组装样本序列:</label>
          <select v-model="selectedAssemblyTask" class="wb-select full-w" @change="onAssemblyTaskSelected">
            <option value="">-- 请选择组装任务 --</option>
            <option v-for="t in assemblyHistory" :key="getAssemblyTaskId(t)" :value="getAssemblyTaskId(t)">
              [{{ t.sample_type || 'ASSEMBLY' }}] {{ t.name || getAssemblyTaskId(t) }}<template v-if="formatAssemblyTime(t.created_at)"> ({{ formatAssemblyTime(t.created_at) }})</template>
            </option>
          </select>
          <div v-if="form.fasta_path" class="selected-path-hint">已锁定序列路径: {{ form.fasta_path }}</div>
        </div>
      </div>
    </div>

    <div v-if="isInspecting" class="inspect-banner">
      <div class="mini-spin"></div>
      <span>正在解析 Contig 结构与碱基统计信息...</span>
    </div>
    <ContigSelector
      v-else-if="inspectedContigs.length > 1"
      :contigs="selectorContigs"
      :total-length="inspectTotalBp"
      :overall-gc="overallGcPercent"
      @update:selection="(val: string[]) => (form.selected_contigs = val)"
    />
    <div v-else-if="singleContig" class="single-contig-bar">
      已解析单条序列: <strong>{{ singleContig.id }}</strong>
      <span>长度 {{ singleContig.length.toLocaleString() }} bp</span>
      <span>GC {{ singleContig.gc_percent }}%</span>
    </div>

    <div class="engine-status-card" :class="{ missing: !activeV42Model }">
      <div class="engine-head">
        <div class="engine-title-row">
          <span class="version-pill">{{ activeModelBadge }}</span>
          <strong>{{ activeV42Model ? activeV42Model.label : '未检测到本地模型目录' }}</strong>
        </div>
        <div class="engine-tools">
          <button type="button" class="wb-btn-link" :disabled="isCapabilitiesLoading" @click="emit('refresh-capabilities')">
            {{ isCapabilitiesLoading ? '探测中...' : '重新探测' }}
          </button>
          <button type="button" class="wb-btn-link" @click="showPathConfig = !showPathConfig">
            {{ showPathConfig ? '收起路径配置' : '配置模型/蛋白库路径' }}
          </button>
        </div>
      </div>

      <div v-if="availableModels.length > 1" class="engine-selector-row">
        <label for="phage-model-select" class="selector-label">切换推理模型:</label>
        <select id="phage-model-select" v-model="form.model_id" class="wb-select flex-1">
          <option v-for="m in availableModels" :key="`${m.model_id}:${m.path}`" :value="m.model_id">
            [{{ m.version }}] {{ m.label }}{{ m.has_unified_judge ? ' (默认主力)' : ' (仅DNA底座/兼容)' }}
          </option>
        </select>
      </div>

      <div v-if="activeV42Model" class="engine-meta-row">
        <span v-if="activeV42Model.has_unified_judge" class="wb-chip ok">Unified 按需分化蛋白引擎已就绪</span>
        <span class="wb-chip ok">200bp SubBinRefiner 已就绪</span>
        <span v-if="activeV42Model.has_context_refiner" class="wb-chip ok">ContextRefiner 已就绪</span>
        <span class="wb-chip">参数量 {{ formatParamsCount(activeV42Model.params) }}</span>
      </div>
      <div v-if="activeV42Model" class="engine-paths-grid">
        <div v-if="activeV42Model.has_unified_judge && activeV42Model.unified_models_root" class="engine-path-item">
          <span class="path-tag">统一根目录</span>
          <span class="meta-path" :title="activeV42Model.unified_models_root">{{ activeV42Model.unified_models_root }}</span>
        </div>
        <div class="engine-path-item">
          <span class="path-tag">{{ activeV42Model.has_unified_judge ? 'DNA 底座' : '模型目录' }}</span>
          <span class="meta-path" :title="activeV42Model.path">{{ activeV42Model.path }}</span>
        </div>
        <div v-if="activeV42Model.has_unified_judge && activeV42Model.unified_judge_dir" class="engine-path-item">
          <span class="path-tag ok">分化蛋白引擎</span>
          <span class="meta-path" :title="activeV42Model.unified_judge_dir">{{ activeV42Model.unified_judge_dir }}</span>
        </div>
      </div>
      <div v-else class="engine-missing-tip">
        请将模型放置于项目 <code>models/full_v4/stage1_2</code>（配套 <code>orf_judge_unified</code>）或相邻 <code>Phage data/models/full_v4</code> 下，或点击右侧手动指定目录。
      </div>

      <div v-if="showPathConfig" class="path-config-drawer">
        <div class="form-group">
          <label>自定义模型目录:</label>
          <div class="input-with-btn">
            <input
              v-model="configModelDir"
              type="text"
              class="wb-input flex-1"
              placeholder="包含 stage1_2.pt（或 student_v4.pt）与 subbin_refiner.pt 的目录"
            />
            <button type="button" class="wb-btn-outline" @click="browseCustomModelDir">浏览</button>
          </div>
        </div>
        <div class="form-group">
          <label>可选 BLASTp 蛋白库前缀:</label>
          <div class="input-with-btn">
            <input v-model="configBlastDb" type="text" class="wb-input flex-1" placeholder="如 database/phage_discovery/phage_refseq_prot" />
            <button type="button" class="wb-btn-outline" @click="browseBlastDbFile">浏览</button>
          </div>
        </div>
        <div class="setup-actions">
          <button type="button" class="wb-btn-primary" @click="applySavedPaths">保存相对路径并刷新</button>
        </div>
      </div>
    </div>

    <div class="params-grid">
      <div class="form-group">
        <label>扫描任务名称</label>
        <input v-model="form.task_name" type="text" class="wb-input full-w" placeholder="输入样本或菌株标识" />
      </div>
      <div class="form-group">
        <label>推理硬件设备</label>
        <select v-model="form.device" class="wb-select full-w">
          <option value="auto">
            自动调度 ({{ computeEnv?.cuda_available ? `GPU: ${computeEnv.gpu_name}` : 'CPU 安全并发' }})
          </option>
          <option value="cuda" :disabled="!computeEnv?.cuda_available">
            CUDA GPU 加速 {{ computeEnv?.cuda_available ? `(${computeEnv.gpu_vram_gb} GB VRAM)` : '(当前无可用 GPU)' }}
          </option>
          <option value="cpu">
            纯 CPU 多核计算 (保留核心, 推荐并发 {{ computeEnv?.safe_workers || 2 }} 线程)
          </option>
        </select>
      </div>
    </div>

    <div class="wb-surface-muted gate-option-box">
      <label class="checkbox-label">
        <input v-model="form.apply_protein_gate" type="checkbox" :disabled="!gateStatus?.ready && !form.blast_db.trim()" />
        <span>启用第二阶段 BLASTp 病毒标志蛋白门控 (提升假阳性过滤，耗时将增加)</span>
      </label>
      <div class="gate-status-text">
        <span v-if="gateStatus?.ready" class="status-ok">已检测到 blastp 与蛋白参考库 ({{ gateStatus.blast_db }})</span>
        <span v-else class="status-warn">未检测到完整的本地 blastp / phage_refseq_prot 库，当前默认采用纯神经引擎极速发现模式</span>
      </div>
    </div>

    <div class="advanced-section">
      <div class="advanced-header-bar">
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
          边界精修解码参数调优 (种子阈值 / 滞回延伸 / 200bp 切割尺度)
        </button>
        <button v-if="showAdvanced" type="button" class="wb-btn-outline" @click="resetThresholds">恢复默认参数</button>
      </div>

      <div v-show="showAdvanced" class="wb-surface-muted advanced-body">
        <div class="params-grid three-cols">
          <div class="form-group">
            <label>种子激活阈值 (Seed)</label>
            <input v-model.number="form.seed_threshold" type="number" step="0.01" min="0.1" max="0.99" class="wb-input full-w" />
          </div>
          <div class="form-group">
            <label>区域滞回延伸 (Extend)</label>
            <input v-model.number="form.extend_threshold" type="number" step="0.01" min="0.05" max="0.95" class="wb-input full-w" />
          </div>
          <div class="form-group">
            <label>200bp 精细边界阈值</label>
            <input v-model.number="form.sub_threshold" type="number" step="0.01" min="0.1" max="0.95" class="wb-input full-w" />
          </div>
          <div class="form-group">
            <label>邻近片段合并间隔 (bp)</label>
            <input v-model.number="form.merge_gap_bp" type="number" step="500" min="0" max="50000" class="wb-input full-w" />
          </div>
          <div class="form-group">
            <label>最短保留区段长度 (bp)</label>
            <input v-model.number="form.min_region_bp" type="number" step="500" min="400" max="50000" class="wb-input full-w" />
          </div>
          <div class="form-group">
            <label>特征抽取并发线程数</label>
            <input v-model.number="form.workers" type="number" min="1" :max="computeEnv?.safe_workers || 8" class="wb-input full-w" />
          </div>
        </div>
      </div>
    </div>

    <div class="setup-actions">
      <button
        type="button"
        class="wb-btn-primary submit-btn"
        :class="{ 'is-busy-mode': isQueueBusy }"
        :disabled="isUploading || isInspecting || isSubmitting"
        @click="onSubmit"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
          <polygon v-if="!isQueueBusy" points="5 3 19 12 5 21 5 3" />
          <path v-else d="M12 5v14M5 12h14" />
        </svg>
        <span v-if="isSubmitting">正在排队提交...</span>
        <span v-else-if="isQueueBusy">加入扫描队列</span>
        <span v-else>启动前噬菌体全基因组扫描</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.setup-card { padding: 20px; gap: 16px; }
.setup-header, .paste-header, .engine-head, .advanced-header-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.title-block h2 { margin: 0 0 4px; font-size: 16px; font-weight: 700; color: #1e293b; }
.subtitle { margin: 0; font-size: 12px; color: #64748b; }
.queue-busy-banner { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 8px; background: #fffbeb; border: 1px solid #fde68a; color: #b45309; font-size: 12px; font-weight: 600; }
.source-tabs { border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }
.drop-col { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 22px 16px; }
.drop-icon { color: #64748b; }
.drop-text, .paste-zone, .form-group { display: flex; flex-direction: column; gap: 5px; font-size: 13px; color: #334155; }
.form-group label { font-size: 12px; font-weight: 600; color: #334155; }
.file-name-highlight { font-weight: 700; color: #1d4ed8; }
.file-path-hint, .selected-path-hint, .meta-path { font-size: 11px; color: #475569; font-family: ui-monospace, monospace; }
.browse-link { color: #2563eb; font-weight: 700; }
.sub-tip { font-size: 11px; color: #94a3b8; }
.paste-header { font-size: 12px; color: #64748b; }
.paste-actions, .engine-tools, .engine-title-row, .engine-selector-row, .input-with-btn { display: flex; align-items: center; gap: 8px; }
.zone-msg { font-size: 12px; color: #64748b; text-align: center; }
.full-w { width: 100%; height: 36px; }
.flex-1 { flex: 1; min-width: 0; }
.inspect-banner { display: flex; align-items: center; gap: 8px; background: #eff6ff; border: 1px solid #bfdbfe; padding: 10px 14px; border-radius: 8px; font-size: 12px; color: #1d4ed8; font-weight: 600; }
.mini-spin { width: 14px; height: 14px; border: 2px solid #93c5fd; border-top-color: #1d4ed8; border-radius: 50%; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.single-contig-bar { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #334155; }
.engine-status-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.engine-status-card.missing { background: #fff7ed; border-color: #fdba74; }
.version-pill { background: #4338ca; color: #ffffff; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 4px; }
.selector-label { font-size: 12px; font-weight: 600; white-space: nowrap; }
.engine-meta-row { display: flex; flex-wrap: wrap; gap: 6px; }
.engine-paths-grid { display: flex; flex-direction: column; gap: 4px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px; }
.engine-path-item { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 11px; }
.path-tag { flex-shrink: 0; padding: 1px 6px; border-radius: 4px; background: #e2e8f0; color: #475569; font-weight: 600; }
.path-tag.ok { background: #dcfce7; color: #15803d; }
.meta-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.engine-missing-tip { font-size: 12px; color: #9a3412; }
.path-config-drawer { border-top: 1px solid #e2e8f0; padding-top: 10px; display: flex; flex-direction: column; gap: 10px; }
.params-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.params-grid.three-cols { grid-template-columns: repeat(3, 1fr); }
.gate-option-box { display: flex; flex-direction: column; gap: 4px; }
.checkbox-label { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #1e293b; cursor: pointer; }
.gate-status-text { font-size: 11px; padding-left: 22px; }
.status-ok { color: #15803d; }
.status-warn { color: #64748b; }
.advanced-section { border-top: 1px solid #e2e8f0; padding-top: 10px; }
.toggle-advanced-btn { border: none; background: transparent; color: #475569; font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; padding: 4px 0; }
.advanced-body { margin-top: 12px; }
.setup-actions { display: flex; justify-content: flex-end; padding-top: 4px; }
.submit-btn { padding: 10px 22px; font-size: 14px; font-weight: 700; }
.submit-btn.is-busy-mode { background: #d97706; }
.submit-btn.is-busy-mode:hover:not(:disabled) { background: #b45309; }
</style>
