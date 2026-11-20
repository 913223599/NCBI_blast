<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { getBridge } from '../../../../../bridge/electron-bridge'
import ContigSelector from '../../annotation/components/ContigSelector.vue'
import type {
  StructureCapabilities,
  StructureInitialPayload,
  StructureInspectContig,
  StructureLinkedSources,
  StructureRunForm,
  StructureSourceMode,
} from '../types'
import { formatGenomeBp } from '../utils'

const props = defineProps<{
  capabilities: StructureCapabilities | null
  linkedSources: StructureLinkedSources
  isCapabilitiesLoading: boolean
  isSourcesLoading: boolean
  isInspecting: boolean
  isSubmitting: boolean
  isQueueBusy: boolean
  inspectedContigs: StructureInspectContig[]
  inspectTotalBp: number
  initialPayload?: StructureInitialPayload | null
}>()

const emit = defineEmits<{
  (e: 'submit', form: StructureRunForm): void
  (
    e: 'inspect',
    payload: {
      source_mode: StructureSourceMode
      fasta_path?: string
      fasta_content?: string
      source_task_id?: string
      region_index?: number
    }
  ): void
  (e: 'refresh-sources'): void
}>()

const bridge = getBridge()
const uiTab = ref<'upload' | 'paste' | 'annotation' | 'phage_discovery'>('upload')
const uploadedFileName = ref<string>('')
const isUploading = ref<boolean>(false)
const isDragging = ref<boolean>(false)
const showAdvanced = ref<boolean>(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const form = reactive<StructureRunForm>({
  task_name: 'PhageStructure_Analysis',
  source_mode: 'file',
  fasta_path: '',
  fasta_content: '',
  source_task_id: '',
  region_index: undefined,
  selected_contigs: [],
  threads: 0,
  genetic_code: 11,
  evalue_cutoff: 1e-4,
  score_cutoff: 28.0,
  force_hmm_rescan: false,
  enable_phold_enhance: false,
  enable_phagetailfinder: true,
  ptf_accurate_mode: false,
})

watch(
  () => props.capabilities,
  (caps) => {
    if (caps && form.threads === 0) {
      form.threads = caps.safe_workers || 8
    }
  },
  { immediate: true }
)

watch(
  () => props.inspectedContigs,
  (list) => {
    form.selected_contigs = list.map((c) => c.id)
  }
)

watch(
  () => props.initialPayload,
  (payload) => {
    if (!payload || !payload.taskId) return
    if (payload.sourceMode === 'annotation') {
      uiTab.value = 'annotation'
      form.source_mode = 'annotation'
      form.source_task_id = payload.taskId
      form.region_index = undefined
      form.task_name = `${payload.taskName || payload.taskId}_Structure`
      triggerLinkedInspect()
    } else if (payload.sourceMode === 'phage_discovery') {
      uiTab.value = 'phage_discovery'
      form.source_mode = 'phage_discovery'
      form.source_task_id = payload.taskId
      form.region_index = payload.regionIndex
      form.task_name = `${payload.taskName || payload.taskId}_Structure`
      triggerLinkedInspect()
    }
  },
  { immediate: true }
)

const overallGcPercent = computed(() => {
  if (!props.inspectedContigs.length || props.inspectTotalBp <= 0) return 0
  let w = 0
  for (const c of props.inspectedContigs) {
    w += Number(c.gc_percent || 0) * Number(c.length_bp || 0)
  }
  return Number((w / props.inspectTotalBp).toFixed(2))
})

const selectorContigs = computed(() =>
  props.inspectedContigs.map((c) => ({
    id: c.id,
    description: `${c.input_type.toUpperCase()} · ${c.cds_count} 蛋白特征`,
    length_bp: c.length_bp,
    gc_content: c.gc_percent,
    selected: true,
  }))
)

const canSubmit = computed(() => {
  if (props.isSubmitting || props.isInspecting) return false
  if (uiTab.value === 'upload') return Boolean(form.fasta_path)
  if (uiTab.value === 'paste') return form.fasta_content.trim().length > 20
  return Boolean(form.source_task_id)
})

function switchTab(tab: 'upload' | 'paste' | 'annotation' | 'phage_discovery'): void {
  uiTab.value = tab
  form.source_mode = tab === 'upload' ? 'file' : tab
  if (tab === 'annotation' || tab === 'phage_discovery') {
    emit('refresh-sources')
  }
}

async function triggerFileSelect(): Promise<void> {
  if (window.electronAPI) {
    const paths = await bridge.request_file_load('phage', false)
    if (paths && paths.length > 0 && paths[0]) {
      applySelectedPath(paths[0])
    }
    return
  }
  fileInputRef.value?.click()
}

function applySelectedPath(path: string): void {
  form.source_mode = 'file'
  form.fasta_path = path
  form.fasta_content = ''
  const parts = path.replace(/\\/g, '/').split('/')
  const name = parts[parts.length - 1] || path
  uploadedFileName.value = name
  const stem = name.replace(/\.(fasta|fa|fna|faa|gbk|gb|gbff|genbank|gz)+$/gi, '')
  if (stem) form.task_name = `${stem}_Structure`
  emit('inspect', { source_mode: 'file', fasta_path: path })
}

async function handleFileUpload(file: File): Promise<void> {
  const nativePath = bridge.get_path_for_file(file)
  if (nativePath) {
    applySelectedPath(nativePath)
    return
  }
  isUploading.value = true
  try {
    const res = await bridge.upload_file(file)
    if (res?.path || res?.file_path) {
      applySelectedPath(res.path || res.file_path)
    } else {
      const text = await file.text()
      uiTab.value = 'paste'
      form.source_mode = 'paste'
      form.fasta_path = ''
      form.fasta_content = text
      uploadedFileName.value = file.name
      emit('inspect', { source_mode: 'paste', fasta_content: text })
    }
  } finally {
    isUploading.value = false
  }
}

function onBrowserFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleFileUpload(file)
  input.value = ''
}

function onDropFile(event: DragEvent): void {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleFileUpload(file)
}

let pasteTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => form.fasta_content,
  (val) => {
    if (uiTab.value !== 'paste') return
    if (pasteTimer) clearTimeout(pasteTimer)
    pasteTimer = setTimeout(() => {
      if (val && val.trim().length > 20) {
        emit('inspect', { source_mode: 'paste', fasta_content: val })
      }
    }, 450)
  }
)

function selectAnnotationSource(taskId: string): void {
  form.source_mode = 'annotation'
  form.source_task_id = taskId
  form.region_index = undefined
  const found = props.linkedSources.annotations.find((a) => a.task_id === taskId)
  if (found) form.task_name = `${found.task_name}_Structure`
  triggerLinkedInspect()
}

function selectDiscoverySource(taskId: string): void {
  form.source_mode = 'phage_discovery'
  form.source_task_id = taskId
  form.region_index = undefined
  const found = props.linkedSources.phage_discoveries.find((p) => p.task_id === taskId)
  if (found) form.task_name = `${found.task_name}_Structure`
  triggerLinkedInspect()
}

function triggerLinkedInspect(): void {
  if (!form.source_task_id) return
  emit('inspect', {
    source_mode: form.source_mode,
    source_task_id: form.source_task_id,
    region_index: form.region_index,
  })
}

function onSubmit(): void {
  if (!canSubmit.value) return
  emit('submit', { ...form, selected_contigs: [...form.selected_contigs] })
}
</script>

<template>
  <div class="setup-shell">
    <!-- 顶部状态条 -->
    <div class="engine-banner">
      <div class="eb-left">
        <h3>噬菌体尾部形态与结构定标预测</h3>
        <p>
          融合特征尾部蛋白 (TSP/MTP/TAP/TTPA-B)、Virfam 头-颈-尾连接器及卷尺蛋白 (TMP polyX/TRs) 定量长度解析
        </p>
      </div>
      <div class="eb-chips">
        <span class="chip" :class="capabilities?.wsl_pyhmmer_ready ? 'ok' : 'warn'">
          {{ isCapabilitiesLoading ? '检测中...' : capabilities?.wsl_pyhmmer_ready ? 'WSL PyHMMER 就绪' : 'PyHMMER 不可用' }}
        </span>
        <span class="chip" :class="capabilities?.structural_hmm_cached ? 'ok' : 'neutral'">
          {{ capabilities?.structural_hmm_cached ? '结构 PHROGs 索引已缓存' : '首次运行自动提取结构库' }}
        </span>
        <span class="chip" :class="capabilities?.phagetailfinder_ready ? 'ok' : 'neutral'">
          PhageTailFinder {{ capabilities?.phagetailfinder_ready ? '双状态 HMM 就绪' : '未就绪' }}
        </span>
        <span v-if="capabilities?.phold_ready" class="chip ok">Phold 3D 模型就绪</span>
      </div>
    </div>

    <!-- 主表单卡 -->
    <div class="setup-card">
      <div class="field-row">
        <label class="field-label">分析任务命名</label>
        <input v-model="form.task_name" type="text" class="text-input" placeholder="例如: Phage_T4_Morphotype" />
      </div>

      <!-- 4 源模式切换 -->
      <div class="tabs-bar">
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'upload' }" @click="switchTab('upload')">
          上传 / 拖拽 FASTA · GBK · FAA
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'paste' }" @click="switchTab('paste')">
          直接粘贴序列文本
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'annotation' }" @click="switchTab('annotation')">
          从历史功能注释导入 ({{ linkedSources.annotations.length }})
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'phage_discovery' }" @click="switchTab('phage_discovery')">
          从前噬菌体扫描区段导入 ({{ linkedSources.phage_discoveries.length }})
        </button>
      </div>

      <!-- Tab 1: 文件上传 -->
      <div
        v-if="uiTab === 'upload'"
        class="drop-zone"
        :class="{ dragging: isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="onDropFile"
        @click="triggerFileSelect"
      >
        <input
          ref="fileInputRef"
          type="file"
          class="hidden-file"
          accept=".fasta,.fa,.fna,.faa,.gbk,.gb,.gbff,.genbank,.gz"
          @change="onBrowserFileChange"
        />
        <div class="drop-title">
          {{ isUploading ? '正在读取并预检文件...' : uploadedFileName ? `已选择: ${uploadedFileName}` : '点击选取或拖拽基因组 FASTA / GenBank (.gbk) / 蛋白 FAA 文件到此处' }}
        </div>
        <div class="drop-sub">自动区分裸核酸基因组 (Pyrodigal + PyHMMER)、带注释 GenBank 或多序列蛋白组 FAA</div>
      </div>

      <!-- Tab 2: 粘贴文本 -->
      <div v-else-if="uiTab === 'paste'" class="paste-box">
        <textarea
          v-model="form.fasta_content"
          rows="7"
          class="paste-area"
          placeholder="在此粘贴 FASTA 核酸、蛋白 FAA 或 GenBank (LOCUS ...) 文本，自动触发结构域与形态预检..."
        ></textarea>
      </div>

      <!-- Tab 3: 功能注释导入 -->
      <div v-else-if="uiTab === 'annotation'" class="linked-box">
        <div v-if="isSourcesLoading" class="empty-src">正在读取历史注释任务...</div>
        <div v-else-if="linkedSources.annotations.length === 0" class="empty-src">暂无已完成的全基因组注释任务</div>
        <div v-else class="src-grid">
          <div
            v-for="a in linkedSources.annotations"
            :key="a.task_id"
            class="src-item"
            :class="{ active: form.source_task_id === a.task_id }"
            @click="selectAnnotationSource(a.task_id)"
          >
            <div class="src-name">{{ a.task_name }}</div>
            <div class="src-meta">{{ a.sample_type }} · {{ a.cds_count }} CDS · {{ formatGenomeBp(a.total_length) }}</div>
          </div>
        </div>
      </div>

      <!-- Tab 4: 前噬菌体扫描区段导入 -->
      <div v-else class="linked-box">
        <div v-if="isSourcesLoading" class="empty-src">正在读取前噬菌体扫描任务...</div>
        <div v-else-if="linkedSources.phage_discoveries.length === 0" class="empty-src">暂无已检出前噬菌体区段的扫描任务</div>
        <div v-else class="src-grid">
          <div
            v-for="p in linkedSources.phage_discoveries"
            :key="p.task_id"
            class="src-item"
            :class="{ active: form.source_task_id === p.task_id }"
            @click="selectDiscoverySource(p.task_id)"
          >
            <div class="src-name">{{ p.task_name }}</div>
            <div class="src-meta">检出 {{ p.region_count }} 区段 · {{ formatGenomeBp(p.total_prophage_bp) }}</div>
          </div>
        </div>
        <div v-if="form.source_task_id" class="region-opt">
          <label>指定区段序号（留空则一次评估该任务全部前噬菌体区段）：</label>
          <input v-model.number="form.region_index" type="number" min="1" class="num-input" placeholder="全部" @change="triggerLinkedInspect" />
        </div>
      </div>

      <!-- Contig 预检选择 -->
      <div v-if="inspectedContigs.length > 0" class="contig-box">
        <ContigSelector
          :contigs="selectorContigs"
          :total-length="inspectTotalBp"
          :overall-gc="overallGcPercent"
          @update:selection="(ids) => (form.selected_contigs = ids)"
        />
      </div>

      <!-- 高级参数折叠 -->
      <div class="adv-toggle-row">
        <button type="button" class="link-btn" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '收起高级判定参数' : '展开高级并行与阈值参数' }}
        </button>
      </div>

      <div v-if="showAdvanced" class="adv-grid">
        <div class="adv-field">
          <label>并行核心数 (留空自动)</label>
          <input v-model.number="form.threads" type="number" min="1" max="64" class="text-input" />
        </div>
        <div class="adv-field">
          <label>遗传密码表</label>
          <select v-model.number="form.genetic_code" class="text-input">
            <option :value="11">Table 11 (标准原核/噬菌体)</option>
            <option :value="4">Table 4 (支原体/螺旋体)</option>
          </select>
        </div>
        <div class="adv-field">
          <label>PHROG 比特分下限 (Score)</label>
          <input v-model.number="form.score_cutoff" type="number" min="15" max="200" step="1" class="text-input" />
        </div>
        <div class="adv-field">
          <label>E-value 上限</label>
          <input v-model.number="form.evalue_cutoff" type="number" step="0.0001" class="text-input" />
        </div>
        <label class="chk-row">
          <input v-model="form.force_hmm_rescan" type="checkbox" />
          <span>强制对已注释蛋白重跑 PHROG 结构 HMM 扫描</span>
        </label>
        <label class="chk-row" :class="{ disabled: !capabilities?.phagetailfinder_ready }">
          <input v-model="form.enable_phagetailfinder" type="checkbox" :disabled="!capabilities?.phagetailfinder_ready" />
          <span>启用 PhageTailFinder 双状态 HMM 尾部模块识别（基于 3,668 Pfam 共线性建模）</span>
        </label>
        <label v-if="form.enable_phagetailfinder && capabilities?.phagetailfinder_ready" class="chk-row">
          <input v-model="form.ptf_accurate_mode" type="checkbox" />
          <span>PhageTailFinder 精确保守模式（提高未命中 Pfam 基因的非尾惩罚以降低误召回）</span>
        </label>
        <label class="chk-row" :class="{ disabled: !capabilities?.phold_ready }">
          <input v-model="form.enable_phold_enhance" type="checkbox" :disabled="!capabilities?.phold_ready" />
          <span>启用 Phold 3D 结构折叠对 &ge;100 aa 未知蛋白补漏（ProstT5 + Foldseek，耗时更长）</span>
        </label>
      </div>

      <!-- 提交底栏 -->
      <div class="submit-bar">
        <span v-if="isQueueBusy" class="queue-hint">当前存在运行中任务，提交后将自动进入安全等待队列。</span>
        <span v-else class="queue-hint">结构 HMM 索引已做极速浓缩优化，单株基因组平均耗时仅数秒。</span>
        <button type="button" class="submit-btn" :disabled="!canSubmit" @click="onSubmit">
          {{ isSubmitting ? '正在提交队列...' : isInspecting ? '正在预检输入...' : '开始结构与形态预测' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.engine-banner {
  background: linear-gradient(135deg, #f8fafc, #eff6ff);
  border: 1px solid #dbeafe;
  border-radius: 14px;
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.eb-left h3 {
  margin: 0;
  font-size: 1.08rem;
  color: #0f172a;
}

.eb-left p {
  margin: 4px 0 0 0;
  font-size: 0.84rem;
  color: #475569;
}

.eb-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip {
  font-size: 0.76rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
}

.chip.ok {
  background: #dcfce7;
  color: #15803d;
}

.chip.warn {
  background: #fee2e2;
  color: #b91c1c;
}

.chip.neutral {
  background: #f1f5f9;
  color: #475569;
}

.setup-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.84rem;
  font-weight: 600;
  color: #334155;
}

.text-input,
.num-input {
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.88rem;
  color: #0f172a;
}

.tabs-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tab-btn {
  padding: 8px 14px;
  border-radius: 9px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 0.83rem;
  font-weight: 600;
  cursor: pointer;
}

.tab-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 30px 20px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.16s;
}

.drop-zone:hover,
.drop-zone.dragging {
  border-color: #2563eb;
  background: #eff6ff;
}

.hidden-file {
  display: none;
}

.drop-title {
  font-size: 0.92rem;
  font-weight: 600;
  color: #1e293b;
}

.drop-sub {
  margin-top: 6px;
  font-size: 0.8rem;
  color: #64748b;
}

.paste-area {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 12px;
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
  resize: vertical;
}

.linked-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
}

.empty-src {
  text-align: center;
  color: #64748b;
  padding: 20px;
  font-size: 0.85rem;
}

.src-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 10px;
  max-height: 220px;
  overflow-y: auto;
}

.src-item {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 9px;
  padding: 10px 12px;
  cursor: pointer;
}

.src-item:hover {
  border-color: #60a5fa;
}

.src-item.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.src-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
}

.src-meta {
  margin-top: 3px;
  font-size: 0.76rem;
  color: #64748b;
}

.region-opt {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.82rem;
  color: #334155;
}

.num-input {
  width: 90px;
}

.adv-toggle-row {
  display: flex;
  justify-content: flex-start;
}

.link-btn {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}

.adv-grid {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.adv-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.8rem;
  color: #475569;
}

.chk-row {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.83rem;
  color: #334155;
  cursor: pointer;
}

.chk-row.disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.submit-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.queue-hint {
  font-size: 0.8rem;
  color: #64748b;
}

.submit-btn {
  padding: 10px 22px;
  border-radius: 9px;
  border: none;
  background: #2563eb;
  color: #ffffff;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
}

.submit-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
</style>
