<script setup lang="ts">
/**
 * BlastView - BLAST 分析视图
 * 采用组件化重构，遵循单一职责原则。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useBlastStore } from '../stores/blast'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge'
import { useI18n } from '../locales'
import { useBlastTaskManager } from '../composables/useBlastTaskManager'
import { useBlastResultHandler } from '../composables/useBlastResultHandler'
import { useBlastDetailViewer } from '../composables/useBlastDetailViewer'

// 子组件
import BlastInputPanel from '../components/blast/BlastInputPanel.vue'
import BlastParamsPanel from '../components/blast/BlastParamsPanel.vue'
import BlastHistoryPanel from '../components/blast/BlastHistoryPanel.vue'
import BlastResultsTable from '../components/blast/BlastResultsTable.vue'
import BlastVisualModal from '../components/blast/BlastVisualModal.vue'
import BlastDetailDialog from '../components/blast/BlastDetailDialog.vue'
import DiversityAnalysisModal from '../components/blast/DiversityAnalysisModal.vue'

const blast = useBlastStore()
const appStore = useAppStore()
const { t } = useI18n()

// 注入Composables
const taskManager = useBlastTaskManager()
const resultHandler = useBlastResultHandler()
const { isTranslating, fetchTaskResults, exportResults, translateAll } = resultHandler

const detailViewer = useBlastDetailViewer()
const { 
  showAllHitsDialog, 
  allHitsData, 
  currentQueryTitle,
  _isLocked,
  _hasUserInteracted,
  _isOpenInternal
} = detailViewer

/* -------- 布局状态 -------- */
const activeSideTool = ref<'input' | 'params' | 'history'>('input')
const isSidebarOpen = ref(true)
const openDropdown = ref<string | null>(null)
const editingTaskId = ref<string | null>(null)
const editName = ref('')
const historyPanelRef = ref<any>(null)

/* -------- 可视化状态 -------- */
const showVisualModal = ref(false)
const visualData = ref<any>(null)
const visualLoading = ref(false)
const visualSortMode = ref('evalue')
const currentXmlPath = ref('')
const currentVisQueryTitle = ref('')

/* -------- 16S 扩增子混样多样性状态 -------- */
const diversityPanelRef = ref<any>(null)
const diversityInitialPath = ref<string>('')
const activeDiversityTaskId = ref<string>('')

function openDiversityWithFile(path?: string, openHistory?: boolean) {
  blast.setAnalysisTarget('diversity')
  diversityInitialPath.value = path || (blast.files && blast.files.length > 0 ? (blast.files[0] || '') : '')
  if (openHistory) {
    activeSideTool.value = 'history'
    isSidebarOpen.value = true
    historyPanelRef.value?.fetchDiversityTasks?.()
  }
}

function handleSelectDiversityTask(task: any) {
  activeDiversityTaskId.value = task.task_id
  blast.setAnalysisTarget('diversity')
  diversityPanelRef.value?.selectHistoryTask?.(task)
}

function handleDiversityTaskChanged(tid: string) {
  activeDiversityTaskId.value = tid
}

function showAlignmentMap(hit: any) {
  if (!hit.xmlFile) {
    appStore.showNotification('该结果没有可用的原始比对数据', 'warning')
    return
  }
  showVisualModal.value = true
  visualLoading.value = true
  currentXmlPath.value = hit.xmlFile
  currentVisQueryTitle.value = hit.queryTitle || ''
  visualData.value = null 
  fetchVisualData()
}

function fetchVisualData() {
  visualLoading.value = true
  getBridge().get_alignment_visualization_data(
    currentXmlPath.value, 
    visualSortMode.value, 
    currentVisQueryTitle.value, 
    (resStr: string) => {
      visualLoading.value = false
      try {
        const data = JSON.parse(resStr)
        if (data.error) {
          appStore.showNotification(`可视化提示: ${data.error}`, 'warning')
          showVisualModal.value = false
        } else {
          visualData.value = data
        }
      } catch {
        appStore.showNotification('解析可视化数据失败', 'error')
        showVisualModal.value = false
      }
    }
  )
}

/* -------- BLAST 交互逻辑 -------- */
function launchBlast(): void {
  // 多样性鉴定模式下直接触发右侧内嵌多样性分析
  if (blast.analysisTarget === 'diversity') {
    if (diversityPanelRef.value?.startAnalysis) {
      diversityPanelRef.value.startAnalysis()
    } else {
      openDiversityWithFile()
    }
    return
  }

  if (!blast.hasInput) {
    appStore.showNotification('请先选择序列文件或粘贴序列', 'warning')
    return
  }
  
  try {
    const generatedTaskName = getFormattedTimestamp()
    const payload = JSON.stringify({
      task_name: generatedTaskName,
      mode: blast.inputMode,
      files: blast.files,
      query: blast.queryText,
      program: blast.params.program,
      database: blast.params.database,
      evalue: blast.params.evalue,
      hitlist_size: blast.params.maxHits,
      matrix_name: blast.params.matrix,
      gap_open: blast.params.gapOpen,
      gap_extend: blast.params.gapExtend,
      filter: blast.params.filterLowComplexity
    })

    getBridge().run_blast_job(payload, (resStr: string) => {
      try {
        const res = JSON.parse(resStr)
        if (res.status === 'started' && res.task_id) {
          blast.addTask({
            taskId: res.task_id,
            fileName: generatedTaskName,
            status: 'queued',
            progress: 0,
            startTime: new Date().toISOString()
          })
          blast.clearFiles()
          blast.queryText = ''
          appStore.showNotification('任务已提交', 'success')
          activeSideTool.value = 'history'
          isSidebarOpen.value = true
          taskManager.startPolling(res.task_id, (taskId) => {
            resultHandler.fetchTaskResults(taskId)
          })
        } else {
          appStore.showNotification('启动失败: ' + (res.error || '未知错误'), 'error')
        }
      } catch (e) {
        appStore.showNotification('解析返回失败', 'error')
      }
    })
  } catch (error) {
    appStore.showNotification('启动失败', 'error')
  }
}

function selectTask(taskId: string): void {
  blast.setActiveTask(taskId)
  fetchTaskResults(taskId)
}

function toggleSideTool(tool: 'input' | 'params' | 'history') {
  if (activeSideTool.value === tool && isSidebarOpen.value) {
    isSidebarOpen.value = false
  } else {
    activeSideTool.value = tool
    isSidebarOpen.value = true
  }
}

function getFormattedTimestamp(date: string | Date = new Date()) {
  const d = new Date(date)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

/* -------- 历史操作中转 -------- */
function startRename(task: any, event: Event) {
  event.stopPropagation()
  editingTaskId.value = task.taskId
  editName.value = task.fileName
  setTimeout(() => { historyPanelRef.value?.renameInputRef?.focus(); historyPanelRef.value?.renameInputRef?.select(); }, 50)
}

function commitRename(task: any) {
  if (editingTaskId.value === task.taskId) {
    const trimmed = editName.value.trim()
    if (trimmed && trimmed !== task.fileName) {
      task.fileName = trimmed
      taskManager.renameTask(task.taskId, trimmed)
    }
    editingTaskId.value = null
  }
}

function refreshTaskList(autoSelectTargetId?: string) {
  try {
    getBridge().get_all_tasks((resStr: string) => {
      try {
        const tasks = JSON.parse(resStr)
        if (Array.isArray(tasks)) {
          blast.tasks = tasks.map(t => ({
            taskId: t.task_id,
            fileName: t.task_name || getFormattedTimestamp(t.start_time),
            status: t.status,
            progress: t.progress || 0,
            startTime: t.start_time
          }))

          // 决定要激活的任务 ID
          const firstTaskId = blast.tasks.length > 0 ? (blast.tasks[0]?.taskId || null) : null
          const targetId = autoSelectTargetId || blast.activeTaskId || firstTaskId

          if (targetId) {
            const found = blast.tasks.find(t => t.taskId === targetId)
            if (found) {
              blast.setActiveTask(targetId)
              activeSideTool.value = 'history'
              isSidebarOpen.value = true
              fetchTaskResults(targetId)

              if (['running', 'pending'].includes(found.status)) {
                taskManager.startPolling(targetId, (doneId) => {
                  fetchTaskResults(doneId)
                })
              }
            }
          }

          // 启动其它所有 running 任务的后台状态同步
          blast.tasks.forEach(t => {
            if (t.status === 'running' && t.taskId !== targetId) {
              taskManager.startPolling(t.taskId, (doneId) => {
                if (blast.activeTaskId === doneId) {
                  fetchTaskResults(doneId)
                }
              })
            }
          })
        }
      } catch (e) {
        console.error('Failed to parse tasks:', e)
      }
    })
  } catch (e) {
    console.error('Failed to get tasks:', e)
  }
}

watch(() => blast.activeTaskId, (newId) => {
  if (newId) {
    refreshTaskList(newId)
  }
})

onMounted(() => {
  // 防御性重置
  _isLocked.value = true
  _hasUserInteracted.value = false
  _isOpenInternal.value = false
  detailViewer.closeDialog()
  
  document.addEventListener('click', () => { openDropdown.value = null; })
  
  // 挂载时立即刷新，并执行两次延时保底以确保跨模块新创建任务已落库
  refreshTaskList()
  setTimeout(() => { refreshTaskList(); }, 200)
  setTimeout(() => { refreshTaskList(); }, 600)
})

onUnmounted(() => {
  taskManager.cleanup()
})
</script>

<template>
  <div class="blast-workspace-container">
    <!-- 顶部工具栏 -->
    <div class="blast-toolbar-top">
      <div class="tool-items">
        <div class="tool-btn" :class="{ active: activeSideTool === 'input' && isSidebarOpen }" @click="toggleSideTool('input')">
          <svg class="tool-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
          </svg>
          <span class="label">{{ t('blast.nav.input') }}</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'params' && isSidebarOpen }" @click="toggleSideTool('params')">
          <svg class="tool-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="12" cy="12" r="3" stroke-width="2"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
          <span class="label">{{ t('blast.nav.params') }}</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'history' && isSidebarOpen }" @click="toggleSideTool('history')">
          <svg class="tool-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="12" cy="12" r="9" stroke-width="2"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 7v5l3 3"/>
          </svg>
          <span class="label">{{ t('blast.nav.history') }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <button 
          class="btn-primary-run" 
          @click="launchBlast" 
          :disabled="blast.analysisTarget === 'isolate' && !blast.hasInput"
        >
          {{ blast.analysisTarget === 'diversity' ? '执行多样性比对' : t('blast.btn.run') }}
        </button>
      </div>
    </div>

    <div class="blast-main-area">
      <!-- 动态侧边栏 -->
      <div class="blast-sidebar" :class="{ collapsed: !isSidebarOpen }">
        <div class="sidebar-content scroll-v">
          <BlastInputPanel 
            v-show="activeSideTool === 'input'" 
            @open-diversity-modal="openDiversityWithFile"
          />
          
          <BlastParamsPanel 
            v-show="activeSideTool === 'params'" 
            :open-dropdown="openDropdown"
            @toggle-dropdown="(id) => openDropdown = openDropdown === id ? null : id"
            @select-option="(id, val) => {
              if (id === 'program') blast.params.program = val
              else if (id === 'database') blast.params.database = val
              else if (id === 'matrix') blast.params.matrix = val
              openDropdown = null
            }"
          />
          
          <BlastHistoryPanel 
            v-show="activeSideTool === 'history'" 
            ref="historyPanelRef"
            :editing-task-id="editingTaskId"
            :active-diversity-task-id="activeDiversityTaskId"
            v-model:edit-name="editName"
            @select-task="selectTask"
            @start-rename="startRename"
            @commit-rename="commitRename"
            @pause-task="(id) => taskManager.pauseTask(id)"
            @resume-task="(id) => taskManager.resumeTask(id, (tid) => taskManager.startPolling(tid, fetchTaskResults))"
            @stop-task="(id) => taskManager.stopTask(id)"
            @delete-task="(id) => taskManager.deleteTask(id)"
            @clear-history="() => taskManager.clearAllHistory()"
            @select-diversity-task="handleSelectDiversityTask"
            @delete-diversity-task="(id) => { if (activeDiversityTaskId === id) activeDiversityTaskId = '' }"
            @clear-diversity-history="() => { activeDiversityTaskId = '' }"
          />
        </div>
        <div class="sidebar-collapse-toggle" @click="isSidebarOpen = !isSidebarOpen">
           {{ isSidebarOpen ? '◀' : '▶' }}
        </div>
      </div>

      <!-- 结果主区域: 单株鉴定结果 vs 16S多样性分析结果 (内嵌无缝切换，不再单开浮窗) -->
      <BlastResultsTable 
        v-if="blast.analysisTarget === 'isolate'"
        :is-translating="isTranslating"
        @view-all-hits="detailViewer.viewAllHits"
        @show-alignment-map="showAlignmentMap"
        @translate-all="translateAll"
        @export-results="exportResults"
      />

      <DiversityAnalysisModal 
        v-else-if="blast.analysisTarget === 'diversity'"
        ref="diversityPanelRef"
        :embedded="true"
        :initial-file-path="diversityInitialPath"
        @switch-to-isolate="blast.setAnalysisTarget('isolate')"
        @task-changed="handleDiversityTaskChanged"
      />
    </div>

    <!-- 弹窗组件 -->
    <BlastVisualModal 
      :show="showVisualModal"
      :loading="visualLoading"
      :data="visualData"
      v-model:sort-mode="visualSortMode"
      @fetch-data="fetchVisualData"
      @close="showVisualModal = false"
    />

    <BlastDetailDialog 
      :show="showAllHitsDialog && !!currentQueryTitle"
      :title="currentQueryTitle || ''"
      :data="allHitsData"
      @close="detailViewer.closeDialog"
    />
  </div>
</template>

<style scoped>
.blast-workspace-container { display: flex; flex-direction: column; height: 100%; background: white; overflow: hidden; }
.blast-toolbar-top { height: 60px; background: white; border-bottom: 1px solid #e2e8f0; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; z-index: 100; }
.tool-items { display: flex; align-items: center; gap: 8px; }
.tool-btn { display: flex; align-items: center; gap: 10px; padding: 8px 16px; cursor: pointer; border-radius: 10px; color: #64748b; font-weight: 600; font-size: 0.82rem; transition: all 0.2s; }
.tool-btn:hover { background: #f8fafc; color: #1e293b; }
.tool-btn.active { color: #2563eb; background: #eff6ff; }
.tool-svg { width: 17px; height: 17px; stroke-width: 2; flex-shrink: 0; }
.tool-divider { width: 1px; height: 24px; background: #e2e8f0; margin: 0 10px; }
.btn-primary-run { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; padding: 10px 24px; border-radius: 10px; font-weight: 700; font-size: 0.85rem; display: flex; align-items: center; gap: 10px; border: none; cursor: pointer; }
.btn-primary-run:hover:not(:disabled) { transform: translateY(-1px); }
.btn-primary-run:disabled { opacity: 0.5; cursor: not-allowed; }

.blast-main-area { flex: 1; display: flex; overflow: hidden; background: #f8fafc; }
.blast-sidebar { 
  width: auto; 
  background: transparent; 
  display: flex; 
  flex-direction: column; 
  position: relative; 
  z-index: 5; 
}
.blast-sidebar.collapsed { width: 0; }
.sidebar-content { 
  flex: 1; 
  overflow-y: auto; 
  overflow-x: hidden;
  padding: 20px; 
  width: 360px; 
  box-sizing: border-box; 
  background: white;
  border-right: 1px solid #e2e8f0;
  transition: width 0.3s ease, padding 0.3s ease, opacity 0.2s;
}
.collapsed .sidebar-content {
  width: 0;
  padding: 0;
  opacity: 0;
  border-right: none;
}
.sidebar-collapse-toggle { position: absolute; right: -12px; top: 50%; transform: translateY(-50%); width: 24px; height: 48px; background: white; border: 1px solid #e2e8f0; border-radius: 12px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 10; font-size: 0.7rem; color: #94a3b8; box-shadow: 2px 0 8px rgba(0,0,0,0.05); }
.sidebar-collapse-toggle:hover { color: #2563eb; background: #f8fafc; }
</style>