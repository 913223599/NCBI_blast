import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getBridge, onEvent } from '../../../../../bridge/electron-bridge'
import { notifyUser } from '../../../../../utils/notify'
import { createLogger } from '../../../../../utils/logger'
import type {
  PhageStructureResult,
  StructureBatchRunPayload,
  StructureCapabilities,
  StructureInspectContig,
  StructureLinkedSources,
  StructureQueueSnapshot,
  StructureRunForm,
  StructureSourceMode,
  StructureTaskHistoryItem,
} from '../types'

const log = createLogger('PhageStructure')

export interface StructureLogLine {
  time: string
  line: string
}

function nowTimeStr(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function usePhageStructure() {
  const bridge = getBridge()

  const capabilities = ref<StructureCapabilities | null>(null)
  const linkedSources = ref<StructureLinkedSources>({ annotations: [], phage_discoveries: [] })
  const historyList = ref<StructureTaskHistoryItem[]>([])
  const currentTask = ref<StructureTaskHistoryItem | null>(null)
  const currentResult = ref<PhageStructureResult | null>(null)
  const queueStatus = ref<StructureQueueSnapshot>({
    max_workers: 1,
    is_busy: false,
    running: [],
    queued: [],
    running_count: 0,
    queued_count: 0,
  })

  const consoleLogs = ref<StructureLogLine[]>([])
  const errorMsg = ref<string>('')
  const isCapabilitiesLoading = ref<boolean>(false)
  const isSourcesLoading = ref<boolean>(false)
  const isInspecting = ref<boolean>(false)
  const isSubmitting = ref<boolean>(false)
  const isResultLoading = ref<boolean>(false)

  const inspectedContigs = ref<StructureInspectContig[]>([])
  const inspectTotalBp = ref<number>(0)

  const isQueued = computed(() => currentTask.value?.status === 'queued')
  const isRunning = computed(() => currentTask.value?.status === 'running')
  const isQueueBusy = computed(
    () =>
      Boolean(queueStatus.value.is_busy) ||
      queueStatus.value.running_count > 0 ||
      queueStatus.value.queued_count > 0 ||
      historyList.value.some((t) => t.status === 'running' || t.status === 'queued')
  )

  let unsubscribeWs: (() => void) | null = null
  let pollingTimer: ReturnType<typeof setInterval> | null = null

  function appendLog(line: string): void {
    if (!line) return
    const last = consoleLogs.value[consoleLogs.value.length - 1]
    if (last && last.line === line) return
    consoleLogs.value.push({ time: nowTimeStr(), line })
    if (consoleLogs.value.length > 200) {
      consoleLogs.value.splice(0, consoleLogs.value.length - 200)
    }
  }

  function syncQueueSnapshot(snap: StructureQueueSnapshot): void {
    queueStatus.value = snap
    const runningSet = new Set(snap.running || [])
    const waitingPosMap = new Map<string, number>()

    if (Array.isArray(snap.waiting_tasks) && snap.waiting_tasks.length > 0) {
      snap.waiting_tasks.forEach((w, idx) => {
        waitingPosMap.set(w.task_id, typeof w.position === 'number' ? w.position : idx + 1)
      })
    } else {
      ;(snap.queued || []).forEach((tid, idx) => waitingPosMap.set(tid, idx + 1))
    }

    historyList.value.forEach((item) => {
      if (runningSet.has(item.task_id)) {
        if (!['completed', 'failed', 'cancelled'].includes(item.status)) {
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
      const cid = currentTask.value.task_id
      if (runningSet.has(cid) && !['completed', 'failed', 'cancelled'].includes(currentTask.value.status)) {
        currentTask.value.status = 'running'
        delete currentTask.value.queue_position
      } else if (waitingPosMap.has(cid)) {
        const pos = waitingPosMap.get(cid) || 1
        currentTask.value.status = 'queued'
        currentTask.value.queue_position = pos
        currentTask.value.current_step = `排队等待中 (#${pos})`
      }
    }
  }

  async function loadCapabilities(): Promise<void> {
    isCapabilitiesLoading.value = true
    try {
      capabilities.value = await bridge.get_phage_structure_capabilities()
    } catch (err) {
      log.warn('读取引擎状态失败:', err)
    } finally {
      isCapabilitiesLoading.value = false
    }
  }

  async function loadLinkedSources(): Promise<void> {
    isSourcesLoading.value = true
    try {
      const res = await bridge.get_phage_structure_sources()
      linkedSources.value = {
        annotations: Array.isArray(res?.annotations) ? res.annotations : [],
        phage_discoveries: Array.isArray(res?.phage_discoveries) ? res.phage_discoveries : [],
      }
    } catch (err) {
      log.warn('读取联动数据源失败:', err)
    } finally {
      isSourcesLoading.value = false
    }
  }

  async function loadQueueStatus(): Promise<void> {
    try {
      const snap = await bridge.get_phage_structure_queue_status()
      if (snap) syncQueueSnapshot(snap)
    } catch (err) {
      log.warn('拉取队列状态失败:', err)
    }
  }

  async function loadHistory(): Promise<void> {
    try {
      const res = await bridge.get_phage_structure_history(100)
      historyList.value = Array.isArray(res?.tasks) ? res.tasks : []
      syncQueueSnapshot(queueStatus.value)
      if (currentTask.value) {
        const fresh = historyList.value.find((t) => t.task_id === currentTask.value?.task_id)
        if (fresh) {
          currentTask.value = { ...currentTask.value, ...fresh }
        }
      }
    } catch (err) {
      log.warn('加载历史列表失败:', err)
    }
  }

  async function loadTaskResult(taskId: string): Promise<void> {
    isResultLoading.value = true
    try {
      const res = (await bridge.get_phage_structure_result(taskId)) as PhageStructureResult
      currentResult.value = res
      if (currentTask.value?.task_id === taskId) {
        currentTask.value.status = 'completed'
        currentTask.value.progress = 100
        currentTask.value.summary = res.summary
      }
    } catch (err) {
      errorMsg.value = `加载结构预测结果失败: ${String(err)}`
    } finally {
      isResultLoading.value = false
    }
  }

  async function inspectInput(payload: {
    source_mode: StructureSourceMode
    fasta_path?: string
    fasta_content?: string
    source_task_id?: string
    region_index?: number
  }): Promise<void> {
    isInspecting.value = true
    errorMsg.value = ''
    try {
      const res = await bridge.inspect_phage_structure_input(payload)
      inspectedContigs.value = Array.isArray(res?.contigs) ? res.contigs : []
      inspectTotalBp.value = Number(res?.total_length || 0)
    } catch (err) {
      inspectedContigs.value = []
      inspectTotalBp.value = 0
      errorMsg.value = `输入预检失败: ${String(err)}`
    } finally {
      isInspecting.value = false
    }
  }

  async function submitTask(form: StructureRunForm): Promise<void> {
    isSubmitting.value = true
    errorMsg.value = ''
    consoleLogs.value = []
    try {
      const payload = {
        task_name: form.task_name,
        source_mode: form.source_mode,
        fasta_path: form.fasta_path || undefined,
        fasta_content: form.fasta_content || undefined,
        source_task_id: form.source_task_id || undefined,
        region_index: form.region_index || undefined,
        selected_contigs: form.selected_contigs.length > 0 ? form.selected_contigs : undefined,
        threads: form.threads > 0 ? form.threads : undefined,
        genetic_code: form.genetic_code,
        evalue_cutoff: form.evalue_cutoff,
        score_cutoff: form.score_cutoff,
        force_hmm_rescan: form.force_hmm_rescan,
        enable_phold_enhance: form.enable_phold_enhance,
        enable_phagetailfinder: form.enable_phagetailfinder,
        ptf_accurate_mode: form.ptf_accurate_mode,
      }
      const res = await bridge.run_phage_structure_task(payload)
      const created: StructureTaskHistoryItem = {
        task_id: res.task_id,
        task_name: res.task_name || form.task_name,
        source_mode: form.source_mode,
        status: res.is_busy ? 'queued' : 'running',
        progress: 0,
        queue_position: res.queue_position,
        current_step: res.is_busy ? `排队等待中 (#${res.queue_position})` : '正在初始化结构与尾部预测流程...',
        created_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
      }
      currentTask.value = created
      currentResult.value = null
      appendLog(created.current_step || '已提交结构预测任务')
      await Promise.all([loadHistory(), loadQueueStatus()])
    } catch (err) {
      errorMsg.value = `提交预测任务失败: ${String(err)}`
    } finally {
      isSubmitting.value = false
    }
  }

  async function submitBatchTasks(batchPayload: StructureBatchRunPayload): Promise<void> {
    isSubmitting.value = true
    errorMsg.value = ''
    consoleLogs.value = []
    try {
      const res = await bridge.run_phage_structure_batch(batchPayload)
      if (!res || res.success === false || !Array.isArray(res.tasks) || res.tasks.length === 0) {
        throw new Error(res?.error || res?.detail || '批量入队失败，未创建有效任务')
      }
      const first = res.tasks[0]
      const snap = res.queue as StructureQueueSnapshot | undefined
      if (snap) {
        syncQueueSnapshot(snap)
      }
      const firstIsRunning = snap ? (snap.running || []).includes(first.task_id) : !first.is_busy
      const created: StructureTaskHistoryItem = {
        task_id: first.task_id,
        task_name: first.task_name,
        source_mode: first.source_mode || 'file',
        status: firstIsRunning ? 'running' : 'queued',
        progress: 0,
        queue_position: first.queue_position,
        current_step: firstIsRunning
          ? `批量队列共 ${res.batch_count} 个样本，正在启动第 1 个任务...`
          : `批量队列共 ${res.batch_count} 个样本，排队等待中 (#${first.queue_position || 1})`,
        created_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
      }
      currentTask.value = created
      currentResult.value = null
      appendLog(`已将 ${res.batch_count} 个结构与尾部形态预测任务按序加入后台排队队列`)
      notifyUser(
        `已批量导入 ${res.batch_count} 个预测任务到队列，系统将自动依次执行`,
        'success'
      )
      await Promise.all([loadHistory(), loadQueueStatus()])
    } catch (err) {
      errorMsg.value = `批量提交排队任务失败: ${String(err)}`
    } finally {
      isSubmitting.value = false
    }
  }

  async function selectTask(task: StructureTaskHistoryItem): Promise<void> {
    errorMsg.value = ''
    if (currentTask.value?.task_id !== task.task_id) {
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
    inspectedContigs.value = []
    inspectTotalBp.value = 0
  }

  async function cancelTask(taskId: string): Promise<void> {
    try {
      await bridge.cancel_phage_structure_task(taskId)
      await Promise.all([loadHistory(), loadQueueStatus()])
    } catch (err) {
      errorMsg.value = `取消任务失败: ${String(err)}`
    }
  }

  async function deleteTask(taskId: string): Promise<void> {
    try {
      await bridge.delete_phage_structure_task(taskId)
      if (currentTask.value?.task_id === taskId) {
        startNewTask()
      }
      await loadHistory()
    } catch (err) {
      errorMsg.value = `删除任务失败: ${String(err)}`
    }
  }

  function downloadFile(
    taskId: string,
    fileType: 'json' | 'summary_tsv' | 'features_tsv' | 'tmp_tsv' | 'gbk'
  ): void {
    const url = bridge.get_phage_structure_download_url(taskId, fileType)
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  async function openResultsFolder(taskId: string): Promise<void> {
    try {
      await bridge.open_phage_structure_folder(taskId)
    } catch (err) {
      errorMsg.value = `打开结果目录失败: ${String(err)}`
    }
  }

  async function fetchGbkForViewer(taskId: string): Promise<{ gbkText: string; taskName: string }> {
    return await bridge.get_phage_structure_gbk(taskId)
  }

  function handleWsEvent(eventType: string, rawData: unknown): void {
    if (eventType === 'phage_structure_queue_update' && rawData) {
      syncQueueSnapshot(rawData as StructureQueueSnapshot)
      return
    }
    const data = rawData as {
      task_id?: string
      progress?: number
      current_step?: string
      status?: StructureTaskHistoryItem['status']
      error?: unknown
    } | null
    if (!data || !data.task_id) return

    const activeId = currentTask.value?.task_id
    if (eventType === 'phage_structure_progress') {
      const h = historyList.value.find((t) => t.task_id === data.task_id)
      if (h) {
        if (typeof data.progress === 'number' && data.progress >= 0) h.progress = data.progress
        if (data.current_step) h.current_step = data.current_step
        if (data.status) h.status = data.status
      }
      if (activeId === data.task_id && currentTask.value) {
        if (typeof data.progress === 'number' && data.progress >= 0) {
          currentTask.value.progress = data.progress
        }
        if (data.current_step) {
          currentTask.value.current_step = data.current_step
          appendLog(data.current_step)
        }
        if (data.status) currentTask.value.status = data.status
      }
    } else if (eventType === 'phage_structure_completed') {
      loadHistory()
      loadQueueStatus()
      if (activeId === data.task_id) {
        appendLog('结构与形态预测完成，正在拉取分析报告...')
        loadTaskResult(data.task_id)
      }
    } else if (eventType === 'phage_structure_error') {
      loadHistory()
      loadQueueStatus()
      if (activeId === data.task_id && currentTask.value) {
        currentTask.value.status = data.status || 'failed'
        currentTask.value.error_msg = String(data.error || '结构预测执行失败')
        currentTask.value.current_step =
          currentTask.value.status === 'cancelled' ? '任务已中止' : '分析异常失败'
        appendLog(currentTask.value.error_msg)
      }
    }
  }

  onMounted(async () => {
    unsubscribeWs = onEvent(handleWsEvent)
    await Promise.all([loadCapabilities(), loadLinkedSources(), loadHistory(), loadQueueStatus()])
    pollingTimer = setInterval(() => {
      if (isQueueBusy.value || isQueued.value || isRunning.value) {
        loadQueueStatus()
        loadHistory()
      }
    }, 2200)
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
    linkedSources,
    historyList,
    currentTask,
    currentResult,
    queueStatus,
    consoleLogs,
    errorMsg,
    isCapabilitiesLoading,
    isSourcesLoading,
    isInspecting,
    isSubmitting,
    isResultLoading,
    isQueued,
    isRunning,
    isQueueBusy,
    inspectedContigs,
    inspectTotalBp,
    loadCapabilities,
    loadLinkedSources,
    loadHistory,
    inspectInput,
    submitTask,
    submitBatchTasks,
    selectTask,
    startNewTask,
    cancelTask,
    deleteTask,
    downloadFile,
    openResultsFolder,
    fetchGbkForViewer,
  }
}
