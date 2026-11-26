/**
 * WorkspacePopulationLandscape 核心状态与计算逻辑 Composable
 * 负责系统发育树联动、ANI/CDS Jaccard 矩阵切换、样本显隐过滤、基因家族预计算与整图导出
 */
import { ref, computed } from 'vue'
import {
  CATEGORY_ORDER,
  normalizeCategoryName,
  inferClusterCategory,
  getClusterConsensusLen,
  getClusterVariantInfo,
  type ClusterVariantInfo,
} from '../../utils/pangenomeVariants'
import {
  computeCdsJaccardMatrix,
  computeUpgmaClustering,
  type HierarchicalClusteringResult,
} from '../../utils/clustering'
import { exportCompleteFigure } from '../../utils/exportLandscapeFigure'

export interface PopulationLandscapeProps {
  aniMatrix: Record<string, Record<string, number | null>>
  afMatrix?: Record<string, Record<string, number>>
  aniTaxonomyMatrix?: Record<string, Record<string, string>>
  aniMetricType?: string
  aniClustering?: any
  sampleNames: Record<string, string>
  tailMatrix?: Record<string, Record<string, number>>
  lysisMatrix?: Record<string, Record<string, number>>
  clusters?: any[]
  lifestyles?: any[]
  armsRaceMatrix?: Record<string, any>
  selectedPair: [string, string] | null
}

export interface PopulationLandscapeEmits {
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
}

export type MetricMatrixMode = 'ani' | 'cds_jaccard'

export function usePopulationLandscape(
  props: PopulationLandscapeProps,
  emit: PopulationLandscapeEmits
) {
  const viewMode = ref<'matrix' | 'chord'>('matrix')

  function handleSelectSample(sid: string) {
    emit('select-sample', sid)
  }

  function handleSelectPair(pair: [string, string]) {
    emit('select-pair', pair)
  }

  const hoveredGeneCluster = ref<{ cluster: any; rowId: string; variant: ClusterVariantInfo } | null>(null)
  const selectedGeneCluster = ref<any | null>(null)
  const geneCategoryFilter = ref<string>('ALL')
  const genePartitionFilter = ref<'ALL' | 'VARIABLE' | 'CORE' | 'UNIQUE'>('ALL')

  // 零开销十字准星垂直导轨状态
  const crosshairVisible = ref(false)
  const crosshairLeft = ref(0)
  const crosshairWidth = ref(5)

  function handleClusterMouseEnter(e: MouseEvent, c: any, rowId: string) {
    const target = e.currentTarget as HTMLElement
    if (target) {
      crosshairLeft.value = target.offsetLeft
      crosshairWidth.value = target.offsetWidth || 5
      crosshairVisible.value = true
    }
    hoveredGeneCluster.value = { cluster: c, rowId, variant: c._variantMap[rowId] }
  }

  function handleClusterMouseLeave() {
    crosshairVisible.value = false
    hoveredGeneCluster.value = null
  }

  // 板块与轨道折叠/显隐控制
  const isLegendCollapsed = ref(false)
  const isPhylogenyTrackVisible = ref(true)
  const isMetadataTrackVisible = ref(true)
  const isAniTrackVisible = ref(true)
  const isGeneMatrixTrackVisible = ref(true)

  // 密度模式
  const displayDensity = ref<'spacious' | 'comfortable' | 'compact' | 'ultra'>('spacious')

  // 样本基础标识列表
  const allSampleIdList = computed<string[]>(() => Object.keys(props.sampleNames || {}))

  // 核心度量模式
  const currentMatrixMode = ref<MetricMatrixMode>('ani')

  // 预计算全量样本之间的 CDS 基因功能谱 Jaccard 相似度矩阵
  const cdsMatrixData = computed(() => {
    return computeCdsJaccardMatrix(allSampleIdList.value, props.clusters || [])
  })

  // 基于 CDS 功能谱执行 UPGMA 层次聚类
  const cdsClustering = computed<HierarchicalClusteringResult>(() => {
    return computeUpgmaClustering(allSampleIdList.value, cdsMatrixData.value.matrix)
  })

  // 当前激活的聚类模型
  const activeClustering = computed(() => {
    if (currentMatrixMode.value === 'cds_jaccard') {
      return cdsClustering.value
    }
    return props.aniClustering
  })

  // 当前激活的相似度矩阵
  const activeSimilarityMatrix = computed(() => {
    if (currentMatrixMode.value === 'cds_jaccard') {
      return cdsMatrixData.value.matrix
    }
    return props.aniMatrix
  })

  // 自然顺序排序算法
  function naturalSort(ids: string[]): string[] {
    return ids.toSorted((a, b) => {
      const nameA = props.sampleNames[a] || a
      const nameB = props.sampleNames[b] || b
      return nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' })
    })
  }

  // 排序模式
  const sampleSortOrder = ref<'natural' | 'cluster'>('cluster')

  const rawClusteredIds = computed<string[]>(() => {
    if (activeClustering.value?.ordered_ids?.length) {
      return activeClustering.value.ordered_ids
    }
    return allSampleIdList.value
  })

  const orderedSampleIds = computed<string[]>(() => {
    const all = Object.keys(props.sampleNames || {})
    if (sampleSortOrder.value === 'natural') {
      return naturalSort(all)
    }
    return rawClusteredIds.value
  })

  // 样本显隐与聚焦控制
  const hiddenSampleIds = ref<Set<string>>(new Set())
  const isSampleFilterOpen = ref<boolean>(false)

  const visibleSampleIds = computed<string[]>(() => {
    return orderedSampleIds.value.filter(id => !hiddenSampleIds.value.has(id))
  })

  function toggleSampleVisibility(sampleId: string) {
    const newSet = new Set(hiddenSampleIds.value)
    if (newSet.has(sampleId)) {
      newSet.delete(sampleId)
    } else {
      if (visibleSampleIds.value.length <= 1) return
      newSet.add(sampleId)
    }
    hiddenSampleIds.value = newSet
  }

  function showAllSamples() {
    hiddenSampleIds.value = new Set()
  }

  function clearAllSamples() {
    const newSet = new Set<string>()
    orderedSampleIds.value.forEach(id => newSet.add(id))
    const keepId = props.selectedPair?.[0] || orderedSampleIds.value[0]
    if (keepId) newSet.delete(keepId)
    hiddenSampleIds.value = newSet
  }

  function focusOnlyPair() {
    if (!props.selectedPair) return
    const [s1, s2] = props.selectedPair
    const newSet = new Set<string>()
    orderedSampleIds.value.forEach(id => {
      if (id !== s1 && id !== s2) newSet.add(id)
    })
    hiddenSampleIds.value = newSet
  }

  function focusOnlySingle(sampleId: string) {
    const newSet = new Set<string>()
    orderedSampleIds.value.forEach(id => {
      if (id !== sampleId) newSet.add(id)
    })
    hiddenSampleIds.value = newSet
  }

  function invertSampleSelection() {
    const newSet = new Set<string>()
    orderedSampleIds.value.forEach(id => {
      if (!hiddenSampleIds.value.has(id)) newSet.add(id)
    })
    if (newSet.size >= orderedSampleIds.value.length) {
      const keepId = props.selectedPair?.[0] || orderedSampleIds.value[0]
      if (keepId) newSet.delete(keepId)
    }
    hiddenSampleIds.value = newSet
  }

  function openClusterDrawer(c: any) {
    selectedGeneCluster.value = c
  }

  // 动态行高
  const rowHeight = computed(() => {
    if (displayDensity.value === 'spacious') return 36
    if (displayDensity.value === 'ultra') return 11
    if (displayDensity.value === 'compact') return 17
    return 24
  })

  // 元数据映射
  const sampleAnnotations = computed(() => {
    const map: Record<string, { lifestyle: string; safe: boolean; acrCount: number }> = {}
    props.lifestyles?.forEach(l => {
      map[l.sample_id] = {
        lifestyle: l.lifestyle || 'Lytic',
        safe: l.is_safe_for_therapy !== false,
        acrCount: props.armsRaceMatrix?.[l.sample_id]?.acr_count || 0,
      }
    })
    return map
  })

  // 核心预计算：构建带变异缓存的基因家族列表
  const sortedGeneClusters = computed(() => {
    if (!props.clusters || props.clusters.length === 0) return []
    const n = visibleSampleIds.value.length
    const allSampleIds = orderedSampleIds.value

    let list = props.clusters.map(c => {
      const infCat = inferClusterCategory(c)
      const consLen = getClusterConsensusLen(c)

      const variantMap: Record<string, ClusterVariantInfo> = {}
      allSampleIds.forEach(sid => {
        variantMap[sid] = getClusterVariantInfo(c, sid, consLen, infCat)
      })

      return {
        ...c,
        _inferredCategory: infCat,
        _consensusLen: consLen,
        _variantMap: variantMap,
      }
    })

    if (geneCategoryFilter.value !== 'ALL') {
      const targetCat = normalizeCategoryName(geneCategoryFilter.value)
      list = list.filter(c => normalizeCategoryName(c._inferredCategory) === targetCat)
    }

    if (genePartitionFilter.value === 'VARIABLE') {
      list = list.filter(c => {
        const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
        return cnt < n && cnt > 0
      })
    } else if (genePartitionFilter.value === 'CORE') {
      list = list.filter(c => {
        const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
        return cnt === n && n > 0
      })
    } else if (genePartitionFilter.value === 'UNIQUE') {
      list = list.filter(c => {
        const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
        return cnt === 1
      })
    }

    return list.toSorted((a, b) => {
      const catA = CATEGORY_ORDER[a._inferredCategory] || 99
      const catB = CATEGORY_ORDER[b._inferredCategory] || 99
      if (catA !== catB) return catA - catB
      return (b.sample_count || 0) - (a.sample_count || 0)
    })
  })

  // 泛基因组核心基因统计
  const pangenomePartition = computed(() => {
    if (!props.clusters) return { core: 0, accessory: 0, total: 0, corePct: '0' }
    const total = props.clusters.length
    const n = visibleSampleIds.value.length
    let core = 0
    let accessory = 0
    props.clusters.forEach(c => {
      let presentInVisible = 0
      visibleSampleIds.value.forEach(sid => {
        if (c.presence_map?.[sid]) presentInVisible++
      })
      if (presentInVisible === n && n > 0) core++
      else accessory++
    })
    return { core, accessory, total, corePct: total > 0 ? ((core / total) * 100).toFixed(0) : '0' }
  })

  function getActiveCellValue(rowId: string, colId: string): number | null | undefined {
    return activeSimilarityMatrix.value?.[rowId]?.[colId]
  }

  function getAniCellColor(val: number | null | undefined): string {
    if (val === null || val === undefined) return '#f8fafc'
    if (val === 0) return '#f8fafc'
    if (val >= 99.5) return '#1e3a8a'
    if (val >= 97.0) return '#2563eb'
    if (val >= 95.0) return '#3b82f6'
    if (val >= 90.0) return '#60a5fa'
    if (val >= 80.0) return '#93c5fd'
    if (val >= 70.0) return '#bfdbfe'
    return '#eff6ff'
  }

  function getAniTextColor(val: number | null | undefined): string {
    if (val === null || val === undefined || val === 0) return '#94a3b8'
    return val >= 95.0 ? '#ffffff' : '#1e3a8a'
  }

  function formatAniDisplay(val: number | null | undefined, s1: string, s2: string): string {
    if (s1 === s2) return '100'
    if (val === null || val === undefined) return '-'
    if (val === 0) return currentMatrixMode.value === 'cds_jaccard' ? '0' : '-'
    if (val >= 99.95) return '100'
    return val.toFixed(1)
  }

  function getAniCellTitle(rowId: string, colId: string): string {
    const name1 = props.sampleNames[rowId] || rowId
    const name2 = props.sampleNames[colId] || colId
    if (rowId === colId) {
      return `${name1}: 自身参照 100.0%`
    }

    if (currentMatrixMode.value === 'cds_jaccard') {
      const stat = cdsMatrixData.value.stats?.[rowId]?.[colId]
      const val = cdsMatrixData.value.mat?.[rowId]?.[colId]
      const valStr = val !== null && val !== undefined ? `${val.toFixed(1)}%` : '0.0%'
      const sharedStr = stat
        ? `\n共享同源 CDS: ${stat.shared} / ${stat.union} 家族 (${valStr})\n差异得失: ${name1} 独有 ${stat.s1Unique} 个, ${name2} 独有 ${stat.s2Unique} 个`
        : ''
      const aniVal = props.aniMatrix?.[rowId]?.[colId]
      const aniRef = aniVal !== null && aniVal !== undefined ? `\n全基因组核酸 ANI: ${aniVal.toFixed(1)}%` : ''
      return `${name1} ↔ ${name2}\n度量模式: CDS 基因功能谱一致性 (Jaccard 相似度)${sharedStr}${aniRef}\n[生物学意义: 衡量基因组蛋白质家族的获得与缺失，对应右侧条形码的断点与缺失]`
    }

    const aniVal = props.aniMatrix?.[rowId]?.[colId]
    const afVal = props.afMatrix?.[rowId]?.[colId]
    const callVal = props.aniTaxonomyMatrix?.[rowId]?.[colId]

    const metric = props.aniMetricType || 'OrthoANI'
    const aniStr = aniVal !== null && aniVal !== undefined ? `${aniVal.toFixed(1)}%` : '未达显著同源阈值 (NA)'
    const afStr = afVal !== undefined ? `${afVal.toFixed(1)}%` : '-'
    const callStr = callVal ? `\n分类判定: ${callVal}` : ''
    const cdsVal = cdsMatrixData.value.mat?.[rowId]?.[colId]
    const cdsRef = cdsVal !== undefined && cdsVal !== null ? `\n参考 CDS 功能谱: ${cdsVal.toFixed(1)}%` : ''

    return `${name1} ↔ ${name2}\n度量标准: 全基因组 ${metric} (DNA 核酸)\n一致性 (ANI): ${aniStr}\n对齐覆盖度 (AF): ${afStr}${callStr}${cdsRef}\n[提示: 可切换为 'CDS功能谱' 查看基因得失]`
  }

  function handleCellClick(s1: string, s2: string) {
    if (s1 === s2) {
      emit('select-sample', s1)
    } else {
      emit('select-pair', [s1, s2])
    }
  }

  const isCurrentPair = (s1: string, s2: string) => {
    if (!props.selectedPair) return false
    return (
      (props.selectedPair[0] === s1 && props.selectedPair[1] === s2) ||
      (props.selectedPair[0] === s2 && props.selectedPair[1] === s1)
    )
  }

  const isExporting = ref(false)

  async function handleExportFigure(format: 'png' | 'svg' = 'png') {
    if (isExporting.value) return
    isExporting.value = true
    try {
      if (viewMode.value === 'chord') {
        const svgEl = document.querySelector('.phylogenomic-chord-canvas svg') as SVGSVGElement | null
        if (svgEl) {
          const svgClone = svgEl.cloneNode(true) as SVGSVGElement
          svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
          const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
          bgRect.setAttribute('width', '100%')
          bgRect.setAttribute('height', '100%')
          bgRect.setAttribute('fill', '#ffffff')
          svgClone.insertBefore(bgRect, svgClone.firstChild)

          const svgXml = new XMLSerializer().serializeToString(svgClone)
          if (format === 'svg') {
            const blob = new Blob([svgXml], { type: 'image/svg+xml;charset=utf-8' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `Figure1_Chord_Diagram_${Date.now()}.svg`
            a.click()
            URL.revokeObjectURL(url)
          } else {
            const bbox = svgEl.getBoundingClientRect()
            const width = bbox.width || 800
            const height = bbox.height || 680
            const canvas = document.createElement('canvas')
            const scale = 2.0
            canvas.width = width * scale
            canvas.height = height * scale
            const ctx = canvas.getContext('2d')
            if (ctx) {
              ctx.scale(scale, scale)
              const img = new Image()
              const blob = new Blob([svgXml], { type: 'image/svg+xml;charset=utf-8' })
              const url = URL.createObjectURL(blob)
              await new Promise<void>((resolve) => {
                img.onload = () => {
                  ctx.drawImage(img, 0, 0, width, height)
                  URL.revokeObjectURL(url)
                  canvas.toBlob(pngBlob => {
                    if (pngBlob) {
                      const pngUrl = URL.createObjectURL(pngBlob)
                      const a = document.createElement('a')
                      a.href = pngUrl
                      a.download = `Figure1_Chord_Diagram_${Date.now()}.png`
                      a.click()
                      URL.revokeObjectURL(pngUrl)
                    }
                    resolve()
                  }, 'image/png')
                }
                img.src = url
              })
            }
          }
        }
        return
      }

      const sortLabel =
        sampleSortOrder.value === 'cluster'
          ? `进化聚类 (${currentMatrixMode.value === 'cds_jaccard' ? 'CDS功能谱' : '全基因组ANI'})`
          : '自然顺序'

      await exportCompleteFigure({
        title: '系统发育与泛基因组同源矩阵',
        subtitle: `${visibleSampleIds.value.length} 株系 · ${sortedGeneClusters.value.length} 基因家族 · ${sortLabel}`,
        visibleSampleIds: visibleSampleIds.value,
        orderedSampleIds: orderedSampleIds.value,
        sampleNames: props.sampleNames,
        sortedGeneClusters: sortedGeneClusters.value,
        aniMatrix: props.aniMatrix,
        lifestyles: props.lifestyles,
        treeRoot: activeClustering.value?.root,
        sortOrder: sampleSortOrder.value,
        isPhylogenyTrackVisible: isPhylogenyTrackVisible.value,
        isMetadataTrackVisible: isMetadataTrackVisible.value,
        isAniTrackVisible: isAniTrackVisible.value,
        isGeneMatrixTrackVisible: isGeneMatrixTrackVisible.value,
        activeSimilarityMatrix: activeSimilarityMatrix.value,
        format,
      })
    } catch (err) {
      console.error('导出图表失败:', err)
    } finally {
      isExporting.value = false
    }
  }

  return {
    viewMode,
    handleSelectSample,
    handleSelectPair,
    hoveredGeneCluster,
    selectedGeneCluster,
    geneCategoryFilter,
    genePartitionFilter,
    crosshairVisible,
    crosshairLeft,
    crosshairWidth,
    handleClusterMouseEnter,
    handleClusterMouseLeave,
    isLegendCollapsed,
    isPhylogenyTrackVisible,
    isMetadataTrackVisible,
    isAniTrackVisible,
    isGeneMatrixTrackVisible,
    displayDensity,
    allSampleIdList,
    currentMatrixMode,
    cdsMatrixData,
    cdsClustering,
    activeClustering,
    activeSimilarityMatrix,
    sampleSortOrder,
    rawClusteredIds,
    orderedSampleIds,
    hiddenSampleIds,
    isSampleFilterOpen,
    visibleSampleIds,
    toggleSampleVisibility,
    showAllSamples,
    clearAllSamples,
    focusOnlyPair,
    focusOnlySingle,
    invertSampleSelection,
    openClusterDrawer,
    rowHeight,
    sampleAnnotations,
    sortedGeneClusters,
    pangenomePartition,
    getActiveCellValue,
    getAniCellColor,
    getAniTextColor,
    formatAniDisplay,
    getAniCellTitle,
    handleCellClick,
    isCurrentPair,
    isExporting,
    handleExportFigure,
  }
}
