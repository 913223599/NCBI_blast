<script setup lang="ts">
/**
 * AssemblyView - 基因组组装工作台 (纯净重构版)
 * 采用 侧边栏-主内容 桌面端双栏架构，全面对接 NGCS 引擎
 */
import { ref, onMounted } from 'vue';
import { useAssembly } from './Assembly/composables/useAssembly';
import AssemblyHistory from './Assembly/components/AssemblyHistory.vue';
import AssemblySetup from './Assembly/components/AssemblySetup.vue';
import AssemblyQueueCard from './Assembly/components/AssemblyQueueCard.vue';
import AssemblyProgress from './Assembly/components/AssemblyProgress.vue';
import AssemblyResults from './Assembly/components/AssemblyResults.vue';
import type { AssemblyTaskItem, AssemblyRunParams } from './Assembly/types';

const {
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
  openFolder
} = useAssembly();

// 是否显式处于“新建任务表单”模式
const showSetupForm = ref<boolean>(false);

onMounted(async () => {
  await fetchHistory();
  const firstTask = historyTasks.value[0];
  if (firstTask && !activeTaskId.value) {
    await loadTaskResult(firstTask.id);
  } else if (historyTasks.value.length === 0) {
    showSetupForm.value = true;
  }
});

async function onRunTask(params: AssemblyRunParams) {
  showSetupForm.value = false;
  try {
    await submitTask(params);
  } catch (e) {
    // 错误已在 composable 中处理
  }
}

async function onSelectHistory(item: AssemblyTaskItem) {
  showSetupForm.value = false;
  await loadTaskResult(item.id);
}

function onStartNew() {
  showSetupForm.value = true;
  activeTaskId.value = '';
  currentTask.value = null;
  resultData.value = null;
}

async function handleDeleteTask(taskId: string) {
  await deleteTask(taskId);
  if (!activeTaskId.value || !currentTask.value) {
    const nextTask = historyTasks.value[0];
    if (nextTask) {
      await loadTaskResult(nextTask.id);
    } else {
      showSetupForm.value = true;
    }
  }
}
</script>

<template>
  <div class="assembly-view-container">
    <div class="desktop-layout">
      <!-- 1. 左侧侧边栏：历史任务列表 -->
      <aside class="sidebar">
        <div class="sidebar-top">
          <div class="sidebar-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
            </svg>
            <span>拼接历史记录</span>
            <span v-if="queueStatus && queueStatus.waiting_count > 0" class="queue-counter-tag" :title="`当前有 ${queueStatus.waiting_count} 个任务在排队`">
              排队中 {{ queueStatus.waiting_count }}
            </span>
          </div>
          <button class="new-task-btn" @click="onStartNew" title="新建拼接任务">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            新建
          </button>
        </div>

        <div class="sidebar-list">
          <AssemblyHistory
            :tasks="historyTasks"
            :active-id="activeTaskId"
            :is-loading="isHistoryLoading"
            @select="onSelectHistory"
            @delete="handleDeleteTask"
            @refresh="fetchHistory"
          />
        </div>
      </aside>

      <!-- 2. 右侧主工作区 (严格状态互斥渲染) -->
      <main class="main-content">
        <!-- 错误横幅 -->
        <transition name="slide-fade">
          <div v-if="error" class="error-banner">
            <div class="err-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div class="err-msg">{{ error }}</div>
          </div>
        </transition>

        <!-- 2.1 新建配置面板 -->
        <section v-if="showSetupForm || !currentTask" key="setup-panel" class="section-pane">
          <AssemblySetup 
            :is-running="isRunning" 
            :is-busy="isEngineBusy" 
            @run="onRunTask" 
          />
        </section>

        <!-- 2.2 排队等待卡片 -->
        <section v-else-if="currentTask && (currentTask.status === 'queued' || currentTask.status === 'pending')" :key="`queued-${currentTask.id}`" class="section-pane">
          <AssemblyQueueCard
            :task="currentTask"
            :queue-status="queueStatus"
            @cancel="cancelTask(currentTask.id)"
            @start-new="onStartNew"
          />
        </section>

        <!-- 2.3 正在运行面板 -->
        <section v-else-if="currentTask && (currentTask.status === 'running' || isRunning)" :key="`running-${currentTask.id}`" class="section-pane">
          <AssemblyProgress
            :task="currentTask"
            :logs="consoleLogs"
            @cancel="cancelTask(currentTask.id)"
          />
        </section>

        <!-- 2.4 组装完成结果看板 -->
        <section v-else-if="currentTask" :key="`result-${currentTask.id}`" class="section-pane">
          <AssemblyResults
            :task="currentTask"
            :result="resultData"
            @download="downloadFasta(currentTask.id)"
            @open-folder="openFolder(currentTask.id)"
          />
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.assembly-view-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: #f8fafc;
  overflow: hidden;
}

.desktop-layout {
  display: flex;
  flex: 1;
  height: 100%;
  overflow: hidden;
}

/* 侧边栏 */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: white;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
}
.queue-counter-tag {
  font-size: 0.68rem;
  font-weight: 700;
  background: #fef3c7;
  color: #b45309;
  padding: 2px 6px;
  border-radius: 10px;
}

.new-task-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 10px;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.new-task-btn:hover {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.sidebar-list {
  flex: 1;
  overflow: hidden;
}

/* 主内容区 */
.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  gap: 16px;
  box-sizing: border-box;
  position: relative;
}

/* 美化全局滚动条 */
.main-content::-webkit-scrollbar {
  width: 6px;
}
.main-content::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
.main-content::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

.section-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

/* 错误横幅 */
.error-banner {
  margin: 12px 16px 0 16px;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #b91c1c;
  font-size: 0.8rem;
}
.err-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.err-msg {
  flex: 1;
  font-weight: 500;
}

.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.25s ease-out;
}
.slide-fade-enter-from,
.slide-fade-leave-to {
  transform: translateY(-8px);
  opacity: 0;
}
</style>
