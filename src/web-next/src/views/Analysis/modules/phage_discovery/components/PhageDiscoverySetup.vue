<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getBridge } from '../../../../../bridge/electron-bridge'
import ContigSelector from '../../annotation/components/ContigSelector.vue'
import type { PhageCapabilities, PhageContigInspectItem, PhageScanForm } from '../types'

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

const bridge = getBridge()

const inputMode = ref<'upload' | 'paste' | 'assembly'>('upload')
const uploadedFileName = ref<string>('')
const isUploading = ref<boolean>(false)
const isDragging = ref<boolean>(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const assemblyHistory = ref<any[]>([])
const isAssemblyLoading = ref<boolean>(false)
const selectedAssemblyTask = ref<string>('')

const showAdvanced = ref<boolean>(false)
const showPathConfig = ref<boolean>(false)
const configModelDir = ref<string>('')
const configBlastDb = ref<string>('')

const form = reactive<PhageScanForm>({
  task_name: 'PhageDiscovery_V42',
  fasta_path: '',
  fasta_content: '',
  selected_contigs: [],
  custom_model_dir: '',
  device: 'auto',
  workers: 0,
  apply_protein_gate: false,
  blast_db: '',
  seed_threshold: 0.95,
  extend_threshold: 0.30,
  sub_threshold: 0.45,
  merge_gap_bp: 3000,
  min_region_bp: 3000,
})

const activeV42Model = computed(() => {
  const list = props.capabilities?.models || []
  return list.length > 0 ? list[0] : null
})

const computeEnv = computed(() => props.capabilities?.compute)
const gateStatus = computed(() => props.capabilities?.protein_gate)

const overallGcPercent = computed(() => {
  if (!props.inspectedContigs.length || props.inspectTotalBp <= 0) return 0
  let weighted = 0
  for (const c of props.inspectedContigs) {
    weighted += Number(c.gc_percent || 0) * Number(c.length || 0)
  }
  return Number((weighted / props.inspectTotalBp).toFixed(2))
})

const selectorContigs = computed(() =>
  props.inspectedContigs.map((c) => ({
    id: c.id,
    description: c.description || '',
    length_bp: c.length,
    gc_content: c.gc_percent,
    selected: true,
  }))
)

const singleContig = computed(() => {
  return props.inspectedContigs.length === 1 ? (props.inspectedContigs[0] ?? null) : null
})

watch(
  activeV42Model,
  (model) => {
    if (!model?.decoder_defaults) return
    form.seed_threshold = model.decoder_defaults.seed_threshold
    form.extend_threshold = model.decoder_defaults.extend_threshold
    form.sub_threshold = model.decoder_defaults.sub_threshold
    form.merge_gap_bp = model.decoder_defaults.merge_gap_bp
    form.min_region_bp = model.decoder_defaults.min_region_bp
  },
  { immediate: true }
)

watch(
  computeEnv,
  (env) => {
    if (env && form.workers === 0) {
      form.workers = env.safe_workers || 2
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

let pasteTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => form.fasta_content,
  (val) => {
    if (inputMode.value !== 'paste') return
    if (pasteTimer) clearTimeout(pasteTimer)
    pasteTimer = setTimeout(() => {
      if (val && val.trim().length > 20) {
        emit('inspect', { fasta_content: val })
      }
    }, 450)
  }
)

function switchMode(mode: 'upload' | 'paste' | 'assembly'): void {
  inputMode.value = mode
  if (mode === 'assembly' && assemblyHistory.value.length === 0) {
    loadAssemblyHistory()
  }
}

async function loadAssemblyHistory(): Promise<void> {
  isAssemblyLoading.value = true
  try {
    const res = await bridge.get_assembly_history()
    const list = Array.isArray(res) ? res : res?.history || res?.tasks || []
    assemblyHistory.value = list.filter((t: any) => t.status === 'completed' || t.contigs_path)
  } catch (err) {
    console.error('[PhageDiscoverySetup] 读取拼接历史失败:', err)
  } finally {
    isAssemblyLoading.value = false
  }
}

function onAssemblyTaskSelected(): void {
  const t = assemblyHistory.value.find((item: any) => item.task_id === selectedAssemblyTask.value)
  if (!t) return
  const candidatePath = t.contigs_path || t.fasta_path || t.output_fasta || ''
  if (candidatePath) {
    form.fasta_path = candidatePath
    form.fasta_content = ''
    uploadedFileName.value = t.name || t.task_id
    if (!form.task_name || form.task_name === 'PhageDiscovery_V42') {
      form.task_name = `${t.name || t.task_id}_PhageScan`
    }
    emit('inspect', { fasta_path: candidatePath })
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
  form.fasta_path = path
  form.fasta_content = ''
  const parts = path.replace(/\\/g, '/').split('/')
  const name = parts[parts.length - 1] || path
  uploadedFileName.value = name
  const stem = name.replace(/\.(fasta|fa|fna|fsa|gbk|gb|genbank|gz)+$/gi, '')
  if (stem) form.task_name = `${stem}_PhageScan`
  emit('inspect', { fasta_path: path })
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
      inputMode.value = 'paste'
      form.fasta_path = ''
      form.fasta_content = text
      uploadedFileName.value = file.name
      emit('inspect', { fasta_content: text })
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

function loadDemoSequence(): void {
  inputMode.value = 'paste'
  form.fasta_path = ''
  const blockHost = 'ATGCGTACGTAGCTAGCTGATCGATCGTAGCTAGCTAGCATGCATCGATCGATCGATCGA'
  const blockPhage = 'ATGGCTAAAGAATTCGGATCCATGCGACTAGTCAGTGCATATGACTAGCTGACTGACTGAC'
  const hostLeft = blockHost.repeat(40)
  const corePhage = blockPhage.repeat(90)
  const hostRight = blockHost.repeat(40)
  form.fasta_content = `>Demo_Bacterial_Chromosome_With_Candidate_Region\n${hostLeft}${corePhage}${hostRight}\n`
  form.task_name = 'Demo_Genome_V42'
  emit('inspect', { fasta_content: form.fasta_content })
}

function clearPasteData(): void {
  form.fasta_content = ''
}

async function browseCustomModelDir(): Promise<void> {
  const picked = await bridge.request_directory_select('选择 Student V4.2 模型目录')
  if (picked) {
    configModelDir.value = picked
  }
}

async function browseBlastDbFile(): Promise<void> {
  if (window.electronAPI) {
    const paths = await bridge.request_file_load(['phr', 'pin', 'psq', 'pdb', 'pal'], false)
    if (paths && paths.length > 0 && paths[0]) {
      configBlastDb.value = paths[0].replace(/\.(phr|pin|psq|pdb|pal|pog|pos|pot|ptf|pto)$/i, '')
    }
  }
}

function applySavedPaths(): void {
  emit('save-config', {
    default_model_dir: configModelDir.value.trim() || undefined,
    blast_db: configBlastDb.value.trim() || undefined,
  })
  showPathConfig.value = false
}

function resetThresholds(): void {
  const def = activeV42Model.value?.decoder_defaults
  form.seed_threshold = def?.seed_threshold ?? 0.95
  form.extend_threshold = def?.extend_threshold ?? 0.30
  form.sub_threshold = def?.sub_threshold ?? 0.45
  form.merge_gap_bp = def?.merge_gap_bp ?? 3000
  form.min_region_bp = def?.min_region_bp ?? 3000
}

function formatParamsCount(n?: number): string {
  if (!n) return '--'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
}

function onSubmit(): void {
  if (!form.fasta_path && !form.fasta_content.trim()) {
    (window as any).app?.showNotification('请先选择或粘贴待扫描的基因组序列', 'warning')
    return
  }
  if (!activeV42Model.value && !form.custom_model_dir.trim()) {
    (window as any).app?.showNotification('未检测到 Student V4.2 模型权重，请先配置模型目录', 'error')
    showPathConfig.value = true
    return
  }
  emit('submit', { ...form })
}

onMounted(() => {
  if (inputMode.value === 'assembly') {
    loadAssemblyHistory()
  }
})
</script>

<template>
  <div class="setup-card">
    <!-- 1. 顶部标题与示例加载 -->
    <div class="setup-header">
      <div class="title-block">
        <h2>前噬菌体与噬菌体边界精细扫描 (Student V4.2)</h2>
        <p class="subtitle">基于多尺度 DNA 序列与 ORF 语义上下文模型，结合 200bp SubBinRefiner 实现精确切割</p>
      </div>
      <div class="header-actions">
        <button type="button" class="sample-btn" @click="loadDemoSequence">载入验证样本</button>
      </div>
    </div>

    <!-- 队列状态繁忙提示横幅 -->
    <div v-if="isQueueBusy" class="queue-busy-banner">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      <span>当前已有扫描任务正在执行或等待中：本次提交将严格串行加入等待队列，前序完成后自动启动。</span>
    </div>

    <!-- 2. 输入源切换 -->
    <div class="source-tabs">
      <button
        type="button"
        class="tab-btn"
        :class="{ active: inputMode === 'upload' }"
        @click="switchMode('upload')"
      >
        本地基因组文件
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ active: inputMode === 'paste' }"
        @click="switchMode('paste')"
      >
        直接粘贴 FASTA / GBK
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ active: inputMode === 'assembly' }"
        @click="switchMode('assembly')"
      >
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
          class="drop-zone"
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
              <span class="main-tip">拖拽细菌全基因组或拼接 Contigs 至此，或 <span class="browse-link">点击浏览文件</span></span>
              <span class="sub-tip">支持 .fasta / .fa / .fna / .fasta.gz / .gbk / .gbff 格式</span>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="inputMode === 'paste'" class="paste-zone">
        <div class="paste-header">
          <span class="paste-tip">粘贴完整 FASTA 或 GenBank 核酸序列文本</span>
          <div class="paste-actions">
            <span class="char-count">{{ form.fasta_content.length }} 字符</span>
            <button type="button" class="clear-btn" @click="clearPasteData">清空</button>
          </div>
        </div>
        <textarea
          v-model="form.fasta_content"
          rows="5"
          class="fasta-textarea"
          placeholder=">Chromosome_1&#10;ATGCGTACGTAGCTAGCTAG..."
        ></textarea>
      </div>

      <div v-else class="assembly-zone">
        <div v-if="isAssemblyLoading" class="zone-loading">正在获取已完成的基因组拼接任务...</div>
        <div v-else-if="assemblyHistory.length === 0" class="zone-empty">
          暂未检测到已完成的拼接产物，请通过文件选择或直接粘贴输入。
        </div>
        <div v-else class="assembly-select-wrapper">
          <label class="select-label">选择已组装样本序列:</label>
          <select v-model="selectedAssemblyTask" class="custom-select" @change="onAssemblyTaskSelected">
            <option value="">-- 请选择组装任务 --</option>
            <option v-for="t in assemblyHistory" :key="t.task_id" :value="t.task_id">
              [{{ t.sample_type || 'ASSEMBLY' }}] {{ t.name || t.task_id }} ({{ String(t.created_at || '').slice(0, 16) }})
            </option>
          </select>
          <div v-if="form.fasta_path" class="selected-path-hint">
            已锁定序列路径: {{ form.fasta_path }}
          </div>
        </div>
      </div>
    </div>

    <!-- 3. Contig 多序列预检与勾选 -->
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

    <!-- 4. V4.2 模型状态与算力卡片 -->
    <div class="engine-status-card" :class="{ missing: !activeV42Model }">
      <div class="engine-head">
        <div class="engine-title-row">
          <span class="version-pill">Student V4.2</span>
          <strong>{{ activeV42Model ? activeV42Model.label : '未检测到本地 V4.2 模型目录' }}</strong>
        </div>
        <div class="engine-tools">
          <button
            type="button"
            class="text-link-btn"
            :disabled="isCapabilitiesLoading"
            @click="emit('refresh-capabilities')"
          >
            {{ isCapabilitiesLoading ? '探测中...' : '重新探测' }}
          </button>
          <button type="button" class="text-link-btn" @click="showPathConfig = !showPathConfig">
            {{ showPathConfig ? '收起路径配置' : '配置模型/蛋白库路径' }}
          </button>
        </div>
      </div>

      <div v-if="activeV42Model" class="engine-meta-row">
        <span class="meta-chip ok">200bp SubBinRefiner 已就绪</span>
        <span v-if="activeV42Model.has_context_refiner" class="meta-chip ok">ContextRefiner 已就绪</span>
        <span class="meta-chip">参数量 {{ formatParamsCount(activeV42Model.params) }}</span>
        <span class="meta-path" :title="activeV42Model.path">{{ activeV42Model.path }}</span>
      </div>
      <div v-else class="engine-missing-tip">
        请将完整 V4.2 模型目录放置于项目 <code>models/full_v4/student_v4_2</code> 或相邻 <code>Phage data/models/full_v4/student_v4_2</code> 下，或点击右侧手动指定目录。
      </div>

      <div v-if="showPathConfig" class="path-config-drawer">
        <div class="config-row">
          <label>自定义 V4.2 模型目录:</label>
          <div class="input-with-btn">
            <input
              v-model="configModelDir"
              type="text"
              class="text-input"
              placeholder="包含 student_v4.pt 与 subbin_refiner.pt 的目录路径"
            />
            <button type="button" class="outline-btn" @click="browseCustomModelDir">浏览</button>
          </div>
        </div>
        <div class="config-row">
          <label>可选 BLASTp 蛋白库前缀:</label>
          <div class="input-with-btn">
            <input
              v-model="configBlastDb"
              type="text"
              class="text-input"
              placeholder="如 database/phage_discovery/phage_refseq_prot"
            />
            <button type="button" class="outline-btn" @click="browseBlastDbFile">浏览</button>
          </div>
        </div>
        <div class="config-actions">
          <button type="button" class="save-cfg-btn" @click="applySavedPaths">保存相对路径并刷新</button>
        </div>
      </div>
    </div>

    <!-- 5. 任务核心配置 -->
    <div class="params-grid">
      <div class="form-group">
        <label>扫描任务名称</label>
        <input v-model="form.task_name" type="text" class="text-input" placeholder="输入样本或菌株标识" />
      </div>

      <div class="form-group">
        <label>推理硬件设备</label>
        <select v-model="form.device" class="custom-select">
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

    <!-- 第二阶段可选门控 -->
    <div class="gate-option-box">
      <label class="checkbox-label">
        <input
          v-model="form.apply_protein_gate"
          type="checkbox"
          :disabled="!gateStatus?.ready && !form.blast_db.trim()"
        />
        <span>启用第二阶段 BLASTp 病毒标志蛋白门控 (提升假阳性过滤，耗时将增加)</span>
      </label>
      <div class="gate-status-text">
        <span v-if="gateStatus?.ready" class="status-ok">
          已检测到 blastp 与蛋白参考库 ({{ gateStatus.blast_db }})
        </span>
        <span v-else class="status-warn">
          未检测到完整的本地 blastp / phage_refseq_prot 库，当前默认采用纯 V4.2 神经引擎极速发现模式
        </span>
      </div>
    </div>

    <!-- 6. 高级解码边界精修参数 -->
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
        <button v-if="showAdvanced" type="button" class="reset-btn" @click="resetThresholds">
          恢复 V4.2 默认
        </button>
      </div>

      <div v-show="showAdvanced" class="advanced-body">
        <div class="params-grid three-cols">
          <div class="form-group">
            <label>种子激活阈值 (Seed)</label>
            <input v-model.number="form.seed_threshold" type="number" step="0.01" min="0.1" max="0.99" class="text-input" />
          </div>
          <div class="form-group">
            <label>区域滞回延伸 (Extend)</label>
            <input v-model.number="form.extend_threshold" type="number" step="0.01" min="0.05" max="0.95" class="text-input" />
          </div>
          <div class="form-group">
            <label>200bp 精细边界阈值</label>
            <input v-model.number="form.sub_threshold" type="number" step="0.01" min="0.1" max="0.95" class="text-input" />
          </div>
          <div class="form-group">
            <label>邻近片段合并间隔 (bp)</label>
            <input v-model.number="form.merge_gap_bp" type="number" step="500" min="0" max="50000" class="text-input" />
          </div>
          <div class="form-group">
            <label>最短保留区段长度 (bp)</label>
            <input v-model.number="form.min_region_bp" type="number" step="500" min="400" max="50000" class="text-input" />
          </div>
          <div class="form-group">
            <label>特征抽取并发线程数</label>
            <input v-model.number="form.workers" type="number" min="1" :max="computeEnv?.safe_workers || 8" class="text-input" />
          </div>
        </div>
      </div>
    </div>

    <!-- 7. 提交按钮 -->
    <div class="setup-actions">
      <button
        type="button"
        class="submit-btn"
        :class="{ 'is-busy-mode': isQueueBusy }"
        :disabled="isUploading || isInspecting || isSubmitting"
        @click="onSubmit"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
          <polygon v-if="!isQueueBusy" points="5 3 19 12 5 21 5 3" />
          <path v-else d="M12 5v14M5 12h14" />
        </svg>
        <span v-if="isSubmitting">正在排队提交...</span>
        <span v-else-if="isQueueBusy">加入 V4.2 扫描队列</span>
        <span v-else>启动 V4.2 前噬菌体全基因组扫描</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.setup-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.queue-busy-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
  font-size: 12px;
  font-weight: 600;
}

.setup-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.title-block h2 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}

.subtitle {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.sample-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
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
}

.tab-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.tab-btn.active {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  padding: 22px 16px;
  text-align: center;
  cursor: pointer;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}

.drop-zone:hover,
.drop-zone.dragging {
  border-color: #3b82f6;
  background: #eff6ff;
}

.drop-icon {
  color: #64748b;
}

.drop-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: #334155;
}

.file-name-highlight {
  font-weight: 700;
  color: #1d4ed8;
}

.file-path-hint {
  font-size: 11px;
  color: #64748b;
  font-family: 'Consolas', monospace;
}

.browse-link {
  color: #2563eb;
  font-weight: 700;
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
  font-size: 12px;
  color: #64748b;
}

.paste-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.clear-btn {
  border: 1px solid #cbd5e1;
  background: white;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}

.fasta-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 10px;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  resize: vertical;
}

.assembly-zone {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px;
}

.zone-loading,
.zone-empty {
  font-size: 12px;
  color: #64748b;
  text-align: center;
}

.assembly-select-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.select-label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.selected-path-hint {
  font-size: 11px;
  color: #475569;
  font-family: 'Consolas', monospace;
}

.inspect-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  color: #1d4ed8;
  font-weight: 600;
}

.mini-spin {
  width: 14px;
  height: 14px;
  border: 2px solid #93c5fd;
  border-top-color: #1d4ed8;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.single-contig-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  color: #334155;
}

.engine-status-card {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.engine-status-card.missing {
  background: #fff7ed;
  border-color: #fdba74;
}

.engine-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.engine-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #1e293b;
}

.version-pill {
  background: #4338ca;
  color: white;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
}

.engine-tools {
  display: flex;
  gap: 10px;
}

.text-link-btn {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.engine-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.meta-chip {
  padding: 2px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #334155;
  font-weight: 600;
}

.meta-chip.ok {
  background: #dcfce7;
  color: #15803d;
}

.meta-path {
  color: #64748b;
  font-family: 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

.engine-missing-tip {
  font-size: 12px;
  color: #9a3412;
}

.path-config-drawer {
  border-top: 1px solid #e2e8f0;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #334155;
}

.input-with-btn {
  display: flex;
  gap: 8px;
}

.outline-btn {
  border: 1px solid #cbd5e1;
  background: white;
  color: #334155;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.config-actions {
  display: flex;
  justify-content: flex-end;
}

.save-cfg-btn {
  background: #2563eb;
  color: white;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.params-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.params-grid.three-cols {
  grid-template-columns: repeat(3, 1fr);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.text-input,
.custom-select {
  height: 36px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 0 10px;
  font-size: 13px;
  color: #1e293b;
  background: white;
  box-sizing: border-box;
  width: 100%;
}

.gate-option-box {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  cursor: pointer;
}

.gate-status-text {
  font-size: 11px;
  padding-left: 22px;
}

.status-ok {
  color: #15803d;
}

.status-warn {
  color: #64748b;
}

.advanced-section {
  border-top: 1px solid #e2e8f0;
  padding-top: 10px;
}

.advanced-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.toggle-advanced-btn {
  border: none;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
}

.reset-btn {
  border: 1px solid #cbd5e1;
  background: white;
  color: #475569;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.advanced-body {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.setup-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 10px 22px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.16s;
}

.submit-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.submit-btn.is-busy-mode {
  background: #d97706;
}

.submit-btn.is-busy-mode:hover:not(:disabled) {
  background: #b45309;
}

.submit-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
