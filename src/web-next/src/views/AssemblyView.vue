<script setup lang="ts">
/**
 * AssemblyView - 二代基因组拼接仪表盘 (重构版)
 * 采用左侧配置、右侧操作的专业布局，最大化提升操作流流畅度。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useAssembly } from './Assembly/composables/useAssembly'
import { onEvent } from '../bridge'
import AssemblyStepper from './Assembly/components/AssemblyStepper.vue'
import FileUploadZone from './Assembly/components/FileUploadZone.vue'
import ConfigPanel from './Assembly/components/ConfigPanel.vue'
import ActionHeader from './Assembly/components/ActionHeader.vue'
import HistoryDrawer from './Assembly/components/HistoryDrawer.vue'

const { 
  taskState, isRunning, currentStep, history, selectedFiles, showResults,
  queueStatus, queuePaused,
  fetchHistory, startTask, stopTask, deleteTask, pickCustomHost,
  resumeTask, restartTask, updateQueueStatus, submitBatch, reorderQueue
} = useAssembly()

// 🔗 队列拖拽管理状态
const draggedQueueIdx = ref<number | null>(null)

const onQueueDragStart = (idx: number, event: DragEvent) => {
  draggedQueueIdx.value = idx
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.dropEffect = 'move'
  }
}

const onQueueDrop = (dropIdx: number) => {
  if (draggedQueueIdx.value === null || draggedQueueIdx.value === dropIdx) return
  
  // 仅在前端视觉上重排，随后下发后端全量 ID 列表确立顺序
  const newQueue = [...queueStatus.value]
  const [movedItem] = newQueue.splice(draggedQueueIdx.value, 1)
  newQueue.splice(dropIdx, 0, movedItem)
  
  queueStatus.value = newQueue
  const taskIds = newQueue.map(t => t.id)
  if (reorderQueue) reorderQueue(taskIds)
  
  draggedQueueIdx.value = null
}

const handleQueueDelete = (taskId: string, status: string) => {
  if (status === 'running') {
    stopTask(taskId)
  } else {
    deleteTask(taskId)
  }
}

const showHistory = ref(false)

const handleOpenResults = async (taskId: string) => {
  if (!taskId) return;
  try {
    const root = await (window as any).electronAPI?.getProjectRoot();
    if (root) {
      const fullPath = `${root}/results/assembly/${taskId}`;
      await (window as any).electronAPI?.openPath(fullPath);
    }
  } catch (e) {
    console.error('无法打开结果目录:', e);
  }
};

let cleanup: (() => void) | null = null;

onMounted(async () => {
  if (typeof fetchHistory === 'function') await fetchHistory();
  
  cleanup = onEvent(async (type: string, data: any) => {
    // 1. 处理过程进度 (来自 AssemblyManager)
    if (type === 'assembly_progress') {
      if (data.progress !== undefined) {
        if (data.task_id) taskState.id = data.task_id;
        taskState.progress = data.progress;
        taskState.stage = data.step as any;
        isRunning.value = true;
        
        const isPhage = String(taskState.sampleType) === 'PHAGE';
        const steps = isPhage 
          ? ['数据质控', '宿主剔除', '读长合并', '基因组组装', '前噬菌体分离', '支架构建', '一致性校正', '功能注释']
          : ['数据质控', '读长合并', '基因组组装', '支架构建', '一致性校正', '功能注释'];
        
        const idx = steps.indexOf(data.step.split(' ')[0]);
        if (idx !== -1) currentStep.value = idx;
        
        // 🔗 联动效应：同步更新侧边栏历史列表中的状态
        const hTask = history.value.find(h => h.id === data.task_id);
        if (hTask && hTask.status !== 'running') {
          hTask.status = 'running';
        }

        if (data.status === 'success') {
          isRunning.value = false;
          currentStep.value = 5;
          await fetchHistory();
        } else if (data.status === 'failed' || data.status === 'error' || data.status === 'aborted') {
          isRunning.value = false;
          await fetchHistory();
          if (data.message) {
             (window as any).app?.showNotification(data.message, 'error');
          }
        }
      }
    }
    
    // 2. 处理全局状态/错误 (来自 AssemblyWorker)
    if (type === 'assembly_status') {
      isRunning.value = false;
      if (data.status === 'waiting_env' && data.message === 'NEED_CONDA') {
        (window as any).app?.showNotification('未检测到拼接环境 (Conda)，正在尝试自动部署...', 'warning');
      } else if (data.status === 'error') {
        (window as any).app?.showNotification(`任务失败: ${data.error || '未知错误'}`, 'error');
      } else if (data.status === 'finished') {
        currentStep.value = 5;
        (window as any).app?.showNotification('拼接任务已成功完成！', 'success');
        await fetchHistory();
      }
    }

    // 3. 处理队列状态变更 (来自 PersistentAssemblyQueue)
    if (type === 'assembly_queue_status') {
      updateQueueStatus(data);
    }
  });
});

onUnmounted(() => {
  if (cleanup) cleanup();
});
</script>

<template>
  <div class="assembly-layout">
    <!-- 顶部导航栏 -->
    <header class="top-nav">
      <ActionHeader 
        class="main-header"
        :isRunning="isRunning" 
        :canStart="selectedFiles.length > 0"
        :onStart="startTask"
        :onStop="() => stopTask('current')"
        :onToggleHistory="() => showHistory = true"
        :queueCount="queueStatus.length"
      />
    </header>

    <main class="dashboard-content">
      <!-- 左侧：参数控制面板 (380px 固定) -->
      <aside class="sidebar-config">
        <ConfigPanel 
          v-model:taskState="taskState"
          :isRunning="false"
          :onPickCustomHost="pickCustomHost"
        />
      </aside>

      <!-- 核心：数据与进度画布 -->
      <section class="main-canvas">
        <!-- 🔗 队列状态条 -->
        <div v-if="queueStatus.length > 0" class="queue-status-bar">
          <span class="queue-icon">📋</span>
          <span>队列中 <strong>{{ queueStatus.length }}</strong> 个任务</span>
          <span v-if="queuePaused" class="queue-badge paused">⏸ 已暂停</span>
          <span class="queue-tasks">
            <span v-for="(q, idx) in queueStatus.slice(0, 5)" :key="q.id" class="queue-chip"
              :class="{ active: q.status === 'running' }"
              :draggable="q.status !== 'running'"
              @dragstart="q.status !== 'running' ? onQueueDragStart(idx, $event) : null"
              @dragover.prevent
              @drop="q.status !== 'running' ? onQueueDrop(idx) : null">
              {{ q.name || q.id }}
              <!-- 右上角悬浮删除按钮 (仅队列等待中的允许叉掉，运行中的通过停止按钮) -->
              <span v-if="q.status !== 'running'" class="queue-delete-btn" @click.stop="handleQueueDelete(q.id, q.status)">×</span>
            </span>
          </span>
        </div>

        <div class="canvas-header">
           <AssemblyStepper 
            :currentStep="currentStep" 
            :sampleType="taskState.sampleType"
            :progress="taskState.progress"
            :stage="taskState.stage"
            :taskId="taskState.id"
            @openResults="handleOpenResults"
          />
        </div>
        
        <div class="canvas-body">
          <FileUploadZone 
            v-model:selectedFiles="selectedFiles"
            :disabled="false"
          />
        </div>
      </section>
    </main>

    <!-- 任务历史抽屉 -->
    <HistoryDrawer 
      :show="showHistory" 
      :history="history" 
      @close="showHistory = false"
      @delete="deleteTask"
      @resume="resumeTask"
      @restart="restartTask"
    />
  </div>
</template>

<style scoped>
.assembly-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  overflow: hidden;
}

.top-nav {
  height: 80px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0,0,0,0.05);
  display: flex;
  align-items: center;
  padding: 0 40px;
  z-index: 100;
}

.main-header { width: 100%; }

.dashboard-content {
  flex: 1;
  display: flex;
  overflow: hidden;
  padding: 24px;
  gap: 24px;
}

.sidebar-config {
  width: 400px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  border-radius: 16px;
  scrollbar-width: none;
}
.sidebar-config::-webkit-scrollbar { display: none; }

.main-canvas {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto;
}

.canvas-header {
  flex: 0;
}

.canvas-body {
  flex: 1;
  display: flex;
  flex-direction: column;
}

@media (max-width: 1200px) {
  .dashboard-content { flex-direction: column; overflow-y: auto; }
  .sidebar-config { width: 100%; }
  .assembly-layout { overflow-y: auto; height: auto; }
}

/* 队列状态条 */
.queue-status-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: rgba(59, 130, 246, 0.06);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 10px;
  font-size: 13px;
  color: #475569;
  flex-wrap: wrap;
}
.queue-icon { font-size: 16px; }
.queue-tasks { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
.queue-chip {
  position: relative;
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.12);
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
  cursor: grab;
  user-select: none;
  transition: all 0.2s;
}
.queue-chip:active { cursor: grabbing; opacity: 0.7; }
.queue-chip.active {
  background: rgba(30, 160, 255, 0.2);
  color: #1ea0ff;
  border-color: rgba(30, 160, 255, 0.3);
}

.queue-delete-btn {
  display: none;
  position: absolute;
  top: -6px;
  right: -6px;
  width: 16px;
  height: 16px;
  line-height: 14px;
  text-align: center;
  background: var(--bio-error, #f44336);
  color: white;
  border-radius: 50%;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.queue-chip:hover .queue-delete-btn {
  display: block;
}
.queue-delete-btn:hover {
  background: #d32f2f;
  transform: scale(1.1);
}
.queue-badge.paused {
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  font-size: 11px;
  font-weight: 600;
}
</style>
