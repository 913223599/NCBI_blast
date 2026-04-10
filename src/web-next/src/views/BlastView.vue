<script setup lang="ts">
/**
 * BlastView - BLAST 分析视图
 * 精简、现代、专业的工作区布局
 * 
 * 职责：
 * - UI渲染和用户交互
 * - 协调各个Composable模块
 */
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useBlastStore } from '../stores/blast'
import { useAppStore } from '../stores/app'
import { useStrainStore } from '../stores/strain'
import { getBridge } from '../bridge/pyqt-bridge'
import { useI18n } from '../locales'
import { useBlastTaskManager } from '../composables/useBlastTaskManager'
import { useBlastResultHandler } from '../composables/useBlastResultHandler'
import { useBlastDetailViewer } from '../composables/useBlastDetailViewer'

const blast = useBlastStore()
const appStore = useAppStore()
const strainStore = useStrainStore()
const router = useRouter()
const { t } = useI18n()

// 注入Composables
const taskManager = useBlastTaskManager()
const resultHandler = useBlastResultHandler()
const { isTranslating, fetchTaskResults, exportResults, translateAll } = resultHandler

// 使用并解构查看器状态，确保模板能自动解包 Ref
const detailViewer = useBlastDetailViewer()
const { 
  showAllHitsDialog, 
  allHitsData, 
  currentQueryTitle,
  _isLocked,
  _hasUserInteracted,
  _isOpenInternal
} = detailViewer

// 立即强制锁定，防止任何意外弹出
_isLocked.value = true
_hasUserInteracted.value = false
_isOpenInternal.value = false
detailViewer.closeDialog()

// 创建本地计算属性，添加更严格的保护
const shouldShowDetailDialog = computed(() => {
  // 必须同时满足所有条件
  const hasValidTitle = currentQueryTitle.value && 
                        typeof currentQueryTitle.value === 'string' && 
                        currentQueryTitle.value.trim().length > 0
  
  return showAllHitsDialog.value && hasValidTitle
})

/* -------- 核心状态 -------- */
const activeSideTool = ref<'input' | 'params' | 'history'>('input')
const isSidebarOpen = ref(true)
const openDropdown = ref<string | null>(null)
const editingTaskId = ref<string | null>(null)
const editName = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

/* -------- BLAST 交互逻辑 -------- */
function selectFiles(): void {
  try {
    getBridge().request_file_load('fasta')
  } catch (error) {
    console.warn('[Blast] Bridge not available:', error)
  }
}

/**
 * 启动BLAST任务
 */
function launchBlast(): void {
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

    getBridge().run_blast_job(payload, (resStr) => {
      try {
        const res = JSON.parse(resStr)
        if (res.status === 'started' && res.task_id) {
          // 添加任务到列表
          blast.addTask({
            taskId: res.task_id,
            fileName: generatedTaskName,
            status: 'queued',
            progress: 0,
            startTime: new Date().toISOString()
          })
          
          // 清空输入
          blast.clearFiles()
          blast.queryText = ''
          
          // 显示通知并切换到历史面板
          appStore.showNotification('任务已提交', 'success')
          activeSideTool.value = 'history'
          isSidebarOpen.value = true
          
          // 启动轮询，完成后自动获取结果
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
    console.error('[Blast] 启动失败:', error)
    appStore.showNotification('启动失败', 'error')
  }
}

/**
 * 导出结果（委托给ResultHandler）
 */
// 已通过解构直接使用 handleResult.exportResults

/**
 * 批量翻译（委托给ResultHandler）
 */
// 已通过解构直接使用 handleResult.translateAll

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

/* -------- 辅助工具 -------- */
function getFormattedTimestamp(date: string | Date = new Date()) {
  const d = new Date(date)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function startRename(task: any, event: Event) {
  event.stopPropagation()
  editingTaskId.value = task.taskId
  editName.value = task.fileName
  setTimeout(() => { renameInputRef.value?.focus(); renameInputRef.value?.select(); }, 50)
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

function clearAllHistory() {
  if (confirm('确定要清空所有分析历史吗？')) {
    taskManager.clearAllHistory()
  }
}

function deleteSingleTask(taskId: string, event: Event) {
  event.stopPropagation()
  taskManager.deleteTask(taskId)
}

function pauseTask(taskId: string, event: Event) {
  event.stopPropagation()
  taskManager.pauseTask(taskId)
}

function resumeTask(taskId: string, event: Event) {
  event.stopPropagation()
  taskManager.resumeTask(taskId, (tid) => {
    taskManager.startPolling(tid, (completedTaskId) => {
      fetchTaskResults(completedTaskId)
    })
  })
}

function stopTask(taskId: string, event: Event) {
  event.stopPropagation()
  if (confirm('确定要取消此任务的执行吗？')) {
    taskManager.stopTask(taskId)
  }
}

function openNcbi(accession: string): void {
  if (!accession || accession === '-' || accession === 'N/A') {
    appStore.showNotification('该条目无有效的NCBI访问号', 'warning')
    return
  }
  
  const url = `https://www.ncbi.nlm.nih.gov/nuccore/${accession}`
  try {
    getBridge().open_external_url(url)
  } catch (e) {
    console.error('Failed to open URL via bridge:', e)
    window.open(url, '_blank')
  }
}

function viewAllHits(csvFile: string, queryTitle: string): void {
  detailViewer.viewAllHits(csvFile, queryTitle)
}

/**
 * 样本一键入库 (从大表触发)
 */
function saveToStore(hit: any) {
  // 1. 尝试从 speciesName 中提取第一个干净的物种共识名
  // e.g. "Aeromonas hydrophila(94%), ..." -> "Aeromonas hydrophila"
  const rawSpecies = hit.translatedName || hit.speciesName || ''
  const consensusMatch = rawSpecies.match(/^([A-Za-z]+)\s+([A-Za-z\.\-_0-9]+)/)
  const cleanConsensus = consensusMatch 
    ? `${consensusMatch[1]} ${consensusMatch[2].replace(/[,\(\)].*$/, '')}`.trim()
    : rawSpecies

  // 2. 构造一个符合样本库结构的初始对象
  const draftRecord = {
    // 优先使用清晰的共识名作为默认样本名，而不是 QueryID
    name: cleanConsensus || hit.queryTitle,
    species: cleanConsensus || rawSpecies,
    accession: hit.accession,
    strain: hit.genusStrain,
    sequence: hit.rawSequence || '', 
    metadata: {
      blast_identity: hit.identity,
      blast_evalue: hit.evalue,
      blast_task_id: blast.activeTaskId,
      blast_hit_title: hit.hitTitle,
      original_query_id: hit.queryTitle // 保留原始 ID 备查
    }
  }

  // 3. 将草稿存入 Pinia Store
  strainStore.setPendingBlastDraft(draftRecord)

  // 3. 跳转到菌毒种库页面
  router.push('/strain')
  
  appStore.showNotification('已抓取鉴定结果，请选择一个存储孔位进行入库', 'success')
}

function toggleDropdown(id: string, event: Event) {
  event.stopPropagation()
  openDropdown.value = openDropdown.value === id ? null : id
}

function selectOption(id: string, value: any) {
  if (id === 'program') blast.params.program = value
  else if (id === 'database') blast.params.database = value
  else if (id === 'matrix') blast.params.matrix = value
  openDropdown.value = null
}

function getProgramLabel() { return PROGRAM_OPTIONS.find(o => o.value === blast.params.program)?.label || '核酸/蛋白' }
function getDatabaseLabel() { 
  const all = [...DB_OPTIONS.nucleotide, ...DB_OPTIONS.protein]
  return all.find(o => o.value === blast.params.database)?.label || '选择库'
}
function getMatrixLabel() { return MATRIX_OPTIONS.find(o => o.value === blast.params.matrix)?.label || '选择矩阵' }
function statusLabel(s: string) { 
  const m: any = { queued: t('blast.status.queued'), running: t('blast.status.running'), done: t('blast.status.done'), completed: t('blast.status.completed'), error: t('blast.status.error'), failed: t('blast.status.failed'), cancelled: t('blast.status.cancelled'), paused: t('blast.status.paused') }
  return m[s] || s
}

/* -------- 数据常量 -------- */
const DB_OPTIONS = {
  nucleotide: [
    { value: 'nt', label: 'nt - 全球核酸库' },
    { value: 'refseq_rna', label: 'refseq_rna - 参考 RNA' },
    { value: 'refseq_genomic', label: 'refseq_genomic - 参考基因组' }
  ],
  protein: [
    { value: 'nr', label: 'nr - 非冗余蛋白库' },
    { value: 'swissprot', label: 'swissprot - Swiss-Prot' }
  ]
}
const MATRIX_OPTIONS = [{ value: 'BLOSUM62', label: 'BLOSUM62' }, { value: 'PAM30', label: 'PAM30' }]
const PROGRAM_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'blastn', label: 'blastn (核酸)' },
  { value: 'blastp', label: 'blastp (蛋白)' }
]

onMounted(() => {
  // 防御性措施：确保弹窗始终处于关闭状态
  // 在组件挂载时强制重置，防止Vite热更新导致的状态不一致
  
  // 立即强制重置所有状态
  _isLocked.value = true
  _hasUserInteracted.value = false
  _isOpenInternal.value = false
  detailViewer.closeDialog()
  
  document.addEventListener('click', () => { openDropdown.value = null; })
  setTimeout(() => {
    try {
      getBridge().get_all_tasks((resStr) => {
        try {
          const tasks = JSON.parse(resStr)
          if (Array.isArray(tasks)) {
            blast.tasks = tasks.map(t => ({
              taskId: t.task_id, fileName: t.task_name || getFormattedTimestamp(t.start_time),
              status: t.status, progress: t.progress || 0, startTime: t.start_time
            }))
            // 为运行中的任务启动轮询
            blast.tasks.forEach(t => { 
              if (t.status === 'running') {
                taskManager.startPolling(t.taskId, (taskId) => {
                  fetchTaskResults(taskId)
                })
              }
            })
          }
        } catch { }
      })
    } catch { }
  }, 500)
})

// 组件卸载时清理资源
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
          <span class="icon">📁</span>
          <span class="label">{{ t('blast.nav.input') }}</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'params' && isSidebarOpen }" @click="toggleSideTool('params')">
          <span class="icon">⚙️</span>
          <span class="label">{{ t('blast.nav.params') }}</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'history' && isSidebarOpen }" @click="toggleSideTool('history')">
          <span class="icon">🕐</span>
          <span class="label">{{ t('blast.nav.history') }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <button class="btn-primary-run" @click="launchBlast" :disabled="!blast.hasInput">
          {{ t('blast.btn.run') }}
        </button>
      </div>
    </div>

    <div class="blast-main-area">
      <!-- 动态侧边栏 -->
      <div class="blast-sidebar" :class="{ collapsed: !isSidebarOpen }">
        <div class="sidebar-content scroll-v">
          <!-- 输入面板 -->
          <div v-show="activeSideTool === 'input'" class="panel-section">
            <h3 class="section-title">{{ t('blast.input.title') }}</h3>
            <div class="mode-tabs-neo">
              <button class="mode-tab" :class="{ active: blast.inputMode === 'file' }" @click="blast.switchInputMode('file')">{{ t('blast.input.file') }}</button>
              <button class="mode-tab" :class="{ active: blast.inputMode === 'text' }" @click="blast.switchInputMode('text')">{{ t('blast.input.text') }}</button>
            </div>
            
            <div v-if="blast.inputMode === 'file'" class="file-area">
              <div class="drop-zone-neo" @click="selectFiles">
                <span class="dz-icon">📤</span>
                <span class="dz-text">{{ t('blast.input.drop') }}</span>
              </div>
              <div class="file-list-neo">
                 <div v-for="f in blast.files" :key="f" class="file-item-neo">
                   <span class="name">{{ f.split(/[/\\]/).pop() }}</span>
                   <button class="del" @click="blast.removeFile(f)">✕</button>
                 </div>
              </div>
            </div>
            <textarea v-else v-model="blast.queryText" class="neo-textarea" placeholder=">Sequence_Title..." />
          </div>

          <!-- 参数面板 -->
          <div v-show="activeSideTool === 'params'" class="panel-section">
            <h3 class="section-title">{{ t('blast.param.title') }}</h3>
            <div class="form-group">
              <label>{{ t('blast.param.prog') }}</label>
              <div class="select-box-neo" @click.stop="toggleDropdown('program', $event)">
                {{ getProgramLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'program'" class="dropdown-list">
                  <div v-for="o in PROGRAM_OPTIONS" :key="o.value" class="opt" @click="selectOption('program', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>{{ t('blast.param.db') }}</label>
              <div class="select-box-neo" @click.stop="toggleDropdown('db', $event)">
                 {{ getDatabaseLabel() }} <span class="arrow">▼</span>
                 <div v-if="openDropdown === 'db'" class="dropdown-list">
                    <div class="group">核酸</div>
                    <div v-for="o in DB_OPTIONS.nucleotide" :key="o.value" class="opt" @click="selectOption('database', o.value)">{{ o.label }}</div>
                    <div class="group">蛋白</div>
                    <div v-for="o in DB_OPTIONS.protein" :key="o.value" class="opt" @click="selectOption('database', o.value)">{{ o.label }}</div>
                 </div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                 <label>{{ t('blast.param.eval') }}</label>
                 <input type="number" v-model="blast.params.evalue" class="neo-input" />
              </div>
              <div class="form-group">
                 <label>{{ t('blast.param.max') }}</label>
                 <input type="number" v-model="blast.params.maxHits" class="neo-input" />
              </div>
            </div>
            <div class="form-group">
               <label>{{ t('blast.param.threads') }}</label>
               <input type="number" v-model="blast.params.threads" class="neo-input" min="1" max="128" />
            </div>
            <div class="form-group" style="display: flex; align-items: center; gap: 8px;">
               <input type="checkbox" id="filter-complex" v-model="blast.params.filterLowComplexity" style="accent-color: #2563eb;" />
               <label for="filter-complex" style="margin-bottom: 0; cursor: pointer;">{{ t('blast.param.filter') }}</label>
            </div>
            <h3 class="section-title sub">{{ t('blast.model.title') }}</h3>
            <div class="form-group">
               <label>{{ t('blast.model.matrix') }}</label>
               <div class="select-box-neo" @click.stop="toggleDropdown('matrix', $event)">
                  {{ getMatrixLabel() }} <span class="arrow">▼</span>
                  <div v-if="openDropdown === 'matrix'" class="dropdown-list">
                    <div v-for="o in MATRIX_OPTIONS" :key="o.value" class="opt" @click="selectOption('matrix', o.value)">{{ o.label }}</div>
                  </div>
               </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                 <label>Gap Open</label>
                 <input type="number" v-model="blast.params.gapOpen" class="neo-input" />
              </div>
              <div class="form-group">
                 <label>Gap Extend</label>
                 <input type="number" v-model="blast.params.gapExtend" class="neo-input" />
              </div>
            </div>
          </div>

          <!-- 历史面板 -->
          <div v-show="activeSideTool === 'history'" class="panel-section">
            <h3 class="section-title">{{ t('blast.hist.title') }}</h3>
            <div class="history-list">
               <div v-for="t in blast.tasks" :key="t.taskId" class="task-card" :class="{ active: blast.activeTaskId === t.taskId }" @click="selectTask(t.taskId)">
                  <div class="title" @dblclick="startRename(t, $event)">
                    <span v-if="editingTaskId !== t.taskId">{{ t.fileName }}</span>
                    <input v-else v-model="editName" class="rename-inp" ref="renameInputRef" @blur="commitRename(t)" @keyup.enter="commitRename(t)" />
                  </div>
                  <div class="meta">
                    <span class="status" :class="t.status">{{ statusLabel(t.status) }}</span>
                  </div>
                  <!-- 进度条模块：对所有未完成的任务保持显示进度，以便断点接续时明确当前的进度节点 -->
                  <div class="progress-bar-container" v-if="['running', 'paused', 'queued', 'error', 'failed', 'cancelled'].includes(t.status)">
                    <div class="progress-bar-fill" :style="{ width: t.progress + '%' }"></div>
                    <span class="progress-text">{{ t.progress }}%</span>
                  </div>
                  <div class="card-actions">
                     <button v-if="t.status === 'running'" title="暂停" @click.stop="pauseTask(t.taskId, $event)">⏸</button>
                     <!-- 将原有的 paused 单一继续，扩展为对所有未跑完（中断/暂停/失败/取消）任务展现断点接续功能 -->
                     <button v-if="['paused', 'error', 'failed', 'cancelled'].includes(t.status)" title="断点接续 / 继续" @click.stop="resumeTask(t.taskId, $event)">▶️</button>
                     <button v-if="['running', 'paused', 'queued'].includes(t.status)" title="取消" @click.stop="stopTask(t.taskId, $event)">⏹</button>
                     <!-- 重新运行功能如果后续需要实现全新清空重跑可在这里添加，目前以断点接续为主 -->
                     <button title="删除" @click.stop="deleteSingleTask(t.taskId, $event)">🗑</button>
                  </div>
               </div>
            </div>
            <div v-if="blast.tasks.length > 0" class="history-footer">
               <button class="text-btn-warn" @click="clearAllHistory">{{ t('blast.hist.clear') }}</button>
            </div>
          </div>
        </div>

        <!-- 侧边栏收起 handle -->
        <div class="sidebar-collapse-toggle" @click="isSidebarOpen = !isSidebarOpen">
           {{ isSidebarOpen ? '◀' : '▶' }}
        </div>
      </div>

      <!-- 结果主区域 -->
      <div class="blast-results">
         <div class="results-header">
            <div class="title">📊 {{ blast.resultTitle }}</div>
            <div class="actions">
               <button class="btn-ai" @click="translateAll" :disabled="isTranslating">{{ t('blast.btn.trans') }}</button>
               <button class="btn-export" @click="exportResults">{{ t('blast.btn.export') }}</button>
            </div>
         </div>
        <div class="table-wrapper scroll-v">
           <table v-if="blast.results.length > 0">
             <thead>
                <tr>
                  <th>{{ t('blast.res.query') }}</th>
                  <th>{{ t('blast.res.detail') }} (含全部结果)</th>
                  <th>{{ t('blast.res.bg') }}</th>
                  <th>{{ t('blast.res.id') }}</th>
                  <th>{{ t('blast.res.eval') }}</th>
                  <th>NCBI</th>
                  <th>操作</th>
                </tr>
             </thead>
             <tbody>
               <tr v-for="h in blast.results" :key="h.accession" class="blast-row-neo">
                 <td class="mono">{{ h.queryTitle }}</td>
                 <td class="detail-cell-neo">
                   <div class="sp">{{ h.translatedName || h.speciesName }}</div>
                   <div class="st">{{ h.genusStrain }}</div>
                   <div class="gs">{{ h.geneSource }}</div>
                   <div v-if="h.csvFile" class="view-all-link" @click="viewAllHits(h.csvFile, h.queryTitle)">
                     查看完整比对列表 ({{ h.csvFile ? '更多' : '0' }}) →
                   </div>
                 </td>
                 <td class="bio">
                    <div class="tag">{{ h.seqType }}</div>
                    <div class="host">宿主: {{ h.host }}</div>
                 </td>
                 <td>
                    <div class="id-val" :class="h.identity >= 97 ? 'high-id' : 'low-id'">
                      {{ h.identity.toFixed(1) }}%
                    </div>
                 </td>
                 <td class="mono">{{ h.evalue }}</td>
                 <td>
                   <button 
                     v-if="h.accession && h.accession !== '-' && h.accession !== 'N/A'" 
                     class="link-btn" 
                     @click="openNcbi(h.accession)"
                     title="在NCBI中查看"
                   >
                     🔗
                   </button>
                   <span v-else class="no-link">-</span>
                 </td>
                 <td>
                    <button class="btn-action-save" @click="saveToStore(h)" title="入库">
                      📥 入库
                    </button>
                  </td>
               </tr>
             </tbody>
           </table>
           <div v-else class="empty-hint">
             <div class="icon">🧬</div>
             <p>{{ t('blast.hist.empty') }}</p>
           </div>
        </div>
      </div>
    </div>

    <!-- 所有比对结果弹窗 -->
    <Transition name="dialog-fade">
      <div 
        v-if="shouldShowDetailDialog" 
        class="dialog-overlay" 
        @click.self="detailViewer.closeDialog"
      >
        <div class="dialog-container">
          <div class="dialog-header">
            <h3>📋 {{ currentQueryTitle }} - 全部比对结果 ({{ allHitsData.length }} 条)</h3>
            <button class="close-btn" @click="detailViewer.closeDialog">✕</button>
          </div>
          <div class="dialog-body scroll-v">
            <table v-if="allHitsData.length > 0" class="detail-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>物种名称</th>
                  <th>相似度</th>
                  <th>E值</th>
                  <th>Accession</th>
                  <th>标题</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(hit, index) in allHitsData" :key="index" v-memo="[hit.acc, hit.similarity]">
                  <td>{{ index + 1 }}</td>
                  <td>{{ hit.species || '-' }}</td>
                  <td>
                    <span :class="parseFloat(hit.similarity) >= 98 ? 'high-id' : 'low-id'">
                      {{ hit.similarity }}
                    </span>
                  </td>
                  <td class="mono">{{ hit.evalue }}</td>
                  <td class="mono">{{ hit.acc || '-' }}</td>
                  <td class="title-cell">{{ hit.title || '-' }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="loading-skeleton-container">
              <div v-for="i in 10" :key="i" class="skeleton-row"></div>
              <p class="loading-text">正在精准解析 {{ allHitsData.length === 0 ? '' : allHitsData.length }} 条比对结果...</p>
            </div>
          </div>
          <div class="dialog-footer">
            <button class="btn-primary" @click="detailViewer.closeDialog">确认</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* 主布局结构 */
.blast-workspace-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  overflow: hidden;
}

/* 顶部工具菜单栏 (板块1) */
.blast-toolbar-top {
  height: 60px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 100;
}

.tool-items { display: flex; align-items: center; gap: 8px; }
.tool-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  cursor: pointer;
  border-radius: 10px;
  color: #64748b;
  transition: all 0.2s;
  font-weight: 600;
  font-size: 0.82rem;
}
.tool-btn:hover { background: #f8fafc; color: #1e293b; }
.tool-btn.active { color: #2563eb; background: #eff6ff; }
.tool-btn .icon { font-size: 1.2rem; }

.tool-divider { width: 1px; height: 24px; background: #e2e8f0; margin: 0 10px; }

.btn-primary-run {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  padding: 10px 24px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.85rem;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
  display: flex;
  align-items: center;
  gap: 10px;
}
.btn-primary-run:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 15px rgba(37, 99, 235, 0.3); }

/* 下方两栏容器 */
.blast-main-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  background: #f8fafc;
}

/* 侧边栏 (工具栏) - 板块2 */
.blast-sidebar {
  width: 360px;
  background: white;
  transition: none; /* 取消动画 */
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 5;
  border-right: 1px solid #e2e8f0;
  overflow: visible; /* 确保 handle 可见 */
}
.blast-sidebar.collapsed { width: 0; border-right: none; }

.sidebar-content {
  padding: 24px;
  flex: 1;
  overflow-y: auto;
  white-space: nowrap; /* 防止收缩时文字折行 */
}
.collapsed .sidebar-content { display: none; }

/* 结果栏 - 板块3 */
.blast-results {
  flex: 1;
  background: white;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 收起 Handle - 修复被遮挡问题 */
.sidebar-collapse-toggle {
  position: absolute;
  left: 100%; /* 始终在内容区右侧边缘 */
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 60px;
  background: white;
  border: 1px solid #e2e8f0;
  border-left: none; /* 贴合侧边栏 */
  border-radius: 0 10px 10px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 10;
  font-size: 0.61rem;
  color: #94a3b8;
  box-shadow: 2px 0 6px rgba(0,0,0,0.06);
}
.sidebar-collapse-toggle:hover { color: #2563eb; background: #f8fafc; }

.section-title { font-size: 1rem; font-weight: 800; color: #0f172a; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;}
.section-title.sub { margin-top: 32px; border-top: 1px dashed #e2e8f0; padding-top: 20px; }

.mode-tabs-neo { display: flex; background: #f1f5f9; padding: 4px; border-radius: 8px; margin-bottom: 20px; }
.mode-tab { flex: 1; padding: 8px; font-size: 0.78rem; font-weight: 700; border-radius: 6px; color: #64748b; cursor: pointer; }
.mode-tab.active { background: white; color: #2563eb; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

.drop-zone-neo { border: 2px dashed #cbd5e1; border-radius: 12px; padding: 24px; text-align: center; cursor: pointer; transition: all 0.2s; }
.drop-zone-neo:hover { border-color: #2563eb; background: #f0f7ff; }
.dz-icon { font-size: 1.8rem; display: block; margin-bottom: 8px; }
.dz-text { font-size: 0.82rem; font-weight: 700; color: #475569; }

.file-item-neo { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #f8fafc; border-radius: 8px; margin-top: 8px; font-size: 0.78rem; color: #1e293b; border: 1px solid #f1f5f9; }
.file-item-neo .del { color: #94a3b8; cursor: pointer; font-size: 0.8rem; }
.file-item-neo .del:hover { color: #ef4444; }

.neo-textarea { width: 100%; height: 320px; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; resize: none; background: #f8fafc; line-height: 1.6; }

.form-group { margin-bottom: 20px; }
.form-group label { font-size: 0.75rem; font-weight: 800; color: #64748b; margin-bottom: 8px; display: block; text-transform: uppercase; letter-spacing: 0.02em; }
.select-box-neo { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; font-size: 0.82rem; cursor: pointer; position: relative; display: flex; justify-content: space-between; align-items: center; }
.dropdown-list { position: absolute; top: 110%; left: 0; right: 0; background: white; border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 8px 20px rgba(0,0,0,0.12); z-index: 100; max-height: 250px; overflow-y: auto; padding: 6px; }
.dropdown-list .opt { padding: 10px 12px; font-size: 0.82rem; border-radius: 6px; }
.dropdown-list .opt:hover { background: #f1f5f9; color: #2563eb; }
.dropdown-list .group { padding: 8px 12px; font-size: 0.68rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; }

.neo-input { width: 100%; padding: 10px 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; font-size: 0.82rem; color: #0f172a; }
.form-row { display: flex; gap: 16px; }

.panel-section { animation: fadeIn 0.3s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

/* 历史列表 */
.history-list { margin-top: 10px; }
.task-card { border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px; margin-bottom: 10px; cursor: pointer; position: relative; transition: all 0.2s; background: #fff; }
.task-card:hover { border-color: #cbd5e1; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.task-card.active { border-color: #2563eb; background: #eff6ff; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1); }
.task-card .title { font-size: 0.82rem; font-weight: 800; margin-bottom: 6px; color: #1e293b; }
.task-card .meta { display: flex; justify-content: space-between; font-size: 0.68rem; color: #94a3b8; font-weight: 500; }
.status.done, .status.completed { color: #16a34a; }
.status.running { color: #2563eb; }
.task-card .card-actions { position: absolute; top: 12px; right: 12px; opacity: 1; transition: opacity 0.2s; display: flex; gap: 4px; }

.task-card .card-actions button {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  cursor: pointer;
  width: 26px;
  height: 26px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
  font-size: 0.85rem;
  transition: all 0.2s;
  color: #64748b;
}
.task-card .card-actions button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.progress-bar-container {
  height: 6px;
  background-color: #e2e8f0;
  border-radius: 3px;
  margin-top: 8px;
  overflow: hidden;
  position: relative;
}
.progress-bar-fill {
  height: 100%;
  background-color: #3b82f6;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.progress-text {
  position: absolute;
  right: 0;
  top: -16px;
  font-size: 0.65rem;
  font-weight: 700;
  color: #3b82f6;
}

.history-footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid #f1f5f9; text-align: center; }
.text-btn-warn { border: none; background: none; color: #ef4444; font-size: 0.78rem; font-weight: 700; cursor: pointer; padding: 8px 16px; border-radius: 6px; }
.text-btn-warn:hover { background: #fef2f2; }

/* 结果表格 */
.results-header { padding: 18px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; background: #fff; }
.results-header .title { font-size: 1.1rem; font-weight: 800; color: #1e293b; display: flex; align-items: center; gap: 8px; }
.actions { display: flex; gap: 10px; }
.btn-ai { background: white; border: 1.5px solid #2563eb; color: #2563eb; padding: 8px 18px; border-radius: 10px; font-size: 0.78rem; font-weight: 800; cursor: pointer; transition: all 0.2s; }
.btn-ai:hover:not(:disabled) { background: #2563eb; color: white; transform: translateY(-1px); box-shadow: 0 4px 10px rgba(37, 99, 235, 0.2); }
.btn-export { background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; padding: 8px 18px; border-radius: 10px; font-size: 0.78rem; font-weight: 800; cursor: pointer; transition: all 0.2s; }
.btn-export:hover { background: #f1f5f9; border-color: #cbd5e1; }

.btn-action-save {
  padding: 6px 12px;
  background: #f0fdf4;
  color: #16a34a;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-action-save:hover {
  background: #16a34a;
  color: white;
  border-color: #16a34a;
  box-shadow: 0 4px 12px rgba(22, 163, 74, 0.2);
  transform: translateY(-1px);
}

.table-wrapper { flex: 1; overflow: auto; background: white; }
table { width: 100%; border-collapse: separate; border-spacing: 0; }
thead th { position: sticky; top: 0; background: #f8fafc; padding: 14px 20px; text-align: left; font-size: 0.72rem; color: #64748b; font-weight: 800; border-bottom: 1px solid #e2e8f0; z-index: 10; text-transform: uppercase; }
tbody td { padding: 18px 20px; border-bottom: 1px solid #f1f5f9; font-size: 0.85rem; vertical-align: middle; }
tbody tr:hover { background: #fafbfc; }

.sp { font-weight: 800; font-size: 0.92rem; color: #0f172a; line-height: 1.4; }
.st { font-size: 0.75rem; color: #64748b; margin-top: 3px; font-weight: 500; }
.gs { font-size: 0.75rem; color: #2563eb; font-weight: 700; margin-top: 3px; }

.id-val { 
  font-family: 'JetBrains Mono', monospace; 
  font-weight: 800; 
  font-size: 0.88rem; 
}
.id-val.high-id { color: #16a34a; } /* 97%及以上：绿色 */
.id-val.low-id { color: #94a3b8; }  /* 97%以下：灰色 */

.mono { font-family: 'JetBrains Mono', monospace; color: #475569; font-size: 0.78rem; font-weight: 500; }
.link-btn { background: #f1f5f9; border: none; padding: 6px; border-radius: 6px; cursor: pointer; transition: all 0.2s; font-size: 0.85rem; }
.link-btn:hover { background: #e2e8f0; transform: scale(1.1); }
.no-link { color: #cbd5e1; font-size: 0.85rem; }

.scroll-v { overflow-y: auto; scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
.scroll-v::-webkit-scrollbar { width: 6px; }
.scroll-v::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
.scroll-v::-webkit-scrollbar-track { background: transparent; }

.empty-hint { height: 80%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #94a3b8; text-align: center; }
/* 提示链接样式 */
.view-all-link {
  margin-top: 8px;
  font-size: 0.72rem;
  color: #3b82f6;
  cursor: pointer;
  display: inline-block;
  font-weight: 600;
  padding: 2px 0;
  border-bottom: 1px solid transparent;
  transition: all 0.2s;
}

.view-all-link:hover {
  color: #2563eb;
  border-bottom-color: #2563eb;
  transform: translateX(4px);
}

.blast-row-neo {
  transition: background-color 0.2s;
}

.blast-row-neo:hover {
  background-color: #f8fafc !important;
}

.detail-cell-neo {
  padding-bottom: 14px !important;
}

/* 弹窗样式 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog-container {
  background: white;
  border-radius: 16px;
  width: 90%;
  max-width: 1200px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.dialog-header {
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(to right, #f8fafc, #ffffff);
  border-radius: 16px 16px 0 0;
}

.dialog-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  color: #0f172a;
}

.close-btn {
  background: #f1f5f9;
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1.2rem;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #e2e8f0;
  color: #ef4444;
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

.detail-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

.detail-table thead th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  padding: 14px 16px;
  text-align: left;
  font-size: 0.72rem;
  color: #64748b;
  font-weight: 800;
  border-bottom: 2px solid #e2e8f0;
  z-index: 10;
  text-transform: uppercase;
}

.detail-table tbody td {
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.82rem;
  vertical-align: middle;
}

.detail-table tbody tr:hover {
  background: #fafbfc;
}

.detail-table .title-cell {
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
}

.dialog-footer {
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  background: #f8fafc;
  border-radius: 0 0 16px 16px;
}

.btn-primary {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 15px rgba(37, 99, 235, 0.3);
}

/* 弹窗过渡动画 */
.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.dialog-fade-enter-active .dialog-container {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}

.dialog-fade-enter-from .dialog-container {
  transform: scale(0.96) translateY(10px);
  opacity: 0;
}

.dialog-fade-leave-to .dialog-container {
  transform: scale(1.01);
  opacity: 0;
}

/* 骨架屏样式 */
.loading-skeleton-container {
  padding: 24px;
}

.skeleton-row {
  height: 20px;
  background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  margin-bottom: 12px;
  border-radius: 4px;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.loading-text {
  text-align: center;
  color: #64748b;
  font-size: 0.85rem;
  margin-top: 20px;
  font-weight: 500;
}
</style>