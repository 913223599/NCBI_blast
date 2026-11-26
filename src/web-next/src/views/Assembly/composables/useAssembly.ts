/**
 * useAssembly - 基因组组装 Composable 状态与逻辑编排 (纯净重构版)
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiDelete, apiGet, apiPost, onEvent } from '../../../bridge/electron-bridge'
import { downloadFileFromUrl } from '../../../utils/fileDownloader'
import { createLogger } from '../../../utils/logger'
import type {
  AssemblyQueueStatus,
  AssemblyResultData,
  AssemblyRunParams,
  AssemblyTaskItem,
} from '../types'

const logger = createLogger('Assembly')

function toErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

interface AssemblyQueueEventPayload {
  queue?: Array<{ id: string; status?: string; position?: number; name?: string; sample_type?: string }>
  running_task?: AssemblyQueueStatus['running_task']
  waiting_tasks?: AssemblyQueueStatus['waiting_tasks']
  waiting_count?: number
  is_busy?: boolean
  current_task_id?: string | null
}

interface AssemblyLogEventPayload {
  task_id?: string
  line?: string
}

interface AssemblyProgressEventPayload {
  task_id?: string
  step?: string
  progress?: number
  status?: string
  stats?: AssemblyTaskItem['results']
}

interface AssemblyRunApiResponse {
  success?: boolean
  code?: number
  error?: string
  msg?: string
  message?: string
  task_id?: string
  queue_position?: number
  is_busy?: boolean
  status?: string
  data?: {
    task_id?: string
    queue_position?: number
    is_busy?: boolean
    status?: string
  }
}

export function useAssembly() {
  const isRunning = ref<boolean>(false)
  const currentTask = ref<AssemblyTaskItem | null>(null)
  const resultData = ref<AssemblyResultData | null>(null)
  const historyTasks = ref<AssemblyTaskItem[]>([])
  const activeTaskId = ref<string>('')
  const error = ref<string | null>(null)
  const consoleLogs = ref<string[]>([])
  const isHistoryLoading = ref<boolean>(false)
  const queueStatus = ref<AssemblyQueueStatus | null>(null)

  const isEngineBusy = computed(
    () => Boolean(queueStatus.value?.is_busy) || historyTasks.value.some((t) => t.status === 'running')
  )

  async function fetchHistory() {
    isHistoryLoading.value = true
    try {
      const [histRes, qRes] = await Promise.all([
        apiGet<AssemblyTaskItem[] | { data?: AssemblyTaskItem[]; tasks?: AssemblyTaskItem[] }>('/api/assembly/history'),
        apiGet<AssemblyQueueStatus & { data?: AssemblyQueueStatus }>('/api/assembly/queue'),
      ])

      let tasks: AssemblyTaskItem[] = []
      if (Array.isArray(histRes)) {
        tasks = histRes
      } else if (histRes && Array.isArray(histRes.data)) {
        tasks = histRes.data
      } else if (histRes && Array.isArray(histRes.tasks)) {
        tasks = histRes.tasks
      }
      historyTasks.value = tasks

      if (qRes) {
        queueStatus.value = qRes.data || qRes
      }

      if (currentTask.value) {
        const focusId = activeTaskId.value || currentTask.value.id
        const matched = tasks.find((t) => t.id === focusId)
        if (matched) {
          const curStatus = currentTask.value.status
          const isCurTerminal = curStatus === 'completed' || curStatus === 'failed' || curStatus === 'aborted'
          const isQueueRunningFocus = queueStatus.value?.running_task?.id === matched.id

          if (!isCurTerminal) {
            if (matched.status === 'running' || isQueueRunningFocus) {
              currentTask.value.status = 'running'
              isRunning.value = true
              currentTask.value.progress = Math.max(currentTask.value.progress || 0, matched.progress || 0)
              if (!currentTask.value.last_step || currentTask.value.last_step.includes('排队')) {
                currentTask.value.last_step = matched.last_step || '正在运行...'
              }
            } else if (matched.status === 'completed' || matched.status === 'failed' || matched.status === 'aborted') {
              currentTask.value.status = matched.status
              currentTask.value.progress = matched.progress ?? currentTask.value.progress
              currentTask.value.last_step = matched.last_step || currentTask.value.last_step
              if (matched.results) {
                currentTask.value.results = { ...(currentTask.value.results || {}), ...matched.results }
              }
              isRunning.value = false
            }
          }
        }
      }
    } catch (e: unknown) {
      logger.warn('获取历史记录或队列失败:', e)
    } finally {
      isHistoryLoading.value = false
    }
  }

  async function submitTask(params: AssemblyRunParams) {
    error.value = null
    const taskId = `Assembly_${Date.now()}`
    const payload = {
      task_id: taskId,
      name: params.name || `Task_${taskId.slice(-6)}`,
      sample_type: params.sample_type || 'BACTERIA',
      tech: params.tech || 'ILLUMINA',
      r1: params.r1_path,
      r2: params.r2_path || null,
      long_reads: params.long_reads_path || null,
      config: {
        name: params.name,
        sample_type: params.sample_type,
        tech: params.tech,
        r1: params.r1_path,
        r2: params.r2_path || null,
        long_reads: params.long_reads_path || null,
        r1_name: params.r1_name,
        r2_name: params.r2_name,
        long_reads_name: params.long_reads_name,
        params: {
          threads: params.threads || 8,
          mode: params.mode || 'isolate',
          min_read_length: params.min_read_length || 1000,
          min_contig_length: params.min_contig_length || 500,
          min_containment_identity: params.min_containment_identity ?? null,
          max_reads: params.max_reads || null,
          enable_qc: params.enable_qc ?? true,
        },
      },
    }

    const isQueued = isEngineBusy.value
    const newTaskItem: AssemblyTaskItem = {
      id: taskId,
      name: payload.name,
      sample_type: payload.sample_type,
      tech: payload.tech,
      status: isQueued ? 'queued' : 'running',
      progress: 0,
      last_step: isQueued ? '等待排队调度中...' : '正在启动 NGCS 组装调度...',
      created_at: Date.now() / 1000,
      updated_at: Date.now() / 1000,
      config: payload.config,
      results: null,
      queue_position: isQueued ? (queueStatus.value?.waiting_count || 0) + 1 : 1,
    }

    historyTasks.value = [newTaskItem, ...historyTasks.value.filter((t) => t.id !== taskId)]
    activeTaskId.value = taskId
    currentTask.value = newTaskItem
    isRunning.value = !isQueued
    resultData.value = null

    consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 拼接任务已派发: ${taskId}`)
    consoleLogs.value.push(
      `[${new Date().toLocaleTimeString()}] 测序平台: ${params.tech} | 模式: ${params.mode} | R1: ${params.r1_path}`
    )
    if (params.r2_path) consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 双端 R2: ${params.r2_path}`)
    if (params.long_reads_path) {
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 三代长读长: ${params.long_reads_path}`)
    }

    try {
      const res = await apiPost<AssemblyRunApiResponse>('/api/assembly/run', payload)
      if (!res || (res.success === false && res.code !== 200)) {
        throw new Error(res?.error || res?.msg || res?.message || '任务提交失败')
      }

      const assignedTaskId = res.task_id || res.data?.task_id || taskId
      const rawPos = res.queue_position ?? res.data?.queue_position ?? 0
      const queuePos = Number(rawPos) > 0 ? Number(rawPos) : 0
      const backendIsBusy = Boolean(res.is_busy ?? res.data?.is_busy ?? false)
      const backendStatus = res.status || res.data?.status

      const curStatus = currentTask.value?.id === taskId ? currentTask.value.status : null
      const alreadyTerminal = curStatus === 'completed' || curStatus === 'failed' || curStatus === 'aborted'
      const alreadyAdvancedToRunning =
        curStatus === 'running' &&
        ((currentTask.value?.progress || 0) > 0 || queueStatus.value?.running_task?.id === assignedTaskId)

      const shouldWaitInQueue =
        !alreadyTerminal &&
        !alreadyAdvancedToRunning &&
        backendStatus !== 'running' &&
        (backendIsBusy || queuePos > 1 || (isQueued && backendStatus === 'queued'))

      if (currentTask.value && currentTask.value.id === taskId && !alreadyTerminal) {
        currentTask.value.id = assignedTaskId
        currentTask.value.queue_position = queuePos
        currentTask.value.status = shouldWaitInQueue ? 'queued' : 'running'
        if (shouldWaitInQueue) {
          currentTask.value.last_step = `排队中 (#${Math.max(1, queuePos)})`
        } else if (!currentTask.value.last_step || currentTask.value.last_step.includes('排队')) {
          currentTask.value.last_step = '正在启动 NGCS 组装调度...'
        }
      }
      if (!alreadyTerminal) isRunning.value = !shouldWaitInQueue
      activeTaskId.value = assignedTaskId

      fetchHistory()
      return res
    } catch (e: unknown) {
      const msg = toErrorMessage(e)
      error.value = `任务提交失败: ${msg}`
      if (currentTask.value && currentTask.value.id === taskId) {
        currentTask.value.status = 'failed'
        currentTask.value.last_step = `提交失败: ${msg}`
      }
      isRunning.value = false
      throw e
    }
  }

  async function loadTaskResult(taskId: string) {
    if (!taskId) return
    activeTaskId.value = taskId
    error.value = null

    const existing = historyTasks.value.find((t) => t.id === taskId)
    if (existing) {
      currentTask.value = { ...existing }
      isRunning.value = existing.status === 'running'
    }

    try {
      const res = await apiGet<
        AssemblyResultData & { success?: boolean; data?: AssemblyResultData }
      >(`/api/assembly/result/${taskId}`)
      const data =
        res && (res.task_id || res.stats)
          ? res
          : res?.data || (res && res.success !== false ? res : null)
      if (data && (data.task_id || data.stats || data.status)) {
        resultData.value = data
        const finalStats = data.stats || currentTask.value?.results
        if (currentTask.value) {
          currentTask.value.status = (data.status as AssemblyTaskItem['status']) || currentTask.value.status
          currentTask.value.results = finalStats ?? null
        }
        const matched = historyTasks.value.find((t) => t.id === taskId)
        if (matched) {
          matched.status = (data.status as AssemblyTaskItem['status']) || matched.status
          if (finalStats) matched.results = { ...(matched.results || {}), ...finalStats }
        }
      }
    } catch (e: unknown) {
      logger.warn(`加载任务结果失败 (${taskId}):`, e)
    }
  }

  async function cancelTask(taskId: string) {
    if (!taskId) return
    try {
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 正在发送终止指令: ${taskId}...`)
      await apiPost(`/api/assembly/stop/${taskId}`)
      if (currentTask.value && currentTask.value.id === taskId) {
        currentTask.value.status = 'aborted'
        isRunning.value = false
      }
      await fetchHistory()
    } catch (e: unknown) {
      error.value = `终止任务失败: ${toErrorMessage(e)}`
    }
  }

  async function deleteTask(taskId: string) {
    if (!taskId) return
    try {
      await apiDelete(`/api/assembly/tasks/${taskId}`)
      historyTasks.value = historyTasks.value.filter((t) => t.id !== taskId)
      if (activeTaskId.value === taskId) {
        activeTaskId.value = ''
        currentTask.value = null
        resultData.value = null
        isRunning.value = false
      }
      await fetchHistory()
    } catch (e: unknown) {
      error.value = `删除任务失败: ${toErrorMessage(e)}`
    }
  }

  async function downloadFasta(taskId: string) {
    if (!taskId) return
    await downloadFileFromUrl(`/api/assembly/download/${taskId}`, `assembly_${taskId}.fasta`)
  }

  async function openFolder(taskId: string) {
    if (!taskId) return
    try {
      await apiPost(`/api/assembly/open-folder/${taskId}`)
    } catch (e: unknown) {
      logger.warn('打开产物目录失败:', e)
    }
  }

  let unsubscribeProgress: (() => void) | null = null
  let pollingTimer: ReturnType<typeof setInterval> | null = null

  onMounted(async () => {
    await fetchHistory()

    unsubscribeProgress = onEvent((type: string, rawData: unknown) => {
      if (type === 'assembly_queue_status' && rawData) {
        const data = rawData as AssemblyQueueEventPayload
        const snapshotList = Array.isArray(data.queue) ? data.queue : []
        const runningItem =
          data.running_task ||
          (snapshotList.find((item) => item.status === 'running' || item.id === data.current_task_id) as
            | AssemblyQueueStatus['running_task']
            | undefined) ||
          null
        const waitingItems = Array.isArray(data.waiting_tasks)
          ? data.waiting_tasks
          : (snapshotList.filter((item) => item.status === 'pending' || item.status === 'queued') as AssemblyQueueStatus['waiting_tasks'])

        queueStatus.value = {
          running_task: runningItem,
          waiting_count: typeof data.waiting_count === 'number' ? data.waiting_count : waitingItems.length,
          waiting_tasks: waitingItems,
          is_busy: typeof data.is_busy === 'boolean' ? data.is_busy : Boolean(data.current_task_id || runningItem),
        }

        const waitingMap = new Map<string, number>()
        waitingItems.forEach((w, idx) => {
          const itemPos = (w as { position?: number }).position ?? w.queue_position
          waitingMap.set(w.id, typeof itemPos === 'number' ? itemPos : idx + 1)
        })

        historyTasks.value.forEach((t) => {
          if (data.current_task_id && t.id === data.current_task_id) {
            if (t.status !== 'completed' && t.status !== 'failed' && t.status !== 'aborted') {
              t.status = 'running'
            }
          } else if (waitingMap.has(t.id)) {
            const pos = waitingMap.get(t.id) || 1
            t.status = 'queued'
            t.queue_position = pos
            t.last_step = `排队中 (#${pos})`
          }
        })

        if (currentTask.value) {
          if (data.current_task_id && currentTask.value.id === data.current_task_id) {
            if (
              currentTask.value.status !== 'completed' &&
              currentTask.value.status !== 'failed' &&
              currentTask.value.status !== 'aborted'
            ) {
              currentTask.value.status = 'running'
              isRunning.value = true
            }
          } else if (waitingMap.has(currentTask.value.id)) {
            const pos = waitingMap.get(currentTask.value.id) || 1
            currentTask.value.status = 'queued'
            currentTask.value.queue_position = pos
            currentTask.value.last_step = `排队中 (#${pos})`
            isRunning.value = false
          }
        }
      }

      if (type === 'assembly_log' && rawData) {
        const { task_id, line } = rawData as AssemblyLogEventPayload
        if (task_id && (activeTaskId.value === task_id || (!activeTaskId.value && currentTask.value?.id === task_id))) {
          if (currentTask.value && (currentTask.value.status === 'queued' || currentTask.value.status === 'pending')) {
            currentTask.value.status = 'running'
            if (!currentTask.value.last_step || currentTask.value.last_step.includes('排队')) {
              currentTask.value.last_step = '正在运行...'
            }
            isRunning.value = true
          }
          const matchedHist = historyTasks.value.find((t) => t.id === task_id)
          if (matchedHist && (matchedHist.status === 'queued' || matchedHist.status === 'pending')) {
            matchedHist.status = 'running'
          }
          if (line) {
            consoleLogs.value.push(line)
            if (consoleLogs.value.length > 2500) consoleLogs.value.splice(0, 500)
          }
        }
      }

      if (type === 'assembly_progress' && rawData) {
        const { task_id, step, progress, status, stats } = rawData as AssemblyProgressEventPayload
        if (!task_id) return
        const matched = historyTasks.value.find((t) => t.id === task_id)
        if (matched) {
          matched.progress = progress !== undefined ? Math.max(matched.progress || 0, progress) : matched.progress
          matched.last_step = step || matched.last_step
          matched.status = (status as AssemblyTaskItem['status']) || matched.status
          if (stats) matched.results = stats
        }

        if (activeTaskId.value === task_id || (!activeTaskId.value && currentTask.value?.id === task_id)) {
          if (currentTask.value) {
            currentTask.value.progress =
              progress !== undefined ? Math.max(currentTask.value.progress || 0, progress) : currentTask.value.progress
            currentTask.value.last_step = step || currentTask.value.last_step
            currentTask.value.status = (status as AssemblyTaskItem['status']) || currentTask.value.status
            if (stats) currentTask.value.results = stats
          }
          if (step) {
            const logEntry = `> [${new Date().toLocaleTimeString()}] ${step}`
            const lastLog = consoleLogs.value[consoleLogs.value.length - 1]
            if (!lastLog || !lastLog.includes(step)) {
              consoleLogs.value.push(logEntry)
              if (consoleLogs.value.length > 2500) consoleLogs.value.splice(0, 500)
            }
          }
          if (status === 'success' || status === 'completed') {
            isRunning.value = false
            loadTaskResult(task_id)
          } else if (status === 'failed' || status === 'aborted') {
            isRunning.value = false
          } else if (status === 'running') {
            isRunning.value = true
          }
        }
      }
    })

    pollingTimer = setInterval(async () => {
      const focusStatus = currentTask.value?.status
      if (
        isRunning.value ||
        focusStatus === 'queued' ||
        focusStatus === 'pending' ||
        queueStatus.value?.is_busy ||
        historyTasks.value.some((t) => t.status === 'running' || t.status === 'queued')
      ) {
        await fetchHistory()
        if (activeTaskId.value) {
          const matched = historyTasks.value.find((t) => t.id === activeTaskId.value)
          if (
            matched &&
            (matched.status === 'completed' || matched.status === 'failed') &&
            resultData.value?.task_id !== activeTaskId.value
          ) {
            isRunning.value = false
            await loadTaskResult(activeTaskId.value)
          }
        }
      }
    }, 3000)
  })

  onUnmounted(() => {
    if (unsubscribeProgress) unsubscribeProgress()
    if (pollingTimer) clearInterval(pollingTimer)
  })

  return {
    isRunning,
    isEngineBusy,
    currentTask,
    resultData,
    historyTasks,
    activeTaskId,
    queueStatus,
    error,
    consoleLogs,
    isHistoryLoading,
    fetchHistory,
    submitTask,
    loadTaskResult,
    cancelTask,
    deleteTask,
    downloadFasta,
    openFolder,
  }
}
