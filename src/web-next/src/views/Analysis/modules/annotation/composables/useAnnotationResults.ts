import { computed, ref } from 'vue'
import { apiPost } from '../../../../../bridge/electron-bridge'
import { useAppStore } from '../../../../../stores/app'
import { createLogger } from '../../../../../utils/logger'
import type { AnnotationTaskItem } from '../types'

const logger = createLogger('AnnotationResults')

export interface AnnotationResultsProps {
  task: AnnotationTaskItem
}

export interface AnnotationResultsEmits {
  (e: 'open-in-viewer', gbkText: string, taskName: string): void
  (e: 'open-structure'): void
  (e: 'download', fileType: string): void
}

export function useAnnotationResults(
  props: AnnotationResultsProps,
  emit: AnnotationResultsEmits
) {
  const appStore = useAppStore()

  const searchQuery = ref<string>('')
  const selectedTypeFilter = ref<string>('ALL')
  const selectedStrandFilter = ref<string>('ALL')
  const selectedCategoryFilter = ref<string>('ALL')
  const selectedEngineFilter = ref<string>('ALL')
  const currentPage = ref<number>(1)
  const pageSize = ref<number>(20)
  const expandedRowId = ref<string | null>(null)
  const showSafetyDetails = ref<boolean>(false)

  async function openResultsFolder(): Promise<void> {
    const workDir = (props.task as AnnotationTaskItem & { work_dir?: string }).work_dir
    const taskId = props.task.task_id

    if (workDir && window.electronAPI?.openPath) {
      try {
        await window.electronAPI.openPath(workDir)
        return
      } catch (e) {
        logger.warn('原生 openPath 失败，切换后端唤起:', e)
      }
    }

    if (taskId) {
      try {
        const res = await apiPost<{ success?: boolean }>(`/api/analysis/annotation/${taskId}/open-folder`)
        if (res && res.success) return
      } catch (e) {
        logger.warn('后端打开目录失败:', e)
      }
    }

    appStore.showNotification(`结果目录位于: results/annotations/${taskId}`, 'info')
  }

  const availableCategories = computed(() => {
    const cats = new Set<string>()
    ;(props.task.features || []).forEach((f) => {
      if (f.category) cats.add(f.category)
    })
    return Array.from(cats)
  })

  const availableEngines = computed(() => {
    const engs = new Set<string>()
    ;(props.task.features || []).forEach((f) => {
      if (f.source_engine) engs.add(f.source_engine)
    })
    return Array.from(engs)
  })

  const filteredFeatures = computed(() => {
    const list = props.task.features || []
    const q = searchQuery.value.trim().toLowerCase()

    return list.filter((item) => {
      if (selectedTypeFilter.value !== 'ALL' && item.feature_type !== selectedTypeFilter.value) return false
      if (selectedStrandFilter.value !== 'ALL' && item.strand !== selectedStrandFilter.value) return false
      if (selectedCategoryFilter.value !== 'ALL' && item.category !== selectedCategoryFilter.value) return false
      if (selectedEngineFilter.value !== 'ALL' && item.source_engine !== selectedEngineFilter.value) return false
      if (q) {
        return (
          Boolean(item.locus_tag?.toLowerCase().includes(q)) ||
          Boolean(item.product?.toLowerCase().includes(q)) ||
          Boolean(item.gene_name?.toLowerCase().includes(q)) ||
          Boolean(item.category?.toLowerCase().includes(q)) ||
          Boolean(item.source_engine?.toLowerCase().includes(q)) ||
          Boolean(item.phrog && (`phrog ${item.phrog}`.toLowerCase().includes(q) || item.phrog.toLowerCase().includes(q))) ||
          Boolean(item.function?.toLowerCase().includes(q))
        )
      }
      return true
    })
  })

  const pagedFeatures = computed(() => {
    const start = (currentPage.value - 1) * pageSize.value
    return filteredFeatures.value.slice(start, start + pageSize.value)
  })

  const totalPages = computed(() => Math.ceil(filteredFeatures.value.length / pageSize.value) || 1)

  function toggleExpand(id: string): void {
    expandedRowId.value = expandedRowId.value === id ? null : id
  }

  function copyText(text?: string | null): void {
    if (!text) return
    navigator.clipboard.writeText(text)
    appStore.showNotification('序列内容已复制到剪贴板', 'success')
  }

  function handleOpenInViewer(): void {
    const gbk = props.task.gbk_content || ''
    if (!gbk) {
      appStore.showNotification('未找到可用的 GenBank 数据，请检查注释产物', 'warning')
      return
    }
    emit('open-in-viewer', gbk, props.task.task_name || props.task.task_id)
  }

  function formatNumber(num?: number | null): string {
    if (num === undefined || num === null || Number.isNaN(Number(num))) return '0'
    return Number(num).toLocaleString()
  }

  const amrList = computed(() => props.task?.safety_audit?.amr_genes || [])
  const vfList = computed(() => props.task?.safety_audit?.virulent_factors || [])
  const acrList = computed(() => props.task?.safety_audit?.anti_crispr_genes || [])

  const hasSafetyAudit = computed(() => {
    const sa = props.task?.safety_audit
    if (!sa || typeof sa !== 'object') return false
    return Boolean(
      sa.safety_passed !== undefined ||
        sa.anti_crispr_status ||
        amrList.value.length ||
        vfList.value.length ||
        acrList.value.length
    )
  })

  const totalSafetyHits = computed(() => amrList.value.length + vfList.value.length + acrList.value.length)

  return {
    searchQuery,
    selectedTypeFilter,
    selectedStrandFilter,
    selectedCategoryFilter,
    selectedEngineFilter,
    currentPage,
    pageSize,
    expandedRowId,
    showSafetyDetails,
    availableCategories,
    availableEngines,
    filteredFeatures,
    pagedFeatures,
    totalPages,
    amrList,
    vfList,
    acrList,
    hasSafetyAudit,
    totalSafetyHits,
    openResultsFolder,
    toggleExpand,
    copyText,
    handleOpenInViewer,
    formatNumber,
  }
}
