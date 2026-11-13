import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getBridge, onEvent } from '../../../../../bridge/electron-bridge'
import type {
  PhageCapabilities,
  PhageContigInspectItem,
  PhageContigOverlayData,
  PhageLogItem,
  PhageQueueSnapshot,
  PhageScanForm,
  PhageScanResultPayload,
  PhageTaskRecord,
} from '../types'

function formatNowTime(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

export function usePhageDiscovery() {
  const bridge = getBridge()

  const capabilities = ref<PhageCapabilities | null>(null)
  const historyList = ref<PhageTaskRecord[]>([])
  const currentTask = ref<PhageTaskRecord | null>(null)
  const currentResult = ref<PhageScanResultPayload | null>(null)
  const queueStatus = ref<PhageQueueSnapshot>({
    max_workers: 1,
    running: [],
    queued: [],
    running_count: 0,
    queued_count: 0,
  })

  const consoleLogs = ref<PhageLogItem[]>([])
  const errorMsg = ref<string>('')
  const isCapabilitiesLoading = ref<boolean>(false)
  const isSubmitting = ref<boolean>(false)
  const isResultLoading = ref<boolean>(false)
  const isInspecting = ref<boolean>(false)

  const inspectedContigs = ref<PhageContigInspectItem[]>([])
  const inspectTotalBp = ref<number>(0)
  const selectedContigIds = ref<string[]>([])

  const isQueued = computed(() => {
    return currentTask.value?.status === 'queued'
  })

  const isRunning = computed(() => {
    return currentTask.value?.status === 'running'
  })

  const isQueueBusy = computed(() => {
    return (
      Boolean(queueStatus.value.is_busy) ||
      queueStatus.value.running_count > 0 ||
      queueStatus.value.queued_count > 0 ||
      historyList.value.some((t) => t.status === 'running' || t.status === 'queued')
    )
  })

  let unsubscribeWs: (() => void) | null = null
  let pollingTimer: ReturnType<typeof setInterval> | null = null

  function syncQueueSnapshot(snap: PhageQueueSnapshot): void {
    queueStatus.value = snap
    const runningSet = new Set(snap.running || [])
    const waitingPosMap = new Map<string, number>()

    if (Array.isArray(snap.waiting_tasks) && snap.waiting_tasks.length > 0) {
      snap.waiting_tasks.forEach((w, idx) => {
        waitingPosMap.set(w.task_id, typeof w.position === 'number' ? w.position : idx + 1)
      })
    } else {
      ;(snap.queued || []).forEach((tid, idx) => {
        waitingPosMap.set(tid, idx + 1)
      })
    }

    const activeSnapshotIds = [...runningSet, ...waitingPosMap.keys()]
    if (activeSnapshotIds.some((id) => !historyList.value.some((t) => t.task_id === id))) {
      loadHistory()
    }

    historyList.value.forEach((item) => {
      if (runningSet.has(item.task_id)) {
        if (item.status !== 'completed' && item.status !== 'failed' && item.status !== 'cancelled') {
          item.status = 'running'
          delete item.queue_position
        }
      } else if (waitingPosMap.has(item.task_id)) {
        const pos = waitingPosMap.get(item.task_id) || 1
        item.status = 'queued'
        item.queue_position = pos
        item.current_step = `排队等待中 (#${pos})`
      }
    })

    if (currentTask.value) {
      const curId = currentTask.value.task_id
      if (runningSet.has(curId)) {
        if (
          currentTask.value.status !== 'completed' &&
          currentTask.value.status !== 'failed' &&
          currentTask.value.status !== 'cancelled'
        ) {
          currentTask.value.status = 'running'
          delete currentTask.value.queue_position
        }
      } else if (waitingPosMap.has(curId)) {
        const pos = waitingPosMap.get(curId) || 1
        currentTask.value.status = 'queued'
        currentTask.value.queue_position = pos
        currentTask.value.current_step = `排队等待中 (#${pos})`
      }
    }
  }

  async function loadCapabilities(): Promise<void> {
    isCapabilitiesLoading.value = true
    try {
      const caps: PhageCapabilities = await bridge.get_phage_discovery_models()
      capabilities.value = caps
    } catch (err) {
      console.error('[PhageDiscovery] 探测 V4.2 模型能力失败:', err)
    } finally {
      isCapabilitiesLoading.value = false
    }
  }

  async function loadQueueStatus(): Promise<void> {
    try {
      const snap: PhageQueueSnapshot = await bridge.get_phage_discovery_queue_status()
      if (snap) syncQueueSnapshot(snap)
    } catch (err) {
      console.error('[PhageDiscovery] 拉取队列状态失败:', err)
    }
  }

  async function loadHistory(): Promise<void> {
    try {
      const res = await bridge.get_phage_discovery_history(100)
      historyList.value = Array.isArray(res?.tasks) ? res.tasks : []
      const waitingPosMap = new Map<string, number>()
      ;(queueStatus.value.queued || []).forEach((tid, idx) => waitingPosMap.set(tid, idx + 1))
      const runningSet = new Set(queueStatus.value.running || [])

      historyList.value.forEach((item) => {
        if (runningSet.has(item.task_id) && item.status === 'queued') {
          item.status = 'running'
        } else if (waitingPosMap.has(item.task_id) && item.status === 'queued') {
          item.queue_position = waitingPosMap.get(item.task_id)
        }
      })

      if (currentTask.value) {
        const refreshed = historyList.value.find((t) => t.task_id === currentTask.value?.task_id)
        if (refreshed) {
          currentTask.value = { ...currentTask.value, ...refreshed }
        }
      }
    } catch (err) {
      console.error('[PhageDiscovery] 加载历史记录失败:', err)
    }
  }

  async function loadTaskResult(taskId: string): Promise<void> {
    isResultLoading.value = true
    try {
      const res = await bridge.get_phage_discovery_result(taskId)
      if (res?.task) {
        currentTask.value = res.task
      }
      currentResult.value = res?.result?.summary ? res.result : null
    } catch (err) {
      errorMsg.value = `读取扫描结果失败: ${String(err)}`
    } finally {
      isResultLoading.value = false
    }
  }

  async function selectTask(task: PhageTaskRecord): Promise<void> {
    errorMsg.value = ''
    const isSwitching = currentTask.value?.task_id !== task.task_id
    if (isSwitching) {
      consoleLogs.value = []
    }
    currentTask.value = { ...task }
    currentResult.value = null
    await loadQueueStatus()
    if (task.status === 'completed') {
      await loadTaskResult(task.task_id)
    }
  }

  function startNewTask(): void {
    errorMsg.value = ''
    currentTask.value = null
    currentResult.value = null
    consoleLogs.value = []
  }

  async function inspectInput(payload: { fasta_path?: string; fasta_content?: string }): Promise<boolean> {
    if (!payload.fasta_path && !payload.fasta_content?.trim()) {
      inspectedContigs.value = []
      inspectTotalBp.value = 0
      selectedContigIds.value = []
      return false
    }
    isInspecting.value = true
    errorMsg.value = ''
    try {
      const res = await bridge.inspect_phage_discovery_fasta(payload)
      const list: PhageContigInspectItem[] = Array.isArray(res?.contigs) ? res.contigs : []
      inspectedContigs.value = list
      inspectTotalBp.value = Number(res?.total_bp || 0)
      selectedContigIds.value = list.map((c) => c.id)
      return true
    } catch (err) {
      inspectedContigs.value = []
      inspectTotalBp.value = 0
      selectedContigIds.value = []
      errorMsg.value = `序列预检失败: ${String(err)}`
      return false
    } finally {
      isInspecting.value = false
    }
  }

  async function saveCustomConfig(payload: {
    default_model_dir?: string
    models_root?: string
    blast_db?: string
  }): Promise<boolean> {
    errorMsg.value = ''
    try {
      const res = await bridge.save_phage_discovery_config(payload)
      if (res?.capabilities) {
        capabilities.value = res.capabilities
      } else {
        await loadCapabilities()
      }
      return true
    } catch (err) {
      errorMsg.value = `保存路径配置失败: ${String(err)}`
      return false
    }
  }

  async function submitTask(form: PhageScanForm): Promise<void> {
    errorMsg.value = ''
    isSubmitting.value = true
    consoleLogs.value = []
    try {
      const payload = {
        task_name: form.task_name.trim() || 'PhageDiscovery_Task',
        fasta_path: form.fasta_path || null,
        fasta_content: form.fasta_content?.trim() ? form.fasta_content : null,
        selected_contigs:
          form.selected_contigs.length > 0 && form.selected_contigs.length < inspectedContigs.value.length
            ? form.selected_contigs
            : null,
        model_id: 'student_v4_2',
        custom_model_dir: form.custom_model_dir.trim() || null,
        device: form.device,
        workers: form.workers > 0 ? form.workers : null,
        apply_protein_gate: form.apply_protein_gate,
        blast_db: form.blast_db.trim() || null,
        seed_threshold: form.seed_threshold,
        extend_threshold: form.extend_threshold,
        sub_threshold: form.sub_threshold,
        merge_gap_bp: form.merge_gap_bp,
        min_region_bp: form.min_region_bp,
      }
      const res = await bridge.run_phage_discovery_task(payload)
      const taskId: string = res?.task_id
      if (taskId) {
        const queuePos = Number(res?.queue_position || 1)
        const busy = Boolean(res?.is_busy || isQueueBusy.value || queuePos > 1)
        const placeholder: PhageTaskRecord = {
          task_id: taskId,
          task_name: payload.task_name,
          model_id: res?.model?.model_id || 'student_v4_2',
          model_version: 'V4.2',
          device: res?.device || form.device,
          apply_protein_gate: form.apply_protein_gate,
          status: 'queued',
          progress: 0,
          queue_position: queuePos,
          current_step: busy ? `排队等待中 (#${queuePos})` : '已加入 V4.2 调度队列...',
          created_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
          updated_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
          summary: {},
          files: {},
          result_path: '',
        }
        historyList.value = [placeholder, ...historyList.value.filter((t) => t.task_id !== taskId)]
        currentTask.value = placeholder
        currentResult.value = null
        consoleLogs.value.push({
          time: formatNowTime(),
          line: `[QUEUE] 已提交扫描任务 ${taskId} (位次: #${queuePos}, 设备: ${placeholder.device})`,
          level: 'info',
        })
        await Promise.all([loadHistory(), loadQueueStatus()])
      }
    } catch (err) {
      errorMsg.value = `提交扫描任务失败: ${String(err)}`
    } finally {
      isSubmitting.value = false
    }
  }

  async function cancelTask(taskId: string): Promise<void> {
    try {
      const res = await bridge.cancel_phage_discovery_task(taskId)
      if (res?.status === 'cancelled') {
        if (currentTask.value?.task_id === taskId) {
          currentTask.value.status = 'cancelled'
          currentTask.value.current_step = '任务已取消'
        }
        const matched = historyList.value.find((t) => t.task_id === taskId)
        if (matched) {
          matched.status = 'cancelled'
          matched.current_step = '任务已取消'
        }
      }
      await Promise.all([loadHistory(), loadQueueStatus()])
    } catch (err) {
      errorMsg.value = `取消任务失败: ${String(err)}`
    }
  }

  async function deleteTask(taskId: string): Promise<void> {
    try {
      await bridge.delete_phage_discovery_task(taskId)
      if (currentTask.value?.task_id === taskId) {
        startNewTask()
      }
      await loadHistory()
    } catch (err) {
      errorMsg.value = `删除任务失败: ${String(err)}`
    }
  }

  function downloadFile(taskId: string, fileType: 'fasta' | 'tsv' | 'gff3' | 'gbk'): void {
    const url = bridge.get_phage_discovery_download_url(taskId, fileType)
    window.open(url, '_blank')
  }

  async function openResultsFolder(taskId: string): Promise<void> {
    try {
      await bridge.open_phage_discovery_folder(taskId)
    } catch (err) {
      errorMsg.value = `打开输出目录失败: ${String(err)}`
    }
  }

  async function fetchRegionGbk(taskId: string, regionIndex: number): Promise<{ gbkText: string; taskName: string }> {
    const res = await bridge.get_phage_discovery_region_gbk(taskId, regionIndex)
    const reg = res?.region
    const taskName = reg ? `${reg.region_id} (${reg.contig_id}:${reg.start_1based}-${reg.end_1based})` : taskId
    return {
      gbkText: String(res?.gbk_text || ''),
      taskName,
    }
  }

  async function fetchContigOverlay(taskId: string, contigId?: string): Promise<PhageContigOverlayData> {
    const res = await bridge.get_phage_discovery_overlay(taskId, contigId)
    return res as PhageContigOverlayData
  }

  async function fetchContigOverlayGbk(
    taskId: string,
    contigId?: string
  ): Promise<{ gbkText: string; taskName: string }> {
    const res = await bridge.get_phage_discovery_overlay_gbk(taskId, contigId)
    const cid = String(res?.contig_id || contigId || 'Contig')
    const regionCnt = Number(res?.region_count || 0)
    return {
      gbkText: String(res?.gbk_text || ''),
      taskName: `${cid} 全基因组叠图 (${regionCnt} Prophage)`,
    }
  }

  async function fetchFastaForAnnotation(
    taskId: string,
    regionIndex?: number
  ): Promise<{ fastaText: string; taskName: string }> {
    const res = await bridge.get_phage_discovery_fasta_text(taskId, regionIndex)
    return {
      fastaText: String(res?.fasta_text || ''),
      taskName: String(res?.label || taskId),
    }
  }

  function handleWsEvent(eventType: string, data: any): void {
    if (eventType === 'phage_discovery_queue_update' && data) {
      syncQueueSnapshot(data as PhageQueueSnapshot)
      return
    }
    if (!data || !data.task_id) return

    const activeId = currentTask.value?.task_id
    if (eventType === 'phage_discovery_progress') {
      const targetInHist = historyList.value.find((t) => t.task_id === data.task_id)
      if (targetInHist) {
        if (typeof data.progress === 'number' && data.progress >= 0) targetInHist.progress = data.progress
        if (data.message) targetInHist.current_step = data.message
        if (data.status) targetInHist.status = data.status
      }
      if (activeId === data.task_id && currentTask.value) {
        if (typeof data.progress === 'number' && data.progress >= 0) {
          currentTask.value.progress = data.progress
        }
        if (data.message) currentTask.value.current_step = data.message
        if (data.status) currentTask.value.status = data.status
      }
    } else if (eventType === 'phage_discovery_log') {
      if (activeId === data.task_id) {
        consoleLogs.value.push({
          time: formatNowTime(),
          line: String(data.line || ''),
          level: String(data.level || 'info'),
        })
        if (consoleLogs.value.length > 300) {
          consoleLogs.value.splice(0, consoleLogs.value.length - 300)
        }
      }
    } else if (eventType === 'phage_discovery_done') {
      loadHistory()
      loadQueueStatus()
      if (activeId === data.task_id) {
        loadTaskResult(data.task_id)
      }
    } else if (eventType === 'phage_discovery_error') {
      loadHistory()
      loadQueueStatus()
      if (activeId === data.task_id && currentTask.value) {
        currentTask.value.status = data.status || 'failed'
        currentTask.value.error_msg = String(data.error || '扫描任务执行异常')
        currentTask.value.current_step =
          currentTask.value.status === 'cancelled' ? '任务已中止' : '扫描失败'
      }
    }
  }

  onMounted(async () => {
    unsubscribeWs = onEvent(handleWsEvent)
    await Promise.all([loadCapabilities(), loadHistory(), loadQueueStatus()])
    pollingTimer = setInterval(() => {
      if (isQueueBusy.value || isQueued.value || isRunning.value) {
        loadQueueStatus()
        loadHistory()
      }
    }, 2500)
  })

  onUnmounted(() => {
    if (unsubscribeWs) {
      unsubscribeWs()
      unsubscribeWs = null
    }
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
  })

  return {
    capabilities,
    historyList,
    currentTask,
    currentResult,
    queueStatus,
    consoleLogs,
    errorMsg,
    isCapabilitiesLoading,
    isSubmitting,
    isResultLoading,
    isInspecting,
    isQueued,
    isRunning,
    isQueueBusy,
    inspectedContigs,
    inspectTotalBp,
    selectedContigIds,
    loadCapabilities,
    loadHistory,
    inspectInput,
    saveCustomConfig,
    submitTask,
    selectTask,
    startNewTask,
    cancelTask,
    deleteTask,
    downloadFile,
    openResultsFolder,
    fetchRegionGbk,
    fetchContigOverlay,
    fetchContigOverlayGbk,
    fetchFastaForAnnotation,
  }
}

