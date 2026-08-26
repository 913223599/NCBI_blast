/**
 * useAnnotation - 功能注释 Composable 状态与逻辑编排
 */
import { ref, onMounted, onUnmounted } from 'vue';
import { getBridge } from '../../../../../bridge';
import { onEvent } from '../../../../../bridge/electron-bridge';
import type { AnnotationRunParams, AnnotationTaskItem, ProgressEventPayload } from '../types';

export function useAnnotation() {
  const isRunning = ref<boolean>(false);
  const currentTask = ref<AnnotationTaskItem | null>(null);
  const historyTasks = ref<AnnotationTaskItem[]>([]);
  const activeTaskId = ref<string>('');
  const error = ref<string | null>(null);
  const consoleLogs = ref<string[]>([]);
  const isHistoryLoading = ref<boolean>(false);

  // 1. 载入历史记录
  async function fetchHistory() {
    isHistoryLoading.value = true;
    try {
      const bridge = getBridge();
      const res = await bridge.get_annotation_history(50);
      if (res && res.success) {
        historyTasks.value = res.data || [];
      }
    } catch (e: any) {
      console.warn('[useAnnotation] 获取历史记录失败:', e);
    } finally {
      isHistoryLoading.value = false;
    }
  }

  // 2. 提交新任务
  async function submitTask(params: AnnotationRunParams) {
    isRunning.value = true;
    error.value = null;
    consoleLogs.value = [];
    currentTask.value = null;

    try {
      const bridge = getBridge();
      const res = await bridge.run_annotation_task(params);
      if (!res || !res.success) {
        throw new Error(res?.detail || res?.error || res?.message || '提交失败');
      }

      activeTaskId.value = res.task_id;
      currentTask.value = {
        task_id: res.task_id,
        task_name: res.task_name,
        sample_type: params.sample_type,
        engine: params.engine,
        status: 'running',
        progress: 5,
        current_step: '正在初始化任务...',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 任务已成功提交，Task ID: ${res.task_id}`);
      await fetchHistory();
    } catch (e: any) {
      error.value = `任务提交失败: ${e.message}`;
      isRunning.value = false;
    }
  }

  // 3. 加载指定任务的结果详情
  async function loadTaskResult(taskId: string) {
    if (!taskId) return;
    activeTaskId.value = taskId;
    error.value = null;

    try {
      const bridge = getBridge();
      const res = await bridge.get_annotation_result(taskId);
      if (res && res.success && res.data) {
        const data = res.data;
        // 关键防守：若进度>=100或已有特征，强制确认为完成态，解除 running 锁定
        if (data.progress >= 100 || data.status === 'completed' || (data.features && data.features.length > 0)) {
          data.status = 'completed';
          isRunning.value = false;
        } else {
          isRunning.value = data.status === 'running' || data.status === 'pending';
        }
        currentTask.value = data;
      } else {
        throw new Error('未获取到有效任务数据');
      }
    } catch (e: any) {
      error.value = `加载任务详情失败: ${e.message}`;
    }
  }

  // 4. 取消任务
  async function cancelTask(taskId?: string) {
    const tid = taskId || activeTaskId.value;
    if (!tid) return;
    try {
      const bridge = getBridge();
      await bridge.cancel_annotation_task(tid);
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 已向任务 ${tid} 发送取消请求`);
      if (currentTask.value && currentTask.value.task_id === tid) {
        currentTask.value.status = 'cancelled';
        currentTask.value.current_step = '已取消';
      }
      isRunning.value = false;
      await fetchHistory();
    } catch (e: any) {
      console.error('[useAnnotation] 取消任务异常:', e);
    }
  }

  // 5. 删除任务
  async function deleteTask(taskId: string) {
    if (!taskId) return;
    try {
      const bridge = getBridge();
      await bridge.delete_annotation_task(taskId);
      if (activeTaskId.value === taskId) {
        activeTaskId.value = '';
        currentTask.value = null;
        isRunning.value = false;
      }
      await fetchHistory();
    } catch (e: any) {
      console.error('[useAnnotation] 删除任务异常:', e);
    }
  }

  // 6. 下载产物文件
  function downloadFile(taskId: string, fileType: string) {
    const url = `/api/analysis/annotation/${taskId}/download/${fileType}`;
    const link = document.createElement('a');
    link.href = url;
    link.download = `${taskId}.${fileType}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  // 7. 注册 WebSocket 进度与完成事件监听
  let unsubEvents: (() => void) | null = null;

  onMounted(() => {
    fetchHistory();

    // 统一监听 WebSocket 事件广播
    unsubEvents = onEvent((eventType: string, data: any) => {
      if (!data) return;

      if (eventType === 'annotation_progress') {
        const payload = data as ProgressEventPayload;
        if (currentTask.value && currentTask.value.task_id === payload.task_id) {
          currentTask.value.progress = payload.progress;
          currentTask.value.current_step = payload.current_step;
          if (payload.log) {
            consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] ${payload.log}`);
          }
        }
        // 更新历史列表中对应卡片的进度
        const match = historyTasks.value.find(t => t.task_id === payload.task_id);
        if (match) {
          match.progress = payload.progress;
          match.current_step = payload.current_step;
          if (payload.progress < 100 && match.status !== 'completed') {
            match.status = 'running';
          }
        }

        // 若进度达到 100%，自动切换为 completed 并拉取结果
        if (payload.progress >= 100) {
          if (activeTaskId.value === payload.task_id || currentTask.value?.task_id === payload.task_id) {
            loadTaskResult(payload.task_id);
            isRunning.value = false;
          }
          fetchHistory();
        }
      } else if (eventType === 'annotation_completed') {
        // 收到完成广播直接拉取并展示结果
        loadTaskResult(data.task_id);
        isRunning.value = false;
        fetchHistory();
      }
    });
  });

  onUnmounted(() => {
    if (unsubEvents) unsubEvents();
  });

  return {
    isRunning,
    currentTask,
    historyTasks,
    activeTaskId,
    error,
    consoleLogs,
    isHistoryLoading,
    fetchHistory,
    submitTask,
    loadTaskResult,
    cancelTask,
    deleteTask,
    downloadFile
  };
}
