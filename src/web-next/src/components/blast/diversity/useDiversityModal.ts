/**
 * useDiversityModal - 16S 扩增子多样性还原与 rrnDB 拷贝数归一化分析状态机
 * 从 DiversityAnalysisModal.vue 拆解而出，封装任务轮询、分组聚合、堆叠柱图数据、物种翻译与 Excel 导出。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { API_BASE, apiDelete, apiGet, apiPost } from '../../../bridge/electron-bridge'
import { useAppStore } from '../../../stores/app'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'
import { createLogger } from '../../../utils/logger'

const logger = createLogger('DiversityModal')
import {
  buildMergedGroupSamples,
  DIVERSITY_PALETTE,
  formatPct,
  formatReadsCount,
  formatTime,
  getStatusLabel,
  isNoiseTaxon,
  parseSamplePattern,
  type SampleGroupDef,
  type StackedSample,
  type StackedSegment,
} from './diversityHelpers'

export interface DetectedAmpliconPackage {
  is_amplicon_package: boolean
  file_name: string
  fastq_count: number
  [key: string]: unknown
}

export interface DiversityHistoryTask {
  task_id: string
  task_name: string
  status: string
  progress?: number
  total_samples: number
  total_reads: number
  created_at?: number
  completed_at?: number
  [key: string]: unknown
}

export interface DiversityTaxonDetail {
  taxon: string
  raw_count: number
  raw_pct: number
  norm_pct: number
  gcn_mean: number
  gcn_match_level?: string
  is_noise?: boolean
  [key: string]: unknown
}

export interface DiversityTaxonOverviewItem {
  taxon: string
  raw_count?: number
  raw_pct?: number
  norm_pct?: number
  overall_raw_pct?: number
  overall_norm_pct?: number
  gcn_mean?: number
  sample_count?: number
  is_noise?: boolean
  [key: string]: unknown
}

export interface DiversitySampleItem {
  sample_name: string
  total_reads: number
  is_group?: boolean
  member_samples?: string[]
  norm_result?: {
    details?: DiversityTaxonDetail[]
    [key: string]: unknown
  }
  [key: string]: unknown
}

export interface DiversityQcSummary {
  total_raw_reads?: number
  total_dropped_reads?: number
  overall_pass_rate_pct?: number
  [key: string]: unknown
}

export interface DiversityResultsPayload {
  samples: DiversitySampleItem[]
  taxa_overview?: DiversityTaxonOverviewItem[]
  taxa_translations?: Record<string, string>
  total_classified_reads?: number
  total_reads?: number
  total_samples?: number
  qc_summary?: DiversityQcSummary
  summary?: Record<string, unknown>
  [key: string]: unknown
}

interface TopBarDraftItem {
  taxon: string
  pct: number
  rawCount: number
  rawPct: number
  normPct: number
  gcn: number
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

export interface DiversityModalProps {
  modelValue?: boolean
  initialFilePath?: string
  embedded?: boolean
}

export interface DiversityModalEmits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
  (e: 'switchToIsolate'): void
  (e: 'taskChanged', taskId: string): void
}

export function useDiversityModal(props: DiversityModalProps, emit: DiversityModalEmits) {
  const appStore = useAppStore()
  const confirmDialog = useConfirmDialog()

  const activeTab = ref<'chart' | 'taxa' | 'matrix'>('chart')
  const abundanceMode = ref<'norm' | 'raw'>('norm')
  const currentFilePath = ref<string>('')
  const isDetecting = ref(false)
  const detectedPackage = ref<DetectedAmpliconPackage | null>(null)

  const isGroupView = ref(false)
  const showGroupModal = ref(false)
  const groupChunkSize = ref<number>(4)
  const sampleGroups = ref<SampleGroupDef[]>([])

  const taxaSearchQuery = ref('')
  const showHistoryDrawer = ref(false)
  const historyTasks = ref<DiversityHistoryTask[]>([])
  const isLoadingHistory = ref(false)

  const isRunning = ref(false)
  const taskId = ref<string>('')
  const progress = ref<number>(0)
  const currentStep = ref<string>('')
  const currentSample = ref<string>('')
  const processedReads = ref<number>(0)
  const totalReads = ref<number>(0)
  const processedSamples = ref<number>(0)
  const totalSamples = ref<number>(0)
  const results = ref<DiversityResultsPayload | null>(null)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const topTaxaCount = ref<number>(15)
  const translations = ref<Record<string, string>>({})
  const isTranslating = ref(false)

  const detailSearchQuery = ref('')
  const detailViewMode = ref<'cards' | 'table'>('cards')
  const collapsedSampleKeys = ref<Set<string>>(new Set())

  const tooltip = ref({
    visible: false,
    x: 0,
    y: 0,
    sample: '',
    taxon: '',
    rawCount: 0,
    rawPct: 0,
    gcn: 1,
    normPct: 0,
  })

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function translateAllTaxa() {
    if (!results.value || !results.value.taxa_overview) return
    const taxaList = results.value.taxa_overview.map((t) => t.taxon).filter(Boolean)
    if (taxaList.length === 0 || isTranslating.value) return

    isTranslating.value = true
    appStore.showNotification(`正在翻译 ${taxaList.length} 种物种拉丁名为规范中文译名...`, 'info')
    try {
      const res = await apiPost('/api/diversity/translate', { taxa: taxaList })
      if (res && res.translations) {
        translations.value = { ...translations.value, ...res.translations }
        appStore.showNotification('物种词条翻译完成', 'success')
      }
    } catch (e: unknown) {
      logger.error('Batch translation error:', e)
      appStore.showNotification('词条翻译请求异常', 'error')
    } finally {
      isTranslating.value = false
    }
  }

  const allSampleNames = computed<string[]>(() => {
    if (!results.value || !results.value.samples) return []
    return results.value.samples
      .map((s) => s.sample_name)
      .toSorted((a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
  })

  function generateConsecutiveGroups(chunkSize?: number) {
    const size = Math.max(1, Number(chunkSize ?? groupChunkSize.value) || 4)
    groupChunkSize.value = size
    const samples = allSampleNames.value
    if (!samples || samples.length === 0) {
      sampleGroups.value = []
      return
    }

    const nums = samples
      .map((s) => {
        const m = s.match(/\d+/)
        return m ? parseInt(m[0], 10) : null
      })
      .filter((n): n is number => n !== null)

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
          pattern,
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
          pattern: chunk.join(','),
        })
        gIdx++
      }
    }
    sampleGroups.value = newGroups
  }

  async function fetchResults() {
    try {
      const res = await apiGet(`/api/diversity/results/${taskId.value}`)
      if (res && res.samples && Array.isArray(res.samples)) {
        results.value = res
        isRunning.value = false
        generateConsecutiveGroups(4)
        if (res.taxa_translations && Object.keys(res.taxa_translations).length > 0) {
          translations.value = { ...translations.value, ...res.taxa_translations }
        } else {
          void translateAllTaxa()
        }
      } else {
        const errMsg = res?.error || res?.detail || '未获取到样本数据'
        appStore.showNotification(`载入分析报告失败: ${errMsg}`, 'error')
      }
    } catch (e: unknown) {
      isRunning.value = false
      appStore.showNotification(`获取分析报告失败: ${toErrorMessage(e)}`, 'error')
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
            void fetchResults()
          } else if (statusRes.status === 'error') {
            stopPolling()
            isRunning.value = false
            appStore.showNotification(`分析失败: ${statusRes.error}`, 'error')
          }
        }
      } catch (e) {
        logger.error('Polling status error:', e)
      }
    }, 1000)
  }

  async function fetchHistoryTasks() {
    isLoadingHistory.value = true
    try {
      const res = await apiGet('/api/diversity/tasks')
      if (Array.isArray(res)) historyTasks.value = res
    } catch (e) {
      logger.error('Fetch history tasks error:', e)
    } finally {
      isLoadingHistory.value = false
    }
  }

  async function syncLatestTaskOrResume() {
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
            if (!results.value) void fetchResults()
            return
          }
        }
      } catch (e) {
        logger.warn('Sync status failed:', e)
      }
    }

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
          if (!results.value) void fetchResults()
        }
      }
    } catch (e) {
      logger.warn('Auto probe latest task failed:', e)
    }
    void fetchHistoryTasks()
  }

  function toggleHistoryDrawer() {
    showHistoryDrawer.value = !showHistoryDrawer.value
    if (showHistoryDrawer.value) void fetchHistoryTasks()
  }

  async function selectHistoryTask(task: DiversityHistoryTask) {
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

  async function deleteHistoryTask(task: DiversityHistoryTask, e: Event) {
    e.stopPropagation()
    const ok = await confirmDialog.confirm({
      title: '删除历史分析任务',
      message: `确定要彻底删除历史分析任务 "${task.task_name}" 吗？此操作将物理删除所有 Checkpoint 与统计数据。`,
      confirmText: '彻底删除',
      danger: true,
    })
    if (!ok) return
    try {
      const res = await apiDelete(`/api/diversity/task/${task.task_id}`)
      if (res && res.status === 'deleted') {
        appStore.showNotification('历史任务已成功删除', 'success')
        if (taskId.value === task.task_id) {
          results.value = null
          taskId.value = ''
        }
        void fetchHistoryTasks()
      } else {
        throw new Error(res?.detail || '删除失败')
      }
    } catch (err: unknown) {
      appStore.showNotification(`删除失败: ${toErrorMessage(err)}`, 'error')
    }
  }

  async function clearAllHistory() {
    const ok = await confirmDialog.confirm({
      title: '清空全部历史结果',
      message: '确定要清空全部历史多样性分析结果吗？此操作不可恢复。',
      confirmText: '全部清空',
      danger: true,
    })
    if (!ok) return
    try {
      const res = await apiDelete('/api/diversity/tasks/clear')
      if (res && res.status === 'cleared') {
        appStore.showNotification('已清空全部历史分析数据', 'success')
        results.value = null
        taskId.value = ''
        historyTasks.value = []
        showHistoryDrawer.value = false
      }
    } catch (err: unknown) {
      appStore.showNotification(`清空失败: ${toErrorMessage(err)}`, 'error')
    }
  }

  function resetToNewAnalysis() {
    results.value = null
    taskId.value = ''
    currentFilePath.value = ''
    detectedPackage.value = null
  }

  function close() {
    emit('update:modelValue', false)
    emit('close')
  }

  async function detectPackage(filePath: string) {
    if (!filePath) return
    isDetecting.value = true
    try {
      const res = await apiPost('/api/diversity/detect_package', { file_path: filePath })
      detectedPackage.value = res && res.is_amplicon_package ? res : null
    } catch (e) {
      logger.error('Detect package failed:', e)
    } finally {
      isDetecting.value = false
    }
  }

  function handleUploadSuccess(paths: string[]) {
    if (paths && paths.length > 0 && paths[0]) {
      currentFilePath.value = paths[0]
      void detectPackage(paths[0])
    }
  }

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
      const res = await apiPost('/api/diversity/run', { input_path: currentFilePath.value })
      if (res && res.task_id) {
        taskId.value = String(res.task_id)
        startPolling()
      } else {
        throw new Error(res?.detail || '任务创建失败')
      }
    } catch (err: unknown) {
      isRunning.value = false
      appStore.showNotification(`启动失败: ${toErrorMessage(err)}`, 'error')
    }
  }

  const topTaxaList = computed(() => {
    if (!results.value || !results.value.taxa_overview) return []
    const biologicalTaxa = results.value.taxa_overview.filter((t) => {
      const name = (t.taxon || '').toLowerCase()
      return !t.is_noise && !name.includes('噪声') && !name.includes('noise') && !name.startsWith('other')
    })
    const count = topTaxaCount.value >= 900 ? biologicalTaxa.length : topTaxaCount.value
    return biologicalTaxa.slice(0, count).map((t) => t.taxon)
  })

  function getTaxonColor(taxon: string): string {
    const lower = taxon.toLowerCase()
    if (lower.includes('低频测序噪声') || lower.includes('sequencing noise')) return '#475569'
    if (lower.includes('长尾微量物种') || lower.includes('minor taxa') || lower.includes('其他')) return '#94a3b8'
    const idx = topTaxaList.value.indexOf(taxon)
    return idx >= 0 ? DIVERSITY_PALETTE[idx % DIVERSITY_PALETTE.length] || '#0284c7' : '#94a3b8'
  }

  const activeGroups = computed(() => {
    const samples = allSampleNames.value
    return sampleGroups.value.map((g) => ({ ...g, matchedSamples: parseSamplePattern(g.pattern, samples) }))
  })

  const unassignedSamples = computed(() => {
    const samples = allSampleNames.value
    const assigned = new Set<string>()
    activeGroups.value.forEach((g) => g.matchedSamples.forEach((s) => assigned.add(s)))
    return samples.filter((s) => !assigned.has(s))
  })

  const activeSamples = computed(() => {
    if (!results.value || !results.value.samples) return []
    const rawSamples = results.value.samples
    if (!isGroupView.value) return rawSamples
    const validGroups = activeGroups.value.filter((g) => g.name.trim() && g.matchedSamples.length > 0)
    if (validGroups.length === 0) return rawSamples
    return buildMergedGroupSamples(rawSamples, validGroups)
  })

  function addGroup() {
    sampleGroups.value.push({ id: `g_${Date.now()}`, name: `分组 ${sampleGroups.value.length + 1}`, pattern: '' })
  }
  function removeGroup(id: string) {
    sampleGroups.value = sampleGroups.value.filter((g) => g.id !== id)
  }
  function setChunkSizeAndGenerate(size: number) {
    groupChunkSize.value = size
    generateConsecutiveGroups(size)
  }
  function clearAllGroups() {
    sampleGroups.value = []
  }
  function resetDefaultGroups() {
    generateConsecutiveGroups(groupChunkSize.value || 4)
  }

  const stackedBarData = computed<StackedSample[]>(() => {
    const samples = activeSamples.value
    if (!samples || samples.length === 0) return []
    const isNorm = abundanceMode.value === 'norm'

    return samples.map((s: DiversitySampleItem) => {
      const details = s.norm_result?.details || []
      const segments: StackedSegment[] = []
      let cumulative = 0
      const topItems: TopBarDraftItem[] = []
      let minorTaxaPct = 0
      let minorTaxaRaw = 0
      let minorTaxaCount = 0
      let noisePct = 0
      let noiseRaw = 0

      details.forEach((d: DiversityTaxonDetail) => {
        const pct = Number(isNorm ? d.norm_pct : d.raw_pct) || 0
        const nameLower = (d.taxon || '').toLowerCase()
        const isNoise = d.is_noise || nameLower.includes('噪声') || nameLower.includes('noise')
        if (isNoise) {
          noisePct += pct
          noiseRaw += d.raw_count
        } else if (topTaxaList.value.includes(d.taxon)) {
          topItems.push({ taxon: d.taxon, pct, rawCount: d.raw_count, rawPct: d.raw_pct, normPct: d.norm_pct, gcn: d.gcn_mean })
        } else {
          minorTaxaPct += pct
          minorTaxaRaw += d.raw_count
          minorTaxaCount++
        }
      })

      if (minorTaxaPct > 0) {
        const rounded = Math.round(minorTaxaPct * 100) / 100
        topItems.push({ taxon: `长尾微量物种 (${minorTaxaCount} 种)`, pct: rounded, rawCount: minorTaxaRaw, rawPct: rounded, normPct: rounded, gcn: 1.0 })
      }
      if (noisePct > 0) {
        const rounded = Math.round(noisePct * 100) / 100
        topItems.push({ taxon: '低频测序噪声 (已质控过滤)', pct: rounded, rawCount: noiseRaw, rawPct: rounded, normPct: rounded, gcn: 1.0 })
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
          yTop: cumulative + height,
        })
        cumulative += height
      })

      return {
        sampleName: s.sample_name,
        isGroup: !!s.is_group,
        memberSamples: s.member_samples || [],
        totalReads: s.total_reads,
        segments,
      }
    })
  })

  const confirmedSpeciesCount = computed(() => {
    if (!results.value || !results.value.taxa_overview) return 0
    return results.value.taxa_overview.filter((t) => !isNoiseTaxon(t.taxon)).length
  })

  const realTaxaRanks = computed(() => {
    const map = new Map<string, number>()
    if (!results.value || !results.value.taxa_overview) return map
    let rank = 1
    for (const t of results.value.taxa_overview) {
      if (!isNoiseTaxon(t.taxon)) map.set(t.taxon, rank++)
    }
    return map
  })

  function getRealTaxonRank(taxon: string): number | null {
    return realTaxaRanks.value.get(taxon) ?? null
  }

  const filteredTaxaOverview = computed(() => {
    if (!results.value || !results.value.taxa_overview) return []
    const list = results.value.taxa_overview.toSorted((a, b) => {
      const aNoise = isNoiseTaxon(a.taxon) ? 1 : 0
      const bNoise = isNoiseTaxon(b.taxon) ? 1 : 0
      if (aNoise !== bNoise) return aNoise - bNoise
      return Number(b.norm_pct ?? b.overall_norm_pct ?? 0) - Number(a.norm_pct ?? a.overall_norm_pct ?? 0)
    })
    const q = taxaSearchQuery.value.trim().toLowerCase()
    return q ? list.filter((t) => t.taxon.toLowerCase().includes(q)) : list
  })

  function showSegmentTooltip(e: MouseEvent, seg: StackedSegment, sampleName: string) {
    tooltip.value = {
      visible: true,
      x: e.clientX + 12,
      y: e.clientY - 20,
      sample: sampleName,
      taxon: seg.taxon,
      rawCount: seg.rawCount,
      rawPct: seg.rawPct,
      gcn: seg.gcn,
      normPct: seg.normPct,
    }
  }
  function hideTooltip() {
    tooltip.value.visible = false
  }

  function getTaxonZh(taxon: string): string {
    if (!taxon) return ''
    const lower = taxon.toLowerCase()
    if (lower.startsWith('other') || lower.includes('噪声') || lower.includes('低频')) return '低频测序噪声'
    return translations.value[taxon] || ''
  }

  async function exportExcel() {
    if (!taskId.value) return
    try {
      appStore.showNotification('正在生成多工作表科研级 Excel 报告（还原界面卡片、分组及丰度矩阵）...', 'info')
      const payload = {
        groups: activeGroups.value.map((g) => ({ name: g.name, pattern: g.pattern, matchedSamples: g.matchedSamples })),
        translations: translations.value,
      }
      const resp = await fetch(`${API_BASE}/api/diversity/export_excel/${taskId.value}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const blob = await resp.blob()
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = `16S_多样性综合分析报告_${taskId.value}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(downloadUrl)
      appStore.showNotification('Excel 综合分析报告已成功导出', 'success')
    } catch (e: unknown) {
      logger.warn('POST 导出失败，尝试 GET 回退下载:', e)
      window.open(`${API_BASE}/api/diversity/export_excel/${taskId.value}`, '_blank', 'noopener,noreferrer')
    }
  }

  function toggleSampleCollapse(sampleName: string) {
    if (collapsedSampleKeys.value.has(sampleName)) collapsedSampleKeys.value.delete(sampleName)
    else collapsedSampleKeys.value.add(sampleName)
  }
  function expandAllSamples() {
    collapsedSampleKeys.value.clear()
  }
  function collapseAllSamples() {
    collapsedSampleKeys.value = new Set(activeSamples.value.map((s: DiversitySampleItem) => s.sample_name))
  }
  function isSampleCollapsed(sampleName: string): boolean {
    return collapsedSampleKeys.value.has(sampleName)
  }

  function getDominantTaxon(s: DiversitySampleItem): { taxon: string; pct: number } | null {
    const details = s.norm_result?.details || []
    const valid = details.filter((d) => !isNoiseTaxon(d.taxon))
    if (valid.length === 0) return null
    const top = valid[0]!
    const pct = abundanceMode.value === 'norm' ? top.norm_pct || 0 : top.raw_pct || 0
    return { taxon: top.taxon, pct: Number(pct) }
  }

  const filteredActiveSamples = computed(() => {
    const q = detailSearchQuery.value.trim().toLowerCase()
    if (!q) return activeSamples.value
    return activeSamples.value.filter((s: DiversitySampleItem) => {
      if (s.sample_name && s.sample_name.toLowerCase().includes(q)) return true
      if (s.member_samples && s.member_samples.some((m: string) => m.toLowerCase().includes(q))) return true
      const details = s.norm_result?.details || []
      return details.some((d) => d.taxon && d.taxon.toLowerCase().includes(q))
    })
  })

  watch(
    () => props.modelValue,
    (val) => {
      if (val) {
        if (props.initialFilePath) {
          currentFilePath.value = props.initialFilePath
          void detectPackage(props.initialFilePath)
        }
        void syncLatestTaskOrResume()
        void fetchHistoryTasks()
      } else {
        stopPolling()
        showHistoryDrawer.value = false
      }
    }
  )

  onMounted(() => {
    if (props.modelValue) {
      void syncLatestTaskOrResume()
      void fetchHistoryTasks()
    }
  })

  onUnmounted(() => {
    stopPolling()
  })

  return {
    activeTab,
    abundanceMode,
    currentFilePath,
    isDetecting,
    detectedPackage,
    isGroupView,
    showGroupModal,
    groupChunkSize,
    sampleGroups,
    taxaSearchQuery,
    showHistoryDrawer,
    historyTasks,
    isLoadingHistory,
    isRunning,
    taskId,
    progress,
    currentStep,
    currentSample,
    processedReads,
    totalReads,
    processedSamples,
    totalSamples,
    results,
    topTaxaCount,
    tooltip,
    translations,
    isTranslating,
    detailSearchQuery,
    detailViewMode,
    topTaxaList,
    allSampleNames,
    activeGroups,
    unassignedSamples,
    activeSamples,
    stackedBarData,
    confirmedSpeciesCount,
    filteredTaxaOverview,
    filteredActiveSamples,
    formatTime,
    formatReadsCount,
    getStatusLabel,
    formatPct,
    isNoiseTaxon,
    toggleHistoryDrawer,
    selectHistoryTask,
    deleteHistoryTask,
    clearAllHistory,
    resetToNewAnalysis,
    close,
    handleUploadSuccess,
    startAnalysis,
    fetchHistoryTasks,
    getTaxonColor,
    addGroup,
    removeGroup,
    generateConsecutiveGroups,
    parseSamplePattern,
    setChunkSizeAndGenerate,
    clearAllGroups,
    resetDefaultGroups,
    getRealTaxonRank,
    showSegmentTooltip,
    hideTooltip,
    translateAllTaxa,
    getTaxonZh,
    exportExcel,
    toggleSampleCollapse,
    expandAllSamples,
    collapseAllSamples,
    isSampleCollapsed,
    getDominantTaxon,
  }
}
