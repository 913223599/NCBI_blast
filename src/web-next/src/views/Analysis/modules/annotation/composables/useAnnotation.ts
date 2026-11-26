/**
 * useAnnotation - 功能注释 Composable 状态与逻辑编排
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getBridge } from '../../../../../bridge'
import { onEvent } from '../../../../../bridge/electron-bridge'
import { useAppStore } from '../../../../../stores/app'
import { downloadFileFromUrl } from '../../../../../utils/fileDownloader'
import { createLogger } from '../../../../../utils/logger'
import type {
  AnnotationQueueStatus,
  AnnotationRunParams,
  AnnotationTaskItem,
  ProgressEventPayload,
} from '../types'

const logger = createLogger('Annotation')

function toErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

interface AnnotationApiListResp {
  success?: boolean
  data?: AnnotationTaskItem[]
}

interface AnnotationQueueResp {
  success?: boolean
  data?: AnnotationQueueStatus
}

interface AnnotationSubmitResp {
  success?: boolean
  task_id: string
  task_name?: string
  position?: number
  detail?: string
  error?: string
  message?: string
}

interface AnnotationResultResp {
  success?: boolean
  data?: AnnotationTaskItem
}

export function useAnnotation() {
  const isRunning = ref<boolean>(false)
  const currentTask = ref<AnnotationTaskItem | null>(null)
  const historyTasks = ref<AnnotationTaskItem[]>([])
  const activeTaskId = ref<string>('')
  const error = ref<string | null>(null)
  const consoleLogs = ref<string[]>([])
  const isHistoryLoading = ref<boolean>(false)
  const queueStatus = ref<AnnotationQueueStatus | null>(null)

  const isEngineBusy = computed(
    () => Boolean(queueStatus.value?.is_busy) || historyTasks.value.some((t) => t.status === 'running')
  )

  async function fetchHistory() {
    isHistoryLoading.value = true
    try {
      const bridge = getBridge()
      const [histRes, qRes] = (await Promise.all([
        bridge.get_annotation_history(200),
        bridge.get_annotation_queue_status ? bridge.get_annotation_queue_status() : Promise.resolve(null),
      ])) as [AnnotationApiListResp | null, AnnotationQueueResp | null]

      if (histRes && histRes.success) {
        historyTasks.value = histRes.data || []
      }
      if (qRes && qRes.success && qRes.data) {
        queueStatus.value = qRes.data
      }
    } catch (e: unknown) {
      logger.warn('获取历史记录失败:', e)
    } finally {
      isHistoryLoading.value = false
    }
  }

  async function submitTask(params: AnnotationRunParams) {
    error.value = null
    try {
      const bridge = getBridge()
      const res = (await bridge.run_annotation_task(
        params as unknown as Record<string, unknown>
      )) as AnnotationSubmitResp | null
      if (!res || !res.success) {
        throw new Error(res?.detail || res?.error || res?.message || '提交失败')
      }

      const newTaskId = res.task_id
      const position = res.position || 1
      const pad = (n: number) => n.toString().padStart(2, '0')
      const now = new Date()
      const nowStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`

      const newTaskItem: AnnotationTaskItem = {
        task_id: newTaskId,
        task_name: res.task_name || params.task_name,
        sample_type: params.sample_type,
        engine: params.engine,
        status: 'queued',
        progress: 0,
        position,
        current_step: `已进入排队队列 #${position}`,
        created_at: nowStr,
        updated_at: nowStr,
      }

      historyTasks.value = [newTaskItem, ...historyTasks.value.filter((t) => t.task_id !== newTaskId)]
      activeTaskId.value = newTaskId
      currentTask.value = newTaskItem
      consoleLogs.value.push(
        `[${new Date().toLocaleTimeString()}] 任务已提交至队列，Task ID: ${newTaskId} (排队位次: #${position})`
      )
      await fetchHistory()
      return res
    } catch (e: unknown) {
      error.value = `任务提交失败: ${toErrorMessage(e)}`
      throw e
    }
  }

  async function loadTaskResult(taskId: string) {
    if (!taskId) return
    activeTaskId.value = taskId
    error.value = null

    const existing = historyTasks.value.find((t) => t.task_id === taskId)
    if (existing) {
      const qMatch = queueStatus.value?.waiting_tasks?.find((w) => w.task_id === taskId)
      currentTask.value = {
        ...existing,
        summary: existing.summary || ({} as AnnotationTaskItem['summary']),
        features: existing.features || [],
        safety_audit: existing.safety_audit || ({} as AnnotationTaskItem['safety_audit']),
        position: qMatch?.position || existing.position || 1,
      }
      isRunning.value = existing.status === 'running'
      if (existing.status === 'queued' || existing.status === 'pending') {
        return
      }
    }

    try {
      const bridge = getBridge()
      const res = (await bridge.get_annotation_result(taskId)) as AnnotationResultResp | null
      if (res && res.success && res.data) {
        const data = res.data
        if (!data.summary || typeof data.summary !== 'object') {
          data.summary = {} as AnnotationTaskItem['summary']
        }
        if (!Array.isArray(data.features)) {
          data.features = []
        }
        if (!data.safety_audit || typeof data.safety_audit !== 'object') {
          data.safety_audit = {} as AnnotationTaskItem['safety_audit']
        }

        if (!data.position && queueStatus.value?.waiting_tasks) {
          const qMatch = queueStatus.value.waiting_tasks.find((w) => w.task_id === taskId)
          if (qMatch && typeof qMatch.position === 'number') {
            data.position = qMatch.position
          }
        }
        if (!data.position && existing && existing.position) {
          data.position = existing.position
        }

        if (data.progress >= 100 || data.status === 'completed' || (data.features && data.features.length > 0)) {
          data.status = 'completed'
          isRunning.value = false
        } else if (data.status === 'running') {
          isRunning.value = true
        } else {
          isRunning.value = false
        }
        currentTask.value = data
      }
    } catch (e: unknown) {
      logger.warn(`加载任务结果提示: ${toErrorMessage(e)}`)
    }
  }

  async function cancelTask(taskId?: string) {
    const tid = taskId || activeTaskId.value
    if (!tid) return
    try {
      const bridge = getBridge()
      await bridge.cancel_annotation_task(tid)
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 已向任务 ${tid} 发送取消请求`)
      if (currentTask.value && currentTask.value.task_id === tid) {
        currentTask.value.status = 'cancelled'
        currentTask.value.current_step = '已取消'
      }
      const match = historyTasks.value.find((t) => t.task_id === tid)
      if (match) {
        match.status = 'cancelled'
        match.current_step = '已取消'
      }
      await fetchHistory()
    } catch (e: unknown) {
      logger.error('取消任务异常:', e)
    }
  }

  async function deleteTask(taskId: string) {
    if (!taskId) return
    try {
      const bridge = getBridge()
      await bridge.delete_annotation_task(taskId)
      if (activeTaskId.value === taskId) {
        activeTaskId.value = ''
        currentTask.value = null
        isRunning.value = false
      }
      await fetchHistory()
    } catch (e: unknown) {
      logger.error('删除任务异常:', e)
    }
  }

  async function downloadFile(taskId: string, fileType: string) {
    if (!taskId) return
    const appStore = useAppStore()
    const ext = fileType.toLowerCase()
    const typeNames: Record<string, string> = {
      gbk: 'GenBank 产物 (.gbk)',
      gff: 'GFF3 注释 (.gff)',
      faa: '蛋白质 FASTA (.faa)',
      ffn: '核酸基因 FASTA (.ffn)',
      tsv: 'TSV 功能注释表 (.tsv)',
      json: 'Summary 统计 (.json)',
    }
    const defaultFilename = `${taskId}.${ext}`
    const url = `/api/analysis/annotation/${taskId}/download/${ext}`
    appStore.showNotification(`正在准备下载 ${typeNames[ext] || ext}...`, 'info')
    try {
      const result = await downloadFileFromUrl(url, defaultFilename)
      if (result.success) {
        appStore.showNotification(
          result.savedPath ? `文件已成功保存至: ${result.savedPath}` : `文件已成功下载: ${defaultFilename}`,
          'success'
        )
      } else if (!result.cancelled) {
        appStore.showNotification(`下载失败: ${result.error || '未知错误'}`, 'error')
      }
    } catch (err: unknown) {
      appStore.showNotification(`下载异常: ${toErrorMessage(err)}`, 'error')
    }
  }

  let unsubEvents: (() => void) | null = null

  onMounted(() => {
    fetchHistory()

    unsubEvents = onEvent((eventType: string, rawData: unknown) => {
      if (!rawData) return

      if (eventType === 'annotation_queue_status') {
        const data = rawData as AnnotationQueueStatus
        queueStatus.value = data
        if (data.waiting_tasks) {
          const waitingMap = new Map(data.waiting_tasks.map((t) => [t.task_id, t]))
          const hasMissing = data.waiting_tasks.some(
            (w) => !historyTasks.value.some((t) => t.task_id === w.task_id)
          )
          if (hasMissing) fetchHistory()

          historyTasks.value.forEach((t) => {
            const qItem = waitingMap.get(t.task_id)
            if (qItem) {
              t.status = 'queued'
              t.position = qItem.position
              t.current_step = `排队等待中 #${qItem.position}`
            }
          })

          if (currentTask.value) {
            const qItem = waitingMap.get(currentTask.value.task_id)
            if (qItem) {
              currentTask.value.status = 'queued'
              currentTask.value.position = qItem.position
              currentTask.value.current_step = `排队等待中 #${qItem.position}`
            }
          }
        }
        if (data.current_task) {
          const runId = data.current_task.task_id
          const match = historyTasks.value.find((t) => t.task_id === runId)
          if (match && match.status !== 'completed') match.status = 'running'
          if (currentTask.value && currentTask.value.task_id === runId) {
            currentTask.value.status = 'running'
            isRunning.value = true
          }
        }
      } else if (eventType === 'annotation_progress') {
        const payload = rawData as ProgressEventPayload
        if (currentTask.value && currentTask.value.task_id === payload.task_id) {
          currentTask.value.status = 'running'
          currentTask.value.progress = payload.progress
          currentTask.value.current_step = payload.current_step
          isRunning.value = true
          if (payload.log) {
            consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] ${payload.log}`)
          }
        }
        const match = historyTasks.value.find((t) => t.task_id === payload.task_id)
        if (match) {
          match.progress = payload.progress
          match.current_step = payload.current_step
          if (payload.progress < 100 && match.status !== 'completed') {
            match.status = 'running'
          }
        }
        if (payload.progress >= 100) {
          if (activeTaskId.value === payload.task_id || currentTask.value?.task_id === payload.task_id) {
            loadTaskResult(payload.task_id)
          }
          fetchHistory()
        }
      } else if (eventType === 'annotation_completed') {
        const donePayload = rawData as { task_id?: string }
        if (donePayload.task_id) {
          if (activeTaskId.value === donePayload.task_id || currentTask.value?.task_id === donePayload.task_id) {
            loadTaskResult(donePayload.task_id)
          }
        }
        fetchHistory()
      }
    })
  })

  onUnmounted(() => {
    if (unsubEvents) unsubEvents()
  })

  return {
    isRunning,
    isEngineBusy,
    currentTask,
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
    downloadFile,
  }
}
