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
const isSummaryCollapsed = ref(false)
const isLegendCollapsed = ref(false)

const isPhylogenyTrackVisible = ref(true)
const isMetadataTrackVisible = ref(true)
const isAniTrackVisible = ref(true)
const isGeneMatrixTrackVisible = ref(true)

// 密度模式 (Comfortable / Compact / Ultra-Scale 50+) 与视口自适应
const displayDensity = ref<'comfortable' | 'compact' | 'ultra'>('comfortable')
const viewportMaxHeight = ref<'620px' | '860px' | 'none'>('620px')

function openClusterDrawer(c: any) {
  selectedGeneCluster.value = c
  // 默认选取当前分析对的第1株，或该基因存在的第1株作为对照基准
  if (props.selectedPair?.[0] && c.presence_map?.[props.selectedPair[0]]) {
    selectedBaselineSampleId.value = props.selectedPair[0]
  } else {
    const firstPresent = orderedSampleIds.value.find((sid: string) => !!c.presence_map?.[sid])
    selectedBaselineSampleId.value = firstPresent || orderedSampleIds.value[0] || ''
  }
}

// 1. 聚类排序后的样本 ID 列表 (基于系统发育树)
const orderedSampleIds = computed<string[]>(() => {
  if (props.aniClustering?.ordered_ids?.length) {
    return props.aniClustering.ordered_ids
  }
  return Object.keys(props.sampleNames || {})
})

// 1.1 动态系统发育树几何拓扑 (归一化高精度坐标体系，与表格行高 100% 绝对物理对齐)
const rowHeight = computed(() => {
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
  const ids = orderedSampleIds.value
  const n = ids.length
  const currentHeight = rowHeight.value // 24 / 17 / 11

  if (n === 0) return { width: 44, height: currentHeight, branches: [] as TreeBranch[], tips: [] as TreeTip[] }

  const totalHeight = n * currentHeight
  const baseRadius = displayDensity.value === 'ultra' ? 1.5 : (displayDensity.value === 'compact' ? 2.0 : 2.5)

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

// 2. 宏观群体统计
const populationStats = computed(() => {
  const ids = orderedSampleIds.value
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
  'Tail': 1,
  'Lysis': 2,
  'Defense & Host Interaction': 3,
  'Packaging': 4,
  'Structural': 5,
  'Replication & Repair': 6,
  'Metabolism & AMG': 7,
  'Hypothetical': 8
}

// 智能生物学分类推断器 (保证尾丝与受体结合蛋白 100% 归类)
function inferClusterCategory(c: any): string {
  if (!c) return 'Hypothetical'
  const rawCat = c.category || ''
  const prod = (c.representative_product || '').toLowerCase()
  
  if (rawCat === 'Tail' || /tail|baseplate|fiber|spike|receptor|adhesin|sheath|collar/i.test(prod)) {
    return 'Tail'
  }
  if (rawCat === 'Lysis' || /lysin|endolysin|holin|spanin|lysozyme|amidase|murein/i.test(prod)) {
    return 'Lysis'
  }
  if (rawCat === 'Defense & Host Interaction' || rawCat === 'Defense' || /anti-crispr|acr|cas\d+|restriction|modification|toxin|defense/i.test(prod)) {
    return 'Defense & Host Interaction'
  }
  if (rawCat === 'Packaging' || /terminase|portal|packaging|maturase/i.test(prod)) {
    return 'Packaging'
  }
  if (rawCat === 'Structural' || /capsid|head|neck|virion|structural/i.test(prod)) {
    return 'Structural'
  }
  if (rawCat === 'Replication & Repair' || /polymerase|helicase|primase|ligase|recombinase|dnase|rnase|resolvase|gyrase/i.test(prod)) {
    return 'Replication & Repair'
  }
  if (rawCat === 'Metabolism & AMG' || /synthase|reductase|kinase|transferase|dehydrogenase/i.test(prod)) {
    return 'Metabolism & AMG'
  }
  if (rawCat && rawCat !== 'Hypothetical' && rawCat !== 'Other Functional') {
    return rawCat
  }
  return 'Hypothetical'
}

function getCatColor(cat: string): string {
  const map: Record<string, string> = {
    'Tail': '#f59e0b',
    'Lysis': '#059669',
    'Defense & Host Interaction': '#dc2626',
    'Packaging': '#7c3aed',
    'Structural': '#2563eb',
    'Replication & Repair': '#d97706',
    'Metabolism & AMG': '#0891b2',
    'Hypothetical': '#94a3b8'
  }
  return map[cat] || '#94a3b8'
}

const sortedGeneClusters = computed(() => {
  if (!props.clusters || props.clusters.length === 0) return []
  const n = orderedSampleIds.value.length
  
  let list = props.clusters.map(c => ({
    ...c,
    _inferredCategory: inferClusterCategory(c)
  }))

  // 1. 功能分类过滤
  if (geneCategoryFilter.value !== 'ALL') {
    list = list.filter(c => c._inferredCategory === geneCategoryFilter.value)
  }

  // 2. 泛基因组分区/差异过滤
  if (genePartitionFilter.value === 'VARIABLE') {
    // 仅显示在各样本间存在差异的 CDS (非 100% 共享)
    list = list.filter(c => Number(c.sample_count || 0) < n)
  } else if (genePartitionFilter.value === 'CORE') {
    // 仅显示全样本共有的核心 CDS
    list = list.filter(c => Number(c.sample_count || 0) === n)
  } else if (genePartitionFilter.value === 'UNIQUE') {
    // 仅显示单株特有的独有 CDS
    list = list.filter(c => Number(c.sample_count || 0) === 1)
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

// 泛基因组宏观占比
const pangenomePartition = computed(() => {
  if (!props.clusters) return { core: 0, accessory: 0, total: 0 }
  const total = props.clusters.length
  const n = orderedSampleIds.value.length
  let core = 0
  let accessory = 0
  props.clusters.forEach(c => {
    if (Number(c.sample_count) === n) core++
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
    <!-- 顶部宏观统计横幅 (支持收起/展开) -->
    <div class="population-summary-panel">
      <div class="summary-toggle-bar">
        <div class="st-left">
          <span class="st-tag">Overview</span>
          <span class="st-title">宏观群体组学概览指标</span>
        </div>
        <button 
          class="btn-section-toggle" 
          @click="isSummaryCollapsed = !isSummaryCollapsed"
          :title="isSummaryCollapsed ? '展开统计指标卡' : '收起统计指标卡'"
        >
          {{ isSummaryCollapsed ? '展开指标' : '收起指标' }}
        </button>
      </div>

      <div class="population-summary-bar" v-show="!isSummaryCollapsed">
        <div class="summary-stat-box">
          <span class="stat-label">群体规模 (Cohort Size)</span>
          <span class="stat-val">{{ populationStats.n }} <small>株噬菌体</small></span>
          <span class="stat-sub text-green">全部专性烈性 · 100% 治疗安全</span>
        </div>
        <div class="summary-stat-box">
          <span class="stat-label">全基因组 ANI 相似度区间</span>
          <span class="stat-val">{{ populationStats.minAni }}% ~ {{ populationStats.maxAni }}%</span>
          <span class="stat-sub">群体平均 ANI: <strong>{{ populationStats.avgAni }}%</strong></span>
        </div>
        <div class="summary-stat-box">
          <span class="stat-label">泛基因组核心保守率</span>
          <span class="stat-val text-blue">{{ pangenomePartition.corePct }}% <small>Core</small></span>
          <span class="stat-sub">Core: {{ pangenomePartition.core }} | Accessory: {{ pangenomePartition.accessory }}</span>
        </div>
      </div>
    </div>

    <!-- 顶刊旗舰组合图: Phylogenomic Evidence Matrix -->
    <div class="academic-panel flagship-matrix-panel">
      <div class="panel-header flex-header-wrap">
        <div class="title-with-tag">
          <span class="panel-tag">Figure 1 Flagship</span>
          <h3>系统发育 × 元数据 × 全基因组 ANI × 基因内容全序矩阵 (Phylogenomic Evidence Matrix)</h3>
        </div>

        <!-- 组合图交互工具栏 (轨道开关 + 密度模式 + 视口限高 + 分区过滤) -->
        <div class="matrix-comprehensive-toolbar">
          <!-- 1. 轨道显隐切换开关组 (Track Toggles) -->
          <div class="track-toggle-capsule-group">
            <span class="toolbar-sublabel">轨道显隐:</span>
            <button 
              class="btn-track-pill" 
              :class="{ active: isPhylogenyTrackVisible }" 
              @click="isPhylogenyTrackVisible = !isPhylogenyTrackVisible"
              title="显示/隐藏系统发育树轨道"
            >
              进化树
            </button>
            <button 
              class="btn-track-pill" 
              :class="{ active: isMetadataTrackVisible }" 
              @click="isMetadataTrackVisible = !isMetadataTrackVisible"
              title="显示/隐藏元数据 (Lifestyle / Safety / Acr) 轨道"
            >
              元数据
            </button>
            <button 
              class="btn-track-pill" 
              :class="{ active: isAniTrackVisible }" 
              @click="isAniTrackVisible = !isAniTrackVisible"
              title="显示/隐藏全基因组 ANI 相似度矩阵"
            >
              ANI 矩阵
            </button>
            <button 
              class="btn-track-pill" 
              :class="{ active: isGeneMatrixTrackVisible }" 
              @click="isGeneMatrixTrackVisible = !isGeneMatrixTrackVisible"
              title="显示/隐藏泛基因组正交家族矩阵"
            >
              基因全序
            </button>
          </div>

          <!-- 2. 超大规模自适应密度切换 (Comfort / Compact / Ultra-Scale 50+) -->
          <div class="density-switch-group">
            <span class="toolbar-sublabel">显示密度:</span>
            <button 
              class="btn-density-opt" 
              :class="{ active: displayDensity === 'comfortable' }" 
              @click="displayDensity = 'comfortable'"
              title="标准舒适模式 (行高 24px，适合 2~15 株)"
            >
              舒适
            </button>
            <button 
              class="btn-density-opt" 
              :class="{ active: displayDensity === 'compact' }" 
              @click="displayDensity = 'compact'"
              title="紧凑模式 (行高 17px，适合 15~35 株)"
            >
              紧凑
            </button>
            <button 
              class="btn-density-opt btn-density-ultra" 
              :class="{ active: displayDensity === 'ultra' }" 
              @click="displayDensity = 'ultra'"
              title="超大规模全景微缩模式 (行高 11px，适合 35~100+ 株大规模比对)"
            >
              50+ 全景
            </button>
          </div>

          <!-- 3. 视口自适应限高选择器 -->
          <div class="viewport-height-group">
            <span class="toolbar-sublabel">视口限高:</span>
            <select v-model="viewportMaxHeight" class="compact-select">
              <option value="620px">标准限高 (620px 内部滚动)</option>
              <option value="860px">高画板 (860px)</option>
              <option value="none">完全平铺 (无滚动限制)</option>
            </select>
          </div>

          <!-- 4. 图注展开/折叠按钮 -->
          <button 
            class="btn-legend-collapse-opt"
            :class="{ active: !isLegendCollapsed }"
            @click="isLegendCollapsed = !isLegendCollapsed"
            :title="isLegendCollapsed ? '展开上方常驻图注栏' : '收起图注栏以腾出更多矩阵画板空间'"
          >
            {{ isLegendCollapsed ? '展开图注' : '收起图注' }}
          </button>
        </div>
      </div>

      <!-- 差异/分区模式与功能分类过滤条 -->
      <div class="matrix-filter-controls-bar">
        <div class="partition-filter-pills">
          <button 
            class="btn-pill-opt" 
            :class="{ active: genePartitionFilter === 'ALL' }"
            @click="genePartitionFilter = 'ALL'"
          >
            全部 CDS ({{ clusters?.length || 0 }})
          </button>
          <button 
            class="btn-pill-opt text-amber-pill" 
            :class="{ active: genePartitionFilter === 'VARIABLE' }"
            @click="genePartitionFilter = 'VARIABLE'"
            title="仅显示存在样本缺失或分化的差异 CDS 家族"
          >
            仅看差异 CDS ({{ (clusters?.length || 0) - Number(pangenomePartition.core) }})
          </button>
          <button 
            class="btn-pill-opt text-blue-pill" 
            :class="{ active: genePartitionFilter === 'CORE' }"
            @click="genePartitionFilter = 'CORE'"
            title="仅显示全群体 100% 共享的核心 CDS 家族"
          >
            核心 CDS ({{ pangenomePartition.core }})
          </button>
          <button 
            class="btn-pill-opt" 
            :class="{ active: genePartitionFilter === 'UNIQUE' }"
            @click="genePartitionFilter = 'UNIQUE'"
            title="仅显示仅在单一株系中出现的特有 CDS"
          >
            单株特有
          </button>
        </div>

        <div class="cat-filter-wrap">
          <span class="filter-lbl">功能分类:</span>
          <select v-model="geneCategoryFilter" class="compact-cat-select">
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

      <!-- 全局常驻图注卡片栏 (可一键收起/展开) -->
      <div class="global-matrix-legend-card" v-show="!isLegendCollapsed">
        <div class="legend-section-row">
          <div class="legend-subgroup">
            <span class="legend-subgroup-title">CDS 功能模块分类:</span>
            <div class="legend-pills-list">
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #f59e0b;"></span> 尾丝受体 (Tail)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #059669;"></span> 裂解系统 (Lysis)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #dc2626;"></span> 免疫防御 (Defense)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #7c3aed;"></span> DNA包装 (Packaging)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #2563eb;"></span> 结构形态 (Structural)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #d97706;"></span> 复制修饰 (Replication)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #0891b2;"></span> 代谢辅助 (Metabolism)</span>
              <span class="leg-pill"><span class="swatch-sq" style="background-color: #94a3b8;"></span> 假定蛋白 (Hypothetical)</span>
            </div>
          </div>
          <div class="legend-subgroup">
            <span class="legend-subgroup-title">CDS 变异形态:</span>
            <div class="legend-pills-list">
              <span class="leg-pill"><span class="swatch-sq sq-legend-conserved"></span> 等长保守 (纯色实心)</span>
              <span class="leg-pill"><span class="swatch-sq sq-legend-truncated"></span> 缺失截短 (斜斑纹理)</span>
              <span class="leg-pill"><span class="swatch-sq sq-legend-extended"></span> 插入延长 (上下端标)</span>
              <span class="leg-pill"><span class="swatch-dot" style="background-color: #cbd5e1;"></span> 基因缺失</span>
            </div>
          </div>
          <div class="legend-subgroup" v-if="isAniTrackVisible">
            <span class="legend-subgroup-title">全基因组 ANI (%):</span>
            <div class="ani-heat-swatch-list">
              <span class="heat-chip" style="background-color: #eff6ff; color: #1e3a8a;">70</span>
              <span class="heat-chip" style="background-color: #bfdbfe; color: #1e3a8a;">80</span>
              <span class="heat-chip" style="background-color: #60a5fa; color: #ffffff;">90</span>
              <span class="heat-chip" style="background-color: #2563eb; color: #ffffff;">95</span>
              <span class="heat-chip" style="background-color: #1e3a8a; color: #ffffff;">100</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 共享样本排序的一体化矩阵画板 (支持粘性冻结表头与冻结样本列，自适应纵向限高) -->
      <div 
        class="phylogenomic-composite-canvas" 
        :style="{ maxHeight: viewportMaxHeight === 'none' ? 'none' : viewportMaxHeight }"
      >
        <table class="composite-evidence-table">
          <thead>
            <tr>
              <!-- 1. 进化树列头 (可收起) -->
              <th v-if="isPhylogenyTrackVisible" class="th-tree th-sticky-left-1">Phylogeny</th>
              <!-- 2. 样本名称列头 (冻结吸附在左侧) -->
              <th 
                class="th-sample-name" 
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
              >
                Sample ID
              </th>
              <!-- 3. 元数据轨道列头 (可收起) -->
              <template v-if="isMetadataTrackVisible">
                <th class="th-meta">Lifestyle</th>
                <th class="th-meta">Safety</th>
                <th class="th-meta">Acr</th>
              </template>
              <!-- 4. ANI 矩阵列头 (与行样本完全一致的顺序，可收起) -->
              <template v-if="isAniTrackVisible">
                <th 
                  v-for="colId in orderedSampleIds" 
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
              v-for="(rowId, rIdx) in orderedSampleIds" 
              :key="'row-sample-' + rowId"
              class="composite-row"
              :class="{ 'row-pair-selected': selectedPair?.includes(rowId) }"
            >
              <!-- 1. 左侧系统发育拓扑树 (绝对定位容器包裹，杜绝任何对表格行高的反向撑高) -->
              <td 
                v-if="isPhylogenyTrackVisible && rIdx === 0" 
                class="td-tree-col th-sticky-left-1" 
                :rowspan="orderedSampleIds.length"
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

              <!-- 2. 样本名称 (点击可切换聚焦，冻结在左侧) -->
              <td 
                class="td-sample-name-col" 
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                @click="emit('select-sample', rowId)"
                :title="sampleNames[rowId]"
              >
                <strong>{{ sampleNames[rowId] || rowId }}</strong>
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
                  v-for="colId in orderedSampleIds" 
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

      <!-- 悬停基因家族信息提示条 -->
      <div class="cluster-hover-info-strip" v-if="hoveredGeneCluster">
        <span class="chip-cat" :style="{ backgroundColor: getCatColor(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }">
          {{ hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category }}
        </span>
        <strong>{{ hoveredGeneCluster.cluster?.group_id }}</strong>:
        <span>{{ hoveredGeneCluster.cluster?.representative_product }}</span>
        <span class="hover-sample-tag">【{{ sampleNames[hoveredGeneCluster.rowId] || hoveredGeneCluster.rowId }}】: <strong>{{ hoveredGeneCluster.variant?.variantLabel }}</strong></span>
        <span class="text-slate"> (共享率: {{ hoveredGeneCluster.cluster?.sample_count }}/{{ orderedSampleIds.length }} 样本 · 点击可锁定展开全株比对表)</span>
      </div>
      <div class="cluster-hover-info-strip ph-strip" v-else>
        <span class="text-slate">提示：当前已展示全部 {{ sortedGeneClusters.length }} 个 CDS 基因家族。支持通过顶部工具栏自由收起/展开进化树、元数据或 ANI 矩阵，切换 50+ 全景微缩模式。</span>
      </div>

      <!-- 全轨道图谱综合学术图注 -->
      <div class="figure-comprehensive-legend-strip">
        <div class="legend-track-item">
          <strong class="trk-name">Phylogeny</strong>: <span>UPGMA 聚类系统发育拓扑树 (基于全基因组 ANI 矩阵)</span>
        </div>
        <div class="legend-track-item">
          <strong class="trk-name">Lifestyle / Safety</strong>: <span>生活周期 (Lytic 专性烈性) 及安全性 (Safe 毒力/耐药阴性)</span>
        </div>
        <div class="legend-track-item">
          <strong class="trk-name">Acr</strong>: <span>携带的抗 CRISPR (Anti-CRISPR) 基因数</span>
        </div>
        <div class="legend-track-item">
          <strong class="trk-name">ANI (%)</strong>: <span>全基因组平均核酸一致性热阶 (蓝色深浅编码 70%~100%)</span>
        </div>
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
                  v-for="sid in orderedSampleIds" 
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
                v-for="sid in orderedSampleIds" 
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
.population-summary-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-toggle-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 4px;
}

.st-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.st-tag {
  background: #2563eb;
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: 3px;
}

.st-title {
  font-size: 11px;
  font-weight: 700;
  color: #475569;
}

.btn-section-toggle,
.btn-panel-toggle {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  padding: 2px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-section-toggle:hover,
.btn-panel-toggle:hover {
  background: #e2e8f0;
  color: #0f172a;
}

/* 顶部统计条 */
.population-summary-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.summary-stat-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-stat-box.highlight-box {
  border-color: #fde68a;
  background: #fffbeb;
}

.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
}

.stat-val {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.stat-val small {
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
}

.stat-sub {
  font-size: 10px;
  color: #64748b;
}

.text-green { color: #16a34a; }
.text-blue { color: #2563eb; }
.text-amber { color: #d97706; }
.text-slate { color: #64748b; }

/* 旗舰组合面板 */
.academic-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 10px;
}

.flex-header-wrap {
  flex-wrap: wrap;
  gap: 12px;
}

.title-with-tag {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-tag {
  background: #0f172a;
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.panel-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

/* 综合视图工具栏 (轨道开关、密度模式、视口限高) */
.matrix-comprehensive-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-sublabel {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  margin-right: 4px;
}

.track-toggle-capsule-group,
.density-switch-group {
  display: flex;
  align-items: center;
  gap: 2px;
  background: #f1f5f9;
  padding: 2px 4px;
  border-radius: 6px;
}

.btn-track-pill,
.btn-density-opt {
  background: transparent;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-track-pill:hover,
.btn-density-opt:hover {
  color: #0f172a;
}

.btn-track-pill.active,
.btn-density-opt.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.btn-track-pill.active {
  color: #2563eb;
}

.btn-density-ultra.active {
  color: #d97706;
}

.viewport-height-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-legend-collapse-opt {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-legend-collapse-opt:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.btn-legend-collapse-opt.active {
  background: #f1f5f9;
  border-color: #94a3b8;
}

/* 过滤控制栏 */
.matrix-filter-controls-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.cat-filter-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}

.partition-filter-pills {
  display: flex;
  gap: 4px;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 6px;
}

.btn-pill-opt {
  background: transparent;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-pill-opt:hover {
  color: #0f172a;
}

.btn-pill-opt.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.btn-pill-opt.text-amber-pill.active {
  color: #d97706;
  font-weight: 700;
}

.btn-pill-opt.text-blue-pill.active {
  color: #2563eb;
  font-weight: 700;
}

.filter-lbl {
  font-size: 11px;
  color: #64748b;
}

.compact-cat-select,
.compact-select {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 10px;
  padding: 3px 8px;
  color: #334155;
}

/* 一体化画板表格与吸顶/冻结列 */
.phylogenomic-composite-canvas {
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
  width: 130px;
  min-width: 130px;
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

/* 全局常驻图注卡片栏 */
.global-matrix-legend-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 14px;
}

.legend-section-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.legend-subgroup {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.legend-subgroup-title {
  font-size: 11px;
  font-weight: 700;
  color: #334155;
  white-space: nowrap;
}

.legend-pills-list {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ani-heat-swatch-list {
  display: flex;
  align-items: center;
  gap: 2px;
}

.heat-chip {
  font-size: 9px;
  font-weight: 800;
  padding: 2px 5px;
  border-radius: 2px;
  border: 1px solid rgba(0, 0, 0, 0.05);
}

.leg-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  white-space: nowrap;
}

.swatch-sq {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.swatch-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
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

.figure-comprehensive-legend-strip {
  display: flex;
  gap: 16px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 4px;
  padding: 5px 12px;
  font-size: 10px;
  color: #64748b;
  flex-wrap: wrap;
}

.legend-track-item {
  display: inline-flex;
  gap: 4px;
}

.trk-name {
  color: #1e293b;
  font-weight: 700;
}

/* 表体单元格与行高规范 */
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
  width: 130px;
  font-size: 10px;
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
  transform: scale(1.1);
  z-index: 5;
  outline: 1.5px solid #0f172a;
}

.cell-pair-highlight {
  outline: 2px solid #ef4444;
  z-index: 4;
}

/* 基因方块 (超紧凑 4px 宽，高度绝对统一 16px，通过内部纹理与端标区分变异) */
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
  transition: transform 0.12s ease;
}

/* 1. 等长保守：饱满纯色实心色块 (高度完全一致 16px) */
.gene-present-square.sq-conserved {
  height: 16px;
  border-radius: 1px;
  opacity: 1.0;
}

/* 2. 缺失截短变异：高度同样为 16px，内部带明显斜向白纹遮罩，直观呈现残缺斑驳感 */
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

/* 3. 插入延长变异：高度同样为 16px，上下两端带有深色端帽横线标 */
.gene-present-square.sq-extended {
  height: 16px;
  border-radius: 1px;
  border-top: 2px solid #0f172a !important;
  border-bottom: 2px solid #0f172a !important;
  box-shadow: 0 0 0 0.5px #0f172a;
}

.gene-present-square:hover {
  transform: scaleX(2.8) scaleY(1.2);
  z-index: 10;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.5);
}

.gene-absent-dot {
  width: 1.2px;
  height: 1.2px;
  border-radius: 50%;
  background: #cbd5e1;
  margin: 0 auto;
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

/* 悬停基因家族信息提示条 */
.cluster-hover-info-strip {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.cluster-hover-info-strip.ph-strip {
  border-style: dashed;
  background: #fdfdfe;
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

.density-compact .td-sample-name-col {
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

.density-ultra .td-sample-name-col {
  font-size: 8px;
  height: 11px;
  line-height: 11px;
  width: 100px;
  min-width: 100px;
}

.density-ultra .th-sample-name {
  width: 100px;
  min-width: 100px;
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
