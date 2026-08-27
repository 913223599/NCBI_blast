/**
 * useAnnotation - 功能注释 Composable 状态与逻辑编排
 */
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { getBridge } from '../../../../../bridge';
import { onEvent } from '../../../../../bridge/electron-bridge';
import type { 
  AnnotationRunParams, 
  AnnotationTaskItem, 
  ProgressEventPayload, 
  AnnotationQueueStatus 
} from '../types';

export function useAnnotation() {
  const isRunning = ref<boolean>(false);
  const currentTask = ref<AnnotationTaskItem | null>(null);
  const historyTasks = ref<AnnotationTaskItem[]>([]);
  const activeTaskId = ref<string>('');
  const error = ref<string | null>(null);
  const consoleLogs = ref<string[]>([]);
  const isHistoryLoading = ref<boolean>(false);
  const queueStatus = ref<AnnotationQueueStatus | null>(null);

  // 引擎是否正忙（有正在运行的任务）
  const isEngineBusy = computed(() => {
    return !!queueStatus.value?.is_busy || historyTasks.value.some(t => t.status === 'running');
  });

  // 1. 载入历史记录与队列状态
  async function fetchHistory() {
    isHistoryLoading.value = true;
    try {
      const bridge = getBridge();
      const [histRes, qRes] = await Promise.all([
        bridge.get_annotation_history(50),
        bridge.get_annotation_queue_status ? bridge.get_annotation_queue_status() : Promise.resolve(null)
      ]);

      if (histRes && histRes.success) {
        historyTasks.value = histRes.data || [];
      }
      if (qRes && qRes.success) {
        queueStatus.value = qRes.data;
      }
    } catch (e: any) {
      console.warn('[useAnnotation] 获取历史记录失败:', e);
    } finally {
      isHistoryLoading.value = false;
    }
  }

  // 2. 提交新任务 (支持连续排队提交)
  async function submitTask(params: AnnotationRunParams) {
    error.value = null;

    try {
      const bridge = getBridge();
      const res = await bridge.run_annotation_task(params);
      if (!res || !res.success) {
        throw new Error(res?.detail || res?.error || res?.message || '提交失败');
      }

      const newTaskId = res.task_id;
      const position = res.position || 1;

      // 构造前端即时任务快照
      const newTaskItem: AnnotationTaskItem = {
        task_id: newTaskId,
        task_name: res.task_name || params.task_name,
        sample_type: params.sample_type,
        engine: params.engine,
        status: 'queued',
        progress: 0,
        position: position,
        current_step: `已进入排队队列 #${position}`,
        created_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
        updated_at: new Date().toISOString().replace('T', ' ').slice(0, 19),
      };

      // 插入到历史列表顶部
      historyTasks.value = [newTaskItem, ...historyTasks.value.filter(t => t.task_id !== newTaskId)];

      // 切换当前聚焦任务
      activeTaskId.value = newTaskId;
      currentTask.value = newTaskItem;

      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 任务已提交至队列，Task ID: ${newTaskId} (排队位次: #${position})`);
      
      // 刷新最新历史与队列状态
      await fetchHistory();
      return res;
    } catch (e: any) {
      error.value = `任务提交失败: ${e.message}`;
      throw e;
    }
  }

  // 3. 加载指定任务的结果详情 (支持瞬时乐观响应)
  async function loadTaskResult(taskId: string) {
    if (!taskId) return;
    activeTaskId.value = taskId;
    error.value = null;

    // 1. 瞬时乐观展示：优先使用前端现有本地元数据，实现 0ms 瞬间切换
    const existing = historyTasks.value.find(t => t.task_id === taskId);
    if (existing) {
      const qMatch = queueStatus.value?.waiting_tasks?.find(w => w.task_id === taskId);
      currentTask.value = {
        ...existing,
        summary: existing.summary || {} as any,
        features: existing.features || [],
        safety_audit: existing.safety_audit || {} as any,
        position: qMatch?.position || existing.position || 1
      };
      isRunning.value = existing.status === 'running';

      // 性能极速优化：排队中任务已具备全部必要元数据，无需再做任何阻塞性网络等待
      if (existing.status === 'queued' || existing.status === 'pending') {
        return;
      }
    }

    // 2. 对于已完成或运行中任务，向后端拉取最新完整数据
    try {
      const bridge = getBridge();
      const res = await bridge.get_annotation_result(taskId);
      if (res && res.success && res.data) {
        const data = res.data;
        // 关键防守：确保对象结构完整性
        if (!data.summary || typeof data.summary !== 'object') {
          data.summary = {};
        }
        if (!Array.isArray(data.features)) {
          data.features = [];
        }
        if (!data.safety_audit || typeof data.safety_audit !== 'object') {
          data.safety_audit = {};
        }

        // 补齐排队位次
        if (!data.position && queueStatus.value?.waiting_tasks) {
          const qMatch = queueStatus.value.waiting_tasks.find((w: any) => w.task_id === taskId);
          if (qMatch && typeof qMatch.position === 'number') {
            data.position = qMatch.position;
          }
        }
        if (!data.position && existing && existing.position) {
          data.position = existing.position;
        }

        // 关键防守：若进度>=100或已有特征，强制确认为完成态
        if (data.progress >= 100 || data.status === 'completed' || (data.features && data.features.length > 0)) {
          data.status = 'completed';
          isRunning.value = false;
        } else if (data.status === 'running') {
          isRunning.value = true;
        } else {
          isRunning.value = false;
        }
        currentTask.value = data;
      }
    } catch (e: any) {
      console.warn(`[useAnnotation] 加载任务结果提示: ${e.message}`);
    }
  }

  // 4. 取消任务 (支持排队中和运行中)
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
      const match = historyTasks.value.find(t => t.task_id === tid);
      if (match) {
        match.status = 'cancelled';
        match.current_step = '已取消';
      }
      
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

  // 7. 注册 WebSocket 进度与队列事件监听
  let unsubEvents: (() => void) | null = null;

  onMounted(() => {
    fetchHistory();

    // 统一监听 WebSocket 事件广播
    unsubEvents = onEvent((eventType: string, data: any) => {
      if (!data) return;

      // 队列状态快照更新
      if (eventType === 'annotation_queue_status') {
        queueStatus.value = data;
        // 自动校正 historyTasks 中任务的排队序号和运行状态
        if (data.waiting_tasks) {
          const waitingMap = new Map(data.waiting_tasks.map((t: any) => [t.task_id, t]));
          historyTasks.value.forEach(t => {
            if (waitingMap.has(t.task_id)) {
              const qItem: any = waitingMap.get(t.task_id);
              t.status = 'queued';
              t.position = qItem.position;
              t.current_step = `排队等待中 #${qItem.position}`;
            }
          });

          if (currentTask.value && waitingMap.has(currentTask.value.task_id)) {
            const qItem: any = waitingMap.get(currentTask.value.task_id);
            currentTask.value.status = 'queued';
            currentTask.value.position = qItem.position;
            currentTask.value.current_step = `排队等待中 #${qItem.position}`;
          }
        }
        if (data.current_task) {
          const runId = data.current_task.task_id;
          const match = historyTasks.value.find(t => t.task_id === runId);
          if (match && match.status !== 'completed') {
            match.status = 'running';
          }
          if (currentTask.value && currentTask.value.task_id === runId) {
            currentTask.value.status = 'running';
            isRunning.value = true;
          }
        }
      } 
      // 任务单步进度更新
      else if (eventType === 'annotation_progress') {
        const payload = data as ProgressEventPayload;
        if (currentTask.value && currentTask.value.task_id === payload.task_id) {
          currentTask.value.status = 'running';
          currentTask.value.progress = payload.progress;
          currentTask.value.current_step = payload.current_step;
          isRunning.value = true;
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

        // 若进度达到 100%，拉取结果
        if (payload.progress >= 100) {
          if (activeTaskId.value === payload.task_id || currentTask.value?.task_id === payload.task_id) {
            loadTaskResult(payload.task_id);
          }
          fetchHistory();
        }
      } 
      // 任务完成广播
      else if (eventType === 'annotation_completed') {
        if (activeTaskId.value === data.task_id || currentTask.value?.task_id === data.task_id) {
          loadTaskResult(data.task_id);
        }
        fetchHistory();
      }
    });
  });

  onUnmounted(() => {
    if (unsubEvents) unsubEvents();
  });

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
    downloadFile
  };
}

