import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getBridge } from '../../../../../bridge/electron-bridge'
import { createLogger } from '../../../../../utils/logger'
import { notifyUser } from '../../../../../utils/notify'
import type { PhageCapabilities, PhageContigInspectItem, PhageScanForm } from '../types'
import { formatPhageModelBadge } from '../utils'

const logger = createLogger('PhageDiscoverySetup')

export interface AssemblyHistorySummary {
  task_id?: string
  id?: string
  name?: string
  status?: string
  sample_type?: string
  created_at?: unknown
  contigs_path?: string
  fasta_path?: string
  assembly_fasta?: string
  output_fasta?: string
}

export interface PhageDiscoverySetupProps {
  capabilities: PhageCapabilities | null
  isCapabilitiesLoading: boolean
  isInspecting: boolean
  isSubmitting: boolean
  isQueueBusy: boolean
  inspectedContigs: PhageContigInspectItem[]
  inspectTotalBp: number
}

export interface PhageDiscoverySetupEmits {
  (e: 'submit', form: PhageScanForm): void
  (e: 'inspect', payload: { fasta_path?: string; fasta_content?: string }): void
  (e: 'save-config', payload: { default_model_dir?: string; blast_db?: string }): void
  (e: 'refresh-capabilities'): void
}

export function usePhageDiscoverySetup(
  props: PhageDiscoverySetupProps,
  emit: PhageDiscoverySetupEmits
) {
  const bridge = getBridge()

  const inputMode = ref<'upload' | 'paste' | 'assembly'>('upload')
  const uploadedFileName = ref<string>('')
  const isUploading = ref<boolean>(false)
  const isDragging = ref<boolean>(false)
  const fileInputRef = ref<HTMLInputElement | null>(null)

  const assemblyHistory = ref<AssemblyHistorySummary[]>([])
  const isAssemblyLoading = ref<boolean>(false)
  const selectedAssemblyTask = ref<string>('')

  const showAdvanced = ref<boolean>(false)
  const showPathConfig = ref<boolean>(false)
  const configModelDir = ref<string>('')
  const configBlastDb = ref<string>('')

  const form = reactive<PhageScanForm>({
    task_name: 'PhageDiscovery_Stage1_2',
    model_id: '',
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

  const availableModels = computed(() => props.capabilities?.models || [])

  watch(
    availableModels,
    (list) => {
      if (!list.length) {
        form.model_id = ''
        return
      }
      if (!form.model_id || !list.some((m) => m.model_id === form.model_id)) {
        form.model_id = list[0]?.model_id || ''
      }
    },
    { immediate: true }
  )

  const activeV42Model = computed(() => {
    const list = availableModels.value
    if (!list.length) return null
    return list.find((m) => m.model_id === form.model_id) || list[0] || null
  })

  const activeModelBadge = computed(() => {
    const m = activeV42Model.value
    if (!m) return 'Unified V4'
    return formatPhageModelBadge({
      modelId: m.model_id,
      modelVersion: m.version,
      modelLabel: m.label,
      featureProfile: m.feature_profile,
      hasUnifiedJudge: m.has_unified_judge,
    })
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

  const singleContig = computed(() =>
    props.inspectedContigs.length === 1 ? (props.inspectedContigs[0] ?? null) : null
  )

  watch(
    activeV42Model,
    (model) => {
      if (!model?.decoder_defaults) return
      if (model.has_unified_judge && form.task_name === 'PhageDiscovery_Stage1_2') {
        form.task_name = 'PhageDiscovery_Unified'
      } else if (!model.has_unified_judge && form.task_name === 'PhageDiscovery_Unified') {
        form.task_name = 'PhageDiscovery_Stage1_2'
      }
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

  function getAssemblyTaskId(t: AssemblyHistorySummary): string {
    return String(t?.task_id || t?.id || '')
  }

  function formatAssemblyTime(val: unknown): string {
    if (typeof val === 'number' && Number.isFinite(val)) {
      const ms = val < 1e12 ? val * 1000 : val
      const d = new Date(ms)
      if (!Number.isNaN(d.getTime())) {
        const pad = (n: number) => String(n).padStart(2, '0')
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
      }
    }
    if (typeof val === 'string') {
      const trimmed = val.trim()
      if (/^\d+(\.\d+)?$/.test(trimmed)) {
        return formatAssemblyTime(Number(trimmed))
      }
      return trimmed.slice(0, 16)
    }
    return ''
  }

  async function loadAssemblyHistory(): Promise<void> {
    isAssemblyLoading.value = true
    try {
      const res = await bridge.get_assembly_history()
      const resObj = res as
        | AssemblyHistorySummary[]
        | { data?: AssemblyHistorySummary[]; history?: AssemblyHistorySummary[]; tasks?: AssemblyHistorySummary[] }
      const list = Array.isArray(resObj) ? resObj : resObj?.data || resObj?.history || resObj?.tasks || []
      assemblyHistory.value = list.filter((t) => t.status === 'completed' || t.contigs_path || t.fasta_path)
    } catch (err) {
      logger.error('读取拼接历史失败:', err)
    } finally {
      isAssemblyLoading.value = false
    }
  }

  function switchMode(mode: 'upload' | 'paste' | 'assembly'): void {
    inputMode.value = mode
    if (mode === 'assembly' && assemblyHistory.value.length === 0) {
      loadAssemblyHistory()
    }
  }

  function onAssemblyTaskSelected(): void {
    const tid = selectedAssemblyTask.value
    const t = assemblyHistory.value.find((item) => getAssemblyTaskId(item) === tid)
    if (!t) return
    const candidatePath =
      t.contigs_path ||
      t.fasta_path ||
      t.assembly_fasta ||
      t.output_fasta ||
      `results/assembly/${tid}/assemblerstep/assembly_run/assembly.fasta`
    if (candidatePath) {
      form.fasta_path = candidatePath
      form.fasta_content = ''
      uploadedFileName.value = t.name || tid
      if (
        !form.task_name ||
        form.task_name === 'PhageDiscovery_Unified' ||
        form.task_name === 'PhageDiscovery_Stage1_2' ||
        form.task_name === 'PhageDiscovery_V42'
      ) {
        form.task_name = `${t.name || tid}_PhageScan`
      }
      emit('inspect', { fasta_path: candidatePath })
    }
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
        applySelectedPath(res.path || res.file_path || '')
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
    form.fasta_content = `>Demo_Bacterial_Chromosome_With_Candidate_Region\n${blockHost.repeat(40)}${blockPhage.repeat(90)}${blockHost.repeat(40)}\n`
    form.task_name = activeV42Model.value?.has_unified_judge ? 'Demo_Genome_Unified' : 'Demo_Genome_Stage1_2'
    emit('inspect', { fasta_content: form.fasta_content })
  }

  function clearPasteData(): void {
    form.fasta_content = ''
  }

  async function browseCustomModelDir(): Promise<void> {
    const picked = await bridge.request_directory_select('选择前噬菌体发现模型目录')
    if (picked) configModelDir.value = picked
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
      notifyUser('请先选择或粘贴待扫描的基因组序列', 'warning')
      return
    }
    if (!activeV42Model.value && !form.custom_model_dir.trim()) {
      notifyUser('未检测到本地前噬菌体识别模型权重，请先配置模型目录', 'error')
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

  return {
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
  }
}
