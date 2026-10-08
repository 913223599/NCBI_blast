<script setup lang="ts">
/**
 * DiversityAnalysisModal.vue
 * 16S 扩增子混样多样性还原与 rrnDB 拷贝数归一化分析面板
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { apiGet, apiPost, apiDelete, API_BASE } from '../../bridge/electron-bridge'
import { useAppStore } from '../../stores/app'
import { useStrainStore } from '../../stores/strain'
import UniversalUpload from '../common/UniversalUpload.vue'

const props = withDefaults(defineProps<{
  modelValue?: boolean
  initialFilePath?: string
  embedded?: boolean
}>(), {
  modelValue: true,
  embedded: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
  (e: 'switchToIsolate'): void
  (e: 'taskChanged', taskId: string): void
}>()

const appStore = useAppStore()
const strainStore = useStrainStore()

// 状态定义
const activeTab = ref<'chart' | 'taxa' | 'matrix'>('chart')
const abundanceMode = ref<'norm' | 'raw'>('norm') // 'norm': rrnDB校正, 'raw': 原始Reads
const currentFilePath = ref<string>('')
const isDetecting = ref(false)
const detectedPackage = ref<any>(null)

// 样本合并/分组配置状态 (支持如 1-5 合并为组A, 6-9 为组B 等)
export interface SampleGroupDef {
  id: string
  name: string
  pattern: string
}

const isGroupView = ref(false) // 是否启用合并分组展示
const showGroupModal = ref(false) // 分组配置弹窗
const groupChunkSize = ref<number>(4) // 连续 X 个一组的默认 X 跨度
const sampleGroups = ref<SampleGroupDef[]>([]) // 动态分组规则，杜绝硬编码

// 物种总览检索状态
const taxaSearchQuery = ref('')

// 历史记录状态
const showHistoryDrawer = ref(false)
const historyTasks = ref<any[]>([])
const isLoadingHistory = ref(false)

// 任务执行状态
const isRunning = ref(false)
const taskId = ref<string>('')
const progress = ref<number>(0)
const currentStep = ref<string>('')
const currentSample = ref<string>('')
const processedReads = ref<number>(0)
const totalReads = ref<number>(0)
const processedSamples = ref<number>(0)
const totalSamples = ref<number>(0)
const results = ref<any>(null)
let pollTimer: any = null

// 颜色板定义 (支持多达 16 种优势物种区分)
const PALETTE = [
  '#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed',
  '#0891b2', '#db2777', '#4b5563', '#4f46e5', '#16a34a',
  '#ea580c', '#e11d48', '#9333ea', '#0284c7', '#65a30d',
  '#94a3b8'
]

// 交互悬停 Tooltip 状态
const tooltip = ref<{
  visible: boolean
  x: number
  y: number
  sample: string
  taxon: string
  rawCount: number
  rawPct: number
  gcn: number
  normPct: number
}>({
  visible: false,
  x: 0,
  y: 0,
  sample: '',
  taxon: '',
  rawCount: 0,
  rawPct: 0,
  gcn: 1,
  normPct: 0
})

interface StackedSegment {
  taxon: string
  pct: number
  rawCount: number
  rawPct: number
  normPct: number
  gcn: number
  color: string
  yBottom: number
  yTop: number
}

interface StackedSample {
  sampleName: string
  totalReads: number
  isGroup?: boolean
  memberSamples?: string[]
  segments: StackedSegment[]
}

/** 同步最新任务状态或恢复轮询 */
async function syncLatestTaskOrResume() {
  // 1. 如果已有任务 ID，立即刷新该任务
  if (taskId.value) {
    try {
      const statusRes = await apiGet(`/api/diversity/status/${taskId.value}`)
      if (statusRes && statusRes.status !== 'not_found') {
        progress.value = statusRes.progress || 0
        currentStep.value = statusRes.current_step || ''
        currentSample.value = statusRes.current_sample || ''
        processedReads.value = statusRes.processed_reads || 0
        totalReads.value = statusRes.total_reads || 0
        processedSamples.value = statusRes.processed_samples || 0
        totalSamples.value = statusRes.total_samples || 0

        if (statusRes.status === 'running' || statusRes.status === 'queued') {
          isRunning.value = true
          startPolling()
          return
        } else if (statusRes.status === 'completed') {
          isRunning.value = false
          if (!results.value) {
            fetchResults()
          }
          return
        }
      }
    } catch (e) {
      console.warn('Sync status failed:', e)
    }
  }

  // 2. 若当前无活跃任务，自动向后端探测最新任务 (断点恢复或结果重显)
  try {
    const latest = await apiGet('/api/diversity/latest_task')
    if (latest && latest.task_id && latest.status !== 'none' && latest.status !== 'not_found') {
      taskId.value = latest.task_id
      progress.value = latest.progress || 0
      currentStep.value = latest.current_step || ''
      currentSample.value = latest.current_sample || ''
      processedReads.value = latest.processed_reads || 0
      totalReads.value = latest.total_reads || 0
      processedSamples.value = latest.processed_samples || 0
      totalSamples.value = latest.total_samples || 0

      if (latest.status === 'running' || latest.status === 'queued') {
        isRunning.value = true
        startPolling()
      } else if (latest.status === 'completed') {
        isRunning.value = false
        if (!results.value) {
          fetchResults()
        }
      }
    }
  } catch (e) {
    console.warn('Auto probe latest task failed:', e)
  }

  // 同步历史任务列表
  fetchHistoryTasks()
}

/** 获取所有历史多样性分析任务 */
async function fetchHistoryTasks() {
  isLoadingHistory.value = true
  try {
    const res = await apiGet('/api/diversity/tasks')
    if (Array.isArray(res)) {
      historyTasks.value = res
    }
  } catch (e) {
    console.error('Fetch history tasks error:', e)
  } finally {
    isLoadingHistory.value = false
  }
}

/** 打开/关闭历史记录抽屉 */
function toggleHistoryDrawer() {
  showHistoryDrawer.value = !showHistoryDrawer.value
  if (showHistoryDrawer.value) {
    fetchHistoryTasks()
  }
}

/** 选择并加载历史任务 */
async function selectHistoryTask(task: any) {
  if (!task || !task.task_id) return
  taskId.value = task.task_id
  showHistoryDrawer.value = false
  emit('taskChanged', task.task_id)

  if (task.status === 'completed') {
    isRunning.value = false
    stopPolling()
    await fetchResults()
  } else if (task.status === 'running' || task.status === 'queued') {
    isRunning.value = true
    progress.value = task.progress || 0
    startPolling()
  } else {
    isRunning.value = false
    stopPolling()
    appStore.showNotification(`该历史任务状态为: ${getStatusLabel(task.status)}`, 'warning')
  }
}

/** 删除指定历史任务 */
async function deleteHistoryTask(task: any, e: Event) {
  e.stopPropagation()
  if (!confirm(`确定要彻底删除历史分析任务 "${task.task_name}" 吗？此操作将物理删除所有 Checkpoint 与统计数据。`)) {
    return
  }
  try {
    const res = await apiDelete(`/api/diversity/task/${task.task_id}`)
    if (res && res.status === 'deleted') {
      appStore.showNotification('历史任务已成功删除', 'success')
      if (taskId.value === task.task_id) {
        results.value = null
        taskId.value = ''
      }
      fetchHistoryTasks()
    } else {
      throw new Error(res?.detail || '删除失败')
    }
  } catch (err: any) {
    appStore.showNotification(`删除失败: ${err.message || err}`, 'error')
  }
}

/** 清空所有历史任务 */
async function clearAllHistory() {
  if (!confirm('确定要清空全部历史多样性分析结果吗？此操作不可恢复。')) {
    return
  }
  try {
    const res = await apiDelete('/api/diversity/tasks/clear')
    if (res && res.status === 'cleared') {
      appStore.showNotification('已清空全部历史分析数据', 'success')
      results.value = null
      taskId.value = ''
      historyTasks.value = []
      showHistoryDrawer.value = false
    }
  } catch (err: any) {
    appStore.showNotification(`清空失败: ${err.message || err}`, 'error')
  }
}

/** 重置并返回新建分析界面 */
function resetToNewAnalysis() {
  results.value = null
  taskId.value = ''
  currentFilePath.value = ''
  detectedPackage.value = null
}

function formatTime(timestamp: number | string | undefined) {
  if (!timestamp) return ''
  const d = typeof timestamp === 'number' && timestamp < 10000000000 ? new Date(timestamp * 1000) : new Date(timestamp)
  if (isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatReadsCount(num: number | undefined) {
  if (!num) return '0'
  return num.toLocaleString()
}

function getStatusLabel(s: string) {
  const m: Record<string, string> = {
    completed: '已完成',
    running: '分析中',
    interrupted: '已中断',
    queued: '排队中',
    error: '失败'
  }
  return m[s] || s
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.initialFilePath) {
      currentFilePath.value = props.initialFilePath
      detectPackage(props.initialFilePath)
    }
    // 面板重新打开时，立即刷新进度并恢复轮询
    syncLatestTaskOrResume()
    fetchHistoryTasks()
  } else {
    // 仅暂停定时器，保留当前任务与数据状态
    stopPolling()
    showHistoryDrawer.value = false
  }
})

onMounted(() => {
  if (props.modelValue) {
    syncLatestTaskOrResume()
    fetchHistoryTasks()
  }
})

onUnmounted(() => {
  stopPolling()
})

function close() {
  emit('update:modelValue', false)
  emit('close')
}

defineExpose({
  toggleHistoryDrawer,
  startAnalysis,
  resetToNewAnalysis,
  selectHistoryTask,
  fetchHistoryTasks,
  taskId,
  results
})

/** 智能检测压缩包 */
async function detectPackage(filePath: string) {
  if (!filePath) return
  isDetecting.value = true
  try {
    const res = await apiPost('/api/diversity/detect_package', { file_path: filePath })
    if (res && res.is_amplicon_package) {
      detectedPackage.value = res
    } else {
      detectedPackage.value = null
    }
  } catch (e) {
    console.error('Detect package failed:', e)
  } finally {
    isDetecting.value = false
  }
}

function handleUploadSuccess(paths: string[]) {
  if (paths && paths.length > 0 && paths[0]) {
    currentFilePath.value = paths[0]
    detectPackage(paths[0])
  }
}

/** 启动分析 */
async function startAnalysis() {
  if (!currentFilePath.value) {
    appStore.showNotification('请先选择或拖入测序结果压缩包', 'warning')
    return
  }

  isRunning.value = true
  progress.value = 2.0
  currentStep.value = '正在初始化分析任务...'
  results.value = null

  try {
    const res = await apiPost('/api/diversity/run', {
      input_path: currentFilePath.value
    })

    if (res && res.task_id) {
      taskId.value = String(res.task_id)
      startPolling()
    } else {
      throw new Error(res?.detail || '任务创建失败')
    }
  } catch (err: any) {
    isRunning.value = false
    appStore.showNotification(`启动失败: ${err.message || err}`, 'error')
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!taskId.value) return
    try {
      const statusRes = await apiGet(`/api/diversity/status/${taskId.value}`)
      if (statusRes) {
        progress.value = statusRes.progress || 0
        currentStep.value = statusRes.current_step || ''
        currentSample.value = statusRes.current_sample || ''
        processedReads.value = statusRes.processed_reads || 0
        totalReads.value = statusRes.total_reads || 0
        processedSamples.value = statusRes.processed_samples || 0
        totalSamples.value = statusRes.total_samples || 0

        if (statusRes.status === 'completed') {
          stopPolling()
          fetchResults()
        } else if (statusRes.status === 'error') {
          stopPolling()
          isRunning.value = false
          appStore.showNotification(`分析失败: ${statusRes.error}`, 'error')
        }
      }
    } catch (e) {
      console.error('Polling status error:', e)
    }
  }, 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchResults() {
  try {
    const res = await apiGet(`/api/diversity/results/${taskId.value}`)
    if (res && res.samples && Array.isArray(res.samples)) {
      results.value = res
      isRunning.value = false
      generateConsecutiveGroups(4)
    } else {
      const errMsg = res?.error || res?.detail || '未获取到样本数据'
      appStore.showNotification(`载入分析报告失败: ${errMsg}`, 'error')
    }
  } catch (e: any) {
    isRunning.value = false
    appStore.showNotification(`获取分析报告失败: ${e.message || e}`, 'error')
  }
}

/** 全局 Top 10 物种列表 (其余归入 Other) */
const topTaxaList = computed(() => {
  if (!results.value || !results.value.taxa_overview) return []
  const list = results.value.taxa_overview.slice(0, 10).map((t: any) => t.taxon)
  return list
})

function getTaxonColor(taxon: string): string {
  const idx = topTaxaList.value.indexOf(taxon)
  if (idx >= 0 && idx < PALETTE.length) {
    return PALETTE[idx] || '#94a3b8'
  }
  return '#94a3b8' // Other
}

/** 所有原始样本名称列表 (自然排序) */
const allSampleNames = computed<string[]>(() => {
  if (!results.value || !results.value.samples) return []
  return results.value.samples.map((s: any) => s.sample_name).sort((a: string, b: string) => {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
  })
})

/** 范围模式智能解析器 (例如输入 "1-5", "6-9" 等自动识别对应样本) */
function parseSamplePattern(pattern: string, samples: string[]): string[] {
  if (!pattern || !pattern.trim()) return []
  const matched = new Set<string>()
  const tokens = pattern.split(/[,，\s]+/).map(t => t.trim()).filter(Boolean)

  for (const token of tokens) {
    // 匹配范围表达: 如 1-5, -1--5, 1~5, 1至5
    const rangeMatch = token.match(/^(-?\d+)\s*[-~至到]\s*(-?\d+)$/)
    if (rangeMatch) {
      const num1 = Math.abs(parseInt(rangeMatch[1] || '0', 10))
      const num2 = Math.abs(parseInt(rangeMatch[2] || '0', 10))
      const minNum = Math.min(num1, num2)
      const maxNum = Math.max(num1, num2)

      samples.forEach(sName => {
        const m = sName.match(/\d+/)
        if (m) {
          const val = parseInt(m[0], 10)
          if (val >= minNum && val <= maxNum) {
            matched.add(sName)
          }
        }
      })
      continue
    }

    // 精确匹配或前缀匹配
    samples.forEach(sName => {
      const pureToken = token.replace(/^-/, '')
      const pureSample = sName.replace(/^-/, '')
      if (sName === token || pureSample === pureToken || sName.toLowerCase().includes(token.toLowerCase())) {
        matched.add(sName)
      }
    })
  }

  return Array.from(matched).sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
}

/** 动态计算每个分组实际匹配到的样本清单 */
const activeGroups = computed(() => {
  const samples = allSampleNames.value
  return sampleGroups.value.map(g => ({
    ...g,
    matchedSamples: parseSamplePattern(g.pattern, samples)
  }))
})

/** 计算未被任何自定义组包含的剩余样本 */
const unassignedSamples = computed(() => {
  const samples = allSampleNames.value
  const assigned = new Set<string>()
  activeGroups.value.forEach(g => {
    g.matchedSamples.forEach(s => assigned.add(s))
  })
  return samples.filter(s => !assigned.has(s))
})

/** 核心数据驱动源：当前活跃的样本集合 (支持原始样本 vs 合并组自由切换) */
const activeSamples = computed(() => {
  if (!results.value || !results.value.samples) return []
  const rawSamples = results.value.samples

  // 若未启用分组合并视图，直接返回原始所有点位
  if (!isGroupView.value) {
    return rawSamples
  }

  const validGroups = activeGroups.value.filter(g => g.name.trim() && g.matchedSamples.length > 0)
  if (validGroups.length === 0) {
    return rawSamples
  }

  const assignedNames = new Set<string>()
  const mergedResult: any[] = []

  // 1. 计算各合并组聚合数据
  for (const group of validGroups) {
    const subSamples = rawSamples.filter((s: any) => group.matchedSamples.includes(s.sample_name))
    if (subSamples.length === 0) continue

    subSamples.forEach((s: any) => assignedNames.add(s.sample_name))

    let groupTotalReads = 0
    let groupClassifiedReads = 0
    const taxaCounts: Record<string, number> = {}
    const gcnMap: Record<string, number> = {}

    for (const sub of subSamples) {
      groupTotalReads += (sub.total_reads || 0)
      groupClassifiedReads += (sub.classified_reads || 0)
      for (const d of sub.norm_result?.details || []) {
        taxaCounts[d.taxon] = (taxaCounts[d.taxon] || 0) + (d.raw_count || 0)
        gcnMap[d.taxon] = d.gcn_mean || 1.0
      }
    }

    // 重新执行 rrnDB 拷贝数归一化与丰度占比换算
    let totalNorm = 0
    const tempDetails: any[] = []
    for (const [taxon, count] of Object.entries(taxaCounts)) {
      const gcn = gcnMap[taxon] || 1.0
      const normVal = count / gcn
      totalNorm += normVal
      tempDetails.push({
        taxon,
        raw_count: count,
        raw_pct: groupClassifiedReads > 0 ? (count / groupClassifiedReads) * 100 : 0,
        gcn_mean: gcn,
        norm_count: normVal
      })
    }

    const details = tempDetails.map(d => ({
      ...d,
      norm_pct: totalNorm > 0 ? (d.norm_count / totalNorm) * 100 : 0,
      raw_pct: Math.round(d.raw_pct * 100) / 100,
      gcn_rank: 'species',
      gcn_matched: true
    })).sort((a, b) => b.raw_count - a.raw_count)

    mergedResult.push({
      sample_name: group.name,
      is_group: true,
      member_samples: group.matchedSamples,
      total_reads: groupTotalReads,
      classified_reads: groupClassifiedReads,
      taxa_counts: taxaCounts,
      norm_result: {
        total_raw: groupClassifiedReads,
        total_norm: totalNorm,
        details
      }
    })
  }

  // 2. 将未被任何分组覆盖的点位作为单独样本补充到列表末尾
  const unassigned = rawSamples.filter((s: any) => !assignedNames.has(s.sample_name))
  return [...mergedResult, ...unassigned]
})

/** 分组管理操作方法 */
function addGroup() {
  const nextIdx = sampleGroups.value.length + 1
  sampleGroups.value.push({
    id: `g_${Date.now()}`,
    name: `分组 ${nextIdx}`,
    pattern: ''
  })
}

function removeGroup(id: string) {
  sampleGroups.value = sampleGroups.value.filter(g => g.id !== id)
}

/** 生成连续 X 个一组的分组规则 (完全动态，彻底杜绝硬编码) */
function generateConsecutiveGroups(chunkSize?: number) {
  const size = Math.max(1, Number(chunkSize ?? groupChunkSize.value) || 4)
  groupChunkSize.value = size
  const samples = allSampleNames.value
  if (!samples || samples.length === 0) {
    sampleGroups.value = []
    return
  }

  const nums = samples.map(s => {
    const m = s.match(/\d+/)
    return m ? parseInt(m[0], 10) : null
  }).filter((n): n is number => n !== null)

  const newGroups: SampleGroupDef[] = []
  if (nums.length === samples.length && nums.length > 0) {
    const minNum = Math.min(...nums)
    const maxNum = Math.max(...nums)
    let gIdx = 1
    for (let start = minNum; start <= maxNum; start += size) {
      const end = Math.min(start + size - 1, maxNum)
      const pattern = start === end ? `${start}` : `${start}-${end}`
      newGroups.push({
        id: `g_${gIdx}_${Date.now()}`,
        name: `分组 ${gIdx} (点位 ${pattern})`,
        pattern
      })
      gIdx++
    }
  } else {
    let gIdx = 1
    for (let i = 0; i < samples.length; i += size) {
      const chunk = samples.slice(i, i + size)
      newGroups.push({
        id: `g_${gIdx}_${Date.now()}`,
        name: `分组 ${gIdx} (${chunk[0]}~${chunk[chunk.length - 1]})`,
        pattern: chunk.join(',')
      })
      gIdx++
    }
  }

  sampleGroups.value = newGroups
}

/** 快捷设置步长并立即重新生成分组 */
function setChunkSizeAndGenerate(size: number) {
  groupChunkSize.value = size
  generateConsecutiveGroups(size)
}

/** 清空全部规则，进入纯手动自定义分组模式 */
function clearAllGroups() {
  sampleGroups.value = []
}

function resetDefaultGroups() {
  generateConsecutiveGroups(groupChunkSize.value || 4)
}

/** 柱状图数据计算 (由 activeSamples 动态驱动，支持合并与原始视图) */
const stackedBarData = computed<StackedSample[]>(() => {
  const samples = activeSamples.value
  if (!samples || samples.length === 0) return []
  const isNorm = abundanceMode.value === 'norm'

  return samples.map((s: any) => {
    const details = s.norm_result?.details || []
    const segments: StackedSegment[] = []
    let cumulative = 0

    // 分离 Top 物种与 Others
    const topItems: any[] = []
    let otherPct = 0
    let otherRaw = 0

    details.forEach((d: any) => {
      const pct = Number(isNorm ? d.norm_pct : d.raw_pct) || 0
      if (topTaxaList.value.includes(d.taxon)) {
        topItems.push({
          taxon: d.taxon,
          pct: pct,
          rawCount: d.raw_count,
          rawPct: d.raw_pct,
          normPct: d.norm_pct,
          gcn: d.gcn_mean
        })
      } else {
        otherPct += pct
        otherRaw += d.raw_count
      }
    })

    if (otherPct > 0) {
      topItems.push({
        taxon: '其他 (Others)',
        pct: Math.round(otherPct * 100) / 100,
        rawCount: otherRaw,
        rawPct: Math.round(otherPct * 100) / 100,
        normPct: Math.round(otherPct * 100) / 100,
        gcn: 1.0
      })
    }

    topItems.forEach((item) => {
      const height = Number(item.pct) || 0
      segments.push({
        taxon: item.taxon,
        pct: height,
        rawCount: item.rawCount,
        rawPct: item.rawPct,
        normPct: item.normPct,
        gcn: item.gcn,
        color: getTaxonColor(item.taxon),
        yBottom: cumulative,
        yTop: cumulative + height
      })
      cumulative += height
    })

    return {
      sampleName: s.sample_name,
      isGroup: !!s.is_group,
      memberSamples: s.member_samples || [],
      totalReads: s.total_reads,
      segments
    }
  })
})

/** 物种总览与排行榜检索过滤 (专为回答“有什么物种、各占多少”设计) */
const filteredTaxaOverview = computed(() => {
  if (!results.value || !results.value.taxa_overview) return []
  const list = results.value.taxa_overview
  const q = taxaSearchQuery.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((t: any) => t.taxon.toLowerCase().includes(q))
})

function showSegmentTooltip(e: MouseEvent, seg: any, sampleName: string) {
  tooltip.value = {
    visible: true,
    x: e.clientX + 12,
    y: e.clientY - 20,
    sample: sampleName,
    taxon: seg.taxon,
    rawCount: seg.rawCount,
    rawPct: seg.rawPct,
    gcn: seg.gcn,
    normPct: seg.normPct
  }
}

function hideTooltip() {
  tooltip.value.visible = false
}

/** 导出 Excel 报告 */
function exportExcel() {
  if (!taskId.value) return
  const url = `${API_BASE}/api/diversity/export_excel/${taskId.value}`
  window.open(url, '_blank')
}

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div 
    v-if="embedded || modelValue" 
    :class="[embedded ? 'diversity-embedded-container' : 'modal-overlay']" 
    @click.self="!embedded && close()"
  >
    <div class="modal-container-neo" :class="{ 'is-embedded': embedded }">
      <!-- 头部 -->
      <div class="modal-header-neo">
        <div class="header-left">
          <div class="icon-wrap">
            <svg class="header-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7c3 0 5 5 8 5s5-5 8-5M4 17c3 0 5-5 8-5s5 5 8 5M7 8.5v7M17 8.5v7"/>
            </svg>
          </div>
          <div>
            <h2 class="title">16S 扩增子混样多样性还原与 rrnDB 拷贝数校正</h2>
            <p class="subtitle">针对未纯化样本、环境混样与多采样重复点位的高通量全长群落结构解析</p>
          </div>
        </div>
        <div class="header-right">
          <!-- 新建分析按钮 -->
          <button v-if="results && !isRunning" class="btn-tool-neo" @click="resetToNewAnalysis" title="导入新测序包进行分析">
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            <span>新建分析</span>
          </button>

          <!-- 历史记录按钮 -->
          <button class="btn-tool-neo" :class="{ active: showHistoryDrawer }" @click="toggleHistoryDrawer" title="查看或管理历史多样性分析结果">
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="12" cy="12" r="9" stroke-width="2"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 7v5l3 3"/>
            </svg>
            <span>历史分析 ({{ historyTasks.length }})</span>
          </button>

          <button v-if="results" class="btn-export-neo" @click="exportExcel">
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
            <span>导出 Excel 报告</span>
          </button>

          <!-- 视图模式操作: 内嵌模式下提供切回单株结果按钮，浮窗模式下提供关闭✕按钮 -->
          <button v-if="embedded" class="btn-switch-isolate" @click="emit('switchToIsolate')" title="切换到单株鉴定结果页面">
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 15l-3-3m0 0l3-3m-3 3h8M3 12a9 9 0 1118 0 9 9 0 01-18 0z"/>
            </svg>
            <span>单株结果</span>
          </button>
          <button v-else class="btn-close-neo" @click="close">✕</button>
        </div>
      </div>

      <!-- 载入与控制区 -->
      <div v-if="!results && !isRunning" class="import-section-neo">
        <div class="upload-box-wrapper">
          <UniversalUpload 
            type="fasta"
            accept=".zip,.fastq,.fastq.gz"
            label="拖入生工测序交付压缩包 (例如: 16S_三代测序交付结果.zip) 或 FASTQ 集合"
            @success="handleUploadSuccess"
          />
        </div>

        <div v-if="detectedPackage" class="detect-badge-card">
          <div class="badge-status-tag">识别成功</div>
          <div class="detect-info">
            <span class="name">{{ detectedPackage.file_name }}</span>
            <span class="desc">
              检测到 <strong>{{ detectedPackage.fastq_count }} 个</strong> 独立样本的单分子 FASTQ 数据（生工三代测序标准交付件）
            </span>
          </div>
          <button class="btn-start-action" @click="startAnalysis">
            立即启动多样性还原分析
          </button>
        </div>
        <div v-else-if="currentFilePath" class="fallback-launch">
          <button class="btn-start-action" @click="startAnalysis">
            开始分析该文件
          </button>
        </div>

        <!-- 首页快捷历史记录卡片区 (类似单样本查询) -->
        <div v-if="!detectedPackage && historyTasks.length > 0" class="recent-history-section">
          <div class="recent-header">
            <span class="recent-title">历史分析记录 (点击直接载入查看)</span>
            <button class="recent-all-btn" @click="showHistoryDrawer = true">
              查看全部历史 ({{ historyTasks.length }})
            </button>
          </div>
          <div class="recent-task-grid">
            <div 
              v-for="t in historyTasks.slice(0, 3)" 
              :key="t.task_id" 
              class="recent-task-item"
              @click="selectHistoryTask(t)"
            >
              <div class="recent-item-top">
                <span class="item-name" :title="t.task_name">{{ t.task_name }}</span>
                <span class="item-status" :class="t.status">{{ getStatusLabel(t.status) }}</span>
              </div>
              <div class="recent-item-meta">
                <span>{{ formatTime(t.completed_at || t.created_at) }}</span>
                <span>{{ t.total_samples }} 点位 · {{ formatReadsCount(t.total_reads) }} Reads</span>
              </div>
              <div class="recent-item-actions">
                <button 
                  class="btn-item-del" 
                  title="删除此任务"
                  @click.stop="deleteHistoryTask(t, $event)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 运行进度展示 (多核比对 xx/xx 进度) -->
      <div v-if="isRunning" class="progress-section-neo">
        <div class="progress-card-neo">
          <div class="pulse-icon-svg">
            <svg class="exec-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div class="progress-info">
            <div class="step-text">{{ currentStep }}</div>
            <div class="sample-hint" v-if="currentSample">
              正在处理点位: <strong>{{ currentSample }}</strong>
            </div>
          </div>
          <div class="progress-bar-wrap">
            <div class="bar-fill" :style="{ width: `${progress}%` }"></div>
          </div>
          
          <!-- xx/xx 比对进度与百分比清晰看板 -->
          <div class="progress-meta-row">
            <div class="progress-percent-val">{{ progress }}%</div>
            <div class="progress-counter-badge" v-if="totalReads > 0">
              <span class="counter-label">序列比对:</span>
              <span class="counter-num">{{ processedReads.toLocaleString() }} / {{ totalReads.toLocaleString() }} Reads</span>
            </div>
            <div class="progress-counter-badge samples-badge" v-if="totalSamples > 0">
              <span class="counter-label">样本点位:</span>
              <span class="counter-num">{{ processedSamples }} / {{ totalSamples }}</span>
            </div>
          </div>

          <div class="checkpoint-tip">
            <svg class="shield-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 1.944A11.954 11.954 0 012.166 5C2.056 5.649 2 6.319 2 7c0 5.225 3.34 9.67 8 11.317C14.66 16.67 18 12.225 18 7c0-.682-.057-1.35-.166-2.001A11.954 11.954 0 0110 1.944zM11 14a1 1 0 11-2 0 1 1 0 012 0zm0-7a1 1 0 10-2 0v3a1 1 0 102 0V7z" clip-rule="evenodd"/>
            </svg>
            <span>分片落盘与断点保护 (Checkpoint) 生效中，防止大规模数据 OOM 崩溃</span>
          </div>
        </div>
      </div>

      <!-- 分析结果面板 -->
      <div v-if="results" class="results-dashboard-neo">
        <!-- 统计核心条目与样本合并控制栏 -->
        <div class="stats-overview-bar">
          <div class="stat-pill">
            <span class="label">{{ isGroupView ? '当前展示:' : '样本总数:' }}</span>
            <span class="val">{{ activeSamples.length }} {{ isGroupView ? '个分组/独立样本' : '个采样点位' }}</span>
          </div>
          <div class="stat-pill" v-if="isGroupView">
            <span class="label">覆盖点位:</span>
            <span class="val">{{ results?.total_samples || 0 }} 个原始测序点</span>
          </div>
          <div class="stat-pill">
            <span class="label">有效 Reads:</span>
            <span class="val">{{ (results?.total_classified_reads ?? results?.total_reads ?? 0).toLocaleString() }} 条</span>
          </div>
          <div class="stat-pill">
            <span class="label">检出物种:</span>
            <span class="val">{{ results?.taxa_overview?.length || 0 }} 种</span>
          </div>
          <div class="stat-pill pill-rrndb">
            <span class="label">校正状态:</span>
            <span class="val">rrnDB v5.10 已归一化</span>
          </div>

          <!-- 样本合并与分组控制区 -->
          <div class="group-control-bar">
            <button 
              class="group-toggle-btn" 
              :class="{ active: isGroupView }"
              @click="isGroupView = !isGroupView"
              :title="isGroupView ? '点击切换回原始各个采样点位视图' : '点击按规则合并点位（如 1-5 为一组）'"
            >
              <svg class="group-svg" viewBox="0 0 20 20" fill="currentColor">
                <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" />
              </svg>
              <span>{{ isGroupView ? '合并样本视图 (已启用)' : '合并样本点位' }}</span>
            </button>
            <button 
              class="group-config-btn" 
              @click="showGroupModal = true"
              title="配置合并分组规则 (例如 1-5 合并为对照组，6-9 合并为实验组)"
            >
              <svg class="group-svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
              </svg>
              <span>分组规则 ({{ sampleGroups.length }})</span>
            </button>
          </div>

          <!-- 模式切换开关 -->
          <div class="abundance-mode-toggle">
            <button 
              class="toggle-btn" 
              :class="{ active: abundanceMode === 'norm' }"
              @click="abundanceMode = 'norm'"
              title="消除 16S 基因拷贝数偏好，真实还原微生物细胞丰度"
            >
              rrnDB 拷贝数归一化丰度
            </button>
            <button 
              class="toggle-btn" 
              :class="{ active: abundanceMode === 'raw' }"
              @click="abundanceMode = 'raw'"
              title="原始测序下机 Reads 计数比例"
            >
              原始 Reads 占比
            </button>
          </div>
        </div>

        <!-- 精简导航：聚焦物种构成、排行榜与明细 -->
        <div class="sub-tabs-neo">
          <button class="tab-item" :class="{ active: activeTab === 'chart' }" @click="activeTab = 'chart'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
            </svg>
            <span>物种丰度分布图</span>
          </button>
          <button class="tab-item" :class="{ active: activeTab === 'taxa' }" @click="activeTab = 'taxa'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
            </svg>
            <span>检出物种总览与排行榜 (有什么菌)</span>
          </button>
          <button class="tab-item" :class="{ active: activeTab === 'matrix' }" @click="activeTab = 'matrix'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
            <span>样本 / 分组明细大表</span>
          </button>
        </div>

        <!-- TAB 1: 物种丰度分布图 (由 activeSamples 动态驱动，支持合并视图) -->
        <div v-show="activeTab === 'chart'" class="tab-content-neo scroll-y">
          <div class="chart-container-card">
            <!-- 视图状态提示栏 -->
            <div class="chart-status-banner" v-if="isGroupView">
              <span class="banner-tag">合并模式已生效</span>
              <span class="banner-desc">
                已将随机采样点位合并汇总为 {{ activeSamples.length }} 个样本/组，各组内序列 Reads 已重新按 rrnDB GCN 拷贝数精准归一化
              </span>
            </div>

            <div class="chart-legend-wrap">
              <div 
                v-for="taxon in topTaxaList" 
                :key="taxon" 
                class="legend-badge"
              >
                <span class="dot" :style="{ background: getTaxonColor(taxon) }"></span>
                <span class="text">{{ taxon }}</span>
              </div>
              <div class="legend-badge">
                <span class="dot" style="background: #94a3b8"></span>
                <span class="text">其他 (Others)</span>
              </div>
            </div>

            <!-- SVG 堆叠柱状图 -->
            <div class="svg-scroll-container">
              <svg :width="Math.max(800, stackedBarData.length * 48 + 120)" height="360" class="stacked-bar-svg">
                <!-- 背景网格刻度 -->
                <line x1="50" y1="30" x2="100%" y2="30" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="95" x2="100%" y2="95" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="160" x2="100%" y2="160" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="225" x2="100%" y2="225" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="290" x2="100%" y2="290" stroke="#cbd5e1" />

                <!-- Y 轴标签 -->
                <text x="42" y="34" text-anchor="end" class="axis-txt">100%</text>
                <text x="42" y="99" text-anchor="end" class="axis-txt">75%</text>
                <text x="42" y="164" text-anchor="end" class="axis-txt">50%</text>
                <text x="42" y="229" text-anchor="end" class="axis-txt">25%</text>
                <text x="42" y="294" text-anchor="end" class="axis-txt">0%</text>

                <!-- 样本柱体 -->
                <g v-for="(sample, idx) in stackedBarData" :key="sample.sampleName" :transform="`translate(${65 + idx * 46}, 0)`">
                  <g v-for="seg in sample.segments" :key="seg.taxon">
                    <rect 
                      :y="290 - (seg.yTop / 100 * 260)"
                      :height="(seg.pct / 100 * 260)"
                      width="32"
                      :fill="seg.color"
                      rx="3"
                      class="bar-seg"
                      @mousemove="showSegmentTooltip($event, seg, sample.sampleName)"
                      @mouseleave="hideTooltip"
                    />
                  </g>
                  <!-- 分组合并标记 -->
                  <rect 
                    v-if="sample.isGroup" 
                    x="2" 
                    y="294" 
                    width="28" 
                    height="4" 
                    rx="2" 
                    fill="#3b82f6" 
                  />
                  <!-- X 轴样本名 -->
                  <text 
                    x="16" 
                    y="312" 
                    text-anchor="end" 
                    transform="rotate(-40, 16, 312)" 
                    class="sample-x-label"
                    :class="{ 'label-group': sample.isGroup }"
                  >
                    {{ sample.sampleName }}
                  </text>
                </g>
              </svg>
            </div>
          </div>
        </div>

        <!-- TAB 2: 检出物种总览与排行榜 (回答“到底有什么菌，各自多少”) -->
        <div v-show="activeTab === 'taxa'" class="tab-content-neo scroll-y">
          <div class="taxa-overview-card">
            <!-- 顶部过滤与操作栏 -->
            <div class="taxa-toolbar">
              <div class="taxa-search-box">
                <svg class="search-svg" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/>
                </svg>
                <input 
                  type="text" 
                  v-model="taxaSearchQuery" 
                  placeholder="搜索检出菌种或属名 (如 Pseudomonas、Bacillus...)" 
                  class="taxa-search-input"
                />
                <button v-if="taxaSearchQuery" class="clear-search-btn" @click="taxaSearchQuery = ''">✕</button>
              </div>

              <div class="taxa-toolbar-right">
                <span class="taxa-count-tag">
                  共计检出 <strong>{{ filteredTaxaOverview.length }}</strong> 种微生物
                </span>
                <button class="btn-export-excel" @click="exportExcel">
                  <svg viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd" />
                  </svg>
                  <span>导出 Excel 报表</span>
                </button>
              </div>
            </div>

            <!-- 物种总览与排行榜表格 -->
            <table class="neo-data-table taxa-table">
              <thead>
                <tr>
                  <th style="width: 60px;">排名</th>
                  <th>物种拉丁学名 (Taxon)</th>
                  <th style="width: 130px;">16S 拷贝数 (GCN)</th>
                  <th style="width: 120px;">总检出 Reads</th>
                  <th style="width: 240px;">总体校正相对丰度</th>
                  <th style="width: 120px;">原始占比</th>
                  <th style="width: 150px;">点位检出覆盖率</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(t, idx) in filteredTaxaOverview" :key="t.taxon" class="taxa-row">
                  <td class="text-center font-bold">
                    <span class="rank-badge" :class="Number(idx) < 3 ? `rank-${Number(idx) + 1}` : 'rank-normal'">
                      {{ Number(idx) + 1 }}
                    </span>
                  </td>
                  <td>
                    <div class="taxon-name-wrap">
                      <span class="taxon-latin-name">{{ t.taxon }}</span>
                      <span class="top-tag" v-if="Number(idx) === 0">绝对优势种</span>
                      <span class="top-sub-tag" v-else-if="Number(idx) < 3">主要优势种</span>
                    </div>
                  </td>
                  <td>
                    <div class="gcn-cell">
                      <span class="gcn-val">{{ t.gcn_mean || 1.0 }}</span>
                      <span class="badge-match" :class="t.gcn_matched !== false ? 'match-ok' : 'match-fallback'">
                        {{ t.gcn_rank || 'species' }}
                      </span>
                    </div>
                  </td>
                  <td class="mono font-bold">{{ (t.raw_count ?? t.total_raw_count ?? 0).toLocaleString() }}</td>
                  <td>
                    <div class="abundance-progress-wrap">
                      <div class="progress-bar-bg">
                        <div 
                          class="progress-bar-fill" 
                          :style="{ width: `${Math.min(100, Math.max(t.norm_pct ?? t.overall_norm_pct ?? 0, 2))}%`, background: getTaxonColor(t.taxon) }"
                        ></div>
                      </div>
                      <span class="progress-val-txt">{{ t.norm_pct ?? t.overall_norm_pct ?? 0 }}%</span>
                    </div>
                  </td>
                  <td class="mono text-muted">{{ t.raw_pct ?? t.overall_raw_pct ?? 0 }}%</td>
                  <td>
                    <div class="sample-coverage-tag">
                      <span class="cov-num">{{ t.sample_frequency ? `${t.sample_frequency} 点位` : `${t.sample_count || 0} 点位` }}</span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- TAB 3: 样本 / 分组明细大表 (数据源切换为 activeSamples) -->
        <div v-show="activeTab === 'matrix'" class="tab-content-neo scroll-y">
          <div class="matrix-card">
            <table class="neo-data-table">
              <thead>
                <tr>
                  <th style="width: 220px;">样本 / 合并组名称</th>
                  <th>检出物种名称</th>
                  <th>Reads 计数</th>
                  <th>原始占比 (%)</th>
                  <th>16S 拷贝数 (GCN)</th>
                  <th>匹配级别</th>
                  <th>rrnDB 校正后占比 (%)</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="s in activeSamples" :key="s.sample_name">
                  <tr v-for="(d, idx) in s.norm_result?.details || []" :key="d.taxon">
                    <td v-if="idx === 0" :rowspan="s.norm_result?.details.length" class="align-top sample-col">
                      <div class="sample-info-block">
                        <div class="sample-title-row">
                          <span class="mono font-bold">{{ s.sample_name }}</span>
                          <span v-if="s.is_group" class="group-badge">合并组</span>
                        </div>
                        <div v-if="s.is_group && s.member_samples" class="member-samples-preview">
                          <span class="preview-label">包含采样点位 ({{ s.member_samples.length }}个):</span>
                          <div class="member-chips-inline">
                            <span v-for="m in s.member_samples.slice(0, 8)" :key="m" class="sub-chip">{{ m }}</span>
                            <span v-if="s.member_samples.length > 8" class="sub-chip-more">等 {{ s.member_samples.length }} 个</span>
                          </div>
                        </div>
                        <div class="sample-meta-row">
                          <span>总 Reads: {{ (s.total_reads || 0).toLocaleString() }}</span>
                        </div>
                      </div>
                    </td>
                    <td class="italic font-medium">{{ d.taxon }}</td>
                    <td class="mono">{{ d.raw_count }}</td>
                    <td>{{ d.raw_pct }}%</td>
                    <td><strong>{{ d.gcn_mean }}</strong></td>
                    <td>
                      <span class="badge-match" :class="d.gcn_matched ? 'match-ok' : 'match-fallback'">
                        {{ d.gcn_rank }}
                      </span>
                    </td>
                    <td><span class="norm-val">{{ d.norm_pct }}%</span></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 分组配置模态弹窗 (支持 1-5, 6-9 等点位合并规则) -->
      <transition name="drawer-fade">
        <div v-if="showGroupModal" class="group-modal-backdrop" @click.self="showGroupModal = false">
          <div class="group-modal-card">
            <div class="group-modal-header">
              <div class="header-title-wrap">
                <svg class="header-icon-svg" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" />
                </svg>
                <div>
                  <h3 class="modal-h3">样本点位合并与分组规则</h3>
                  <p class="modal-sub">
                    将多个随机采样点位合并为一个样本组进行分析，Reads 自动累加并重新执行 rrnDB 归一化校正
                  </p>
                </div>
              </div>
              <button class="btn-modal-close" @click="showGroupModal = false">✕</button>
            </div>

            <div class="group-modal-body scroll-y">
              <!-- 连续 X 个一组自动切分 与 手动分组控制面板 -->
              <div class="group-config-control-panel">
                <!-- 连续 X 个一组功能区 -->
                <div class="chunk-generator-section">
                  <div class="generator-header">
                    <span class="section-title">连续分组模式 (连续 X 个一组)</span>
                    <span class="section-desc">根据采样编号顺序，按设定跨度自动将所有点位切分为连续的分组</span>
                  </div>
                  <div class="generator-toolbar">
                    <div class="chunk-input-wrap">
                      <span class="chunk-label">每连续</span>
                      <input 
                        type="number" 
                        v-model.number="groupChunkSize" 
                        min="1" 
                        :max="Math.max(1, allSampleNames.length)"
                        class="chunk-num-input"
                      />
                      <span class="chunk-unit">个点位为一组</span>
                    </div>
                    <button class="btn-gen-chunk" @click="generateConsecutiveGroups(groupChunkSize)">
                      自动生成分组
                    </button>
                    <!-- 快捷预设跨度芯片 -->
                    <div class="quick-preset-chips">
                      <button 
                        v-for="s in [2, 3, 4, 5, 8]" 
                        :key="s" 
                        class="btn-preset-chip"
                        :class="{ active: groupChunkSize === s }"
                        @click="setChunkSizeAndGenerate(s)"
                      >
                        {{ s }}个一组
                      </button>
                    </div>
                  </div>
                </div>

                <!-- 手动分组控制区 -->
                <div class="manual-group-section">
                  <div class="manual-header">
                    <span class="section-title">手动分组模式</span>
                    <span class="section-desc">自由添加/删除分组，支持自定义输入任意点位范围（如 1-5、6-9、1,3,5）</span>
                  </div>
                  <div class="manual-toolbar">
                    <button class="btn-sub-action primary" @click="addGroup">+ 新增自定义合并组</button>
                    <button class="btn-sub-action" @click="clearAllGroups" v-if="sampleGroups.length > 0">清空所有规则</button>
                  </div>
                </div>
              </div>

              <!-- 分组规则卡片列表 -->
              <div class="group-rules-list">
                <div v-if="sampleGroups.length === 0" class="empty-rules-hint">
                  当前暂无合并分组规则。您可以选择上方的连续分组模式一键生成，或点击“+ 新增自定义合并组”手动创建。
                </div>
                <div 
                  v-for="(grp, idx) in sampleGroups" 
                  :key="grp.id"
                  class="group-rule-card"
                >
                  <div class="rule-inputs-row">
                    <div class="input-field-group">
                      <label class="field-label">组名称</label>
                      <input 
                        type="text" 
                        v-model="grp.name" 
                        placeholder="例如：对照组 (Control)" 
                        class="rule-input"
                      />
                    </div>
                    <div class="input-field-group flex-2">
                      <label class="field-label">点位范围 / 匹配规则</label>
                      <input 
                        type="text" 
                        v-model="grp.pattern" 
                        placeholder="例如：1-5 或 1,2,3,4,5" 
                        class="rule-input"
                      />
                    </div>
                    <button 
                      class="btn-del-group" 
                      @click="removeGroup(grp.id)"
                      title="删除此分组"
                    >
                      <svg viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
                      </svg>
                    </button>
                  </div>

                  <!-- 实时匹配点位预览 -->
                  <div class="match-preview-box">
                    <span class="preview-title">
                      匹配结果: 
                      <strong>{{ parseSamplePattern(grp.pattern, allSampleNames).length }}</strong> 个点位
                    </span>
                    <div class="match-chips-wrap">
                      <span 
                        v-for="sName in parseSamplePattern(grp.pattern, allSampleNames)" 
                        :key="sName"
                        class="preview-sample-chip"
                      >
                        {{ sName }}
                      </span>
                      <span 
                        v-if="parseSamplePattern(grp.pattern, allSampleNames).length === 0" 
                        class="empty-match-hint"
                      >
                        暂无匹配到的点位 (请检查输入规则)
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 未分组点位状态提示 -->
              <div class="unassigned-status-banner">
                <span class="label">未分组的独立点位 (共 {{ unassignedSamples.length }} 个):</span>
                <div class="unassigned-chips">
                  <span v-for="s in unassignedSamples.slice(0, 15)" :key="s" class="unassigned-chip">{{ s }}</span>
                  <span v-if="unassignedSamples.length > 15" class="unassigned-chip-more">...等 {{ unassignedSamples.length }} 个</span>
                </div>
              </div>
            </div>

            <!-- 弹窗底部操作按钮 -->
            <div class="group-modal-footer">
              <button class="btn-cancel" @click="showGroupModal = false">关闭</button>
              <button 
                class="btn-apply-group" 
                @click="isGroupView = true; showGroupModal = false"
              >
                应用规则并开启合并视图
              </button>
            </div>
          </div>
        </div>
      </transition>


      <!-- 浮动 Tooltip -->
      <div 
        v-if="tooltip.visible" 
        class="floating-tooltip"
        :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
      >
        <div class="tt-sample">{{ tooltip.sample }}</div>
        <div class="tt-taxon">{{ tooltip.taxon }}</div>
        <div class="tt-divider"></div>
        <div class="tt-row">
          <span>原始 Reads:</span>
          <strong>{{ tooltip.rawCount }} 条 ({{ tooltip.rawPct }}%)</strong>
        </div>
        <div class="tt-row">
          <span>16S 基因拷贝数 (GCN):</span>
          <strong>{{ tooltip.gcn }}</strong>
        </div>
        <div class="tt-row tt-highlight">
          <span>rrnDB 校正相对丰度:</span>
          <strong>{{ tooltip.normPct }}%</strong>
        </div>
      </div>
      <!-- 历史记录右侧滑入抽屉 (和单样本查询体验高度对齐) -->
      <transition name="drawer-fade">
        <div v-if="showHistoryDrawer" class="history-drawer-backdrop" @click.self="showHistoryDrawer = false">
          <div class="history-drawer-neo">
            <div class="drawer-header-neo">
              <div class="drawer-title-group">
                <div class="drawer-icon-wrap">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <circle cx="12" cy="12" r="9" stroke-width="2"/>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 7v5l3 3"/>
                  </svg>
                </div>
                <div>
                  <h3 class="drawer-title">历史多样性分析任务</h3>
                  <span class="drawer-subtitle">共 {{ historyTasks.length }} 条分析归档</span>
                </div>
              </div>
              <button class="btn-drawer-close" @click="showHistoryDrawer = false">✕</button>
            </div>

            <!-- 任务列表容器 -->
            <div class="drawer-list-wrap scroll-v">
              <div v-if="isLoadingHistory" class="drawer-empty-hint">
                <span>正在同步历史分析记录...</span>
              </div>
              <div v-else-if="historyTasks.length === 0" class="drawer-empty-hint">
                <span>暂无已归档的历史分析记录</span>
              </div>
              <div v-else class="drawer-task-list">
                <div 
                  v-for="t in historyTasks" 
                  :key="t.task_id"
                  class="drawer-task-card"
                  :class="{ active: taskId === t.task_id }"
                  @click="selectHistoryTask(t)"
                >
                  <div class="card-top-row">
                    <span class="task-file-title" :title="t.task_name">{{ t.task_name }}</span>
                    <span class="task-status-tag" :class="t.status">{{ getStatusLabel(t.status) }}</span>
                  </div>
                  <div class="card-time-row">
                    {{ formatTime(t.completed_at || t.created_at) }}
                  </div>
                  <div class="card-stats-row">
                    <span class="stat-pill">{{ t.total_samples }} 点位</span>
                    <span class="stat-pill">{{ formatReadsCount(t.total_reads) }} Reads</span>
                    <span v-if="t.species_count" class="stat-pill highlight">{{ t.species_count }} 物种</span>
                  </div>
                  <div class="card-action-bar">
                    <button 
                      class="btn-card-del"
                      title="彻底删除此任务"
                      @click.stop="deleteHistoryTask(t, $event)"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 抽屉底栏: 清空全部历史 -->
            <div v-if="historyTasks.length > 0" class="drawer-footer-neo">
              <button class="btn-clear-history-warn" @click="clearAllHistory">
                清空全部历史记录
              </button>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.diversity-embedded-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: white;
  position: relative;
}

.modal-container-neo.is-embedded {
  width: 100%;
  max-width: none;
  height: 100%;
  border-radius: 0;
  box-shadow: none;
  border: none;
}

.btn-switch-isolate {
  display: flex;
  align-items: center;
  gap: 6px;
  background: white;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-switch-isolate:hover {
  background: #f1f5f9;
  color: #1e293b;
  border-color: #94a3b8;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.modal-container-neo {
  width: 95vw;
  max-width: 1280px;
  height: 90vh;
  background: #ffffff;
  border-radius: 18px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.modal-header-neo {
  padding: 16px 24px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #eff6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
}
.header-icon-svg {
  width: 24px;
  height: 24px;
}
.btn-icon-svg {
  width: 16px;
  height: 16px;
}
.tab-svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}
.title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
}
.subtitle {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: #64748b;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn-export-neo {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  background: #10b981;
  color: white;
  border: none;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-export-neo:hover {
  background: #059669;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}
.btn-close-neo {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 8px;
}
.btn-close-neo:hover {
  color: #ef4444;
  background: #fee2e2;
}

.import-section-neo {
  padding: 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  align-items: center;
  justify-content: center;
  flex: 1;
}
.upload-box-wrapper {
  width: 100%;
  max-width: 720px;
}
.detect-badge-card {
  width: 100%;
  max-width: 720px;
  padding: 20px 24px;
  border-radius: 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  display: flex;
  align-items: center;
  gap: 16px;
}
.badge-status-tag {
  background: #16a34a;
  color: white;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
}
.detect-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.detect-info .name {
  font-weight: 700;
  color: #14532d;
  font-size: 0.95rem;
}
.detect-info .desc {
  font-size: 0.82rem;
  color: #166534;
  margin-top: 2px;
}
.btn-start-action {
  padding: 10px 20px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-start-action:hover {
  background: #1d4ed8;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.progress-section-neo {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.progress-card-neo {
  width: 520px;
  padding: 36px 32px;
  background: white;
  border-radius: 18px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.pulse-icon-svg {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
  animation: pulse 1.8s infinite;
}
.exec-svg {
  width: 26px;
  height: 26px;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.85; }
}
.progress-info {
  width: 100%;
}
.step-text {
  font-weight: 700;
  color: #1e293b;
  font-size: 1rem;
}
.sample-hint {
  font-size: 0.82rem;
  color: #64748b;
  margin-top: 5px;
}
.sample-hint strong {
  color: #2563eb;
}
.progress-bar-wrap {
  width: 100%;
  height: 12px;
  background: #f1f5f9;
  border-radius: 6px;
  overflow: hidden;
  margin: 18px 0 14px;
}
.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #38bdf8);
  border-radius: 6px;
  transition: width 0.3s ease;
}
.progress-meta-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}
.progress-percent-val {
  font-weight: 800;
  color: #2563eb;
  font-size: 1.25rem;
  min-width: 60px;
}
.progress-counter-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 600;
}
.progress-counter-badge.samples-badge {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}
.counter-label {
  color: #64748b;
}
.counter-num {
  font-weight: 700;
}
.checkpoint-tip {
  margin-top: 18px;
  font-size: 0.75rem;
  color: #059669;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 7px 14px;
  border-radius: 8px;
  width: 100%;
}
.shield-svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: #10b981;
}

.results-dashboard-neo {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stats-overview-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 24px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.stat-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  background: white;
  border: 1px solid #e2e8f0;
  font-size: 0.8rem;
}
.stat-pill .label { color: #64748b; }
.stat-pill .val { font-weight: 700; color: #1e293b; }
.pill-rrndb { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.pill-rrndb .val { color: #15803d; }

.abundance-mode-toggle {
  margin-left: auto;
  display: flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: 8px;
}
.toggle-btn {
  padding: 5px 12px;
  border: none;
  background: none;
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.toggle-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.sub-tabs-neo {
  display: flex;
  gap: 8px;
  padding: 10px 24px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}
.tab-item {
  padding: 8px 16px;
  border: none;
  background: none;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-item:hover { color: #1e293b; background: #f1f5f9; }
.tab-item.active { background: #eff6ff; color: #2563eb; font-weight: 700; }

.tab-content-neo {
  flex: 1;
  padding: 20px 24px;
  background: #f8fafc;
}
.scroll-y { overflow-y: auto; }

.chart-container-card {
  background: white;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
}
.chart-legend-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
}
.legend-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.76rem;
  color: #334155;
  font-weight: 500;
}
.legend-badge .dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.svg-scroll-container {
  overflow-x: auto;
  padding-bottom: 16px;
}
.stacked-bar-svg {
  display: block;
}
.axis-txt {
  font-size: 11px;
  fill: #94a3b8;
  font-family: sans-serif;
}
.sample-x-label {
  font-size: 10px;
  fill: #475569;
  font-family: monospace;
}
.bar-seg {
  cursor: pointer;
  transition: opacity 0.2s;
}
.bar-seg:hover {
  opacity: 0.85;
}

/* 样本合并控制区与状态提示条 */
.group-control-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.group-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: white;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.group-toggle-btn:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}
.group-toggle-btn.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.15);
}
.group-svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}
.group-config-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.group-config-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}
.chart-status-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 8px 14px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 0.8rem;
}
.banner-tag {
  background: #2563eb;
  color: white;
  font-weight: 700;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
}
.banner-desc {
  color: #1e40af;
  line-height: 1.4;
}
.label-group {
  font-weight: 700;
  fill: #1d4ed8 !important;
}

/* 物种总览与排行榜 (回答“有什么菌”) */
.taxa-overview-card {
  background: white;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.taxa-toolbar {
  padding: 14px 20px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: #fafafa;
}
.taxa-search-box {
  position: relative;
  display: flex;
  align-items: center;
  width: 360px;
}
.search-svg {
  position: absolute;
  left: 12px;
  width: 16px;
  height: 16px;
  color: #94a3b8;
  pointer-events: none;
}
.taxa-search-input {
  width: 100%;
  padding: 8px 34px 8px 36px;
  font-size: 0.82rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: white;
  color: #1e293b;
  outline: none;
  transition: all 0.2s;
}
.taxa-search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.clear-search-btn {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.85rem;
}
.clear-search-btn:hover { color: #475569; }
.taxa-toolbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.taxa-count-tag {
  font-size: 0.82rem;
  color: #64748b;
}
.taxa-count-tag strong {
  color: #0f172a;
}
.btn-export-excel {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #10b981;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-export-excel svg {
  width: 15px;
  height: 15px;
}
.btn-export-excel:hover {
  background: #059669;
}
.taxa-table th {
  background: #f8fafc;
  padding: 12px 14px;
}
.taxa-table td {
  padding: 12px 14px;
  vertical-align: middle;
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 800;
}
.rank-1 { background: #fef08a; color: #854d0e; }
.rank-2 { background: #e2e8f0; color: #475569; }
.rank-3 { background: #fed7aa; color: #9a3412; }
.rank-normal { background: #f1f5f9; color: #64748b; }
.taxon-name-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.taxon-latin-name {
  font-style: italic;
  font-weight: 700;
  color: #1e293b;
  font-size: 0.88rem;
}
.top-tag {
  font-size: 0.7rem;
  background: #fee2e2;
  color: #b91c1c;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}
.top-sub-tag {
  font-size: 0.7rem;
  background: #eff6ff;
  color: #1d4ed8;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.gcn-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.gcn-val {
  font-family: monospace;
  font-weight: 700;
  color: #334155;
}
.abundance-progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.progress-bar-bg {
  flex: 1;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}
.progress-val-txt {
  font-family: monospace;
  font-weight: 800;
  color: #2563eb;
  font-size: 0.84rem;
  min-width: 55px;
  text-align: right;
}
.sample-coverage-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.78rem;
}
.cov-num {
  font-weight: 700;
  color: #0f172a;
}
.cov-pct {
  color: #64748b;
}

/* 样本/分组明细大表强化 */
.sample-col {
  background: #fafafa;
}
.sample-info-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sample-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.group-badge {
  background: #dbeafe;
  color: #1e40af;
  font-size: 0.68rem;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
}
.member-samples-preview {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 2px;
}
.preview-label {
  font-size: 0.7rem;
  color: #64748b;
}
.member-chips-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.sub-chip {
  background: white;
  border: 1px solid #cbd5e1;
  font-size: 0.68rem;
  padding: 1px 4px;
  border-radius: 3px;
  color: #475569;
  font-family: monospace;
}
.sub-chip-more {
  font-size: 0.68rem;
  color: #94a3b8;
}
.sample-meta-row {
  font-size: 0.72rem;
  color: #64748b;
}

/* 分组配置模态弹窗 */
.group-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 10005;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.group-modal-card {
  width: 90vw;
  max-width: 760px;
  max-height: 85vh;
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}
.group-modal-header {
  padding: 16px 22px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
}
.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-icon-svg {
  width: 26px;
  height: 26px;
  color: #2563eb;
  flex-shrink: 0;
}
.modal-h3 {
  margin: 0;
  font-size: 1.05rem;
  color: #0f172a;
  font-weight: 700;
}
.modal-sub {
  margin: 2px 0 0;
  font-size: 0.76rem;
  color: #64748b;
}
.btn-modal-close {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #94a3b8;
  cursor: pointer;
  border-radius: 6px;
  padding: 4px 8px;
}
.btn-modal-close:hover {
  background: #e2e8f0;
  color: #334155;
}
.group-modal-body {
  padding: 20px 22px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.group-config-control-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: #f8fafc;
  padding: 16px 18px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}
.chunk-generator-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.generator-header,
.manual-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.section-title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 6px;
}
.section-desc {
  font-size: 0.74rem;
  color: #64748b;
  line-height: 1.4;
}
.generator-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.chunk-input-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 0.78rem;
  color: #475569;
  font-weight: 500;
}
.chunk-label,
.chunk-unit {
  font-size: 0.76rem;
  color: #64748b;
}
.chunk-num-input {
  width: 52px;
  border: none;
  background: transparent;
  text-align: center;
  font-size: 0.9rem;
  font-weight: 700;
  color: #2563eb;
  outline: none;
}
.chunk-num-input:focus {
  color: #1d4ed8;
}
.btn-gen-chunk {
  background: #2563eb;
  color: white;
  border: none;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.2);
}
.btn-gen-chunk:hover {
  background: #1d4ed8;
  transform: translateY(-1px);
}
.quick-preset-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
}
.btn-preset-chip {
  background: white;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 4px 9px;
  border-radius: 6px;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-preset-chip:hover {
  border-color: #3b82f6;
  color: #2563eb;
  background: #eff6ff;
}
.btn-preset-chip.active {
  background: #dbeafe;
  border-color: #3b82f6;
  color: #1d4ed8;
  font-weight: 700;
}
.manual-group-section {
  padding-top: 12px;
  border-top: 1px dashed #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.manual-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.empty-rules-hint {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.6;
}
.btn-sub-action {
  background: white;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-sub-action:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}
.btn-sub-action.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
.btn-sub-action.primary:hover {
  background: #1d4ed8;
}
.group-rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-rule-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}
.rule-inputs-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.input-field-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.input-field-group.flex-2 {
  flex: 2;
}
.field-label {
  font-size: 0.74rem;
  font-weight: 600;
  color: #64748b;
}
.rule-input {
  padding: 7px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.82rem;
  color: #1e293b;
  outline: none;
  transition: border-color 0.2s;
}
.rule-input:focus {
  border-color: #3b82f6;
}
.btn-del-group {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #fee2e2;
  background: #fef2f2;
  color: #ef4444;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}
.btn-del-group svg {
  width: 16px;
  height: 16px;
}
.btn-del-group:hover {
  background: #fee2e2;
  color: #dc2626;
}
.match-preview-box {
  background: #f8fafc;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px dashed #cbd5e1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.preview-title {
  font-size: 0.74rem;
  color: #64748b;
}
.preview-title strong {
  color: #2563eb;
}
.match-chips-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.preview-sample-chip {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 0.72rem;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}
.empty-match-hint {
  font-size: 0.72rem;
  color: #ef4444;
}
.unassigned-status-banner {
  background: #fafafa;
  border: 1px solid #e2e8f0;
  padding: 10px 14px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.unassigned-status-banner .label {
  font-size: 0.74rem;
  color: #64748b;
  font-weight: 600;
}
.unassigned-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.unassigned-chip {
  background: white;
  border: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
}
.unassigned-chip-more {
  font-size: 0.7rem;
  color: #94a3b8;
}
.group-modal-footer {
  padding: 14px 22px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  background: #f8fafc;
}
.btn-cancel {
  background: white;
  border: 1px solid #cbd5e1;
  color: #475569;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-cancel:hover { background: #f1f5f9; }
.btn-apply-group {
  background: #2563eb;
  border: none;
  color: white;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-apply-group:hover {
  background: #1d4ed8;
}
.badge-match {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
}
.match-ok { background: #dcfce7; color: #15803d; }
.match-fallback { background: #fef3c7; color: #b45309; }
.norm-val { font-weight: 700; color: #2563eb; }

.floating-tooltip {
  position: fixed;
  background: rgba(15, 23, 42, 0.95);
  color: white;
  padding: 12px 16px;
  border-radius: 10px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
  pointer-events: none;
  z-index: 10000;
  font-size: 0.78rem;
  max-width: 280px;
}
.tt-sample { font-size: 0.72rem; color: #94a3b8; font-family: monospace; }
.tt-taxon { font-size: 0.88rem; font-weight: 700; color: #38bdf8; margin: 2px 0 6px; }
.tt-divider { height: 1px; background: rgba(255, 255, 255, 0.1); margin: 6px 0; }
.tt-row { display: flex; justify-content: space-between; gap: 12px; margin-top: 3px; }
.tt-row span { color: #cbd5e1; }
.tt-highlight strong { color: #4ade80; }

/* 头部通用工具按钮 */
.btn-tool-neo {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-tool-neo:hover {
  background: #e2e8f0;
  color: #0f172a;
}
.btn-tool-neo.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

/* 首页快捷历史记录区 */
.recent-history-section {
  margin-top: 24px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 18px 22px;
}
.recent-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.recent-title {
  font-size: 0.88rem;
  font-weight: 700;
  color: #1e293b;
}
.recent-all-btn {
  background: none;
  border: none;
  color: #2563eb;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
.recent-all-btn:hover {
  text-decoration: underline;
}
.recent-task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.recent-task-item {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s;
}
.recent-task-item:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
  transform: translateY(-1px);
}
.recent-item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.recent-item-top .item-name {
  font-size: 0.84rem;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recent-item-top .item-status {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}
.recent-item-meta {
  font-size: 0.72rem;
  color: #64748b;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.recent-item-actions {
  position: absolute;
  right: 8px;
  bottom: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}
.recent-task-item:hover .recent-item-actions {
  opacity: 1;
}
.btn-item-del {
  background: none;
  border: none;
  color: #94a3b8;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
}
.btn-item-del:hover {
  color: #ef4444;
  background: #fee2e2;
}
.btn-item-del svg {
  width: 14px;
  height: 14px;
}

/* 历史抽屉面板 */
.history-drawer-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}
.history-drawer-neo {
  width: 380px;
  max-width: 90%;
  height: 100%;
  background: white;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  animation: slideInRight 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.drawer-fade-enter-active, .drawer-fade-leave-active {
  transition: opacity 0.2s;
}
.drawer-fade-enter-from, .drawer-fade-leave-to {
  opacity: 0;
}

.drawer-header-neo {
  padding: 18px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8fafc;
}
.drawer-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.drawer-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
}
.drawer-icon-wrap svg {
  width: 18px;
  height: 18px;
}
.drawer-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}
.drawer-subtitle {
  font-size: 0.72rem;
  color: #64748b;
}
.btn-drawer-close {
  background: none;
  border: none;
  font-size: 1.1rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
}
.btn-drawer-close:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.drawer-list-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.drawer-empty-hint {
  padding: 40px 20px;
  text-align: center;
  color: #94a3b8;
  font-size: 0.85rem;
}
.drawer-task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.drawer-task-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s;
}
.drawer-task-card:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}
.drawer-task-card.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
}
.card-top-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  gap: 8px;
}
.task-file-title {
  font-size: 0.84rem;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-status-tag {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.task-status-tag.completed, .item-status.completed {
  background: #d1fae5;
  color: #065f46;
}
.task-status-tag.running, .item-status.running {
  background: #dbeafe;
  color: #1e40af;
}
.task-status-tag.interrupted, .item-status.interrupted {
  background: #fef3c7;
  color: #92400e;
}
.card-time-row {
  font-size: 0.72rem;
  color: #94a3b8;
  margin-bottom: 8px;
}
.card-stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.stat-pill {
  font-size: 0.7rem;
  background: #e2e8f0;
  color: #475569;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.stat-pill.highlight {
  background: #fef3c7;
  color: #b45309;
  font-weight: 700;
}

.card-action-bar {
  position: absolute;
  right: 10px;
  bottom: 10px;
  opacity: 0;
  transition: opacity 0.2s;
}
.drawer-task-card:hover .card-action-bar {
  opacity: 1;
}
.btn-card-del {
  background: none;
  border: none;
  color: #94a3b8;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
}
.btn-card-del:hover {
  color: #ef4444;
  background: #fee2e2;
}
.btn-card-del svg {
  width: 16px;
  height: 16px;
}

.drawer-footer-neo {
  padding: 14px 20px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
  text-align: center;
}
.btn-clear-history-warn {
  background: none;
  border: none;
  color: #ef4444;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-clear-history-warn:hover {
  text-decoration: underline;
}
</style>
