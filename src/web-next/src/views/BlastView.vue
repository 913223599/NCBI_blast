<script setup lang="ts">
/**
 * BlastView - BLAST 分析视图
 * 从旧版 index.html #blast-view 迁移
 * 四面板布局：序列输入 / 参数配置 / 分析历史 / 结果矩阵
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useBlastStore } from '../stores/blast'
import { getBridge } from '../bridge/pyqt-bridge'
import { useAppStore } from '../stores/app'

const blast = useBlastStore()
const appStore = useAppStore()

/* -------- BLAST 操作 -------- */
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
          // 如果任务到达终态则停止轮询
          if (['done', 'completed', 'error', 'failed', 'cancelled'].includes(statusObj.status)) {
            window.clearInterval(pollingTimers[taskId])
            delete pollingTimers[taskId]

            // 若成功，拉取最终结果
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

function clearAllHistory() {
  if (confirm('确定要清空所有分析历史及产生的文件吗？此操作不可恢复。')) {
    try {
      getBridge().clear_all_history()
      blast.clearHistory()
      appStore.showNotification('已清空全部记录', 'success')
    } catch { }
  }
}

function deleteSingleTask(taskId: string, event: Event) {
  event.stopPropagation()
  try {
    getBridge().delete_single_task(taskId)
    blast.removeTask(taskId)
  } catch { }
}
const editingTaskId = ref<string | null>(null)
const editName = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

function startRename(task: any, event: Event) {
  event.stopPropagation()
  editingTaskId.value = task.taskId
  editName.value = task.fileName
  // 异步聚焦
  setTimeout(() => {
    renameInputRef.value?.focus()
    renameInputRef.value?.select()
  }, 50)
}

function cancelRename() {
  editingTaskId.value = null
  editName.value = ''
}

function commitRename(task: any) {
  if (editingTaskId.value === task.taskId) {
    const trimmedName = editName.value.trim()
    if (trimmedName && trimmedName !== task.fileName) {
      task.fileName = trimmedName
      try {
        getBridge().rename_task(task.taskId, trimmedName)
      } catch { }
    }
    editingTaskId.value = null
  }
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
          // Extract the top hit from parsed data
          if (res.data && Array.isArray(res.data) && res.data.length > 0) {
            const bestHit = res.data[0]
            hits.push({
              queryTitle: queryId,
              // 共识投票后的物种名（加粗显示）
              speciesName: bestHit.species || 'Unknown',
              // 种属 · 菌株
              genusStrain: [bestHit.genus, bestHit.strain].filter(Boolean).join(' · ') || '',
              // 来源（如 16S rRNA）
              geneSource: bestHit.gene_source || bestHit.gene_type || '',
              // 生物学背景
              seqType: bestHit.seq_type || '',
              host: bestHit.host || '',
              alignLen: bestHit.align_len || '',
              // 核心指标
              identity: parseFloat(bestHit.similarity) || 0,
              evalue: String(bestHit.evalue || 'N/A'),
              accession: bestHit.acc || 'N/A',
              // 原始标题用于翻译
              hitTitle: bestHit.title || '',
              translatedName: null
            })
          }
        }
        const titleSuffix = hits.length > 0 ? ` (已加载 ${hits.length} 项)` : ' (无匹配结果)'
        blast.setResults(hits, '分析结果' + titleSuffix)
      } catch (e) {
        console.error('[Blast] 解析结果失败:', e)
      }
    })
  } catch (error) {
    console.warn('[Blast] 获取任务结果调用失败:', error)
  }
}

function launchBlast(): void {
  if (!blast.hasInput) {
    appStore.showNotification('请先选择序列文件或粘贴序列', 'warning')
    return
  }
  try {
    // 决定默认任务名称（含时间戳），避免在 Windows 上出现非法字符（/ 和 :）
    const now = new Date()
    const timeStr = `${now.getMonth() + 1}-${now.getDate()} ${String(now.getHours()).padStart(2, '0')}.${String(now.getMinutes()).padStart(2, '0')}`

    let baseName = '手动输入比对'
    if (blast.inputMode === 'file' && blast.files.length) {
      baseName = blast.files[0]?.split(/[/\\]/).pop() ?? '文件比对'
    }
    const generatedTaskName = `${baseName} [${timeStr}]`

    // 构造请求参数
    const payload = JSON.stringify({
      task_name: generatedTaskName,
      mode: blast.inputMode,
      files: blast.files,
      query: blast.queryText,
      ...blast.params
    })

    // 调用桥接
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

          appStore.showNotification('BLAST 任务已提交并开始执行', 'success')
          blast.historyVisible = true
          startPolling(res.task_id)
        } else {
          appStore.showNotification('任务启动失败: ' + (res.error || '未知错误'), 'error')
        }
      } catch (e) {
        appStore.showNotification('解析后端返回失败', 'error')
      }
    })
  } catch (error) {
    console.error('[Blast] 启动失败:', error)
  }
}

function stopTask(taskId: string): void {
  try { getBridge().stop_blast_job(taskId) } catch { /* mock */ }
}

function pauseTask(taskId: string): void {
  try { getBridge().pause_blast_job(taskId) } catch { /* mock */ }
}

function exportResults(): void {
  try { getBridge().save_file(JSON.stringify(blast.results), 'blast_results.csv') } catch { /* mock */ }
}

const isTranslating = ref(false)

async function translateAll(): Promise<void> {
  if (blast.results.length === 0) {
    appStore.showNotification('暂无结果可翻译', 'warning')
    return
  }
  if (isTranslating.value) {
    appStore.showNotification('翻译正在进行中...', 'info')
    return
  }

  isTranslating.value = true
  appStore.showNotification(`开始翻译 ${blast.results.length} 条结果...`, 'info')

  const bridge = getBridge()
  let translated = 0

  // Process one at a time to avoid API rate limits
  for (let idx = 0; idx < blast.results.length; idx++) {
    const hit = blast.results[idx]
    if (!hit) continue

    // 1. 翻译物种名称 (加粗部分)
    if (hit.speciesName && !hit.translatedName?.startsWith('[')) {
      try {
        await new Promise<void>((resolve) => {
          bridge.translate_text(hit.speciesName, 'species', (result: string) => {
            if (result && result !== hit.speciesName) {
              hit.translatedName = result
              translated++
            }
            resolve()
          })
          setTimeout(resolve, 5000)
        })
      } catch { }
    }

    // 2. 翻译生物学背景 (序列类型部分)
    if (hit.seqType && !hit.seqType.includes('本地') && !hit.seqType.includes('AI')) {
      try {
        await new Promise<void>((resolve) => {
          bridge.translate_text(hit.seqType, 'other', (result: string) => {
            if (result && result !== hit.seqType) {
              hit.seqType = result
            }
            resolve()
          })
          setTimeout(resolve, 3000)
        })
      } catch { }
    }
  }

  isTranslating.value = false
  appStore.showNotification(`翻译完成，共翻译 ${translated} 条`, 'success')
}

function openNcbi(accession: string): void {
  const url = `https://www.ncbi.nlm.nih.gov/nuccore/${accession}`
  try {
    window.open(url, '_blank')
  } catch {
    // Fallback: try bridge log
    try { getBridge().log_message(`Open NCBI: ${url}`) } catch { }
  }
}

function selectTask(taskId: string): void {
  blast.setActiveTask(taskId)
  fetchTaskResults(taskId)
}
function handleGlobalClick(event: MouseEvent) {
  if (editingTaskId.value) {
    const target = event.target as HTMLElement
    if (!target.classList.contains('rename-input')) {
      const task = blast.tasks.find(t => t.taskId === editingTaskId.value)
      if (task) commitRename(task)
      else editingTaskId.value = null
    }
  }
}

/* -------- 生命周期 -------- */
onMounted(() => {
  document.addEventListener('click', handleGlobalClick)
  // 注册 BLAST 特有的回调 (供 Python 端 executor.py 等分发进度)
  if (typeof window !== 'undefined') {
    (window as any).blastCallback = {
      onFileAdded: (path: string) => blast.addFile(path),
      onTaskCreated: (taskId: string, fileName: string) => {
        blast.addTask({ taskId, fileName, status: 'queued', progress: 0, startTime: new Date().toISOString() })
      },
      onTaskProgress: (taskId: string, progress: number) => blast.updateTaskStatus(taskId, 'running', progress),
      onTaskDone: (taskId: string) => {
        blast.updateTaskStatus(taskId, 'done', 100)
        fetchTaskResults(taskId)
      },
      onTaskError: (taskId: string) => blast.updateTaskStatus(taskId, 'error'),
      onResults: (hits: string) => {
        try { blast.setResults(JSON.parse(hits)) } catch { /* parse error */ }
      }
    }
  }

  // 组件挂载时，从后端加载历史记录以恢复状态
  setTimeout(() => {
    try {
      getBridge().get_all_tasks((resStr) => {
        try {
          const pastTasks = JSON.parse(resStr)
          if (Array.isArray(pastTasks) && pastTasks.length > 0) {
            // 清理并重新注入
            blast.tasks = []
            pastTasks.forEach(t => {
              const params = typeof t.params === 'string' ? JSON.parse(t.params) : (t.params || {})
              const fileName = params.task_name || (params.files && params.files.length > 0 ? (params.files[0]?.split(/[/\\]/).pop() || 'Historical Task') : 'Historical Task')

              blast.tasks.push({
                taskId: t.task_id,
                fileName: fileName,
                status: t.status,
                progress: t.progress || 0,
                startTime: t.start_time
              })
              // 恢复未完成任务的轮询
              if (t.status === 'running' || t.status === 'pending') {
                startPolling(t.task_id)
              }
            })
          }
        } catch (e) {
          console.warn('[Blast] Failed to parse historical tasks', e)
        }
      })
    } catch (e) {
      // Bridge probably not ready
    }
  }, 500) // 给予 Bridge 握手时间
})

onUnmounted(() => { document.removeEventListener('click', handleGlobalClick) })

/** 数据库选项 */
const DB_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
  nucleotide: [
    { value: 'nt', label: 'nt - Nucleotide collection' },
    { value: 'refseq_rna', label: 'refseq_rna - RefSeq RNA' },
    { value: 'refseq_genomic', label: 'refseq_genomic - RefSeq Genomic' }
  ],
  protein: [
    { value: 'nr', label: 'nr - Non-redundant protein' },
    { value: 'swissprot', label: 'swissprot - Swiss-Prot' },
    { value: 'refseq_protein', label: 'refseq_protein - RefSeq Protein' }
  ]
}

/** 矩阵选项 */
const MATRIX_OPTIONS = [
  { value: 'BLOSUM62', label: 'BLOSUM62 (推荐)' },
  { value: 'BLOSUM45', label: 'BLOSUM45' },
  { value: 'BLOSUM80', label: 'BLOSUM80' },
  { value: 'PAM30', label: 'PAM30' },
  { value: 'PAM70', label: 'PAM70' }
]

/** 程序选项 */
const PROGRAM_OPTIONS = [
  { value: 'auto', label: '自动识别 (Auto)' },
  { value: 'blastn', label: 'blastn (核酸 → 核酸)' },
  { value: 'blastp', label: 'blastp (蛋白 → 蛋白)' },
  { value: 'blastx', label: 'blastx (核酸翻译 → 蛋白)' },
  { value: 'tblastn', label: 'tblastn (蛋白 → 核酸翻译)' }
]

/** 状态徽章样式 */
function statusLabel(status: string): string {
  const map: Record<string, string> = {
    queued: '排队中', running: '运行中', done: '已完成', error: '失败', paused: '已暂停'
  }
  return map[status] ?? status
}
</script>

<template>
  <div class="blast-view">
    <!-- 左栏：输入 + 参数 -->
    <div class="left-col">
      <!-- 序列输入面板 -->
      <div class="panel input-panel">
        <div class="panel-header">
          <span class="panel-title">▶ 序列输入</span>
        </div>
        <div class="panel-body">
          <!-- 模式切换 -->
          <div class="mode-tabs">
            <div class="mode-tab" :class="{ active: blast.inputMode === 'file' }"
              @click="blast.switchInputMode('file')">📁 批量文件</div>
            <div class="mode-tab" :class="{ active: blast.inputMode === 'text' }"
              @click="blast.switchInputMode('text')">✏️ 文本粘贴</div>
          </div>
          <!-- File 模式 -->
          <div v-if="blast.inputMode === 'file'">
            <div class="drop-zone" @click="selectFiles" @dragover.prevent>
              <span>📤 点击添加或拖拽文件到此处</span>
            </div>
            <div class="file-list-header">
              <span>待比对文件列表 <span class="badge">{{ blast.fileCount }}</span></span>
              <button class="btn-icon" @click="blast.clearFiles" title="清空列表">🗑</button>
            </div>
            <div class="file-list">
              <div v-for="(filePath, idx) in blast.files" :key="idx" class="file-item">
                <span class="file-name">{{ filePath.split(/[/\\]/).pop() }}</span>
                <button class="btn-icon" @click="blast.removeFile(filePath)">✕</button>
              </div>
              <div v-if="blast.files.length === 0" class="empty-hint">
                拖拽文件至上方区域<br />或者点击添加
              </div>
            </div>
          </div>
          <!-- Text 模式 -->
          <div v-else>
            <textarea v-model="blast.queryText" class="query-textarea" placeholder=">Sequence_Title&#10;ATCG..." />
          </div>
        </div>
      </div>

      <!-- 参数配置面板 -->
      <div class="panel params-panel">
        <div class="panel-header">
          <span class="panel-title">⚙️ 参数配置</span>
          <button class="btn-run" @click="launchBlast">▶ 开始分析</button>
        </div>
        <div class="panel-body scroll-v">
          <div class="form-group">
            <label>分析程序 (Program)</label>
            <select v-model="blast.params.program" class="form-input">
              <option v-for="opt in PROGRAM_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>目标数据库 (Database)</label>
            <select v-model="blast.params.database" class="form-input">
              <optgroup label="核酸数据库">
                <option v-for="opt in DB_OPTIONS.nucleotide" :key="opt.value" :value="opt.value">{{ opt.label }}
                </option>
              </optgroup>
              <optgroup label="蛋白数据库">
                <option v-for="opt in DB_OPTIONS.protein" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </optgroup>
            </select>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>E-Value 阈值</label>
              <input v-model.number="blast.params.evalue" type="number" step="0.01" class="form-input" />
            </div>
            <div class="form-group">
              <label>最大匹配数</label>
              <input v-model.number="blast.params.maxHits" type="number" class="form-input" />
            </div>
          </div>
          <div class="form-group">
            <label>计分矩阵 (Matrix)</label>
            <select v-model="blast.params.matrix" class="form-input">
              <option v-for="opt in MATRIX_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>空隙开启 (Opening)</label>
              <input v-model.number="blast.params.gapOpen" type="number" class="form-input" />
            </div>
            <div class="form-group">
              <label>空隙延伸 (Extension)</label>
              <input v-model.number="blast.params.gapExtend" type="number" class="form-input" />
            </div>
          </div>
          <div class="form-group">
            <label>并行处理线程数</label>
            <input v-model.number="blast.params.threads" type="number" min="1" max="64" class="form-input" />
            <div class="tip">设置本地 CPU 核心调用数量，建议不要超过物理核心数</div>
          </div>
          <div class="checkbox-row">
            <input v-model="blast.params.filterLowComplexity" type="checkbox" id="filter-check" />
            <label for="filter-check">过滤低复杂度区域 (Filter)</label>
          </div>
        </div>
      </div>
    </div>

    <!-- 右栏：历史 + 结果 -->
    <div class="right-col">
      <!-- 历史面板 -->
      <div class="panel history-panel" :class="{ collapsed: !blast.historyVisible }">
        <div class="panel-header">
          <span class="panel-title">🕐 分析历史</span>
          <div class="header-actions">
            <button class="btn-icon" @click="clearAllHistory" title="清空全部历史">🗑</button>
            <button class="btn-icon" @click="blast.toggleHistory" title="收起">
              {{ blast.historyVisible ? '✖' : '◀' }}
            </button>
          </div>
        </div>
        <div v-if="blast.historyVisible" class="panel-body scroll-v">
          <div v-for="task in blast.tasks" :key="task.taskId" class="task-item"
            :class="{ active: blast.activeTaskId === task.taskId }" @click="selectTask(task.taskId)">
            <div class="task-name" @dblclick="startRename(task, $event)" title="双击重命名">
              <span v-if="editingTaskId !== task.taskId">{{ task.fileName }}</span>
              <input v-else v-model="editName" class="rename-input" ref="renameInputRef"
                @blur="commitRename(task)" @keyup.enter="commitRename(task)" @keyup.esc="cancelRename" @click.stop />
            </div>
            <div class="task-meta">
              <span class="task-status" :class="task.status">{{ statusLabel(task.status) }}</span>
              <div v-if="task.status === 'running'" class="progress-bar">
                <div class="progress-fill" :style="{ width: task.progress + '%' }" />
              </div>
            </div>
            <div class="task-actions">
              <button v-if="task.status === 'running'" class="btn-icon sm" @click.stop="pauseTask(task.taskId)"
                title="暂停">⏸</button>
              <button v-if="task.status === 'running'" class="btn-icon sm" @click.stop="stopTask(task.taskId)"
                title="停止">⏹</button>
              <button class="btn-icon sm" @click="deleteSingleTask(task.taskId, $event)" title="删除此记录">🗑</button>
            </div>
          </div>
          <div v-if="blast.tasks.length === 0" class="empty-hint">暂无历史任务</div>
        </div>
      </div>

      <!-- 结果面板 -->
      <div class="panel result-panel">
        <div class="panel-header">
          <span class="panel-title">📊 {{ blast.resultTitle }}</span>
          <div class="header-actions">
            <button class="btn-ghost" @click="translateAll" :disabled="isTranslating">
              {{ isTranslating ? '⏳ 翻译中...' : '🌐 一键 AI 翻译' }}
            </button>
            <button class="btn-ghost" @click="exportResults">💾 导出报表</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-container">
            <table v-if="blast.results.length > 0">
              <thead>
                <tr>
                  <th>查询序列</th>
                  <th>最匹配项 (鉴定详情)</th>
                  <th>生物学背景</th>
                  <th>相似度</th>
                  <th>E值</th>
                  <th>登录号</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(hit, idx) in blast.results" :key="idx">
                  <td class="query-col">{{ hit.queryTitle }}</td>
                  <td class="hit-detail-col">
                    <div class="hit-species">{{ hit.translatedName || hit.speciesName }}</div>
                    <div v-if="hit.genusStrain" class="hit-strain">{{ hit.genusStrain }}</div>
                    <div v-if="hit.geneSource" class="hit-source">{{ hit.geneSource }}</div>
                  </td>
                  <td class="bio-col">
                    <div v-if="hit.seqType" class="bio-tag">{{ hit.seqType }}</div>
                    <div v-if="hit.host" class="bio-host">宿主: {{ hit.host }}</div>
                    <div v-if="hit.alignLen" class="bio-len">比对长度: {{ hit.alignLen }}bp</div>
                  </td>
                  <td>
                    <div class="identity-bar">
                      <div class="identity-fill" :style="{ width: hit.identity + '%' }" />
                      <span>{{ hit.identity.toFixed(1) }}%</span>
                    </div>
                  </td>
                  <td class="mono">{{ hit.evalue }}</td>
                  <td>
                    <a class="accession-link" :href="'https://www.ncbi.nlm.nih.gov/nuccore/' + hit.accession"
                      target="_blank" @click.prevent="openNcbi(hit.accession)">{{ hit.accession }}</a>
                  </td>
                  <td>
                    <button class="btn-icon sm" @click="openNcbi(hit.accession)" title="在 NCBI 查看">🔗</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">
              <div class="empty-icon">🧬</div>
              <p>选择历史任务或提交新序列开始分析</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!blast.historyVisible" class="history-tag" @click="blast.toggleHistory">
      🕐 分析历史
    </div>
  </div>
</template>

<style scoped>
.blast-view {
  display: flex;
  height: 100%;
  gap: 0;
  background: #f1f5f9;
  position: relative;
  overflow: hidden;
  /* Ensure split styling */
}

/* ... */
.history-tag {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background: white;
  border: 1px solid var(--border-color);
  border-right: none;
  border-radius: 8px 0 0 8px;
  padding: 10px 12px;
  font-size: 0.78rem;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  writing-mode: vertical-rl;
  transition: all 0.2s;
  z-index: 100;
  /* Increased z-index */
}

.history-tag:hover {
  background: #f8fafc;
  transform: translateY(-50%) translateX(-2px);
}

.left-col {
  width: 380px;
  min-width: 380px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--border-color);
}

.right-col {
  flex: 1;
  display: flex;
  gap: 1px;
  background: var(--border-color);
}

/* 面板通用 */
.panel {
  background: white;
  display: flex;
  flex-direction: column;
}

.panel-header {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-light);
  background: #fafbfc;
}

.panel-title {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  padding: 14px;
  overflow: hidden;
}

.scroll-v {
  overflow-y: auto;
}

/* 输入面板 */
.input-panel {
  flex: 1;
}

.params-panel {
  flex: 1;
}

.mode-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.mode-tab {
  flex: 1;
  padding: 8px;
  text-align: center;
  font-size: 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  background: var(--bg-page);
  color: var(--text-secondary);
  transition: all 0.2s;
}

.mode-tab.active {
  background: var(--accent-blue);
  color: white;
}

.drop-zone {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  border: 2px dashed var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 0.85rem;
  transition: all 0.2s;
  margin-bottom: 12px;
}

.drop-zone:hover {
  border-color: var(--accent-blue);
  background: rgba(59, 130, 246, 0.03);
}

.file-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.badge {
  background: var(--bg-page);
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 0.7rem;
}

.file-list {
  max-height: 200px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  font-size: 0.8rem;
  border-bottom: 1px solid var(--border-light);
}

.file-name {
  color: var(--text-primary);
  font-family: monospace;
  font-size: 0.78rem;
}

.query-textarea {
  width: 100%;
  min-height: 200px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: 'Consolas', monospace;
  font-size: 0.82rem;
  resize: vertical;
}

/* 表单 */
.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 0.78rem;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-primary);
}

.form-input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 0.82rem;
  background: #fafbfc;
}

.form-input:focus {
  outline: none;
  border-color: var(--accent-blue);
}

.form-row {
  display: flex;
  gap: 10px;
}

.form-row .form-group {
  flex: 1;
}

.tip {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 3px;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}

.checkbox-row input {
  width: auto;
  height: auto;
}

.checkbox-row label {
  margin: 0;
  font-size: 0.82rem;
}

.btn-run {
  padding: 6px 14px;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.3);
  transition: all 0.2s;
}

.btn-run:hover {
  transform: translateY(-1px);
}

/* 历史面板 */
.history-panel {
  width: 240px;
  min-width: 240px;
}

.history-panel.collapsed {
  width: 0;
  min-width: 0;
  overflow: hidden;
}

.task-item {
  padding: 10px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background 0.15s;
}

.task-item:hover {
  background: #f8fafc;
}

.task-item.active {
  background: rgba(59, 130, 246, 0.05);
  border-left: 3px solid var(--accent-blue);
}

.task-name {
  font-size: 0.82rem;
  font-weight: 500;
  margin-bottom: 4px;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-status {
  font-size: 0.72rem;
  padding: 2px 6px;
  border-radius: 4px;
}

.task-status.queued {
  background: #f1f5f9;
  color: #64748b;
}

.task-status.running {
  background: #dbeafe;
  color: #2563eb;
}

.task-status.done {
  background: #d1fae5;
  color: #059669;
}

.task-status.error {
  background: #fee2e2;
  color: #dc2626;
}

.task-status.paused {
  background: #fef3c7;
  color: #d97706;
}

.progress-bar {
  flex: 1;
  height: 4px;
  background: #e2e8f0;
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent-blue);
  transition: width 0.3s;
}

.task-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
}

.rename-input {
  width: 100%;
  font-size: 0.82rem;
  font-weight: 500;
  padding: 2px 4px;
  border: 1px solid var(--accent-blue);
  border-radius: 4px;
  outline: none;
}

/* 结果面板 */
.result-panel {
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-ghost {
  padding: 4px 10px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.78rem;
  border-radius: 4px;
  transition: all 0.15s;
}

.btn-ghost:hover {
  background: #f1f5f9;
  color: var(--text-primary);
}

.table-container {
  overflow: auto;
  height: 100%;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

thead th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
}

tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-light);
}

.mono {
  font-family: monospace;
  font-size: 0.78rem;
}

.identity-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.identity-fill {
  height: 6px;
  background: var(--accent-green);
  border-radius: 3px;
  min-width: 20px;
}

.accession-link {
  color: var(--accent-blue);
  cursor: pointer;
  text-decoration: none;
}

.accession-link:hover {
  text-decoration: underline;
}

/* 鉴定详情列 3 行布局 */
.query-col {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
  font-size: 0.78rem;
}

.hit-detail-col {
  min-width: 180px;
}

.hit-species {
  font-weight: 700;
  font-size: 0.88rem;
  color: var(--text-primary);
  line-height: 1.4;
}

.hit-strain {
  font-size: 0.74rem;
  color: var(--text-muted);
  margin-top: 2px;
}

.hit-source {
  font-size: 0.72rem;
  color: var(--accent-blue);
  margin-top: 2px;
}

/* 生物学背景列 */
.bio-col {
  min-width: 100px;
}

.bio-tag {
  font-size: 0.74rem;
  color: var(--text-secondary);
}

.bio-host {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 2px;
}

.bio-len {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 2px;
}

.btn-icon {
  background: none;
  color: var(--text-muted);
  padding: 4px;
  border-radius: 4px;
  font-size: 0.85rem;
}

.btn-icon:hover {
  background: #f1f5f9;
}

.btn-icon.sm {
  font-size: 0.75rem;
}

.empty-state {
  text-align: center;
  padding: 100px 20px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 3rem;
  opacity: 0.3;
  margin-bottom: 12px;
}

.empty-hint {
  text-align: center;
  padding: 20px;
  color: var(--text-muted);
  font-size: 0.82rem;
}

/* 浮动历史标签 */
.history-tag {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background: white;
  border: 1px solid var(--border-color);
  border-right: none;
  border-radius: 8px 0 0 8px;
  padding: 10px 12px;
  font-size: 0.78rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  writing-mode: vertical-rl;
  transition: all 0.2s;
  z-index: 10;
}

.history-tag:hover {
  background: #f1f5f9;
}
</style>
