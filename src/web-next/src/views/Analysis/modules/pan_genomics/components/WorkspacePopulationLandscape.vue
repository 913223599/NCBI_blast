<script setup lang="ts">
/**
 * WorkspacePopulationLandscape.vue - 旗舰组合图 1: Phylogenomic Evidence Matrix
 * (Phylogeny × Metadata × Whole-Genome ANI × Pan-Genome Gene Content Matrix)
 * 
 * 遵循 Nature / Science / Cell (N/S/C) 组学组合图语法 (Figure Grammar):
 * 1. 共享样本排序 (Shared Phylogenomic Order)
 * 2. 共享生物学对象 (Phage Isolates ↔ Functional Gene Families)
 * 3. 宏观系统发育 → 元数据属性 → 全基因组 ANI 相似度 → 核心/可变基因家族分布 一体化视觉推理闭环
 */
import { ref, computed } from 'vue'
import { FUNCTIONAL_CATEGORIES, inferCategoryFromText } from '../../viewer/utils/render'

const props = defineProps<{
  aniMatrix: Record<string, Record<string, number>>
  aniClustering?: any
  sampleNames: Record<string, string>
  tailMatrix?: Record<string, Record<string, number>>
  lysisMatrix?: Record<string, Record<string, number>>
  clusters?: any[]
  lifestyles?: any[]
  armsRaceMatrix?: Record<string, any>
  selectedPair: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
}>()

const hoveredGeneCluster = ref<any | null>(null)
const selectedGeneCluster = ref<any | null>(null)
const selectedBaselineSampleId = ref<string>('')
const geneCategoryFilter = ref<string>('ALL')
const genePartitionFilter = ref<'ALL' | 'VARIABLE' | 'CORE' | 'UNIQUE'>('ALL')

// 板块与轨道折叠/显隐控制
const isLegendCollapsed = ref(false)

const isPhylogenyTrackVisible = ref(true)
const isMetadataTrackVisible = ref(true)
const isAniTrackVisible = ref(true)
const isGeneMatrixTrackVisible = ref(true)

// 密度模式 (Spacious 宽松 / Comfortable 舒适 / Compact 紧凑 / Ultra 全景 50+)
const displayDensity = ref<'spacious' | 'comfortable' | 'compact' | 'ultra'>('spacious')

// 1. 自然顺序递增排序算法 (Natural Sort: BC01 < BC02 < ... < BC18)
function naturalSort(ids: string[]): string[] {
  return [...ids].sort((a, b) => {
    const nameA = props.sampleNames[a] || a
    const nameB = props.sampleNames[b] || b
    return nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' })
  })
}

// 排序模式: 'natural' 自然顺序递增 (默认) | 'cluster' 系统发育聚类
const sampleSortOrder = ref<'natural' | 'cluster'>('natural')

// 聚类排序后的原始列表
const rawClusteredIds = computed<string[]>(() => {
  if (props.aniClustering?.ordered_ids?.length) {
    return props.aniClustering.ordered_ids
  }
  return Object.keys(props.sampleNames || {})
})

// 当前全局样本 ID 列表 (根据用户选择的排序模式响应式切换)
const orderedSampleIds = computed<string[]>(() => {
  const all = Object.keys(props.sampleNames || {})
  if (sampleSortOrder.value === 'natural') {
    return naturalSort(all)
  }
  return rawClusteredIds.value
})

// 1.1 样本显隐与聚焦控制状态
const hiddenSampleIds = ref<Set<string>>(new Set())
const isSampleFilterOpen = ref<boolean>(false)
const sampleSearchKeyword = ref<string>('')

// 当前活跃可见的样本列表
const visibleSampleIds = computed<string[]>(() => {
  return orderedSampleIds.value.filter(id => !hiddenSampleIds.value.has(id))
})

// 切换单株可见性
function toggleSampleVisibility(sampleId: string) {
  const newSet = new Set(hiddenSampleIds.value)
  if (newSet.has(sampleId)) {
    newSet.delete(sampleId)
  } else {
    // 至少保留 1 个样本可见
    if (visibleSampleIds.value.length <= 1) return
    newSet.add(sampleId)
  }
  hiddenSampleIds.value = newSet
}

// 显示全部样本 (支持搜索态联动)
function showAllSamples() {
  const kw = sampleSearchKeyword.value.trim().toLowerCase()
  if (kw) {
    const newSet = new Set(hiddenSampleIds.value)
    searchableSamples.value.forEach(s => newSet.delete(s.id))
    hiddenSampleIds.value = newSet
  } else {
    hiddenSampleIds.value = new Set()
  }
}

// 全不选/清空样本 (保留第 1 株可见防止矩阵空白)
function clearAllSamples() {
  const kw = sampleSearchKeyword.value.trim().toLowerCase()
  const newSet = new Set(hiddenSampleIds.value)
  if (kw) {
    searchableSamples.value.forEach(s => newSet.add(s.id))
  } else {
    orderedSampleIds.value.forEach(id => newSet.add(id))
  }
  // 至少保留 1 株可见
  if (newSet.size >= orderedSampleIds.value.length) {
    const keepId = props.selectedPair?.[0] || orderedSampleIds.value[0]
    if (keepId) newSet.delete(keepId)
  }
  hiddenSampleIds.value = newSet
}

// 仅聚焦当前选中的对比对
function focusOnlyPair() {
  if (!props.selectedPair) return
  const [s1, s2] = props.selectedPair
  const newSet = new Set<string>()
  orderedSampleIds.value.forEach(id => {
    if (id !== s1 && id !== s2) {
      newSet.add(id)
    }
  })
  hiddenSampleIds.value = newSet
}

// 仅聚焦单个样本
function focusOnlySingle(sampleId: string) {
  const newSet = new Set<string>()
  orderedSampleIds.value.forEach(id => {
    if (id !== sampleId) {
      newSet.add(id)
    }
  })
  hiddenSampleIds.value = newSet
}

// 反选样本 (将当前可见变为隐藏，隐藏变为可见)
function invertSampleSelection() {
  const kw = sampleSearchKeyword.value.trim().toLowerCase()
  const newSet = new Set(hiddenSampleIds.value)
  
  if (kw) {
    searchableSamples.value.forEach(s => {
      if (s.visible) newSet.add(s.id)
      else newSet.delete(s.id)
    })
  } else {
    orderedSampleIds.value.forEach(id => {
      if (!hiddenSampleIds.value.has(id)) {
        newSet.add(id)
      } else {
        newSet.delete(id)
      }
    })
  }

  // 防御：若反选后全被隐藏（如全选态反选），自动保留第 1 株可见
  if (newSet.size >= orderedSampleIds.value.length) {
    const keepId = props.selectedPair?.[0] || orderedSampleIds.value[0]
    if (keepId) newSet.delete(keepId)
  }

  hiddenSampleIds.value = newSet
}

// 搜索样本列表 (始终按自然编号顺序递增排列)
const searchableSamples = computed(() => {
  const kw = sampleSearchKeyword.value.trim().toLowerCase()
  const allIds = naturalSort(Object.keys(props.sampleNames || {}))
  return allIds.map(id => ({
    id,
    name: props.sampleNames[id] || id,
    visible: !hiddenSampleIds.value.has(id)
  })).filter(item => {
    if (!kw) return true
    return item.name.toLowerCase().includes(kw) || item.id.toLowerCase().includes(kw)
  })
})

function openClusterDrawer(c: any) {
  selectedGeneCluster.value = c
  // 默认选取当前分析对的第1株，或该基因存在的第1株作为对照基准
  if (props.selectedPair?.[0] && c.presence_map?.[props.selectedPair[0]]) {
    selectedBaselineSampleId.value = props.selectedPair[0]
  } else {
    const firstPresent = visibleSampleIds.value.find((sid: string) => !!c.presence_map?.[sid])
    selectedBaselineSampleId.value = firstPresent || visibleSampleIds.value[0] || ''
  }
}

// 1.2 动态系统发育树几何拓扑 (归一化高精度坐标体系，与表格行高 100% 绝对物理对齐)
const rowHeight = computed(() => {
  if (displayDensity.value === 'spacious') return 36
  if (displayDensity.value === 'ultra') return 11
  if (displayDensity.value === 'compact') return 17
  return 24
})

interface TreeBranch {
  x1: number
  y1: number
  x2: number
  y2: number
}

interface TreeTip {
  x: number
  y: number
  r: number
  id: string
}

const treeSvgLayout = computed(() => {
  const ids = visibleSampleIds.value
  const n = ids.length
  const currentHeight = rowHeight.value // 36 / 24 / 17 / 11

  if (n === 0) return { width: 44, height: currentHeight, branches: [] as TreeBranch[], tips: [] as TreeTip[] }

  const totalHeight = n * currentHeight
  const baseRadius = displayDensity.value === 'spacious' ? 3.2 : (displayDensity.value === 'ultra' ? 1.5 : (displayDensity.value === 'compact' ? 2.0 : 2.5))

  const tips: TreeTip[] = ids.map((id, idx) => ({
    x: 36,
    y: (idx + 0.5) * currentHeight,
    r: baseRadius,
    id
  }))

  if (n === 1) {
    const tip0 = tips[0]
    return {
      width: 44,
      height: totalHeight,
      branches: tip0 ? [{ x1: 6, y1: tip0.y, x2: 36, y2: tip0.y }] : [],
      tips
    }
  }

  // 动态 UPGMA 聚类构建几何树 (精准物理 Y 坐标)
  let clusters: Array<{
    ids: string[]
    leaves: number[]
    y: number
    x: number
    height: number
  }> = ids.map((id, idx) => ({
    ids: [id],
    leaves: [idx],
    y: (idx + 0.5) * currentHeight,
    x: 36,
    height: 0
  }))

  const branches: TreeBranch[] = []
  let currentStep = 0
  const maxSteps = n - 1

  while (clusters.length > 1) {
    let bestI = 0
    let bestJ = 1
    let maxSimilarity = -1

    for (let i = 0; i < clusters.length; i++) {
      const ci = clusters[i]
      if (!ci) continue
      for (let j = i + 1; j < clusters.length; j++) {
        const cj = clusters[j]
        if (!cj) continue
        let sumSim = 0
        let count = 0
        for (const s1 of ci.ids) {
          for (const s2 of cj.ids) {
            sumSim += props.aniMatrix?.[s1]?.[s2] ?? (s1 === s2 ? 100 : 80)
            count++
          }
        }
        const avgSim = count > 0 ? sumSim / count : 80
        if (avgSim > maxSimilarity) {
          maxSimilarity = avgSim
          bestI = i
          bestJ = j
        }
      }
    }

    const cA = clusters[bestI]
    const cB = clusters[bestJ]
    if (!cA || !cB) break
    currentStep++

    // 计算分叉节点的 x 坐标 (深度从 36 逐渐向左推移到 6)
    const newX = Math.max(6, 36 - (currentStep / maxSteps) * 26)
    const newY = (cA.y + cB.y) / 2

    // 为子节点 A 画线: 水平线 (newX, cA.y) -> (cA.x, cA.y)
    branches.push({ x1: newX, y1: cA.y, x2: cA.x, y2: cA.y })
    // 为子节点 B 画线: 水平线 (newX, cB.y) -> (cB.x, cB.y)
    branches.push({ x1: newX, y1: cB.y, x2: cB.x, y2: cB.y })
    // 垂直连接线: (newX, min(cA.y, cB.y)) -> (newX, max(cA.y, cB.y))
    branches.push({ x1: newX, y1: Math.min(cA.y, cB.y), x2: newX, y2: Math.max(cA.y, cB.y) })

    const merged = {
      ids: [...cA.ids, ...cB.ids],
      leaves: [...cA.leaves, ...cB.leaves],
      y: newY,
      x: newX,
      height: 100 - maxSimilarity
    }

    clusters = clusters.filter((_, idx) => idx !== bestI && idx !== bestJ)
    clusters.push(merged)
  }

  // 根节点向左引一条主干根茎
  const root = clusters[0]
  if (root) {
    branches.push({ x1: 2, y1: root.y, x2: root.x, y2: root.y })
  }

  return {
    width: 44,
    height: totalHeight,
    branches,
    tips
  }
})

// 2. 宏观群体统计 (基于当前可见样本)
const populationStats = computed(() => {
  const ids = visibleSampleIds.value
  const n = ids.length
  if (n < 2) return { n, minAni: '100', maxAni: '100', avgAni: '100' }
  
  let sumAni = 0
  let count = 0
  let minA = 100
  let maxA = 0

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const s1 = ids[i]
      const s2 = ids[j]
      if (s1 && s2) {
        const val = props.aniMatrix?.[s1]?.[s2] ?? 0
        sumAni += val
        count++
        if (val < minA) minA = val
        if (val > maxA) maxA = val
      }
    }
  }

  return {
    n,
    minAni: minA.toFixed(1),
    maxAni: maxA.toFixed(1),
    avgAni: count ? (sumAni / count).toFixed(1) : '100'
  }
})

// 4. 元数据属性映射
const sampleAnnotations = computed(() => {
  const map: Record<string, { lifestyle: string; safe: boolean; acrCount: number }> = {}
  props.lifestyles?.forEach(l => {
    map[l.sample_id] = {
      lifestyle: l.lifestyle || 'Lytic',
      safe: l.is_safe_for_therapy !== false,
      acrCount: props.armsRaceMatrix?.[l.sample_id]?.acr_count || 0
    }
  })
  return map
})

// 5. 排序与分类基因家族列表 (Gene Clusters sorted by Category & Occupancy)
const categoryOrder: Record<string, number> = {
  'Tail & Host Interaction': 1,
  'Lysis': 2,
  'Defense & Host Interaction': 3,
  'Head & Packaging': 4,
  'Integration & Excision': 5,
  'Replication & Repair': 6,
  'Transcription & Regulation': 7,
  'Metabolism & AMG': 8,
  'Other Functional': 9,
  'Hypothetical': 10
}

// 智能生物学分类推断器 (使用全基因组统一权威规则)
function inferClusterCategory(c: any): string {
  if (!c) return 'Hypothetical'
  const prod = c.representative_product || c.representative_annotation?.product || c.cluster_name || ''
  const notes = c.notes || c.representative_annotation?.notes || ''
  return inferCategoryFromText(prod, notes)
}

function getCatColor(cat: string): string {
  if (FUNCTIONAL_CATEGORIES[cat]) {
    return FUNCTIONAL_CATEGORIES[cat].color
  }
  return '#94a3b8'
}

const sortedGeneClusters = computed(() => {
  if (!props.clusters || props.clusters.length === 0) return []
  const n = visibleSampleIds.value.length
  
  let list = props.clusters.map(c => ({
    ...c,
    _inferredCategory: inferClusterCategory(c)
  }))

  // 1. 功能分类过滤
  if (geneCategoryFilter.value !== 'ALL') {
    list = list.filter(c => c._inferredCategory === geneCategoryFilter.value)
  }

  // 2. 泛基因组分区/差异过滤 (基于当前可见样本)
  if (genePartitionFilter.value === 'VARIABLE') {
    // 仅显示在当前可见样本间存在差异的 CDS
    list = list.filter(c => {
      const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
      return cnt < n && cnt > 0
    })
  } else if (genePartitionFilter.value === 'CORE') {
    // 仅显示当前可见样本全部共有的核心 CDS
    list = list.filter(c => {
      const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
      return cnt === n && n > 0
    })
  } else if (genePartitionFilter.value === 'UNIQUE') {
    // 仅显示当前可见样本中单株特有的独有 CDS
    list = list.filter(c => {
      const cnt = visibleSampleIds.value.filter(sid => !!c.presence_map?.[sid]).length
      return cnt === 1
    })
  }

  return list.sort((a, b) => {
    const catA = categoryOrder[a._inferredCategory] || 99
    const catB = categoryOrder[b._inferredCategory] || 99
    if (catA !== catB) return catA - catB
    return (b.sample_count || 0) - (a.sample_count || 0)
  })
})

// 5.1 基因家族群体众数长度计算与微观变异类型探测器
function getClusterConsensusLen(c: any): number {
  if (!c?.presence_map) return 0
  const lens: number[] = Object.values(c.presence_map)
    .map((m: any) => Number(m?.length_aa || 0))
    .filter((l: number) => l > 0)
  if (lens.length === 0) return 0

  const counts: Record<number, number> = {}
  let maxCount = 0
  let modeLen = lens[0] || 0
  for (const l of lens) {
    counts[l] = (counts[l] || 0) + 1
    if (counts[l] > maxCount) {
      maxCount = counts[l]
      modeLen = l
    }
  }
  return modeLen
}

function getClusterVariantInfo(c: any, rowId: string) {
  const item = c.presence_map?.[rowId]
  if (!item) {
    return {
      type: 'absent',
      className: '',
      title: '该样本缺失此 CDS',
      style: {},
      variantLabel: '缺失'
    }
  }

  const consensusLen = getClusterConsensusLen(c)
  const len = Number(item.length_aa || 0)
  const catColor = getCatColor(c._inferredCategory || c.category)

  // 1. 完全等长保守
  if (!consensusLen || len === consensusLen) {
    return {
      type: 'conserved',
      className: 'sq-conserved',
      title: `${c.group_id} (${c._inferredCategory || c.category}): ${c.representative_product} · [等长保守] ${len} aa (与群体众数一致)`,
      style: {
        backgroundColor: catColor
      },
      variantLabel: '等长保守'
    }
  }

  const delta = len - consensusLen
  // 2. 缺失截短变异 (Truncated / Deletion)
  if (delta < 0) {
    const absDelta = Math.abs(delta)
    const pct = ((absDelta / consensusLen) * 100).toFixed(0)
    return {
      type: 'truncated',
      className: 'sq-truncated',
      title: `${c.group_id} (${c._inferredCategory || c.category}): ${c.representative_product} · [缺失截短] -${absDelta} aa (${pct}% 截短，当前 ${len} aa vs 众数 ${consensusLen} aa)`,
      style: {
        backgroundColor: catColor
      },
      variantLabel: `缺失截短 (-${absDelta} aa)`
    }
  }

  // 3. 插入延长变异 (Extended / Insertion)
  const pct = ((delta / consensusLen) * 100).toFixed(0)
  return {
    type: 'extended',
    className: 'sq-extended',
    title: `${c.group_id} (${c._inferredCategory || c.category}): ${c.representative_product} · [插入延长] +${delta} aa (+${pct}% 延长，当前 ${len} aa vs 众数 ${consensusLen} aa)`,
    style: {
      backgroundColor: catColor
    },
    variantLabel: `插入延长 (+${delta} aa)`
  }
}

// 6. 氨基酸变异类型判别器 (Amino Acid Variation Comparator)
interface AminoAcidVariationResult {
  type: 'baseline' | 'identical' | 'deletion' | 'insertion' | 'absent'
  badgeText: string
  badgeClass: string
  diffDetail: string
  lengthDelta: number
}

function getAminoAcidVariation(cluster: any, sid: string, baselineSid: string): AminoAcidVariationResult {
  if (!cluster) {
    return { type: 'absent', badgeText: '缺失', badgeClass: 'var-absent', diffDetail: '—', lengthDelta: 0 }
  }

  const item = cluster.presence_map?.[sid]
  const baseItem = cluster.presence_map?.[baselineSid]

  // 1. 基准样本自身
  if (sid === baselineSid) {
    const len = item?.length_aa || 0
    return {
      type: 'baseline',
      badgeText: '[基准] 对照基准',
      badgeClass: 'var-baseline',
      diffDetail: `基准序列 (${len} aa)`,
      lengthDelta: 0
    }
  }

  // 2. 当前样本缺失此基因
  if (!item) {
    const baseLen = Number(baseItem?.length_aa || 0)
    return {
      type: 'absent',
      badgeText: '基因完全缺失',
      badgeClass: 'var-absent',
      diffDetail: baseLen ? `较基准全长缺失 -${baseLen} aa (-100%)` : '该样本未编码此 CDS',
      lengthDelta: -baseLen
    }
  }

  const targetLen = Number(item.length_aa || 0)
  const baseLen = Number(baseItem?.length_aa || 0)

  // 3. 基准株缺失但当前株存在
  if (!baseItem || baseLen === 0) {
    return {
      type: 'identical',
      badgeText: '单方存在',
      badgeClass: 'var-present',
      diffDetail: `${targetLen} aa (对照基准株缺失此基因)`,
      lengthDelta: targetLen
    }
  }

  const delta = targetLen - baseLen

  // 4. 缺失 / 截短 (Deletion / Truncation)
  if (delta < 0) {
    const absDelta = Math.abs(delta)
    const pct = ((absDelta / baseLen) * 100).toFixed(1)
    return {
      type: 'deletion',
      badgeText: `缺失截短 (-${absDelta} aa)`,
      badgeClass: 'var-deletion',
      diffDetail: `较基准缺失 ${absDelta} 个氨基酸 (${pct}% 长度截短)`,
      lengthDelta: delta
    }
  }

  // 5. 插入 / 延长 (Insertion / Extension)
  if (delta > 0) {
    const pct = ((delta / baseLen) * 100).toFixed(1)
    return {
      type: 'insertion',
      badgeText: `插入延长 (+${delta} aa)`,
      badgeClass: 'var-insertion',
      diffDetail: `较基准插入 +${delta} 个氨基酸 (+${pct}% 长度延长)`,
      lengthDelta: delta
    }
  }

  // 6. 等长同源 (Identical / Point Mutation candidate)
  return {
    type: 'identical',
    badgeText: '等长保守',
    badgeClass: 'var-identical',
    diffDetail: `长度完全一致 (${targetLen} aa) · 同源结构域保守`,
    lengthDelta: 0
  }
}

// 泛基因组宏观占比 (基于当前可见样本)
const pangenomePartition = computed(() => {
  if (!props.clusters) return { core: 0, accessory: 0, total: 0 }
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

function getAniCellColor(val: number): string {
  if (val >= 99) return '#1e3a8a'
  if (val >= 97) return '#2563eb'
  if (val >= 95) return '#3b82f6'
  if (val >= 90) return '#60a5fa'
  if (val >= 80) return '#93c5fd'
  if (val >= 70) return '#bfdbfe'
  return '#eff6ff'
}

function getAniTextColor(val: number): string {
  return val >= 95 ? '#ffffff' : '#1e3a8a'
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
</script>

<template>
  <div class="workspace-population-landscape" :class="['density-' + displayDensity]">
    <!-- 顶刊旗舰组合图: Phylogenomic Evidence Matrix (Figure 1 直接置顶，去除冗余概览) -->
    <div class="academic-panel flagship-matrix-panel">
      <!-- 1. 顶层主标题与全局视图控制带 -->
      <div class="panel-header-deck">
        <div class="deck-title-area">
          <div class="title-main-row">
            <span class="panel-tag-pill">Figure 1</span>
            <h3 class="panel-heading-text">系统发育与泛基因组多维证据矩阵</h3>
            <span class="matrix-scope-badge">
              {{ visibleSampleIds.length }} 株系 (共 {{ orderedSampleIds.length }}) · {{ sortedGeneClusters.length }} 基因家族
            </span>
          </div>

          <!-- 样本可见性与聚焦筛选工具条 -->
          <div class="sample-visibility-toolbar">
            <div class="sample-count-pill" :class="{ 'has-hidden': hiddenSampleIds.size > 0 }">
              <span>显示 <strong>{{ visibleSampleIds.length }}</strong>/{{ orderedSampleIds.length }}</span>
              <span v-if="hiddenSampleIds.size > 0" class="hidden-badge">已隐藏 {{ hiddenSampleIds.size }}</span>
            </div>

            <div class="sample-filter-btn-group">
              <button 
                v-if="hiddenSampleIds.size > 0" 
                class="btn-sample-action btn-show-all" 
                @click="showAllSamples"
                title="恢复显示全部样本"
              >
                全部显示
              </button>

              <button 
                v-if="selectedPair && visibleSampleIds.length > 2" 
                class="btn-sample-action btn-focus-pair" 
                @click="focusOnlyPair"
                title="仅保留当前选中的 2 株对比样本"
              >
                仅看当前对
              </button>

              <!-- 下拉筛选器触发按钮 -->
              <div class="sample-dropdown-wrapper">
                <button 
                  class="btn-sample-action btn-filter-dropdown" 
                  :class="{ active: isSampleFilterOpen }"
                  @click="isSampleFilterOpen = !isSampleFilterOpen"
                  title="勾选或搜索样本"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                  </svg>
                  筛选样本
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                <!-- 弹出浮层 -->
                <div class="sample-dropdown-panel" v-if="isSampleFilterOpen">
                  <div class="sd-header">
                    <input 
                      type="text" 
                      v-model="sampleSearchKeyword" 
                      placeholder="搜索样本..." 
                      class="sd-search-input"
                      @click.stop
                    />
                    <div class="sd-quick-actions">
                      <button class="btn-sd-quick" @click.stop="showAllSamples" title="勾选所有样本">全选</button>
                      <button class="btn-sd-quick" @click.stop="invertSampleSelection" title="反转勾选状态">反选</button>
                      <button class="btn-sd-quick" @click.stop="clearAllSamples" title="仅保留首株，取消其余勾选">全不选</button>
                      <button class="btn-sd-close" @click.stop="isSampleFilterOpen = false">×</button>
                    </div>
                  </div>

                  <div class="sd-sample-list">
                    <div 
                      v-for="s in searchableSamples" 
                      :key="'sd-item-' + s.id" 
                      class="sd-sample-item"
                      :class="{ active: s.visible }"
                      @click="toggleSampleVisibility(s.id)"
                    >
                      <input type="checkbox" :checked="s.visible" @click.stop="toggleSampleVisibility(s.id)" />
                      <span class="sd-name" :title="s.name">{{ s.name }}</span>
                      <button 
                        class="btn-sd-only" 
                        @click.stop="focusOnlySingle(s.id)" 
                        title="仅看这一株"
                      >
                        仅看
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="deck-actions-area">
          <!-- 排序分段控制器 (自然递增 / 系统发育) -->
          <div class="segmented-density-control">
            <span class="control-label">排序:</span>
            <div class="seg-pills">
              <button 
                class="seg-btn" 
                :class="{ active: sampleSortOrder === 'natural' }" 
                @click="sampleSortOrder = 'natural'"
                title="按样本名称与编号自然递增排列 (BC01, BC02...)"
              >
                自然顺序
              </button>
              <button 
                class="seg-btn" 
                :class="{ active: sampleSortOrder === 'cluster' }" 
                @click="sampleSortOrder = 'cluster'"
                title="按系统发育树与全基因组 ANI 相似度聚类排列"
              >
                进化聚类
              </button>
            </div>
          </div>

          <!-- 密度分段控制器 (Segmented Control) -->
          <div class="segmented-density-control">
            <span class="control-label">密度:</span>
            <div class="seg-pills">
              <button 
                class="seg-btn btn-spacious" 
                :class="{ active: displayDensity === 'spacious' }" 
                @click="displayDensity = 'spacious'"
                title="宽松模式 (行高 36px，适合 2~12 株小样本精细观察)"
              >
                宽松
              </button>
              <button 
                class="seg-btn" 
                :class="{ active: displayDensity === 'comfortable' }" 
                @click="displayDensity = 'comfortable'"
                title="舒适模式 (行高 24px，适合 12~25 株)"
              >
                舒适
              </button>
              <button 
                class="seg-btn" 
                :class="{ active: displayDensity === 'compact' }" 
                @click="displayDensity = 'compact'"
                title="紧凑模式 (行高 17px，适合 25~45 株)"
              >
                紧凑
              </button>
              <button 
                class="seg-btn btn-ultra" 
                :class="{ active: displayDensity === 'ultra' }" 
                @click="displayDensity = 'ultra'"
                title="全景微缩模式 (行高 11px，适合 45~100+ 株)"
              >
                50+全景
              </button>
            </div>
          </div>

          <!-- 图注收折按钮 -->
          <button 
            class="btn-legend-toggle"
            :class="{ active: !isLegendCollapsed }"
            @click="isLegendCollapsed = !isLegendCollapsed"
            :title="isLegendCollapsed ? '展开图注' : '收起图注'"
          >
            <svg class="legend-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="14" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
            </svg>
            {{ isLegendCollapsed ? '展开图注' : '收起图注' }}
          </button>
        </div>
      </div>

      <!-- 2. 统一操作带 (Unified Tool Ribbon: 数据切片 + 轨道显隐) -->
      <div class="matrix-ribbon-bar">
        <!-- 左侧：CDS 分区与功能分类过滤 -->
        <div class="ribbon-left-filters">
          <div class="filter-group">
            <span class="ribbon-group-label">CDS 分区:</span>
            <div class="ribbon-pills">
              <button 
                class="r-pill" 
                :class="{ active: genePartitionFilter === 'ALL' }"
                @click="genePartitionFilter = 'ALL'"
              >
                全部 ({{ clusters?.length || 0 }})
              </button>
              <button 
                class="r-pill r-pill-amber" 
                :class="{ active: genePartitionFilter === 'VARIABLE' }"
                @click="genePartitionFilter = 'VARIABLE'"
                title="仅显示存在样本缺失或分化的差异 CDS 家族"
              >
                差异 ({{ (clusters?.length || 0) - Number(pangenomePartition.core) }})
              </button>
              <button 
                class="r-pill r-pill-blue" 
                :class="{ active: genePartitionFilter === 'CORE' }"
                @click="genePartitionFilter = 'CORE'"
                title="仅显示全群体 100% 共享的核心 CDS 家族"
              >
                核心 Core ({{ pangenomePartition.core }})
              </button>
              <button 
                class="r-pill" 
                :class="{ active: genePartitionFilter === 'UNIQUE' }"
                @click="genePartitionFilter = 'UNIQUE'"
                title="仅显示仅在单一株系中出现的特有 CDS"
              >
                单株特有
              </button>
            </div>
          </div>

          <div class="filter-divider"></div>

          <div class="filter-group">
            <span class="ribbon-group-label">功能:</span>
            <select v-model="geneCategoryFilter" class="modern-select select-cat">
              <option value="ALL">全部模块 (All Modules)</option>
              <option value="Tail">尾丝与受体 (Tail)</option>
              <option value="Lysis">裂解系统 (Lysis)</option>
              <option value="Defense & Host Interaction">免疫防御 (Defense/Acr)</option>
              <option value="Replication & Repair">复制修饰 (Replication)</option>
              <option value="Structural">结构形态 (Structural)</option>
              <option value="Packaging">DNA包装 (Packaging)</option>
            </select>
          </div>
        </div>

        <!-- 右侧：多维轨道显隐开关 -->
        <div class="ribbon-right-tracks">
          <span class="ribbon-group-label">显示轨道:</span>
          <div class="track-check-pills">
            <button 
              class="trk-pill" 
              :class="{ active: isPhylogenyTrackVisible }" 
              @click="isPhylogenyTrackVisible = !isPhylogenyTrackVisible"
              title="显示/隐藏系统发育树轨道"
            >
              <span class="trk-dot"></span> 进化树
            </button>
            <button 
              class="trk-pill" 
              :class="{ active: isMetadataTrackVisible }" 
              @click="isMetadataTrackVisible = !isMetadataTrackVisible"
              title="显示/隐藏元数据轨道"
            >
              <span class="trk-dot"></span> 元数据
            </button>
            <button 
              class="trk-pill" 
              :class="{ active: isAniTrackVisible }" 
              @click="isAniTrackVisible = !isAniTrackVisible"
              title="显示/隐藏全基因组 ANI 相似度矩阵"
            >
              <span class="trk-dot"></span> ANI 矩阵
            </button>
            <button 
              class="trk-pill" 
              :class="{ active: isGeneMatrixTrackVisible }" 
              @click="isGeneMatrixTrackVisible = !isGeneMatrixTrackVisible"
              title="显示/隐藏泛基因组正交家族矩阵"
            >
              <span class="trk-dot"></span> 基因全序
            </button>
          </div>
        </div>
      </div>

      <!-- 3. 精炼学术图注条 (可一键收起/展开) -->
      <div class="academic-legend-deck" v-show="!isLegendCollapsed">
        <div class="leg-col leg-col-function">
          <span class="leg-col-title">CDS 功能分类:</span>
          <div class="leg-items-wrap">
            <span v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" class="leg-chip">
              <i :style="{ background: cat.color }"></i>{{ cat.label.split(' ')[0] }}
            </span>
          </div>
        </div>

        <div class="leg-col leg-col-variation">
          <span class="leg-col-title">变异形态:</span>
          <div class="leg-items-wrap">
            <span class="leg-chip"><span class="swatch-sq sq-legend-conserved"></span>等长保守 (纯色)</span>
            <span class="leg-chip"><span class="swatch-sq sq-legend-truncated"></span>缺失截短 (斜纹)</span>
            <span class="leg-chip"><span class="swatch-sq sq-legend-extended"></span>插入延长 (端标)</span>
            <span class="leg-chip"><span class="swatch-dot" style="background-color: #cbd5e1;"></span>基因缺失</span>
          </div>
        </div>

        <div class="leg-col leg-col-ani" v-if="isAniTrackVisible">
          <span class="leg-col-title">全基因组 ANI (%):</span>
          <div class="ani-heat-swatch-list">
            <span class="heat-chip" style="background-color: #eff6ff; color: #1e3a8a;">70</span>
            <span class="heat-chip" style="background-color: #bfdbfe; color: #1e3a8a;">80</span>
            <span class="heat-chip" style="background-color: #60a5fa; color: #ffffff;">90</span>
            <span class="heat-chip" style="background-color: #2563eb; color: #ffffff;">95</span>
            <span class="heat-chip" style="background-color: #1e3a8a; color: #ffffff;">100</span>
          </div>
        </div>
      </div>

      <!-- 共享样本排序的一体化矩阵画板 (支持粘性冻结表头与冻结样本列) -->
      <div class="phylogenomic-composite-canvas">
        <table class="composite-evidence-table">
          <thead>
            <tr>
              <!-- 1. 进化树列头 (可收起) -->
              <th v-if="isPhylogenyTrackVisible" class="th-tree th-sticky-left-1" title="系统发育拓扑树 (基于全基因组 ANI 矩阵进行 UPGMA 聚类构建)">Phylogeny</th>
              <!-- 2. 样本名称列头 (冻结吸附在左侧) -->
              <th 
                class="th-sample-name" 
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                title="样本标识名称"
              >
                Sample ID
              </th>
              <!-- 3. 元数据轨道列头 (可收起) -->
              <template v-if="isMetadataTrackVisible">
                <th class="th-meta" title="噬菌体生活周期 (Lytic 专性烈性 / Lysogenic 温和溶原)">Lifestyle</th>
                <th class="th-meta" title="治疗安全性审计 (Safe 毒力因子与耐药基因阴性)">Safety</th>
                <th class="th-meta" title="抗 CRISPR 攻防系统 (携带的 Anti-CRISPR 基因数)">Acr</th>
              </template>
              <!-- 4. ANI 矩阵列头 (与行样本完全一致的顺序，可收起) -->
              <template v-if="isAniTrackVisible">
                <th 
                  v-for="colId in visibleSampleIds" 
                  :key="'ani-h-' + colId"
                  class="th-ani-col"
                  :class="{ 'th-active-pair': selectedPair?.includes(colId) }"
                >
                  <div class="th-rot-label" :title="sampleNames[colId]">
                    {{ sampleNames[colId] || colId }}
                  </div>
                </th>
              </template>
              <!-- 5. 基因家族存在/缺失矩阵列头 (可收起) -->
              <th 
                v-if="isGeneMatrixTrackVisible" 
                class="th-genefamily-title" 
                :colspan="Math.max(1, sortedGeneClusters.length)"
              >
                <div class="gene-matrix-header-bar">
                  <span class="gene-matrix-title-txt">Pan-Genome Ortholog Content Matrix (共 {{ sortedGeneClusters.length }} 基因家族，按功能着色)</span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="(rowId, rIdx) in visibleSampleIds" 
              :key="'row-sample-' + rowId"
              class="composite-row"
              :class="{ 'row-pair-selected': selectedPair?.includes(rowId) }"
            >
              <!-- 1. 左侧系统发育拓扑树 (绝对定位容器包裹，杜绝任何对表格行高的反向撑高) -->
              <td 
                v-if="isPhylogenyTrackVisible && rIdx === 0" 
                class="td-tree-col th-sticky-left-1" 
                :rowspan="visibleSampleIds.length"
              >
                <div class="tree-absolute-wrapper">
                  <svg 
                    class="tree-composite-svg" 
                    :viewBox="`0 0 ${treeSvgLayout.width} ${treeSvgLayout.height}`"
                    preserveAspectRatio="none"
                  >
                    <!-- 进化树分支线 -->
                    <line 
                      v-for="(b, bIdx) in treeSvgLayout.branches" 
                      :key="'branch-' + bIdx"
                      :x1="b.x1" 
                      :y1="b.y1" 
                      :x2="b.x2" 
                      :y2="b.y2" 
                      stroke="#475569" 
                      stroke-width="1.2" 
                      vector-effect="non-scaling-stroke"
                      stroke-linecap="round"
                    />
                    <!-- 叶子节点末端指示圆点 (精准对齐每行中线) -->
                    <circle 
                      v-for="tip in treeSvgLayout.tips" 
                      :key="'tip-' + tip.id"
                      :cx="tip.x" 
                      :cy="tip.y" 
                      :r="tip.r"
                      fill="#2563eb" 
                      stroke="#ffffff"
                      stroke-width="0.8"
                      vector-effect="non-scaling-stroke"
                    />
                  </svg>
                </div>
              </td>

              <!-- 2. 样本名称 (点击可切换聚焦，带显隐控制，冻结在左侧) -->
              <td 
                class="td-sample-name-col" 
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                :title="sampleNames[rowId]"
              >
                <div class="sample-name-cell-inner">
                  <button 
                    class="btn-sample-eye" 
                    @click.stop="toggleSampleVisibility(rowId)" 
                    title="暂时隐藏该样本"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </button>
                  <span class="sample-title-txt" @click="emit('select-sample', rowId)">
                    {{ sampleNames[rowId] || rowId }}
                  </span>
                </div>
              </td>

              <!-- 3. 样本多维元数据轨道 (Lifestyle | Safety | Acr) (可收起) -->
              <template v-if="isMetadataTrackVisible">
                <td class="td-meta-col">
                  <span class="meta-badge bg-lytic">Lytic</span>
                </td>
                <td class="td-meta-col">
                  <span class="meta-badge bg-safe">Safe</span>
                </td>
                <td class="td-meta-col">
                  <strong class="text-blue">{{ sampleAnnotations[rowId]?.acrCount || 0 }}</strong>
                </td>
              </template>

              <!-- 4. 全基因组 ANI 矩阵单元格 (可收起) -->
              <template v-if="isAniTrackVisible">
                <td 
                  v-for="colId in visibleSampleIds" 
                  :key="'ani-cell-' + rowId + '-' + colId"
                  class="td-ani-val-cell"
                  :style="{ 
                    backgroundColor: getAniCellColor(aniMatrix?.[rowId]?.[colId] ?? 0),
                    color: getAniTextColor(aniMatrix?.[rowId]?.[colId] ?? 0)
                  }"
                  :class="{ 'cell-pair-highlight': isCurrentPair(rowId, colId) }"
                  @click="handleCellClick(rowId, colId)"
                  :title="`${sampleNames[rowId]} ↔ ${sampleNames[colId]}: ANI ${(aniMatrix?.[rowId]?.[colId] ?? 0).toFixed(1)}%`"
                >
                  <span v-if="displayDensity !== 'ultra'">{{ (aniMatrix?.[rowId]?.[colId] ?? 0).toFixed(0) }}</span>
                </td>
              </template>

              <!-- 5. 同源基因家族存在/缺失方块矩阵 (可收起) -->
              <template v-if="isGeneMatrixTrackVisible">
                <td 
                  v-for="c in sortedGeneClusters" 
                  :key="'cluster-' + rowId + '-' + c.group_id"
                  class="td-cluster-block"
                  @mouseenter="hoveredGeneCluster = { cluster: c, rowId, variant: getClusterVariantInfo(c, rowId) }"
                  @mouseleave="hoveredGeneCluster = null"
                  @click="openClusterDrawer(c)"
                >
                  <div 
                    v-if="c.presence_map?.[rowId]"
                    class="gene-present-square"
                    :class="getClusterVariantInfo(c, rowId).className"
                    :style="getClusterVariantInfo(c, rowId).style"
                    :title="getClusterVariantInfo(c, rowId).title"
                  ></div>
                  <div v-else class="gene-absent-dot" title="该样本缺失此 CDS"></div>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 悬停基因家族信息提示条 (固定高度状态栏，杜绝任何页面高度跳变抖动) -->
      <div class="cluster-hover-info-strip" :class="{ active: !!hoveredGeneCluster }">
        <template v-if="hoveredGeneCluster">
          <span class="chip-cat" :style="{ backgroundColor: getCatColor(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }">
            {{ hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category }}
          </span>
          <strong>{{ hoveredGeneCluster.cluster?.group_id }}</strong>:
          <span class="strip-prod-txt">{{ hoveredGeneCluster.cluster?.representative_product }}</span>
          <span class="hover-sample-tag">【{{ sampleNames[hoveredGeneCluster.rowId] || hoveredGeneCluster.rowId }}】: <strong>{{ hoveredGeneCluster.variant?.variantLabel }}</strong></span>
          <span class="text-slate"> (共享率: {{ hoveredGeneCluster.cluster?.sample_count }}/{{ orderedSampleIds.length }} 样本 · 点击展开全株比对)</span>
        </template>
        <template v-else>
          <span class="strip-placeholder-txt">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px; vertical-align: middle;">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            将鼠标悬停在右侧任意同源基因方块上，可在此实时预览详细功能注释与微观变异类型；点击方块可展开跨株全景比对抽屉。
          </span>
        </template>
      </div>

      <!-- CDS 详细属性卡片模态 (点击查看各样本具体 CDS 基因座、起止坐标、氨基酸变异类型标注) -->
      <div class="cds-detail-drawer-card" v-if="selectedGeneCluster">
        <div class="drawer-head">
          <div class="dh-left">
            <span class="chip-cat" :style="{ backgroundColor: getCatColor(selectedGeneCluster._inferredCategory || selectedGeneCluster.category) }">
              {{ selectedGeneCluster._inferredCategory || selectedGeneCluster.category }}
            </span>
            <strong>{{ selectedGeneCluster.group_id }}</strong>
            <span class="dh-prod">{{ selectedGeneCluster.representative_product }}</span>
            <span class="dh-count">群体共享率: {{ selectedGeneCluster.sample_count }}/{{ orderedSampleIds.length }} 样本</span>
          </div>
          <div class="dh-right">
            <div class="baseline-selector">
              <span class="bl-lbl">变异对照基准株:</span>
              <select v-model="selectedBaselineSampleId" class="baseline-select">
                <option 
                  v-for="sid in visibleSampleIds" 
                  :key="'opt-bl-' + sid"
                  :value="sid"
                >
                  {{ sampleNames[sid] || sid }} {{ selectedGeneCluster.presence_map?.[sid] ? `(${selectedGeneCluster.presence_map[sid].length_aa} aa)` : '(缺失)' }}
                </option>
              </select>
            </div>
            <button class="btn-close-drawer" @click="selectedGeneCluster = null">关闭</button>
          </div>
        </div>
        <div class="drawer-samples-table-wrap">
          <table class="drawer-samples-table">
            <thead>
              <tr>
                <th>样本名称</th>
                <th>存在状态</th>
                <th>氨基酸变异类型 (相较于基准株)</th>
                <th>CDS Locus Tag</th>
                <th>基因组起止位置 (物理坐标)</th>
                <th>链方向</th>
                <th>氨基酸长度 (aa)</th>
                <th>功能产物描述 (Product)</th>
              </tr>
            </thead>
            <tbody>
              <tr 
                v-for="sid in visibleSampleIds" 
                :key="'drawer-s-' + sid"
                :class="{ 
                  'row-baseline-highlight': sid === selectedBaselineSampleId,
                  'row-present': !!selectedGeneCluster.presence_map?.[sid], 
                  'row-absent': !selectedGeneCluster.presence_map?.[sid] 
                }"
              >
                <td>
                  <strong>{{ sampleNames[sid] || sid }}</strong>
                  <span v-if="sid === selectedBaselineSampleId" class="badge-ref-tag">基准</span>
                </td>
                <td>
                  <span class="status-pill status-present" v-if="selectedGeneCluster.presence_map?.[sid]">存在 (Present)</span>
                  <span class="status-pill status-absent" v-else>缺失 (Absent)</span>
                </td>
                <td>
                  <div class="variation-cell">
                    <span 
                      class="var-badge" 
                      :class="getAminoAcidVariation(selectedGeneCluster, sid, selectedBaselineSampleId).badgeClass"
                    >
                      {{ getAminoAcidVariation(selectedGeneCluster, sid, selectedBaselineSampleId).badgeText }}
                    </span>
                    <span class="var-desc-text">
                      {{ getAminoAcidVariation(selectedGeneCluster, sid, selectedBaselineSampleId).diffDetail }}
                    </span>
                  </div>
                </td>
                <td>
                  <code>{{ selectedGeneCluster.presence_map?.[sid]?.locus_tag || '—' }}</code>
                </td>
                <td>
                  <span v-if="selectedGeneCluster.presence_map?.[sid]">
                    {{ selectedGeneCluster.presence_map[sid].start }} .. {{ selectedGeneCluster.presence_map[sid].end }} bp
                  </span>
                  <span v-else class="text-slate">—</span>
                </td>
                <td>
                  <code>{{ selectedGeneCluster.presence_map?.[sid]?.strand || '—' }}</code>
                </td>
                <td>
                  <span v-if="selectedGeneCluster.presence_map?.[sid]" class="font-mono-val">
                    {{ selectedGeneCluster.presence_map[sid].length_aa }} aa
                  </span>
                  <span v-else class="text-slate">—</span>
                </td>
                <td class="td-prod-text" :title="selectedGeneCluster.presence_map?.[sid]?.product">
                  {{ selectedGeneCluster.presence_map?.[sid]?.product || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workspace-population-landscape {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 顶部概览指标与折叠条 */
/* 样本可见性与聚焦控制工具条 */
.sample-visibility-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 8px;
  position: relative;
}

.sample-count-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1px 8px;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
}

.sample-count-pill.has-hidden {
  border-color: #fcd34d;
  background: #fffbeb;
}

.hidden-badge {
  background: #fef3c7;
  color: #b45309;
  font-size: 9px;
  font-weight: 700;
  padding: 0 4px;
  border-radius: 3px;
  border: 1px solid #fde68a;
}

.sample-filter-btn-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-sample-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  padding: 2px 7px;
  cursor: pointer;
  transition: all 0.15s ease;
  line-height: 1.2;
}

.btn-sample-action:hover {
  background: #e2e8f0;
  color: #0f172a;
  border-color: #94a3b8;
}

.btn-show-all {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.btn-show-all:hover {
  background: #dbeafe;
}

.btn-focus-pair {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #15803d;
}

.btn-focus-pair:hover {
  background: #dcfce7;
}

.sample-dropdown-wrapper {
  position: relative;
}

.btn-filter-dropdown.active {
  background: #2563eb;
  color: #ffffff;
  border-color: #1d4ed8;
}

.sample-dropdown-panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 50;
  width: 260px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sd-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sd-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  outline: none;
}

.sd-search-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.sd-quick-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.btn-sd-quick {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font-size: 9.5px;
  font-weight: 600;
  color: #475569;
  padding: 1px 6px;
  cursor: pointer;
}

.btn-sd-quick:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.btn-sd-close {
  background: transparent;
  border: none;
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

.btn-sd-close:hover {
  color: #dc2626;
}

.sd-sample-list {
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sd-sample-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 10.5px;
  cursor: pointer;
  transition: background 0.1s ease;
}

.sd-sample-item:hover {
  background: #f1f5f9;
}

.sd-sample-item input[type="checkbox"] {
  margin: 0;
  cursor: pointer;
}

.sd-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #334155;
}

.sd-sample-item.active .sd-name {
  color: #0f172a;
  font-weight: 600;
}

.btn-sd-only {
  background: transparent;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font-size: 8.5px;
  color: #64748b;
  padding: 0 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.sd-sample-item:hover .btn-sd-only {
  opacity: 1;
}

.btn-sd-only:hover {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
}

/* 样本单元格内小眼睛切换按钮 */
.sample-name-cell-inner {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
}

.btn-sample-eye {
  background: transparent;
  border: none;
  padding: 2px;
  margin: 0;
  cursor: pointer;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.btn-sample-eye:hover {
  color: #dc2626;
  background: #fee2e2;
}

.sample-title-txt {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.sample-title-txt:hover {
  color: #2563eb;
}

/* 旗舰组合面板 */
.academic-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 1. 顶层主标题与全局视图控制带 */
.panel-header-deck {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 8px;
}

.deck-title-area {
  display: flex;
  align-items: center;
}

.title-main-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-tag-pill {
  background: #0f172a;
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}

.panel-heading-text {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.matrix-scope-badge {
  background: #eff6ff;
  color: #2563eb;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid #dbeafe;
}

.deck-actions-area {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.control-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-right: 4px;
}

/* 分段选择器 (Segmented Control) */
.segmented-density-control {
  display: flex;
  align-items: center;
}

.seg-pills {
  display: flex;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 6px;
  gap: 2px;
}

.seg-btn {
  background: transparent;
  border: none;
  font-size: 10.5px;
  font-weight: 600;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.seg-btn:hover {
  color: #0f172a;
}

.seg-btn.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.seg-btn.btn-ultra.active {
  color: #d97706;
}

.modern-select {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  font-size: 10.5px;
  font-weight: 600;
  padding: 3px 8px;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
}

.modern-select:hover {
  border-color: #94a3b8;
  background: #ffffff;
}

.modern-select.select-cat {
  max-width: 170px;
}

.btn-legend-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  font-size: 10.5px;
  font-weight: 600;
  color: #475569;
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-legend-toggle:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.btn-legend-toggle.active {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

/* 2. 统一操作带 (Unified Tool Ribbon) */
.matrix-ribbon-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 10px;
  flex-wrap: wrap;
}

.ribbon-left-filters,
.ribbon-right-tracks {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ribbon-group-label {
  font-size: 10.5px;
  font-weight: 700;
  color: #475569;
  white-space: nowrap;
}

.ribbon-pills {
  display: flex;
  gap: 3px;
  background: #e2e8f0;
  padding: 2px;
  border-radius: 5px;
}

.r-pill {
  background: transparent;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.r-pill:hover {
  color: #0f172a;
}

.r-pill.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.r-pill-amber.active {
  color: #d97706;
}

.r-pill-blue.active {
  color: #2563eb;
}

.filter-divider {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
}

/* 轨道开关 */
.track-check-pills {
  display: flex;
  gap: 4px;
}

.trk-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 2px 7px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.trk-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.trk-pill:hover {
  border-color: #94a3b8;
  color: #0f172a;
}

.trk-pill.active {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 700;
}

.trk-pill.active .trk-dot {
  background: #2563eb;
}

/* 3. 精炼学术图注条 (Academic Legend Deck) */
.academic-legend-deck {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 12px;
  flex-wrap: wrap;
}

.leg-col {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.leg-col-title {
  font-size: 10.5px;
  font-weight: 700;
  color: #475569;
  white-space: nowrap;
}

.leg-items-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.leg-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #334155;
  white-space: nowrap;
}

.leg-chip i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  font-style: normal;
}

.ani-heat-swatch-list {
  display: flex;
  align-items: center;
  gap: 2px;
}

.heat-chip {
  font-size: 8.5px;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 2px;
}

.swatch-sq {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 1.5px;
}

.swatch-dot {
  display: inline-block;
  width: 4px;
  height: 4px;
  border-radius: 50%;
}

/* 一体化画板表格与吸顶/冻结列 (内容超长时自然内部滚动) */
.phylogenomic-composite-canvas {
  max-height: 70vh;
  overflow-x: auto;
  overflow-y: auto;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  position: relative;
}

.composite-evidence-table {
  border-collapse: collapse;
  width: 100%;
}

.composite-evidence-table thead th {
  position: sticky;
  top: 0;
  z-index: 20;
  background: #f8fafc;
  padding: 6px 4px;
  font-size: 10px;
  color: #64748b;
  border-bottom: 1.5px solid #cbd5e1;
  vertical-align: bottom;
}

/* 冻结列 (Sticky Left Columns) */
.th-sticky-left-1 {
  position: sticky;
  left: 0;
  z-index: 25;
  background: #f8fafc !important;
}

.td-tree-col.th-sticky-left-1 {
  position: sticky;
  left: 0;
  z-index: 15;
  background: #ffffff !important;
}

.th-sticky-left-2 {
  position: sticky;
  left: 44px;
  z-index: 25;
  background: #f8fafc !important;
  box-shadow: 2px 0 4px rgba(0, 0, 0, 0.05);
}

.td-sample-name-col.th-sticky-left-2 {
  position: sticky;
  left: 44px;
  z-index: 15;
  background: #ffffff !important;
  box-shadow: 2px 0 4px rgba(0, 0, 0, 0.05);
}

.td-sample-name-col.th-sticky-left-1 {
  position: sticky;
  left: 0;
  z-index: 15;
  background: #ffffff !important;
  box-shadow: 2px 0 4px rgba(0, 0, 0, 0.05);
}

.th-tree {
  width: 44px;
  min-width: 44px;
  max-width: 44px;
  text-align: center;
}

.th-sample-name {
  width: 160px;
  min-width: 160px;
  text-align: left;
}

.th-meta {
  width: 46px;
  min-width: 46px;
  text-align: center;
  font-size: 9px;
  font-weight: 700;
}

.th-ani-col {
  width: 32px;
  min-width: 32px;
  max-width: 32px;
  text-align: center;
  padding: 4px 1px;
}

.th-rot-label {
  font-size: 8px;
  font-weight: 700;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 32px;
}

.th-active-pair .th-rot-label {
  color: #2563eb;
}

.th-genefamily-title {
  text-align: left;
  border-left: 2px solid #e2e8f0;
  padding-left: 10px;
}

.gene-matrix-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  font-weight: 700;
  color: #0f172a;
}

.gene-matrix-title-txt {
  white-space: nowrap;
  font-weight: 700;
}

/* 表体单元格与行高规范 (默认 Comfortable 舒适 24px) */
.composite-row {
  border-bottom: 1px solid #f1f5f9;
  height: 24px;
  min-height: 24px;
  max-height: 24px;
  box-sizing: border-box;
}

.composite-row:hover {
  background: #f8fafc;
}

.row-pair-selected {
  background: #eff6ff;
}

.td-tree-col {
  width: 44px;
  min-width: 44px;
  max-width: 44px;
  text-align: center;
  vertical-align: top;
  padding: 0;
  margin: 0;
  position: relative;
  box-sizing: border-box;
  height: 100%;
}

.tree-absolute-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.tree-composite-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.td-sample-name-col {
  width: 160px;
  min-width: 160px;
  font-size: 10.5px;
  color: #334155;
  padding: 0 6px;
  height: 24px;
  line-height: 24px;
  box-sizing: border-box;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  vertical-align: middle;
}

.td-meta-col {
  width: 46px;
  text-align: center;
  padding: 0 2px;
  height: 24px;
  box-sizing: border-box;
  vertical-align: middle;
}

.meta-badge {
  font-size: 7.5px;
  font-weight: 800;
  color: #ffffff;
  padding: 1px 3.5px;
  border-radius: 2px;
  line-height: 1;
}

.bg-lytic { background: #10b981; }
.bg-safe { background: #0284c7; }

.td-ani-val-cell {
  width: 32px;
  min-width: 32px;
  max-width: 32px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  vertical-align: middle;
  font-size: 8px;
  font-weight: 700;
  border: 0.5px solid #ffffff;
  padding: 0;
  box-sizing: border-box;
  cursor: pointer;
  transition: transform 0.1s ease;
}

.td-ani-val-cell:hover {
  outline: 1.5px solid #1d4ed8;
  outline-offset: -1px;
  z-index: 5;
  filter: brightness(1.08);
}

.cell-pair-highlight {
  outline: 2px solid #ef4444;
  outline-offset: -1px;
  z-index: 4;
}

/* 基因方块 (默认舒适 16px 高) */
.td-cluster-block {
  width: 4px;
  min-width: 4px;
  max-width: 5px;
  height: 24px;
  padding: 0;
  box-sizing: border-box;
  text-align: center;
  vertical-align: middle;
  border-left: 0.5px solid #f8fafc;
}

.gene-present-square {
  width: 3.5px;
  height: 16px;
  border-radius: 1px;
  margin: 0 auto;
  cursor: pointer;
  box-sizing: border-box;
  transition: filter 0.1s ease, box-shadow 0.1s ease;
}

/* 1. 等长保守：饱满纯色实心色块 */
.gene-present-square.sq-conserved {
  height: 16px;
  border-radius: 1px;
  opacity: 1.0;
}

/* 2. 缺失截短变异 */
.gene-present-square.sq-truncated {
  height: 16px;
  border-radius: 1px;
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.6) 0,
    rgba(255, 255, 255, 0.6) 1.5px,
    transparent 1.5px,
    transparent 3.5px
  ) !important;
  box-shadow: inset 0 0 0 0.5px rgba(255, 255, 255, 0.8);
}

/* 3. 插入延长变异 */
.gene-present-square.sq-extended {
  height: 16px;
  border-radius: 1px;
  border-top: 2px solid #0f172a !important;
  border-bottom: 2px solid #0f172a !important;
  box-shadow: 0 0 0 0.5px #0f172a;
}

.gene-present-square:hover {
  outline: 1.5px solid #0f172a;
  outline-offset: 0.5px;
  filter: brightness(1.15);
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.35);
  z-index: 10;
}

.gene-absent-dot {
  width: 1.2px;
  height: 1.2px;
  border-radius: 50%;
  background: #cbd5e1;
  margin: 0 auto;
}

/* =========================================================
   宽松模式专属规则 (.density-spacious: 行高 36px, 适合 2~12 株小样本)
   ========================================================= */
.density-spacious .composite-row {
  height: 36px;
  min-height: 36px;
  max-height: 36px;
}

.density-spacious .td-sample-name-col {
  height: 36px;
  line-height: 36px;
  font-size: 11.5px;
  padding: 0 8px;
}

.density-spacious .td-meta-col {
  height: 36px;
  font-size: 9.5px;
}

.density-spacious .meta-badge {
  font-size: 8.5px;
  padding: 2px 5px;
  border-radius: 3px;
}

.density-spacious .th-ani-col {
  width: 38px;
  min-width: 38px;
  max-width: 38px;
}

.density-spacious .th-rot-label {
  max-width: 38px;
  font-size: 9px;
}

.density-spacious .td-ani-val-cell {
  width: 38px;
  min-width: 38px;
  max-width: 38px;
  height: 36px;
  line-height: 36px;
  font-size: 9.5px;
}

.density-spacious .td-cluster-block {
  height: 36px;
  width: 6px;
  min-width: 6px;
  max-width: 7px;
}

.density-spacious .gene-present-square {
  width: 5px;
  height: 24px;
  border-radius: 2px;
}

.density-spacious .gene-present-square.sq-conserved,
.density-spacious .gene-present-square.sq-truncated,
.density-spacious .gene-present-square.sq-extended {
  height: 24px;
}

.density-spacious .gene-present-square.sq-extended {
  border-top-width: 2.5px !important;
  border-bottom-width: 2.5px !important;
}

.density-spacious .gene-absent-dot {
  width: 2px;
  height: 2px;
}

/* =========================================================
   紧凑模式专属规则 (.density-compact: 行高 17px)
   ========================================================= */
.density-compact .composite-row {
  height: 17px;
  min-height: 17px;
  max-height: 17px;
}

.density-compact .td-sample-name-col {
  height: 17px;
  line-height: 17px;
  font-size: 9px;
}

.density-compact .td-meta-col {
  height: 17px;
}

.density-compact .td-ani-val-cell {
  height: 17px;
  line-height: 17px;
  font-size: 7px;
}

.density-compact .td-cluster-block {
  height: 17px;
  width: 3px;
  min-width: 3px;
  max-width: 4px;
}

.density-compact .gene-present-square {
  width: 2.5px;
  height: 12px;
}

.density-compact .gene-present-square.sq-conserved,
.density-compact .gene-present-square.sq-truncated,
.density-compact .gene-present-square.sq-extended {
  height: 12px;
}

/* =========================================================
   全景模式专属规则 (.density-ultra: 行高 11px)
   ========================================================= */
.density-ultra .composite-row {
  height: 11px;
  min-height: 11px;
  max-height: 11px;
}

.density-ultra .td-sample-name-col {
  height: 11px;
  line-height: 11px;
  font-size: 7.5px;
  padding: 0 2px;
}

.density-ultra .td-ani-val-cell {
  width: 14px;
  min-width: 14px;
  max-width: 14px;
  height: 11px;
  line-height: 11px;
}

.density-ultra .th-ani-col {
  width: 14px;
  min-width: 14px;
  max-width: 14px;
}

.density-ultra .td-cluster-block {
  height: 11px;
  width: 2px;
  min-width: 2px;
  max-width: 2px;
}

.density-ultra .gene-present-square {
  width: 1.8px;
  height: 8px;
  border-radius: 0;
}

/* 图注栏中的变异形态样本方块 (高度统一 10px) */
.sq-legend-conserved {
  background-color: #059669;
  height: 10px;
}

.sq-legend-truncated {
  background-color: #059669;
  height: 10px;
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.6) 0,
    rgba(255, 255, 255, 0.6) 1.5px,
    transparent 1.5px,
    transparent 3.5px
  );
}

.sq-legend-extended {
  background-color: #059669;
  height: 10px;
  border-top: 2px solid #0f172a;
  border-bottom: 2px solid #0f172a;
}

.hover-sample-tag {
  color: #1e3a8a;
}

/* 悬停基因家族信息提示条 (固定高度 32px，零布局位移) */
.cluster-hover-info-strip {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0 12px;
  height: 32px;
  min-height: 32px;
  max-height: 32px;
  box-sizing: border-box;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background-color 0.15s ease, border-color 0.15s ease;
  overflow: hidden;
  white-space: nowrap;
}

.cluster-hover-info-strip.active {
  background: #ffffff;
  border-color: #93c5fd;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.08);
}

.strip-placeholder-txt {
  color: #94a3b8;
  font-size: 10.5px;
}

.strip-prod-txt {
  color: #0f172a;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chip-cat {
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
}

/* CDS 详细抽屉卡片 */
.cds-detail-drawer-card {
  background: #ffffff;
  border: 1.5px solid #2563eb;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.15);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 8px;
}

.dh-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.dh-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.baseline-selector {
  display: flex;
  align-items: center;
  gap: 6px;
}

.bl-lbl {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.baseline-select {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
}

.badge-ref-tag {
  background: #1e40af;
  color: #ffffff;
  font-size: 8px;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 2px;
  margin-left: 4px;
}

.row-baseline-highlight {
  background: #f8faff;
  font-weight: 600;
}

.variation-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.var-badge {
  display: inline-block;
  width: fit-content;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
}

.var-conserved {
  background: #dcfce7;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.var-truncated {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
}

.var-extended {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.var-absent {
  background: #f1f5f9;
  color: #94a3b8;
  border: 1px solid #e2e8f0;
}

.var-present {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.var-desc-text {
  font-size: 10px;
  color: #64748b;
}

.font-mono-val {
  font-family: monospace;
  font-weight: 700;
  color: #0f172a;
}

.dh-prod {
  color: #1e3a8a;
  font-weight: 700;
}

.dh-count {
  font-size: 10px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-close-drawer {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
  font-size: 10px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-close-drawer:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
}

.drawer-samples-table-wrap {
  overflow-x: auto;
}

.drawer-samples-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.drawer-samples-table th {
  background: #f8fafc;
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
  font-size: 10px;
  color: #64748b;
}

.drawer-samples-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
}

.row-present {
  background: #ffffff;
}

.row-absent {
  background: #fafafa;
  opacity: 0.7;
}

.status-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.status-present {
  background: #dcfce7;
  color: #166534;
}

.status-absent {
  background: #f1f5f9;
  color: #94a3b8;
}

.drawer-samples-table code {
  font-family: monospace;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 10px;
  color: #0f172a;
}

.td-prod-text {
  color: #334155;
  max-width: 250px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 紧凑模式 (Compact 15~35株) */
.density-compact .composite-row {
  height: 17px;
  min-height: 17px;
  max-height: 17px;
}

.density-compact .th-sample-name,
.density-compact .td-sample-name-col {
  width: 125px;
  min-width: 125px;
  max-width: 125px;
  font-size: 9.5px;
  height: 17px;
  line-height: 17px;
}

.density-compact .td-meta-col {
  height: 17px;
}

.density-compact .td-ani-val-cell {
  width: 24px;
  min-width: 24px;
  max-width: 24px;
  height: 17px;
  line-height: 17px;
  font-size: 7.5px;
}

.density-compact .th-ani-col {
  width: 24px;
  min-width: 24px;
  max-width: 24px;
}

.density-compact .td-cluster-block {
  height: 17px;
}

.density-compact .gene-present-square {
  height: 12px;
}

/* 超大规模全景微缩模式 (Ultra-Scale 35~100+株) */
.density-ultra .composite-row {
  height: 11px;
  min-height: 11px;
  max-height: 11px;
}

.density-ultra .th-sample-name,
.density-ultra .td-sample-name-col {
  width: 95px;
  min-width: 95px;
  max-width: 95px;
  font-size: 8px;
  height: 11px;
  line-height: 11px;
}

.density-ultra .th-sticky-left-2 {
  left: 36px;
}

.density-ultra .th-tree,
.density-ultra .td-tree-col {
  width: 36px;
  min-width: 36px;
  max-width: 36px;
}

.density-ultra .td-meta-col {
  height: 11px;
}

.density-ultra .td-ani-val-cell {
  width: 14px;
  min-width: 14px;
  max-width: 14px;
  height: 11px;
  line-height: 11px;
  font-size: 0;
  border-width: 0.2px;
}

.density-ultra .th-ani-col {
  width: 14px;
  min-width: 14px;
  max-width: 14px;
}

.density-ultra .th-rot-label {
  display: none;
}

.density-ultra .td-cluster-block {
  width: 3px;
  min-width: 3px;
  height: 11px;
}

.density-ultra .gene-present-square {
  width: 2.5px;
  height: 8px;
  border-radius: 0;
}

.density-ultra .meta-badge {
  font-size: 6px;
  padding: 0 2px;
}
</style>
