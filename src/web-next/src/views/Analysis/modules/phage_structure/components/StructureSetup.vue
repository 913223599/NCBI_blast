<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { getBridge } from '../../../../../bridge/electron-bridge'
import ContigSelector from '../../annotation/components/ContigSelector.vue'
import type {
  StructureBatchQueuedEntry,
  StructureBatchRunPayload,
  StructureCapabilities,
  StructureInitialPayload,
  StructureInspectContig,
  StructureLinkedSources,
  StructureRunForm,
  StructureSourceMode,
} from '../types'
import {
  countFastaRecords,
  deriveStructureTaskName,
  detectSequenceFormatLabel,
  formatGenomeBp,
} from '../utils'

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
  (e: 'submit-batch', payload: StructureBatchRunPayload): void
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

const ALLOWED_EXT_RE = /\.(fasta|fa|fna|faa|gbk|gb|gbff|genbank)(\.gz)?$/i

const bridge = getBridge()
const uiTab = ref<'upload' | 'paste' | 'annotation' | 'phage_discovery'>('upload')
const uploadedFileName = ref<string>('')
const isUploading = ref<boolean>(false)
const isDragging = ref<boolean>(false)
const showAdvanced = ref<boolean>(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const appendFileMode = ref<boolean>(false)
const uploadNotice = ref<string>('')

const batchFiles = ref<StructureBatchQueuedEntry[]>([])
const selectedAnnotationIds = ref<string[]>([])
const selectedDiscoveryIds = ref<string[]>([])
const splitPhageRegions = ref<boolean>(false)
const splitFastaRecords = ref<boolean>(false)

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
      selectedAnnotationIds.value = [payload.taskId]
      form.region_index = undefined
      form.task_name = `${payload.taskName || payload.taskId}_Structure`
      triggerLinkedInspect()
    } else if (payload.sourceMode === 'phage_discovery') {
      uiTab.value = 'phage_discovery'
      form.source_mode = 'phage_discovery'
      form.source_task_id = payload.taskId
      selectedDiscoveryIds.value = [payload.taskId]
      form.region_index = payload.regionIndex
      splitPhageRegions.value = false
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

const pastedRecordCount = computed(() => countFastaRecords(form.fasta_content))
const canSplitPastedFasta = computed(
  () =>
    uiTab.value === 'paste' &&
    form.fasta_content.trim().startsWith('>') &&
    pastedRecordCount.value > 1
)

const selectedDiscoveryTotalRegions = computed(() => {
  let total = 0
  for (const tid of selectedDiscoveryIds.value) {
    const found = props.linkedSources.phage_discoveries.find((p) => p.task_id === tid)
    total += found ? Math.max(1, Number(found.region_count || 1)) : 1
  }
  return total
})

const isBatchSubmission = computed(() => {
  if (uiTab.value === 'upload') return batchFiles.value.length > 1
  if (uiTab.value === 'paste') return canSplitPastedFasta.value && splitFastaRecords.value
  if (uiTab.value === 'annotation') return selectedAnnotationIds.value.length > 1
  if (uiTab.value === 'phage_discovery') {
    if (selectedDiscoveryIds.value.length > 1) return true
    if (selectedDiscoveryIds.value.length === 1 && splitPhageRegions.value && !form.region_index) {
      return selectedDiscoveryTotalRegions.value > 1
    }
  }
  return false
})

const plannedTaskCount = computed(() => {
  if (uiTab.value === 'upload') return batchFiles.value.length
  if (uiTab.value === 'paste') {
    if (form.fasta_content.trim().length <= 20) return 0
    return canSplitPastedFasta.value && splitFastaRecords.value ? pastedRecordCount.value : 1
  }
  if (uiTab.value === 'annotation') return selectedAnnotationIds.value.length
  if (uiTab.value === 'phage_discovery') {
    if (selectedDiscoveryIds.value.length === 0) return 0
    if (splitPhageRegions.value && !form.region_index) {
      return selectedDiscoveryTotalRegions.value
    }
    return selectedDiscoveryIds.value.length
  }
  return 0
})

const canSubmit = computed(() => {
  if (props.isSubmitting || isUploading.value) return false
  if (!isBatchSubmission.value && props.isInspecting) return false
  if (uiTab.value === 'upload') return batchFiles.value.length > 0
  if (uiTab.value === 'paste') return form.fasta_content.trim().length > 20
  if (uiTab.value === 'annotation') return selectedAnnotationIds.value.length > 0
  if (uiTab.value === 'phage_discovery') return selectedDiscoveryIds.value.length > 0
  return false
})

function switchTab(tab: 'upload' | 'paste' | 'annotation' | 'phage_discovery'): void {
  uiTab.value = tab
  form.source_mode = tab === 'upload' ? 'file' : tab
  uploadNotice.value = ''
  if (tab === 'annotation' || tab === 'phage_discovery') {
    emit('refresh-sources')
  }
}

async function triggerFileSelect(append: boolean = false): Promise<void> {
  uploadNotice.value = ''
  appendFileMode.value = append
  if (window.electronAPI) {
    const paths = await bridge.request_file_load('phage', true)
    if (paths && paths.length > 0) {
      addPathsToQueue(paths, append)
    }
    return
  }
  fileInputRef.value?.click()
}

function buildEntryFromPath(filePath: string, fallbackName?: string): StructureBatchQueuedEntry {
  const parts = filePath.replace(/\\/g, '/').split('/')
  const fileName = fallbackName || parts[parts.length - 1] || filePath
  return {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    file_name: fileName,
    task_name: deriveStructureTaskName(fileName),
    source_mode: 'file',
    fasta_path: filePath,
    format_label: detectSequenceFormatLabel(fileName),
  }
}

function syncSingleUploadState(): void {
  if (batchFiles.value.length === 1) {
    const first = batchFiles.value[0]!
    form.source_mode = first.source_mode
    form.fasta_path = first.fasta_path || ''
    form.fasta_content = first.fasta_content || ''
    form.task_name = first.task_name
    uploadedFileName.value = first.file_name
    if (first.fasta_path) {
      emit('inspect', { source_mode: 'file', fasta_path: first.fasta_path })
    } else if (first.fasta_content) {
      emit('inspect', { source_mode: 'paste', fasta_content: first.fasta_content })
    }
  } else if (batchFiles.value.length > 1) {
    form.source_mode = 'file'
    form.fasta_path = ''
    form.fasta_content = ''
    uploadedFileName.value = `${batchFiles.value.length} 个已导入样本`
  } else {
    form.fasta_path = ''
    form.fasta_content = ''
    uploadedFileName.value = ''
  }
}

function addPathsToQueue(paths: string[], append: boolean): void {
  const cleanPaths = paths.map((p) => (p || '').trim()).filter(Boolean)
  if (!cleanPaths.length) return
  const incoming = cleanPaths.map((p) => buildEntryFromPath(p))
  mergeEntriesToBatch(incoming, append)
}

function mergeEntriesToBatch(incoming: StructureBatchQueuedEntry[], append: boolean): void {
  if (!append) {
    batchFiles.value = [...incoming]
  } else {
    const existingKeys = new Set(
      batchFiles.value.map((it) => `${it.fasta_path || ''}::${it.file_name}`)
    )
    for (const item of incoming) {
      const key = `${item.fasta_path || ''}::${item.file_name}`
      if (!existingKeys.has(key)) {
        existingKeys.add(key)
        batchFiles.value.push(item)
      }
    }
  }
  syncSingleUploadState()
}

function removeBatchFile(id: string): void {
  batchFiles.value = batchFiles.value.filter((it) => it.id !== id)
  syncSingleUploadState()
}

function clearBatchFiles(): void {
  batchFiles.value = []
  uploadNotice.value = ''
  syncSingleUploadState()
}

async function handleFilesUpload(rawFiles: File[], append: boolean): Promise<void> {
  if (!rawFiles.length) return
  uploadNotice.value = ''

  const validFiles = rawFiles.filter((f) => ALLOWED_EXT_RE.test(f.name) || rawFiles.length === 1)
  const skippedCount = rawFiles.length - validFiles.length
  if (skippedCount > 0) {
    uploadNotice.value = `已自动跳过 ${skippedCount} 个非 FASTA / GenBank 序列文件`
  }
  if (!validFiles.length) return

  const resolvedEntries: StructureBatchQueuedEntry[] = []
  const needHttpUpload: File[] = []

  for (const file of validFiles) {
    const nativePath = bridge.get_path_for_file(file)
    if (nativePath) {
      resolvedEntries.push(buildEntryFromPath(nativePath, file.name))
    } else {
      needHttpUpload.push(file)
    }
  }

  if (needHttpUpload.length > 0) {
    isUploading.value = true
    try {
      const uploadResults =
        needHttpUpload.length === 1
          ? [await bridge.upload_file(needHttpUpload[0]!)]
          : await bridge.upload_files_batch(needHttpUpload)

      for (let i = 0; i < needHttpUpload.length; i += 1) {
        const file = needHttpUpload[i]!
        const res = uploadResults[i]
        const uploadedPath = res?.path || res?.file_path || ''
        if (uploadedPath) {
          resolvedEntries.push(buildEntryFromPath(uploadedPath, file.name))
        } else {
          const text = await file.text()
          resolvedEntries.push({
            id: `${Date.now()}_${i}_${Math.random().toString(36).slice(2, 7)}`,
            file_name: file.name,
            task_name: deriveStructureTaskName(file.name),
            source_mode: 'paste',
            fasta_content: text,
            format_label: detectSequenceFormatLabel(file.name),
          })
        }
      }
    } finally {
      isUploading.value = false
    }
  }

  if (resolvedEntries.length > 0) {
    mergeEntriesToBatch(resolvedEntries, append)
  }
}

function onBrowserFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  if (files.length > 0) {
    handleFilesUpload(files, appendFileMode.value)
  }
  appendFileMode.value = false
  input.value = ''
}

function onDropFile(event: DragEvent): void {
  isDragging.value = false
  const files = event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : []
  if (files.length > 0) {
    const shouldAppend = batchFiles.value.length > 0
    handleFilesUpload(files, shouldAppend)
  }
}

let pasteTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => form.fasta_content,
  (val) => {
    if (uiTab.value !== 'paste') return
    if (pasteTimer) clearTimeout(pasteTimer)
    pasteTimer = setTimeout(() => {
      if (val && val.trim().length > 20 && !(splitFastaRecords.value && countFastaRecords(val) > 1)) {
        emit('inspect', { source_mode: 'paste', fasta_content: val })
      }
    }, 450)
  }
)

function toggleAnnotationSelection(taskId: string): void {
  const idx = selectedAnnotationIds.value.indexOf(taskId)
  if (idx >= 0) {
    selectedAnnotationIds.value.splice(idx, 1)
  } else {
    selectedAnnotationIds.value.push(taskId)
  }
  syncAnnotationSelectionState()
}

function selectAllAnnotations(): void {
  if (selectedAnnotationIds.value.length === props.linkedSources.annotations.length) {
    selectedAnnotationIds.value = []
  } else {
    selectedAnnotationIds.value = props.linkedSources.annotations.map((a) => a.task_id)
  }
  syncAnnotationSelectionState()
}

function syncAnnotationSelectionState(): void {
  form.source_mode = 'annotation'
  form.region_index = undefined
  if (selectedAnnotationIds.value.length === 1) {
    const tid = selectedAnnotationIds.value[0]!
    form.source_task_id = tid
    const found = props.linkedSources.annotations.find((a) => a.task_id === tid)
    if (found) form.task_name = `${found.task_name}_Structure`
    triggerLinkedInspect()
  } else {
    form.source_task_id = selectedAnnotationIds.value[0] || ''
  }
}

function toggleDiscoverySelection(taskId: string): void {
  const idx = selectedDiscoveryIds.value.indexOf(taskId)
  if (idx >= 0) {
    selectedDiscoveryIds.value.splice(idx, 1)
  } else {
    selectedDiscoveryIds.value.push(taskId)
  }
  syncDiscoverySelectionState()
}

function selectAllDiscoveries(): void {
  if (selectedDiscoveryIds.value.length === props.linkedSources.phage_discoveries.length) {
    selectedDiscoveryIds.value = []
  } else {
    selectedDiscoveryIds.value = props.linkedSources.phage_discoveries.map((p) => p.task_id)
  }
  syncDiscoverySelectionState()
}

function syncDiscoverySelectionState(): void {
  form.source_mode = 'phage_discovery'
  if (selectedDiscoveryIds.value.length > 1) {
    form.region_index = undefined
  }
  if (selectedDiscoveryIds.value.length === 1) {
    const tid = selectedDiscoveryIds.value[0]!
    form.source_task_id = tid
    const found = props.linkedSources.phage_discoveries.find((p) => p.task_id === tid)
    if (found) form.task_name = `${found.task_name}_Structure`
    if (!splitPhageRegions.value) {
      triggerLinkedInspect()
    }
  } else {
    form.source_task_id = selectedDiscoveryIds.value[0] || ''
  }
}

function triggerLinkedInspect(): void {
  if (!form.source_task_id) return
  emit('inspect', {
    source_mode: form.source_mode,
    source_task_id: form.source_task_id,
    region_index: form.region_index,
  })
}

function buildSharedOptions() {
  return {
    threads: form.threads > 0 ? form.threads : undefined,
    genetic_code: form.genetic_code,
    evalue_cutoff: form.evalue_cutoff,
    score_cutoff: form.score_cutoff,
    force_hmm_rescan: form.force_hmm_rescan,
    enable_phold_enhance: form.enable_phold_enhance,
    enable_phagetailfinder: form.enable_phagetailfinder,
    ptf_accurate_mode: form.ptf_accurate_mode,
  }
}

function onSubmit(): void {
  if (!canSubmit.value) return

  if (!isBatchSubmission.value) {
    emit('submit', { ...form, selected_contigs: [...form.selected_contigs] })
    return
  }

  const shared = buildSharedOptions()
  if (uiTab.value === 'upload') {
    const payload: StructureBatchRunPayload = {
      items: batchFiles.value.map((f) => ({
        task_name: f.task_name.trim() || deriveStructureTaskName(f.file_name),
        source_mode: f.source_mode,
        fasta_path: f.fasta_path,
        fasta_content: f.fasta_content,
      })),
      ...shared,
    }
    emit('submit-batch', payload)
    batchFiles.value = []
    syncSingleUploadState()
    return
  }

  if (uiTab.value === 'paste') {
    const payload: StructureBatchRunPayload = {
      items: [
        {
          task_name: form.task_name.trim() || 'Paste_Batch',
          source_mode: 'paste',
          fasta_content: form.fasta_content,
        },
      ],
      split_fasta_records: true,
      ...shared,
    }
    emit('submit-batch', payload)
    return
  }

  if (uiTab.value === 'annotation') {
    const items = selectedAnnotationIds.value.map((tid) => {
      const meta = props.linkedSources.annotations.find((a) => a.task_id === tid)
      return {
        task_name: meta ? `${meta.task_name}_Structure` : `${tid}_Structure`,
        source_mode: 'annotation' as const,
        source_task_id: tid,
      }
    })
    emit('submit-batch', { items, ...shared })
    return
  }

  if (uiTab.value === 'phage_discovery') {
    const items = selectedDiscoveryIds.value.map((tid) => {
      const meta = props.linkedSources.phage_discoveries.find((p) => p.task_id === tid)
      return {
        task_name: meta ? `${meta.task_name}_Structure` : `${tid}_Structure`,
        source_mode: 'phage_discovery' as const,
        source_task_id: tid,
        region_index: selectedDiscoveryIds.value.length === 1 && !splitPhageRegions.value ? form.region_index : undefined,
      }
    })
    emit('submit-batch', {
      items,
      split_phage_regions: splitPhageRegions.value,
      ...shared,
    })
  }
}
</script>

<template>
  <div class="setup-shell">
    <!-- 顶部状态条 -->
    <div class="engine-banner">
      <div class="eb-left">
        <h3>噬菌体尾部形态与结构定标预测</h3>
        <p>
          融合特征尾部蛋白 (TSP/MTP/TAP/TTPA-B)、Virfam 连接器、PhageTailFinder 双状态 HMM 与 TMP 分子标尺解析（支持批量导入自动排队）
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
      <div v-if="!isBatchSubmission" class="field-row">
        <label class="field-label">分析任务命名</label>
        <input v-model="form.task_name" type="text" class="text-input" placeholder="例如: Phage_T4_Morphotype" />
      </div>

      <!-- 4 源模式切换 -->
      <div class="tabs-bar">
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'upload' }" @click="switchTab('upload')">
          批量上传 / 拖拽 FASTA · GBK · FAA
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'paste' }" @click="switchTab('paste')">
          直接粘贴序列文本
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'annotation' }" @click="switchTab('annotation')">
          从历史功能注释批量导入 ({{ linkedSources.annotations.length }})
        </button>
        <button type="button" class="tab-btn" :class="{ active: uiTab === 'phage_discovery' }" @click="switchTab('phage_discovery')">
          从前噬菌体扫描区段批量导入 ({{ linkedSources.phage_discoveries.length }})
        </button>
      </div>

      <!-- Tab 1: 多文件批量上传 / 拖拽 -->
      <div v-if="uiTab === 'upload'" class="upload-wrap">
        <input
          ref="fileInputRef"
          type="file"
          multiple
          class="hidden-file"
          accept=".fasta,.fa,.fna,.faa,.gbk,.gb,.gbff,.genbank,.gz"
          @change="onBrowserFileChange"
        />

        <div
          class="drop-zone"
          :class="{ dragging: isDragging, compact: batchFiles.length > 0 }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="onDropFile"
          @click="triggerFileSelect(batchFiles.length > 0)"
        >
          <div class="drop-title">
            <template v-if="isUploading">正在上传并解析导入文件...</template>
            <template v-else-if="batchFiles.length === 1">
              已选择: {{ uploadedFileName }}（点击可继续追加更多文件自动批量排队，或直接拖入多个文件）
            </template>
            <template v-else-if="batchFiles.length > 1">
              已导入 {{ batchFiles.length }} 个基因组 / 蛋白文件（点击此处继续追加，或继续拖拽追加）
            </template>
            <template v-else>
              点击多选或一次拖入多个 FASTA / GenBank (.gbk) / 蛋白 FAA 文件到此区域
            </template>
          </div>
          <div class="drop-sub">支持单株直测与批量多文件队列导入：提交后后台按序自动执行，无需逐个等待</div>
        </div>

        <div v-if="uploadNotice" class="notice-line">{{ uploadNotice }}</div>

        <!-- 单文件追加快捷栏 -->
        <div v-if="batchFiles.length === 1" class="single-file-bar">
          <span class="sf-path" :title="batchFiles[0]?.fasta_path || batchFiles[0]?.file_name">
            {{ batchFiles[0]?.format_label }} · {{ batchFiles[0]?.file_name }}
          </span>
          <div class="sf-actions">
            <button type="button" class="mini-act" @click="triggerFileSelect(true)">+ 追加更多文件</button>
            <button type="button" class="mini-act danger" @click="clearBatchFiles">移除</button>
          </div>
        </div>

        <!-- 多文件批量待排队列表 -->
        <div v-if="batchFiles.length > 1" class="batch-list-box">
          <div class="batch-list-head">
            <span>待自动排队任务清单 ({{ batchFiles.length }} 个样本将依次入队分析)</span>
            <div class="bl-actions">
              <button type="button" class="mini-act" @click="triggerFileSelect(true)">+ 继续追加文件</button>
              <button type="button" class="mini-act danger" @click="clearBatchFiles">清空列表</button>
            </div>
          </div>
          <div class="batch-rows">
            <div v-for="(entry, idx) in batchFiles" :key="entry.id" class="batch-row">
              <span class="br-idx">#{{ idx + 1 }}</span>
              <span class="br-fmt">{{ entry.format_label }}</span>
              <input
                v-model="entry.task_name"
                type="text"
                class="br-name-inp"
                placeholder="自定义任务名"
              />
              <span class="br-file" :title="entry.fasta_path || entry.file_name">{{ entry.file_name }}</span>
              <button type="button" class="br-del" title="从批次中移除" @click="removeBatchFile(entry.id)">移除</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 2: 粘贴文本 -->
      <div v-else-if="uiTab === 'paste'" class="paste-box">
        <textarea
          v-model="form.fasta_content"
          rows="7"
          class="paste-area"
          placeholder="在此粘贴单条/多条 FASTA 核酸、蛋白 FAA 或 GenBank (LOCUS ...) 文本..."
        ></textarea>
        <label v-if="canSplitPastedFasta" class="split-banner">
          <input v-model="splitFastaRecords" type="checkbox" />
          <span>
            检测到 <strong>{{ pastedRecordCount }}</strong> 条独立 FASTA 序列，勾选后按每条序列自动拆分为 {{ pastedRecordCount }} 个独立排队任务
          </span>
        </label>
      </div>

      <!-- Tab 3: 功能注释批量多选导入 -->
      <div v-else-if="uiTab === 'annotation'" class="linked-box">
        <div v-if="isSourcesLoading" class="empty-src">正在读取历史注释任务...</div>
        <div v-else-if="linkedSources.annotations.length === 0" class="empty-src">暂无已完成的全基因组注释任务</div>
        <template v-else>
          <div class="linked-toolbar">
            <span>可多选勾选多个注释样本一键加入排队队列（已选 {{ selectedAnnotationIds.length }} / {{ linkedSources.annotations.length }}）</span>
            <button type="button" class="mini-act" @click="selectAllAnnotations">
              {{ selectedAnnotationIds.length === linkedSources.annotations.length ? '取消全选' : '全选全部' }}
            </button>
          </div>
          <div class="src-grid">
            <div
              v-for="a in linkedSources.annotations"
              :key="a.task_id"
              class="src-item"
              :class="{ active: selectedAnnotationIds.includes(a.task_id) }"
              @click="toggleAnnotationSelection(a.task_id)"
            >
              <div class="src-head">
                <span class="src-name">{{ a.task_name }}</span>
                <span class="chk-badge" :class="{ checked: selectedAnnotationIds.includes(a.task_id) }">
                  {{ selectedAnnotationIds.includes(a.task_id) ? '已选' : '选择' }}
                </span>
              </div>
              <div class="src-meta">{{ a.sample_type }} · {{ a.cds_count }} CDS · {{ formatGenomeBp(a.total_length) }}</div>
            </div>
          </div>
        </template>
      </div>

      <!-- Tab 4: 前噬菌体扫描区段批量导入与自动拆分 -->
      <div v-else class="linked-box">
        <div v-if="isSourcesLoading" class="empty-src">正在读取前噬菌体扫描任务...</div>
        <div v-else-if="linkedSources.phage_discoveries.length === 0" class="empty-src">暂无已检出前噬菌体区段的扫描任务</div>
        <template v-else>
          <div class="linked-toolbar">
            <span>支持多选前噬菌体扫描任务批量入队（已选 {{ selectedDiscoveryIds.length }} / {{ linkedSources.phage_discoveries.length }}）</span>
            <button type="button" class="mini-act" @click="selectAllDiscoveries">
              {{ selectedDiscoveryIds.length === linkedSources.phage_discoveries.length ? '取消全选' : '全选全部' }}
            </button>
          </div>
          <div class="src-grid">
            <div
              v-for="p in linkedSources.phage_discoveries"
              :key="p.task_id"
              class="src-item"
              :class="{ active: selectedDiscoveryIds.includes(p.task_id) }"
              @click="toggleDiscoverySelection(p.task_id)"
            >
              <div class="src-head">
                <span class="src-name">{{ p.task_name }}</span>
                <span class="chk-badge" :class="{ checked: selectedDiscoveryIds.includes(p.task_id) }">
                  {{ selectedDiscoveryIds.includes(p.task_id) ? '已选' : '选择' }}
                </span>
              </div>
              <div class="src-meta">检出 {{ p.region_count }} 区段 · {{ formatGenomeBp(p.total_prophage_bp) }}</div>
            </div>
          </div>
          <div v-if="selectedDiscoveryIds.length > 0" class="discovery-opts">
            <label v-if="selectedDiscoveryTotalRegions > 1 && !(selectedDiscoveryIds.length === 1 && form.region_index)" class="split-banner">
              <input v-model="splitPhageRegions" type="checkbox" />
              <span>
                按检出区段自动拆分为 <strong>{{ selectedDiscoveryTotalRegions }}</strong> 个独立排队任务逐一预测尾型
              </span>
            </label>
            <div v-if="selectedDiscoveryIds.length === 1 && !splitPhageRegions" class="region-opt">
              <label>或指定单一区段序号（留空评估全部区段）：</label>
              <input v-model.number="form.region_index" type="number" min="1" class="num-input" placeholder="全部" @change="triggerLinkedInspect" />
            </div>
          </div>
        </template>
      </div>

      <!-- 单样本 Contig 预检选择 (仅非批量模式展示) -->
      <div v-if="!isBatchSubmission && inspectedContigs.length > 0" class="contig-box">
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
          {{ showAdvanced ? '收起高级判定参数（全批共用）' : '展开高级并行与阈值参数（全批共用）' }}
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
        <span v-if="isBatchSubmission" class="queue-hint batch">
          已就绪 {{ plannedTaskCount }} 个待排队任务，提交后后台串行队列将自动依次分析完成。
        </span>
        <span v-else-if="isQueueBusy" class="queue-hint">当前存在运行中任务，提交后将自动进入安全等待队列。</span>
        <span v-else class="queue-hint">支持单样本提交或批量多文件导入，结构 HMM 索引已浓缩加速。</span>
        <button type="button" class="submit-btn" :disabled="!canSubmit" @click="onSubmit">
          <template v-if="isSubmitting">正在提交排队队列...</template>
          <template v-else-if="isUploading">正在上传文件...</template>
          <template v-else-if="!isBatchSubmission && isInspecting">正在预检输入...</template>
          <template v-else-if="isBatchSubmission">批量加入排队队列 ({{ plannedTaskCount }} 个任务)</template>
          <template v-else>开始结构与形态预测</template>
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

.upload-wrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 28px 20px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.16s;
}

.drop-zone.compact {
  padding: 18px 16px;
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

.notice-line {
  font-size: 0.78rem;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 6px 10px;
}

.single-file-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 9px;
}

.sf-path {
  font-size: 0.82rem;
  font-weight: 600;
  color: #1e40af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sf-actions,
.bl-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.mini-act {
  padding: 4px 10px;
  border-radius: 7px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #2563eb;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}

.mini-act.danger {
  color: #dc2626;
  border-color: #fecaca;
}

.batch-list-box {
  border: 1px solid #dbeafe;
  background: #f8fafc;
  border-radius: 11px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.batch-list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 0.83rem;
  font-weight: 700;
  color: #1e293b;
  flex-wrap: wrap;
}

.batch-rows {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 250px;
  overflow-y: auto;
}

.batch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 6px 10px;
}

.br-idx {
  font-family: ui-monospace, monospace;
  font-size: 0.76rem;
  font-weight: 700;
  color: #2563eb;
  min-width: 24px;
}

.br-fmt {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  flex-shrink: 0;
}

.br-name-inp {
  flex: 1.1;
  min-width: 140px;
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.81rem;
  color: #0f172a;
}

.br-file {
  flex: 1;
  font-size: 0.77rem;
  color: #64748b;
  font-family: ui-monospace, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.br-del {
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #fecaca;
  background: #fff1f2;
  color: #dc2626;
  font-size: 0.74rem;
  font-weight: 600;
  flex-shrink: 0;
}

.paste-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
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

.split-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 9px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  font-size: 0.82rem;
  cursor: pointer;
}

.linked-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.linked-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 0.8rem;
  color: #475569;
  font-weight: 600;
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

.src-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}

.src-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chk-badge {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  flex-shrink: 0;
}

.chk-badge.checked {
  background: #2563eb;
  color: #ffffff;
}

.src-meta {
  margin-top: 3px;
  font-size: 0.76rem;
  color: #64748b;
}

.discovery-opts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.region-opt {
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
  flex-wrap: wrap;
}

.queue-hint {
  font-size: 0.8rem;
  color: #64748b;
}

.queue-hint.batch {
  color: #1d4ed8;
  font-weight: 600;
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
