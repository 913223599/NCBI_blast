import { computed, reactive, ref, watch } from 'vue'
import { getBridge } from '../../../../../bridge/electron-bridge'
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
} from '../utils'

export interface StructureSetupProps {
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
}

export interface StructureInspectPayload {
  source_mode: StructureSourceMode
  fasta_path?: string
  fasta_content?: string
  source_task_id?: string
  region_index?: number
}

export interface StructureSetupEmits {
  (e: 'submit', form: StructureRunForm): void
  (e: 'submit-batch', payload: StructureBatchRunPayload): void
  (e: 'inspect', payload: StructureInspectPayload): void
  (e: 'refresh-sources'): void
}

const ALLOWED_EXT_RE = /\.(fasta|fa|fna|faa|gbk|gb|gbff|genbank)(\.gz)?$/i

export function useStructureSetup(props: StructureSetupProps, emit: StructureSetupEmits) {
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
    phold_trigger_mode: 'auto',
    enable_phagetailfinder: true,
    ptf_accurate_mode: false,
    enable_ai_classifier: true,
  })

  function triggerLinkedInspect(): void {
    if (!form.source_task_id) return
    emit('inspect', {
      source_mode: form.source_mode,
      source_task_id: form.source_task_id,
      region_index: form.region_index,
    })
  }

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

  function addPathsToQueue(paths: string[], append: boolean): void {
    const cleanPaths = paths.map((p) => (p || '').trim()).filter(Boolean)
    if (!cleanPaths.length) return
    mergeEntriesToBatch(cleanPaths.map((p) => buildEntryFromPath(p)), append)
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
      uploadNotice.value = `已跳过 ${skippedCount} 个非序列文件`
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
          const uploadedPath =
            typeof res?.path === 'string'
              ? res.path
              : typeof res?.file_path === 'string'
                ? res.file_path
                : ''
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
      handleFilesUpload(files, batchFiles.value.length > 0)
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

  function toggleAnnotationSelection(taskId: string): void {
    const idx = selectedAnnotationIds.value.indexOf(taskId)
    if (idx >= 0) selectedAnnotationIds.value.splice(idx, 1)
    else selectedAnnotationIds.value.push(taskId)
    syncAnnotationSelectionState()
  }

  function selectAllAnnotations(): void {
    selectedAnnotationIds.value =
      selectedAnnotationIds.value.length === props.linkedSources.annotations.length
        ? []
        : props.linkedSources.annotations.map((a) => a.task_id)
    syncAnnotationSelectionState()
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

  function toggleDiscoverySelection(taskId: string): void {
    const idx = selectedDiscoveryIds.value.indexOf(taskId)
    if (idx >= 0) selectedDiscoveryIds.value.splice(idx, 1)
    else selectedDiscoveryIds.value.push(taskId)
    syncDiscoverySelectionState()
  }

  function selectAllDiscoveries(): void {
    selectedDiscoveryIds.value =
      selectedDiscoveryIds.value.length === props.linkedSources.phage_discoveries.length
        ? []
        : props.linkedSources.phage_discoveries.map((p) => p.task_id)
    syncDiscoverySelectionState()
  }

  function buildSharedOptions() {
    return {
      threads: form.threads > 0 ? form.threads : undefined,
      genetic_code: form.genetic_code,
      evalue_cutoff: form.evalue_cutoff,
      score_cutoff: form.score_cutoff,
      force_hmm_rescan: form.force_hmm_rescan,
      enable_phold_enhance: form.enable_phold_enhance,
      phold_trigger_mode: form.phold_trigger_mode,
      enable_phagetailfinder: form.enable_phagetailfinder,
      ptf_accurate_mode: form.ptf_accurate_mode,
      enable_ai_classifier: form.enable_ai_classifier,
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
      emit('submit-batch', {
        items: [
          {
            task_name: form.task_name.trim() || 'Paste_Batch',
            source_mode: 'paste',
            fasta_content: form.fasta_content,
          },
        ],
        split_fasta_records: true,
        ...shared,
      })
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
      emit('submit-batch', { items, split_phage_regions: splitPhageRegions.value, ...shared })
    }
  }

  return {
    uiTab,
    uploadedFileName,
    isUploading,
    isDragging,
    showAdvanced,
    fileInputRef,
    uploadNotice,
    batchFiles,
    selectedAnnotationIds,
    selectedDiscoveryIds,
    splitPhageRegions,
    splitFastaRecords,
    form,
    overallGcPercent,
    selectorContigs,
    pastedRecordCount,
    canSplitPastedFasta,
    selectedDiscoveryTotalRegions,
    isBatchSubmission,
    plannedTaskCount,
    canSubmit,
    switchTab,
    triggerFileSelect,
    removeBatchFile,
    clearBatchFiles,
    onBrowserFileChange,
    onDropFile,
    toggleAnnotationSelection,
    selectAllAnnotations,
    toggleDiscoverySelection,
    selectAllDiscoveries,
    triggerLinkedInspect,
    onSubmit,
  }
}
