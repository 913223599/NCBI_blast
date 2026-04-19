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
  fetchHistory, startTask, stopTask, deleteTask, pickCustomHost,
  resumeTask, restartTask
} = useAssembly()

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
          ? ['数据质控', '宿主剔除', '基因组组装', '打磨校正', '功能注释']
          : ['数据质控', '基因组组装', '打磨校正', '功能注释'];
        
        const idx = steps.indexOf(data.step.split(' ')[0]);
        if (idx !== -1) currentStep.value = idx;

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
      />
    </header>

    <main class="dashboard-content">
      <!-- 左侧：参数控制面板 (380px 固定) -->
      <aside class="sidebar-config">
        <ConfigPanel 
          v-model:taskState="taskState"
          :isRunning="isRunning"
          :onPickCustomHost="pickCustomHost"
        />
      </aside>

      <!-- 核心：数据与进度画布 -->
      <section class="main-canvas">
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
            :disabled="isRunning"
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
</style>
