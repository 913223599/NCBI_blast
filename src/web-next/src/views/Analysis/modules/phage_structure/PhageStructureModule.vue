<script setup lang="ts">
import { watch } from 'vue'
import { usePhageStructure } from './composables/usePhageStructure'
import type { StructureInitialPayload } from './types'
import StructureHistory from './components/StructureHistory.vue'
import StructureProgress from './components/StructureProgress.vue'
import StructureQueueCard from './components/StructureQueueCard.vue'
import StructureResults from './components/StructureResults.vue'
import StructureSetup from './components/StructureSetup.vue'

const props = defineProps<{
  initialPayload?: StructureInitialPayload | null
}>()

const emit = defineEmits<{
  (e: 'open-viewer', payload: { gbkText: string; taskName: string }): void
}>()

const {
  capabilities,
  linkedSources,
  historyList,
  currentTask,
  currentResult,
  queueStatus,
  consoleLogs,
  errorMsg,
  isCapabilitiesLoading,
  isSourcesLoading,
  isInspecting,
  isSubmitting,
  isResultLoading,
  isQueued,
  isRunning,
  isQueueBusy,
  inspectedContigs,
  inspectTotalBp,
  loadLinkedSources,
  inspectInput,
  submitTask,
  selectTask,
  startNewTask,
  cancelTask,
  deleteTask,
  downloadFile,
  openResultsFolder,
  fetchGbkForViewer,
} = usePhageStructure()

watch(
  () => props.initialPayload,
  (val) => {
    if (val && val.taskId) {
      startNewTask()
      loadLinkedSources()
    }
  },
  { immediate: true }
)

async function handleOpenViewer(): Promise<void> {
  if (!currentTask.value) return
  try {
    const payload = await fetchGbkForViewer(currentTask.value.task_id)
    if (payload.gbkText) {
      emit('open-viewer', payload)
    } else {
      ;(window as any).app?.showNotification('该任务不包含核酸序列，无法在序列图谱查看', 'warning')
    }
  } catch (err) {
    ;(window as any).app?.showNotification(`打开基因组图谱失败: ${String(err)}`, 'error')
  }
}
</script>

<template>
  <div class="structure-module-container">
    <div class="desktop-layout">
      <!-- 1. 左侧历史任务栏 -->
      <aside class="sidebar">
        <div class="sidebar-top">
          <div class="sidebar-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
              <polygon points="12 2 19 6 19 13 12 17 5 13 5 6" />
              <line x1="12" y1="17" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </svg>
            <span>结构与尾型预测记录</span>
          </div>
          <button type="button" class="new-task-btn" @click="startNewTask">新建</button>
        </div>

        <div class="sidebar-list">
          <StructureHistory
            :tasks="historyList"
            :active-task-id="currentTask?.task_id"
            @select="selectTask"
            @delete="deleteTask"
          />
        </div>
      </aside>

      <!-- 2. 右侧主内容工作区 -->
      <main class="main-content">
        <div v-if="errorMsg" class="error-banner">
          <span>{{ errorMsg }}</span>
        </div>

        <!-- 2.1 新建与导入配置 -->
        <section v-if="!currentTask" key="setup">
          <StructureSetup
            :capabilities="capabilities"
            :linked-sources="linkedSources"
            :is-capabilities-loading="isCapabilitiesLoading"
            :is-sources-loading="isSourcesLoading"
            :is-inspecting="isInspecting"
            :is-submitting="isSubmitting"
            :is-queue-busy="isQueueBusy"
            :inspected-contigs="inspectedContigs"
            :inspect-total-bp="inspectTotalBp"
            :initial-payload="initialPayload"
            @submit="submitTask"
            @inspect="inspectInput"
            @refresh-sources="loadLinkedSources"
          />
        </section>

        <!-- 2.2 排队等待 -->
        <section v-else-if="isQueued" :key="`queued-${currentTask.task_id}`">
          <StructureQueueCard
            :task="currentTask"
            :queue-status="queueStatus"
            @cancel="cancelTask(currentTask.task_id)"
            @start-new="startNewTask"
          />
        </section>

        <!-- 2.3 运行进度 -->
        <section v-else-if="isRunning" :key="`running-${currentTask.task_id}`">
          <StructureProgress
            :progress="currentTask.progress"
            :current-step="currentTask.current_step"
            :logs="consoleLogs"
            :task-id="currentTask.task_id"
            @cancel="cancelTask(currentTask.task_id)"
            @start-new="startNewTask"
          />
        </section>

        <!-- 2.4 完整结果呈现 -->
        <section v-else-if="currentTask.status === 'completed'" :key="`res-${currentTask.task_id}`">
          <StructureResults
            :task="currentTask"
            :result="currentResult"
            :is-loading="isResultLoading"
            @download="(ft) => downloadFile(currentTask!.task_id, ft)"
            @open-folder="openResultsFolder(currentTask!.task_id)"
            @open-viewer="handleOpenViewer"
          />
        </section>

        <!-- 2.5 失败或取消状态 -->
        <section v-else :key="`err-${currentTask.task_id}`" class="status-box">
          <h3>任务状态: {{ currentTask.status === 'failed' ? '执行失败' : '已取消' }}</h3>
          <p>{{ currentTask.error_msg || currentTask.current_step }}</p>
          <button type="button" class="retry-btn" @click="startNewTask">返回重新配置</button>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.structure-module-container {
  width: 100%;
  padding: 20px 24px;
  box-sizing: border-box;
}

.desktop-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 20px;
  align-items: start;
}

.sidebar {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px;
  position: sticky;
  top: 16px;
}

.sidebar-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
}

.new-task-btn {
  padding: 5px 12px;
  border-radius: 7px;
  border: none;
  background: #2563eb;
  color: #ffffff;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.sidebar-list {
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

.main-content {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.error-banner {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.85rem;
}

.status-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 36px 24px;
  text-align: center;
}

.retry-btn {
  margin-top: 12px;
  padding: 8px 18px;
  border-radius: 8px;
  border: none;
  background: #2563eb;
  color: #ffffff;
  font-weight: 600;
  cursor: pointer;
}

@media (max-width: 960px) {
  .desktop-layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: static;
  }
}
</style>
