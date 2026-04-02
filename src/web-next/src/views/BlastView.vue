<script setup lang="ts">
/**
 * BlastView - BLAST 分析视图
 * 精简、现代、专业的工作区布局
 */
import { onMounted, ref } from 'vue'
import { useBlastStore } from '../stores/blast'
import { getBridge } from '../bridge/pyqt-bridge'
import { useAppStore } from '../stores/app'

const blast = useBlastStore()
const appStore = useAppStore()

/* -------- 核心状态 -------- */
const isTranslating = ref(false)
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

const pollingTimers: Record<string, number> = {}

function startPolling(taskId: string) {
  if (pollingTimers[taskId]) return
  pollingTimers[taskId] = window.setInterval(() => {
    try {
      getBridge().get_task_status(taskId, (resStr) => {
        try {
          const statusObj = resStr ? JSON.parse(resStr) : null
          if (!statusObj || !statusObj.status) return

          blast.updateTaskStatus(taskId, statusObj.status, statusObj.progress)
          if (['done', 'completed', 'error', 'failed', 'cancelled'].includes(statusObj.status)) {
            window.clearInterval(pollingTimers[taskId])
            delete pollingTimers[taskId]
            if (statusObj.status === 'done' || statusObj.status === 'completed') {
              fetchTaskResults(taskId)
            }
          }
        } catch (e) { /* ignore */ }
      })
    } catch {
      window.clearInterval(pollingTimers[taskId])
      delete pollingTimers[taskId]
    }
  }, 1000)
}

function fetchTaskResults(taskId: string) {
  try {
    getBridge().get_task_results(taskId, (resStr) => {
      try {
        const resultsArray = JSON.parse(resStr)
        if (!Array.isArray(resultsArray)) return

        const hits: any[] = []
        for (const res of resultsArray) {
          const queryId = res.sequence_id || '未知序列'
          if (res.data && Array.isArray(res.data) && res.data.length > 0) {
            const bestHit = res.data[0]
            hits.push({
              queryTitle: queryId,
              speciesName: bestHit.species || 'Unknown',
              genusStrain: [bestHit.genus, bestHit.strain].filter(Boolean).join(' · ') || '',
              geneSource: bestHit.gene_source || bestHit.gene_type || '',
              seqType: bestHit.seq_type || '',
              host: bestHit.host || '',
              alignLen: bestHit.align_len || '',
              identity: parseFloat(bestHit.similarity) || 0,
              evalue: String(bestHit.evalue || 'N/A'),
              accession: bestHit.acc || 'N/A',
              hitTitle: bestHit.title || '',
              translatedName: null
            })
          }
        }
        hits.sort((a, b) => a.queryTitle.localeCompare(b.queryTitle, undefined, { numeric: true, sensitivity: 'base' }))
        blast.setResults(hits, '分析结果 (' + hits.length + ' 项)')
      } catch (e) {
        console.error('[Blast] 解析结果失败:', e)
      }
    })
  } catch (error) {
    console.warn('[Blast] 获取任务结果失败:', error)
  }
}

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
          startPolling(res.task_id)
        } else {
          appStore.showNotification('启动失败: ' + (res.error || '未知错误'), 'error')
        }
      } catch (e) {
        appStore.showNotification('解析返回失败', 'error')
      }
    })
  } catch (error) {
    console.error('[Blast] 启动失败:', error)
  }
}

function exportResults(): void {
  try { getBridge().save_file(JSON.stringify(blast.results), 'blast_results.csv') } catch { }
}

async function translateAll(): Promise<void> {
  if (blast.results.length === 0) return
  if (isTranslating.value) return
  isTranslating.value = true
  appStore.showNotification(`开始翻译 ${blast.results.length} 条结果...`, 'info')
  const bridge = getBridge()
  let translated = 0
  blast.results.forEach((hit) => {
    if (hit.speciesName && !hit.translatedName) {
      bridge.translate_text(hit.speciesName, 'species', (result: string) => {
        if (result && result !== hit.speciesName) {
          hit.translatedName = result
          translated++
        }
      })
    }
  })
  isTranslating.value = false
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
      try { getBridge().rename_task(task.taskId, trimmed) } catch { }
    }
    editingTaskId.value = null
  }
}

function clearAllHistory() {
  if (confirm('确定要清空所有分析历史吗？')) {
    try { getBridge().clear_all_history(); blast.clearHistory(); } catch { }
  }
}

function deleteSingleTask(taskId: string, event: Event) {
  event.stopPropagation()
  try { getBridge().delete_single_task(taskId); blast.removeTask(taskId); } catch { }
}

function openNcbi(accession: string): void {
  window.open(`https://www.ncbi.nlm.nih.gov/nuccore/${accession}`, '_blank')
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
  const m: any = { queued: '排队', running: '运行', done: '完成', error: '失败' }
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
            blast.tasks.forEach(t => { if (t.status === 'running') startPolling(t.taskId) })
          }
        } catch { }
      })
    } catch { }
  }, 500)
})
</script>

<template>
  <div class="blast-workspace-container">
    <!-- 顶部工具栏 -->
    <div class="blast-toolbar-top">
      <div class="tool-items">
        <div class="tool-btn" :class="{ active: activeSideTool === 'input' && isSidebarOpen }" @click="toggleSideTool('input')">
          <span class="icon">📁</span>
          <span class="label">序列输入</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'params' && isSidebarOpen }" @click="toggleSideTool('params')">
          <span class="icon">⚙️</span>
          <span class="label">分析参数</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'history' && isSidebarOpen }" @click="toggleSideTool('history')">
          <span class="icon">🕐</span>
          <span class="label">分析历史</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <button class="btn-primary-run" @click="launchBlast" :disabled="!blast.hasInput">
          <span class="icon">▶</span> 执行比对分析
        </button>
      </div>
    </div>

    <div class="blast-main-area">
      <!-- 动态侧边栏 -->
      <div class="blast-sidebar" :class="{ collapsed: !isSidebarOpen }">
        <div class="sidebar-content scroll-v">
          <!-- 输入面板 -->
          <div v-show="activeSideTool === 'input'" class="panel-section">
            <h3 class="section-title">▶ 序列输入</h3>
            <div class="mode-tabs-neo">
              <button class="mode-tab" :class="{ active: blast.inputMode === 'file' }" @click="blast.switchInputMode('file')">批量文件</button>
              <button class="mode-tab" :class="{ active: blast.inputMode === 'text' }" @click="blast.switchInputMode('text')">粘贴文本</button>
            </div>
            
            <div v-if="blast.inputMode === 'file'" class="file-area">
              <div class="drop-zone-neo" @click="selectFiles">
                <span class="dz-icon">📤</span>
                <span class="dz-text">点击或拖拽 FASTA</span>
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
            <h3 class="section-title">⚙️ 任务参数</h3>
            <div class="form-group">
              <label>分析程序</label>
              <div class="select-box-neo" @click.stop="toggleDropdown('program', $event)">
                {{ getProgramLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'program'" class="dropdown-list">
                  <div v-for="o in PROGRAM_OPTIONS" :key="o.value" class="opt" @click="selectOption('program', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>任务数据库</label>
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
                 <label>E-Value</label>
                 <input type="number" v-model="blast.params.evalue" class="neo-input" />
              </div>
              <div class="form-group">
                 <label>最大匹配</label>
                 <input type="number" v-model="blast.params.maxHits" class="neo-input" />
              </div>
            </div>
            <h3 class="section-title sub">🧬 模型选项</h3>
            <div class="form-group">
               <label>计分矩阵</label>
               <div class="select-box-neo" @click.stop="toggleDropdown('matrix', $event)">
                  {{ getMatrixLabel() }} <span class="arrow">▼</span>
                  <div v-if="openDropdown === 'matrix'" class="dropdown-list">
                    <div v-for="o in MATRIX_OPTIONS" :key="o.value" class="opt" @click="selectOption('matrix', o.value)">{{ o.label }}</div>
                  </div>
               </div>
            </div>
          </div>

          <!-- 历史面板 -->
          <div v-show="activeSideTool === 'history'" class="panel-section">
            <h3 class="section-title">🕐 分析历史</h3>
            <div class="history-list">
               <div v-for="t in blast.tasks" :key="t.taskId" class="task-card" :class="{ active: blast.activeTaskId === t.taskId }" @click="selectTask(t.taskId)">
                  <div class="title" @dblclick="startRename(t, $event)">
                    <span v-if="editingTaskId !== t.taskId">{{ t.fileName }}</span>
                    <input v-else v-model="editName" class="rename-inp" ref="renameInputRef" @blur="commitRename(t)" @keyup.enter="commitRename(t)" />
                  </div>
                  <div class="meta">
                    <span class="status" :class="t.status">{{ statusLabel(t.status) }}</span>
                    <span class="time">{{ getFormattedTimestamp(t.startTime).split(' ')[1] }}</span>
                  </div>
                  <div class="card-actions">
                     <button @click.stop="deleteSingleTask(t.taskId, $event)">🗑</button>
                  </div>
               </div>
            </div>
            <div v-if="blast.tasks.length > 0" class="history-footer">
               <button class="text-btn-warn" @click="clearAllHistory">清空全部历史记录</button>
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
              <button class="btn-ai" @click="translateAll" :disabled="isTranslating">🌐 AI 翻译</button>
              <button class="btn-export" @click="exportResults">💾 导出</button>
           </div>
        </div>
        <div class="table-wrapper scroll-v">
           <table v-if="blast.results.length > 0">
             <thead>
               <tr>
                 <th>查询序列</th>
                 <th>鉴定详情 (物种/菌株/基因)</th>
                 <th>生物学背景</th>
                 <th>相似度 (Identity)</th>
                 <th>E值</th>
                 <th>NCBI</th>
               </tr>
             </thead>
             <tbody>
               <tr v-for="h in blast.results" :key="h.accession">
                 <td class="mono">{{ h.queryTitle }}</td>
                 <td>
                   <div class="sp">{{ h.translatedName || h.speciesName }}</div>
                   <div class="st">{{ h.genusStrain }}</div>
                   <div class="gs">{{ h.geneSource }}</div>
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
                 <td><button class="link-btn" @click="openNcbi(h.accession)">🔗</button></td>
               </tr>
             </tbody>
           </table>
           <div v-else class="empty-hint">
             <div class="icon">🧬</div>
             <p>数据已准备就绪，请选择历史或发起新比对</p>
           </div>
        </div>
      </div>
    </div>
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
.status.done { color: #16a34a; }
.status.running { color: #2563eb; }
.task-card .card-actions { position: absolute; top: 12px; right: 12px; opacity: 0; transition: opacity 0.2s; }
.task-card:hover .card-actions { opacity: 1; }

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

.scroll-v { overflow-y: auto; scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
.scroll-v::-webkit-scrollbar { width: 6px; }
.scroll-v::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
.scroll-v::-webkit-scrollbar-track { background: transparent; }

.empty-hint { height: 80%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #94a3b8; text-align: center; }
.empty-hint .icon { font-size: 3.5rem; opacity: 0.15; margin-bottom: 16px; }
.empty-hint p { font-size: 0.9rem; font-weight: 500; }
</style>
