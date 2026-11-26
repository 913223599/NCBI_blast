/**
 * useBlastTaskManager - BLAST任务管理组合式函数
 *
 * 职责：
 * - 任务轮询监控
 * - 任务状态更新
 * - 任务生命周期管理（启动、暂停、恢复、停止、删除）
 */
import { useBlastStore } from '../stores/blast'
import { getBridge } from '../bridge'
import { createLogger } from '../utils/logger'

const logger = createLogger('BlastTaskManager')

export function useBlastTaskManager() {
  const blast = useBlastStore()
  const pollingTimers: Record<string, number> = {}

  function startPolling(taskId: string, onCompleted?: (taskId: string) => void) {
    if (pollingTimers[taskId]) return

    pollingTimers[taskId] = window.setInterval(() => {
      try {
        getBridge().get_task_status(taskId, (resStr: string) => {
          try {
            const statusObj = resStr ? JSON.parse(resStr) : null
            if (!statusObj || !statusObj.status) return

            blast.updateTaskStatus(taskId, statusObj.status, statusObj.progress)

            if (['done', 'completed', 'error', 'failed', 'cancelled'].includes(statusObj.status)) {
              stopPolling(taskId)
              if (onCompleted && (statusObj.status === 'done' || statusObj.status === 'completed')) {
                onCompleted(taskId)
              }
            }
          } catch (e) {
            logger.error('Parse status error:', e)
          }
        })
      } catch (e) {
        logger.error('Polling error:', e)
        stopPolling(taskId)
      }
    }, 1000)
  }

  function stopPolling(taskId: string) {
    if (pollingTimers[taskId]) {
      window.clearInterval(pollingTimers[taskId])
      delete pollingTimers[taskId]
    }
  }

  function pauseTask(taskId: string) {
    try {
      getBridge().pause_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'paused')
    } catch (e) {
      logger.error('Pause task failed:', e)
    }
  }

  function resumeTask(taskId: string, onResume?: (taskId: string) => void) {
    try {
      getBridge().resume_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'running')
      if (onResume) onResume(taskId)
    } catch (e) {
      logger.error('Resume task failed:', e)
    }
  }

  function stopTask(taskId: string) {
    try {
      getBridge().stop_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'cancelled')
      stopPolling(taskId)
    } catch (e) {
      logger.error('Stop task failed:', e)
    }
  }

  function deleteTask(taskId: string) {
    try {
      getBridge().delete_single_task(taskId)
      blast.removeTask(taskId)
      stopPolling(taskId)
    } catch (e) {
      logger.error('Delete task failed:', e)
    }
  }

  function renameTask(taskId: string, newName: string) {
    try {
      getBridge().rename_task(taskId, newName)
    } catch (e) {
      logger.error('Rename task failed:', e)
    }
  }

  function clearAllHistory() {
    try {
      getBridge().clear_all_history()
      blast.clearHistory()
      Object.keys(pollingTimers).forEach((taskId) => stopPolling(taskId))
    } catch (e) {
      logger.error('Clear history failed:', e)
    }
  }

  function cleanup() {
    Object.keys(pollingTimers).forEach((taskId) => stopPolling(taskId))
  }

  return {
    startPolling,
    stopPolling,
    pauseTask,
    resumeTask,
    stopTask,
    deleteTask,
    renameTask,
    clearAllHistory,
    cleanup,
  }
}
