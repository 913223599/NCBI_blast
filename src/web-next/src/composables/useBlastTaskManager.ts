/**
 * useBlastTaskManager - BLAST任务管理组合式函数
 * 
 * 职责：
 * - 任务轮询监控
 * - 任务状态更新
 * - 任务生命周期管理（启动、暂停、恢复、停止、删除）
 */
import { ref } from 'vue'
import { useBlastStore } from '../stores/blast'
import { getBridge } from '../bridge/pyqt-bridge'

export function useBlastTaskManager() {
  const blast = useBlastStore()
  const pollingTimers: Record<string, number> = {}

  /**
   * 启动任务状态轮询
   */
  function startPolling(taskId: string, onCompleted?: (taskId: string) => void) {
    if (pollingTimers[taskId]) return
    
    pollingTimers[taskId] = window.setInterval(() => {
      try {
        getBridge().get_task_status(taskId, (resStr) => {
          try {
            const statusObj = resStr ? JSON.parse(resStr) : null
            if (!statusObj || !statusObj.status) return

            blast.updateTaskStatus(taskId, statusObj.status, statusObj.progress)
            
            // 任务完成或失败时停止轮询
            if (['done', 'completed', 'error', 'failed', 'cancelled'].includes(statusObj.status)) {
              stopPolling(taskId)
              
              // 回调通知调用方
              if (onCompleted && (statusObj.status === 'done' || statusObj.status === 'completed')) {
                onCompleted(taskId)
              }
            }
          } catch (e) {
            console.error('[TaskManager] Parse status error:', e)
          }
        })
      } catch (e) {
        console.error('[TaskManager] Polling error:', e)
        stopPolling(taskId)
      }
    }, 1000)
  }

  /**
   * 停止任务轮询
   */
  function stopPolling(taskId: string) {
    if (pollingTimers[taskId]) {
      window.clearInterval(pollingTimers[taskId])
      delete pollingTimers[taskId]
    }
  }

  /**
   * 暂停任务
   */
  function pauseTask(taskId: string) {
    try {
      getBridge().pause_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'paused')
    } catch (e) {
      console.error('[TaskManager] Pause task failed:', e)
    }
  }

  /**
   * 恢复任务
   */
  function resumeTask(taskId: string, onResume?: (taskId: string) => void) {
    try {
      getBridge().resume_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'running')
      
      // 恢复后重新启动轮询
      if (onResume) {
        onResume(taskId)
      }
    } catch (e) {
      console.error('[TaskManager] Resume task failed:', e)
    }
  }

  /**
   * 停止任务
   */
  function stopTask(taskId: string) {
    try {
      getBridge().stop_blast_job(taskId)
      blast.updateTaskStatus(taskId, 'cancelled')
      stopPolling(taskId)
    } catch (e) {
      console.error('[TaskManager] Stop task failed:', e)
    }
  }

  /**
   * 删除任务
   */
  function deleteTask(taskId: string) {
    try {
      getBridge().delete_single_task(taskId)
      blast.removeTask(taskId)
      stopPolling(taskId)
    } catch (e) {
      console.error('[TaskManager] Delete task failed:', e)
    }
  }

  /**
   * 重命名任务
   */
  function renameTask(taskId: string, newName: string) {
    try {
      getBridge().rename_task(taskId, newName)
    } catch (e) {
      console.error('[TaskManager] Rename task failed:', e)
    }
  }

  /**
   * 清空所有历史
   */
  function clearAllHistory() {
    try {
      getBridge().clear_all_history()
      blast.clearHistory()
      
      // 清理所有轮询定时器
      Object.keys(pollingTimers).forEach(taskId => stopPolling(taskId))
    } catch (e) {
      console.error('[TaskManager] Clear history failed:', e)
    }
  }

  /**
   * 清理资源（组件卸载时调用）
   */
  function cleanup() {
    Object.keys(pollingTimers).forEach(taskId => stopPolling(taskId))
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
    cleanup
  }
}
