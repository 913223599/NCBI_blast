<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePhageDiscovery } from './composables/usePhageDiscovery'
import type { PhageContigOverlayData } from './types'
import PhageDiscoveryHistory from './components/PhageDiscoveryHistory.vue'
import PhageDiscoveryProgress from './components/PhageDiscoveryProgress.vue'
import PhageDiscoveryQueueCard from './components/PhageDiscoveryQueueCard.vue'
import PhageDiscoveryResults from './components/PhageDiscoveryResults.vue'
import PhageDiscoverySetup from './components/PhageDiscoverySetup.vue'

const emit = defineEmits<{
  (e: 'open-viewer', payload: { gbkText: string; taskName: string }): void
  (e: 'open-annotation', payload: { fastaText: string; taskName: string; sampleType?: string }): void
}>()

const {
  capabilities,
  historyList,
  currentTask,
  currentResult,
  queueStatus,
  consoleLogs,
  errorMsg,
  isCapabilitiesLoading,
  isSubmitting,
  isResultLoading,
  isInspecting,
  isQueued,
  isRunning,
  isQueueBusy,
  inspectedContigs,
  inspectTotalBp,
  loadCapabilities,
  inspectInput,
  saveCustomConfig,
  submitTask,
  selectTask,
  startNewTask,
  cancelTask,
  deleteTask,
  downloadFile,
  openResultsFolder,
  fetchRegionGbk,
  fetchContigOverlay,
  fetchContigOverlayGbk,
  fetchFastaForAnnotation,
} = usePhageDiscovery()

const overlayData = ref<PhageContigOverlayData | null>(null)
const isOverlayLoading = ref<boolean>(false)
const overlayCache = new Map<string, PhageContigOverlayData>()
let activeOverlayRequestKey = ''

async function loadOverlayForContig(contigId?: string): Promise<void> {
  const taskId = currentTask.value?.task_id
  if (!taskId || currentTask.value?.status !== 'completed') return
  const targetCid =
    contigId ||
    currentResult.value?.contigs?.find((c) => c.hit_count > 0)?.id ||
    currentResult.value?.contigs?.[0]?.id
  if (!targetCid) {
    overlayData.value = null
    return
  }
  const cacheKey = `${taskId}:${targetCid}`
  activeOverlayRequestKey = cacheKey
  const cached = overlayCache.get(cacheKey)
  if (cached) {
    overlayData.value = cached
    return
  }
  isOverlayLoading.value = true
  try {
    const data = await fetchContigOverlay(taskId, targetCid)
    if (overlayCache.size > 16) {
      overlayCache.clear()
    }
    overlayCache.set(cacheKey, data)
    if (activeOverlayRequestKey === cacheKey) {
      overlayData.value = data
    }
  } catch (err) {
    console.warn('[PhageDiscovery] 加载 Contig 叠图分片失败:', err)
  } finally {
    if (activeOverlayRequestKey === cacheKey) {
      isOverlayLoading.value = false
    }
  }
}

watch(
  () => currentResult.value?.task_id,
  (tid) => {
    if (!tid) {
      overlayData.value = null
      return
    }
    loadOverlayForContig()
  }
)

async function handleOpenViewer(regionIndex: number): Promise<void> {
  if (!currentTask.value) return
  try {
    const payload = await fetchRegionGbk(currentTask.value.task_id, regionIndex)
    if (payload.gbkText) {
      emit('open-viewer', payload)
    } else {
      ;(window as any).app?.showNotification('未能获取到该区段的 GenBank 序列文件', 'warning')
    }
  } catch (err) {
    ;(window as any).app?.showNotification(`打开图谱失败: ${String(err)}`, 'error')
  }
}

async function handleOpenOverlayViewer(contigId: string): Promise<void> {
  if (!currentTask.value) return
  try {
    const payload = await fetchContigOverlayGbk(currentTask.value.task_id, contigId)
    if (payload.gbkText) {
      emit('open-viewer', payload)
    } else {
      ;(window as any).app?.showNotification('未能生成全基因组叠图 GenBank 文本', 'warning')
    }
  } catch (err) {
    ;(window as any).app?.showNotification(`打开全基因组叠图失败: ${String(err)}`, 'error')
  }
}

async function handleOpenAnnotation(regionIndex?: number): Promise<void> {
  if (!currentTask.value) return
  try {
    const res = await fetchFastaForAnnotation(currentTask.value.task_id, regionIndex)
    if (res.fastaText) {
      emit('open-annotation', {
        fastaText: res.fastaText,
        taskName: res.taskName,
        sampleType: 'PHAGE',
      })
    } else {
      ;(window as any).app?.showNotification('未检测到可用于注释的 FASTA 序列', 'warning')
    }
  } catch (err) {
    ;(window as any).app?.showNotification(`跳转注释工作台失败: ${String(err)}`, 'error')
  }
}
</script>

<template>
  <div class="phage-module-container">
    <div class="desktop-layout">
      <!-- 1. 左侧历史与队列状态栏 -->
      <aside class="sidebar">
        <div class="sidebar-top">
          <div class="sidebar-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <span>V4.2 扫描历史</span>
            <span
              v-if="queueStatus.running_count > 0 || queueStatus.queued_count > 0"
              class="queue-counter-tag"
              :title="`运行中: ${queueStatus.running_count}, 排队中: ${queueStatus.queued_count}`"
            >
              {{ queueStatus.running_count + queueStatus.queued_count }} 运行/排队
            </span>
          </div>
          <button type="button" class="new-task-btn" @click="startNewTask">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span>新建</span>
          </button>
        </div>

        <div class="sidebar-list">
          <PhageDiscoveryHistory
            :tasks="historyList"
            :active-task-id="currentTask?.task_id"
            @select="selectTask"
            @delete="deleteTask"
          />
        </div>
      </aside>

      <!-- 2. 右侧主内容区域 -->
      <main class="main-content">
        <div v-if="errorMsg" class="error-banner">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{{ errorMsg }}</span>
        </div>

        <!-- 2.1 新建配置 -->
        <section v-if="!currentTask" class="section-setup">
          <PhageDiscoverySetup
            :capabilities="capabilities"
            :is-capabilities-loading="isCapabilitiesLoading"
            :is-inspecting="isInspecting"
            :is-submitting="isSubmitting"
            :is-queue-busy="isQueueBusy"
            :inspected-contigs="inspectedContigs"
            :inspect-total-bp="inspectTotalBp"
            @submit="submitTask"
            @inspect="inspectInput"
            @save-config="saveCustomConfig"
            @refresh-capabilities="loadCapabilities"
          />
        </section>

        <!-- 2.2 排队等待卡片 -->
        <section v-else-if="isQueued" :key="`queued-${currentTask.task_id}`">
          <PhageDiscoveryQueueCard
            :task="currentTask"
            :queue-status="queueStatus"
            @cancel="cancelTask(currentTask.task_id)"
            @start-new="startNewTask"
          />
        </section>

        <!-- 2.3 运行推理进度 -->
        <section v-else-if="isRunning" :key="`progress-${currentTask.task_id}`">
          <PhageDiscoveryProgress
            :progress="currentTask.progress"
            :current-step="currentTask.current_step"
            :logs="consoleLogs"
            :task-id="currentTask.task_id"
            :status="currentTask.status"
            @cancel="cancelTask(currentTask.task_id)"
            @start-new="startNewTask"
          />
        </section>

        <!-- 2.3 完成结果展示 -->
        <section v-else-if="currentTask.status === 'completed'" :key="`results-${currentTask.task_id}`">
          <PhageDiscoveryResults
            :task="currentTask"
            :result="currentResult"
            :is-loading="isResultLoading"
            :overlay-data="overlayData"
            :is-overlay-loading="isOverlayLoading"
            @download="(fmt) => downloadFile(currentTask!.task_id, fmt)"
            @open-folder="openResultsFolder(currentTask!.task_id)"
            @open-viewer="handleOpenViewer"
            @open-overlay-viewer="handleOpenOverlayViewer"
            @open-annotation="handleOpenAnnotation"
            @contig-change="loadOverlayForContig"
          />
        </section>

        <!-- 2.4 失败或中止态 -->
        <section v-else :key="`status-${currentTask.task_id}`" class="status-box">
          <div class="status-box-content">
            <div class="status-icon" :class="currentTask.status">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <h3>任务状态: {{ currentTask.status === 'failed' ? '扫描失败' : '已中止' }}</h3>
            <p>{{ currentTask.error_msg || currentTask.current_step }}</p>
            <button type="button" class="retry-btn" @click="startNewTask">返回新建扫描</button>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.phage-module-container {
  width: 100%;
  padding: 20px 24px;
  box-sizing: border-box;
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
  font-weight: 700;
  color: #1e293b;
  font-size: 14px;
}

.queue-counter-tag {
  font-size: 11px;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
}

.new-task-btn {
  display: inline-flex;
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
  max-width: 440px;
  margin: 0 auto;
}

.status-icon {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  color: #64748b;
}

.status-icon.failed {
  background: #fee2e2;
  color: #dc2626;
}

.status-box h3 {
  margin: 0;
  font-size: 16px;
  color: #1e293b;
}

.status-box p {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.retry-btn {
  margin-top: 8px;
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

