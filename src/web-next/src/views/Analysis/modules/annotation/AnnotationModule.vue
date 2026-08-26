<script setup lang="ts">
/**
 * AnnotationModule - 基因组功能注释工作台主模块
 * 采用 侧边栏-主内容 桌面端双栏架构
 */
import { ref, onMounted } from 'vue';
import { useAnnotation } from './composables/useAnnotation';
import AnnotationHistory from './components/AnnotationHistory.vue';
import AnnotationSetup from './components/AnnotationSetup.vue';
import AnnotationProgress from './components/AnnotationProgress.vue';
import AnnotationResults from './components/AnnotationResults.vue';
import type { AnnotationTaskItem, AnnotationRunParams } from './types';

const emit = defineEmits<{
  (e: 'open-viewer', payload: { gbkText: string; taskName: string }): void;
}>();

const {
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
} = useAnnotation();

// 是否显示新建任务表单
const showSetupForm = ref<boolean>(false);

onMounted(async () => {
  await fetchHistory();
  const firstTask = historyTasks.value[0];
  if (firstTask && !activeTaskId.value) {
    await loadTaskResult(firstTask.task_id);
  } else if (historyTasks.value.length === 0) {
    showSetupForm.value = true;
  }
});

async function onRunTask(params: AnnotationRunParams) {
  showSetupForm.value = false;
  await submitTask(params);
}

async function onSelectHistory(item: AnnotationTaskItem) {
  showSetupForm.value = false;
  await loadTaskResult(item.task_id);
}

function onOpenViewer(gbkText: string, taskName: string) {
  emit('open-viewer', { gbkText, taskName });
}

function onStartNew() {
  showSetupForm.value = true;
  activeTaskId.value = '';
  currentTask.value = null;
}
</script>

<template>
  <div class="annotation-module-container">
    <div class="desktop-layout">
      <!-- 1. 左侧侧边栏：历史任务列表 -->
      <aside class="sidebar">
        <div class="sidebar-top">
          <div class="sidebar-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
            </svg>
            <span>注释历史记录</span>
          </div>
          <button class="new-task-btn" @click="onStartNew" title="新建注释任务">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            新建
          </button>
        </div>

        <div class="sidebar-list">
          <AnnotationHistory 
            :tasks="historyTasks" 
            :active-id="activeTaskId" 
            :is-loading="isHistoryLoading"
            @select="onSelectHistory"
            @delete="deleteTask"
            @refresh="fetchHistory"
          />
        </div>
      </aside>

      <!-- 2. 右侧主工作区 (严格互斥渲染) -->
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

        <!-- 2.1 新建配置面板 (新建模式独占) -->
        <section v-if="showSetupForm || (!isRunning && !currentTask)" class="section-setup">
          <AnnotationSetup :is-running="isRunning" @run="onRunTask" />
        </section>

        <!-- 2.2 运行进度与终端面板 -->
        <section v-else-if="isRunning && currentTask" class="section-progress">
          <AnnotationProgress 
            :progress="currentTask.progress" 
            :current-step="currentTask.current_step"
            :logs="consoleLogs"
            :task-id="currentTask.task_id"
            @cancel="cancelTask(currentTask.task_id)"
            @view-results="loadTaskResult(currentTask.task_id)"
          />
        </section>

        <!-- 2.3 结果展示面板 -->
        <section v-else-if="currentTask && currentTask.status === 'completed'" class="section-results">
          <AnnotationResults 
            :task="currentTask"
            @open-in-viewer="(gbk, name) => onOpenViewer(gbk, name)"
            @download="(type) => downloadFile(currentTask!.task_id, type)"
          />
        </section>

        <!-- 2.4 任务失败或取消占位 -->
        <section v-else-if="currentTask" class="status-box">
          <div class="status-box-content">
            <div class="status-icon" :class="currentTask.status">
              <svg v-if="currentTask.status === 'failed'" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
              </svg>
              <svg v-else width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h3>任务状态: {{ currentTask.status === 'failed' ? '分析失败' : '已取消' }}</h3>
            <p>{{ currentTask.error_msg || currentTask.current_step }}</p>
            <button class="retry-btn" @click="onStartNew">重新配置分析</button>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.annotation-module-container {
  width: 100%;
  padding: 20px 24px;
}

.desktop-layout {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.sidebar {
  width: 290px;
  flex-shrink: 0;
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 16px 14px;
  position: sticky;
  top: 10px;
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.sidebar-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 0 2px;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #1e293b;
  font-size: 14px;
}

.new-task-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.new-task-btn:hover {
  background: #2563eb;
  color: white;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
}

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  color: #b91c1c;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
}

.err-icon {
  display: flex;
  align-items: center;
}

.status-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 40px 20px;
  text-align: center;
}

.status-box-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 400px;
  margin: 0 auto;
}

.status-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon.failed { background: #fee2e2; color: #dc2626; }
.status-icon.cancelled { background: #f1f5f9; color: #64748b; }

.status-box h3 {
  margin: 0;
  color: #1e293b;
  font-size: 16px;
}

.status-box p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.retry-btn {
  margin-top: 10px;
  background: #2563eb;
  color: white;
  border: none;
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
</style>
