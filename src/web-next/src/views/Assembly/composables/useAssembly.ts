/**
 * useAssembly - 基因组组装 Composable 状态与逻辑编排 (纯净重构版)
 */
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { onEvent, apiGet, apiPost, apiDelete, API_BASE } from '../../../bridge/electron-bridge';
import type { 
  AssemblyRunParams, 
  AssemblyTaskItem, 
  AssemblyResultData, 
  AssemblyQueueStatus 
} from '../types';

export function useAssembly() {
  const isRunning = ref<boolean>(false);
  const currentTask = ref<AssemblyTaskItem | null>(null);
  const resultData = ref<AssemblyResultData | null>(null);
  const historyTasks = ref<AssemblyTaskItem[]>([]);
  const activeTaskId = ref<string>('');
  const error = ref<string | null>(null);
  const consoleLogs = ref<string[]>([]);
  const isHistoryLoading = ref<boolean>(false);
  const queueStatus = ref<AssemblyQueueStatus | null>(null);

  // 引擎是否正忙（有正在运行的任务）
  const isEngineBusy = computed(() => {
    return !!queueStatus.value?.is_busy || historyTasks.value.some(t => t.status === 'running');
  });

  // 1. 获取任务历史记录与队列状态
  async function fetchHistory() {
    isHistoryLoading.value = true;
    try {
      const [histRes, qRes] = await Promise.all([
        apiGet('/api/assembly/history'),
        apiGet('/api/assembly/queue')
      ]);

      if (histRes && histRes.code === 200) {
        historyTasks.value = histRes.data || [];
      }
      if (qRes && qRes.code === 200) {
        queueStatus.value = qRes.data;
      }
    } catch (e: any) {
      console.warn('[useAssembly] 获取历史记录或队列失败:', e);
    } finally {
      isHistoryLoading.value = false;
    }
  }

  // 2. 提交新拼接任务
  async function submitTask(params: AssemblyRunParams) {
    error.value = null;

    try {
      const taskId = `Assembly_${Date.now()}`;
      const payload = {
        task_id: taskId,
        name: params.name || `Task_${taskId.slice(-6)}`,
        sample_type: params.sample_type || 'BACTERIA',
        tech: params.tech || 'ILLUMINA',
        r1: params.r1_path,
        r2: params.r2_path || null,
        config: {
          name: params.name,
          sample_type: params.sample_type,
          tech: params.tech,
          r1: params.r1_path,
          r2: params.r2_path || null,
          r1_name: params.r1_name,
          r2_name: params.r2_name,
          params: {
            threads: params.threads || 8,
            mode: params.mode || 'isolate',
            min_read_length: params.min_read_length || 500
          }
        }
      };

      const res = await apiPost('/api/assembly/run', payload);

      if (!res || res.code !== 200) {
        throw new Error(res?.msg || res?.message || res?.error || '任务提交失败');
      }

      const queuePos = res.data?.queue_position || 1;

      // 乐观添加任务快照到历史列表
      const newTaskItem: AssemblyTaskItem = {
        id: taskId,
        name: payload.name,
        sample_type: payload.sample_type,
        tech: payload.tech,
        status: queuePos > 1 ? 'queued' : 'running',
        progress: 0,
        last_step: queuePos > 1 ? `排队中 (#${queuePos})` : '正在启动 NGCS 引擎...',
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        config: payload.config,
        results: null,
        queue_position: queuePos
      };

      historyTasks.value = [newTaskItem, ...historyTasks.value.filter(t => t.id !== taskId)];
      activeTaskId.value = taskId;
      currentTask.value = newTaskItem;
      isRunning.value = true;
      resultData.value = null;

      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 拼接任务已提交: ${taskId} (排队位次: #${queuePos})`);
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 测序平台: ${params.tech} | 模式: ${params.mode} | R1: ${params.r1_path}`);
      if (params.r2_path) {
        consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 双端 R2: ${params.r2_path}`);
      }

      await fetchHistory();
      return res;
    } catch (e: any) {
      error.value = `任务提交失败: ${e.message}`;
      throw e;
    }
  }

  // 3. 加载任务结果与详情
  async function loadTaskResult(taskId: string) {
    if (!taskId) return;
    activeTaskId.value = taskId;
    error.value = null;

    const existing = historyTasks.value.find(t => t.id === taskId);
    if (existing) {
      currentTask.value = { ...existing };
      isRunning.value = existing.status === 'running';
    }

    try {
      const res = await apiGet(`/api/assembly/result/${taskId}`);
      if (res && res.code === 200 && res.data) {
        resultData.value = res.data;
        if (currentTask.value) {
          currentTask.value.status = res.data.status;
          currentTask.value.results = res.data.stats;
        }
      }
    } catch (e: any) {
      console.warn(`[useAssembly] 加载任务结果失败 (${taskId}):`, e);
    }
  }

  // 4. 取消/终止任务
  async function cancelTask(taskId: string) {
    if (!taskId) return;
    try {
      consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] 正在发送终止指令: ${taskId}...`);
      await apiPost(`/api/assembly/stop/${taskId}`);
      
      if (currentTask.value && currentTask.value.id === taskId) {
        currentTask.value.status = 'aborted';
        isRunning.value = false;
      }
      await fetchHistory();
    } catch (e: any) {
      error.value = `终止任务失败: ${e.message}`;
    }
  }

  // 5. 删除任务
  async function deleteTask(taskId: string) {
    if (!taskId) return;
    try {
      await apiDelete(`/api/assembly/tasks/${taskId}`);
      historyTasks.value = historyTasks.value.filter(t => t.id !== taskId);
      
      if (activeTaskId.value === taskId) {
        activeTaskId.value = '';
        currentTask.value = null;
        resultData.value = null;
        isRunning.value = false;
      }
      await fetchHistory();
    } catch (e: any) {
      error.value = `删除任务失败: ${e.message}`;
    }
  }

  // 6. 下载 FASTA 产物
  function downloadFasta(taskId: string) {
    if (!taskId) return;
    const downloadUrl = `${API_BASE}/api/assembly/download/${taskId}`;
    window.open(downloadUrl, '_blank');
  }

  // 7. WebSocket 实时遥测事件监听
  let unsubscribeProgress: (() => void) | null = null;
  let pollingTimer: any = null;

  onMounted(async () => {
    await fetchHistory();

    // 监听 assembly_progress 广播
    unsubscribeProgress = onEvent((type: string, data: any) => {
      if (type === 'assembly_progress' && data) {
        const { task_id, step, progress, status, stats } = data;
        
        // 更新历史任务列表中匹配的任务
        const matched = historyTasks.value.find(t => t.id === task_id);
        if (matched) {
          matched.progress = progress;
          matched.last_step = step;
          matched.status = status;
          if (stats) matched.results = stats;
        }

        // 如果是当前聚焦任务
        if (activeTaskId.value === task_id || (!activeTaskId.value && currentTask.value?.id === task_id)) {
          if (currentTask.value) {
            currentTask.value.progress = progress;
            currentTask.value.last_step = step;
            currentTask.value.status = status;
            if (stats) currentTask.value.results = stats;
          }
          if (step) {
            consoleLogs.value.push(`[${new Date().toLocaleTimeString()}] ${step}`);
          }
          if (status === 'success' || status === 'completed') {
            isRunning.value = false;
            loadTaskResult(task_id);
          } else if (status === 'failed' || status === 'aborted') {
            isRunning.value = false;
          } else if (status === 'running') {
            isRunning.value = true;
          }
        }
      }
    });

    // 智能轮询队列状态 (每 3 秒一次)
    pollingTimer = setInterval(async () => {
      if (isRunning.value || queueStatus.value?.is_busy || historyTasks.value.some(t => t.status === 'running' || t.status === 'queued')) {
        await fetchHistory();
        if (activeTaskId.value && isRunning.value) {
          const matched = historyTasks.value.find(t => t.id === activeTaskId.value);
          if (matched && (matched.status === 'completed' || matched.status === 'failed')) {
            isRunning.value = false;
            await loadTaskResult(activeTaskId.value);
          }
        }
      }
    }, 3000);
  });

  onUnmounted(() => {
    if (unsubscribeProgress) unsubscribeProgress();
    if (pollingTimer) clearInterval(pollingTimer);
  });

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
    downloadFasta
  };
}
