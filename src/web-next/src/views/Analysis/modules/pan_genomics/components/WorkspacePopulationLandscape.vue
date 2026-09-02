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
import { FUNCTIONAL_CATEGORIES } from '../../viewer/utils/render'
import {
  CATEGORY_ORDER,
  normalizeCategoryName,
  inferClusterCategory,
  getCatColor,
  getCategoryChinese,
  getClusterConsensusLen,
  getClusterVariantInfo,
  type ClusterVariantInfo
} from '../utils/pangenomeVariants'

import PhylogenyTreeSvg from './subcomponents/PhylogenyTreeSvg.vue'
import SampleFilterPopover from './subcomponents/SampleFilterPopover.vue'
import GeneClusterDetailDrawer from './subcomponents/GeneClusterDetailDrawer.vue'
import PanGenomicsChordDiagram from './subcomponents/PanGenomicsChordDiagram.vue'

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

// 零开销十字准星垂直导轨状态 (GPU 硬件加速，规避上万个 DOM 节点的响应式 Class Diff)
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

// 密度模式 (Spacious 宽松 / Comfortable 舒适 / Compact 紧凑 / Ultra 全景 50+)
const displayDensity = ref<'spacious' | 'comfortable' | 'compact' | 'ultra'>('spacious')

// 自然顺序排序算法
function naturalSort(ids: string[]): string[] {
  return [...ids].sort((a, b) => {
    const nameA = props.sampleNames[a] || a
    const nameB = props.sampleNames[b] || b
    return nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' })
  })
}

// 排序模式: 'cluster' 系统发育聚类 (默认) | 'natural' 自然顺序递增
const sampleSortOrder = ref<'natural' | 'cluster'>('cluster')

const rawClusteredIds = computed<string[]>(() => {
  if (props.aniClustering?.ordered_ids?.length) {
    return props.aniClustering.ordered_ids
  }
  return Object.keys(props.sampleNames || {})
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
      acrCount: props.armsRaceMatrix?.[l.sample_id]?.acr_count || 0
    }
  })
  return map
})

// 核心预计算：构建带变异缓存的基因家族列表 (O(1) 模板读取)
const sortedGeneClusters = computed(() => {
  if (!props.clusters || props.clusters.length === 0) return []
  const n = visibleSampleIds.value.length
  const allSampleIds = orderedSampleIds.value

  let list = props.clusters.map(c => {
    const infCat = inferClusterCategory(c)
    const consLen = getClusterConsensusLen(c)

    // 预先为所有样本计算变异信息 (显式传递 infCat 保证矩阵与抽屉颜色绝对一致)
    const variantMap: Record<string, ClusterVariantInfo> = {}
    allSampleIds.forEach(sid => {
      variantMap[sid] = getClusterVariantInfo(c, sid, consLen, infCat)
    })

    return {
      ...c,
      _inferredCategory: infCat,
      _consensusLen: consLen,
      _variantMap: variantMap
    }
  })

  // 1. 功能分类过滤
  if (geneCategoryFilter.value !== 'ALL') {
    const targetCat = normalizeCategoryName(geneCategoryFilter.value)
    list = list.filter(c => normalizeCategoryName(c._inferredCategory) === targetCat)
  }

  // 2. 泛基因组分区过滤
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

  return list.sort((a, b) => {
    const catA = CATEGORY_ORDER[a._inferredCategory] || 99
    const catB = CATEGORY_ORDER[b._inferredCategory] || 99
    if (catA !== catB) return catA - catB
    return (b.sample_count || 0) - (a.sample_count || 0)
  })
})

// 泛基因组核心基因统计
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
    <!-- 顶刊旗舰组合图: Phylogenomic Evidence Matrix -->
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

          <!-- 样本可见性工具条 -->
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

              <!-- 独立样本筛选浮层 -->
              <SampleFilterPopover
                v-model:isOpen="isSampleFilterOpen"
                :ordered-sample-ids="orderedSampleIds"
                :hidden-sample-ids="hiddenSampleIds"
                :sample-names="sampleNames"
                :selected-pair="selectedPair"
                @toggle-sample="toggleSampleVisibility"
                @show-all="showAllSamples"
                @clear-all="clearAllSamples"
                @invert-selection="invertSampleSelection"
                @focus-pair="focusOnlyPair"
                @focus-single="focusOnlySingle"
              />
            </div>
          </div>
        </div>

        <div class="deck-actions-area">
          <!-- 视图模式控制器 (矩阵条形码 vs 拓扑弦图) -->
          <div class="segmented-density-control">
            <span class="control-label">视图:</span>
            <div class="seg-pills">
              <button
                class="seg-btn"
                :class="{ active: viewMode === 'matrix' }"
                @click="viewMode = 'matrix'"
                title="矩阵条形码视图 (全基因组证据矩阵与变异探测)"
              >
                矩阵条形码
              </button>
              <button
                class="seg-btn"
                :class="{ active: viewMode === 'chord' }"
                @click="viewMode = 'chord'"
                title="群体拓扑弦图 (同源基因共享流与功能二分关联)"
              >
                拓扑弦图
              </button>
            </div>
          </div>

          <!-- 排序分段控制器 -->
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

          <!-- 密度分段控制器 -->
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
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </svg>
            {{ isLegendCollapsed ? '展开图注' : '收起图注' }}
          </button>
        </div>
      </div>

      <!-- 2. 统一操作带 (Unified Tool Ribbon) -->
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
                核心基因 ({{ pangenomePartition.core }})
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
              <option value="ALL">全部功能模块</option>
              <option v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" :value="key">
                {{ cat.label }}
              </option>
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
      <div class="academic-legend-deck" v-show="!isLegendCollapsed && viewMode === 'matrix'">
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

      <!-- 视图 A: 共享样本排序的一体化矩阵画板 -->
      <div v-if="viewMode === 'matrix'" class="phylogenomic-composite-canvas" @mouseleave="handleClusterMouseLeave">
        <!-- 零响应式开销的 GPU 硬件加速十字准星垂直导轨 (平滑悬浮于对应列，0 次 VNode Diff) -->
        <div 
          v-show="crosshairVisible" 
          class="crosshair-vertical-guide"
          :style="{
            left: `${crosshairLeft}px`,
            width: `${crosshairWidth}px`
          }"
        ></div>

        <table class="composite-evidence-table">
          <thead>
            <tr>
              <!-- 1. 进化树列头 (可收起) -->
              <th v-if="isPhylogenyTrackVisible" class="th-tree th-sticky-left-1" title="系统发育拓扑树 (UPGMA 聚类构建)">系统发育</th>
              <!-- 2. 样本名称列头 -->
              <th
                class="th-sample-name"
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                title="样本标识名称"
              >
                样本编号
              </th>
              <!-- 3. 元数据轨道列头 -->
              <template v-if="isMetadataTrackVisible">
                <th class="th-meta" title="噬菌体生活周期 (Lytic 专性烈性 / Lysogenic 温和溶原)">生活周期</th>
                <th class="th-meta" title="治疗安全性审计 (Safe 毒力因子与耐药基因阴性)">生物安全</th>
                <th class="th-meta" title="抗 CRISPR 攻防系统 (携带的 Anti-CRISPR 基因数)">抗 CRISPR</th>
              </template>
              <!-- 4. ANI 矩阵列头 -->
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
              <!-- 5. 基因家族存在/缺失矩阵列头 -->
              <th
                v-if="isGeneMatrixTrackVisible"
                class="th-genefamily-title"
                :colspan="Math.max(1, sortedGeneClusters.length)"
              >
                <div class="gene-matrix-header-bar">
                  <span class="gene-matrix-title-txt">泛基因组直系同源基因矩阵 (共 {{ sortedGeneClusters.length }} 基因家族，按功能着色)</span>
                </div>
              </th>
              <!-- 6. 弹性吸纳列 -->
              <th class="th-elastic-spacer"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(rowId, rIdx) in visibleSampleIds"
              :key="'row-sample-' + rowId"
              class="composite-row"
              :class="{ 'row-pair-selected': selectedPair?.includes(rowId) }"
            >
              <!-- 1. 左侧系统发育拓扑树 (独立子组件渲染) -->
              <td
                v-if="isPhylogenyTrackVisible && rIdx === 0"
                class="td-tree-col th-sticky-left-1"
                :rowspan="visibleSampleIds.length"
              >
                <PhylogenyTreeSvg
                  :visible-sample-ids="visibleSampleIds"
                  :ani-matrix="aniMatrix"
                  :row-height="rowHeight"
                  :display-density="displayDensity"
                />
              </td>

              <!-- 2. 样本名称 -->
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

              <!-- 3. 样本多维元数据轨道 -->
              <template v-if="isMetadataTrackVisible">
                <td class="td-meta-col">
                  <span
                    :class="['meta-badge', (sampleAnnotations[rowId]?.lifestyle === 'Lytic') ? 'bg-lytic' : 'bg-temperate']"
                    :title="sampleAnnotations[rowId]?.lifestyle === 'Lytic' ? '专性烈性噬菌体' : '检出温和溶源整合元件'"
                  >
                    {{ sampleAnnotations[rowId]?.lifestyle === 'Lytic' ? '烈性' : '温和' }}
                  </span>
                </td>
                <td class="td-meta-col">
                  <span
                    :class="['meta-badge', sampleAnnotations[rowId]?.safe ? 'bg-safe' : 'bg-risk']"
                    :title="sampleAnnotations[rowId]?.safe ? '治疗应用安全' : '含有潜在毒力或整合风险元件'"
                  >
                    {{ sampleAnnotations[rowId]?.safe ? '安全' : '警示' }}
                  </span>
                </td>
                <td class="td-meta-col">
                  <strong class="text-blue">{{ sampleAnnotations[rowId]?.acrCount || 0 }}</strong>
                </td>
              </template>

              <!-- 4. 全基因组 ANI 矩阵单元格 -->
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

              <!-- 5. 同源基因家族存在/缺失方块矩阵 (纯静态零 Diff 渲染 + 绝对定位导轨极速联动) -->
              <template v-if="isGeneMatrixTrackVisible">
                <td
                  v-for="c in sortedGeneClusters"
                  :key="'cluster-' + rowId + '-' + c.group_id"
                  class="td-cluster-block"
                  @mouseenter="handleClusterMouseEnter($event, c, rowId)"
                  @click="openClusterDrawer(c)"
                >
                  <div
                    v-if="c.presence_map?.[rowId]"
                    class="gene-present-square"
                    :class="c._variantMap[rowId].className"
                    :style="c._variantMap[rowId].style"
                    :title="c._variantMap[rowId].title"
                  ></div>
                  <div v-else class="gene-absent-dot" title="该样本缺失此 CDS"></div>
                </td>
              </template>

              <!-- 6. 弹性吸纳单元格 -->
              <td class="td-elastic-spacer"></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 视图 B: 群体拓扑弦图画板 -->
      <div v-else class="phylogenomic-chord-canvas">
        <PanGenomicsChordDiagram
          :clusters="clusters || []"
          :sample-names="sampleNames"
          :visible-sample-ids="visibleSampleIds"
          :ani-matrix="aniMatrix"
          :tail-matrix="tailMatrix"
          :lifestyles="lifestyles"
          :selected-pair="selectedPair"
          @select-sample="handleSelectSample"
          @select-pair="handleSelectPair"
          @open-cluster-drawer="openClusterDrawer"
        />
      </div>

      <!-- 悬停基因家族信息提示条 (固定高度状态栏) -->
      <div v-if="viewMode === 'matrix'" class="cluster-hover-info-strip" :class="{ active: !!hoveredGeneCluster }">
        <template v-if="hoveredGeneCluster">
          <span class="chip-cat" :style="{ backgroundColor: getCatColor(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }">
            {{ getCategoryChinese(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }}
          </span>
          <strong>{{ hoveredGeneCluster.cluster?.group_id }}</strong>:
          <span class="strip-prod-txt">{{ hoveredGeneCluster.cluster?.representative_product }}</span>
          <span class="hover-sample-tag">【{{ sampleNames[hoveredGeneCluster.rowId] || hoveredGeneCluster.rowId }}】: <strong>{{ hoveredGeneCluster.variant?.variantLabel }}</strong></span>
          <span class="text-slate"> (共享率: {{ hoveredGeneCluster.cluster?.sample_count }}/{{ orderedSampleIds.length }} 样本 · 点击展开跨株比对)</span>
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

      <!-- CDS 详细属性卡片模态 (独立抽屉子组件) -->
      <GeneClusterDetailDrawer
        :cluster="selectedGeneCluster"
        :visible-sample-ids="visibleSampleIds"
        :sample-names="sampleNames"
        :selected-pair="selectedPair"
        :total-sample-count="orderedSampleIds.length"
        @close="selectedGeneCluster = null"
      />
    </div>
  </div>
</template>

<style scoped>
.workspace-population-landscape {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.phylogenomic-chord-canvas {
  width: 100%;
  min-height: 680px;
  background: white;
  border-radius: 8px;
  overflow: hidden;
}

/* 样本可见性工具条 */
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

/* 样本单元格小眼睛 */
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
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 1. 顶层主标题与全局视图控制带 */
.panel-header-deck {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 6px;
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

/* 分段选择器 */
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

/* 2. 统一操作带 */
.matrix-ribbon-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 5px 10px;
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

/* 3. 精炼学术图注条 */
.academic-legend-deck {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 5px 12px;
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

/* 一体化画板表格与吸顶/冻结列 */
.phylogenomic-composite-canvas {
  max-height: 72vh;
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
  padding: 5px 4px;
  font-size: 10px;
  color: #64748b;
  border-bottom: 1.5px solid #cbd5e1;
  vertical-align: bottom;
}

/* 冻结列 */
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
  width: 24px;
  min-width: 24px;
  max-width: 24px;
  text-align: center;
  padding: 4px 0;
  box-sizing: border-box;
}

.th-rot-label {
  font-size: 8px;
  font-weight: 700;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 24px;
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
.bg-temperate { background: #f59e0b; }
.bg-risk { background: #f43f5e; }

.td-ani-val-cell {
  width: 24px;
  min-width: 24px;
  max-width: 24px;
  height: 24px;
  min-height: 24px;
  max-height: 24px;
  line-height: 24px;
  text-align: center;
  vertical-align: middle;
  font-size: 8px;
  font-weight: 700;
  border: 0.5px solid #ffffff;
  padding: 0;
  box-sizing: border-box;
  cursor: pointer;
  aspect-ratio: 1 / 1;
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

/* 基因方块 */
.td-cluster-block {
  width: 5px !important;
  min-width: 5px !important;
  max-width: 5px !important;
  height: 24px;
  padding: 0 !important;
  margin: 0 !important;
  box-sizing: border-box;
  text-align: center;
  vertical-align: middle;
  border-left: 0.5px solid #f8fafc;
}

/* 零响应式开销的 GPU 硬件加速十字准星垂直导轨 */
.crosshair-vertical-guide {
  position: absolute;
  top: 0;
  bottom: 0;
  height: 100%;
  pointer-events: none;
  background-color: rgba(37, 99, 235, 0.12);
  z-index: 10;
  border-left: 0.5px solid rgba(37, 99, 235, 0.4);
  border-right: 0.5px solid rgba(37, 99, 235, 0.4);
  box-sizing: border-box;
}

.th-elastic-spacer,
.td-elastic-spacer {
  width: auto !important;
  min-width: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
  border: none !important;
  background: transparent !important;
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

.gene-present-square:hover {
  filter: brightness(1.2);
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.35);
  transform: scale(1.1);
  z-index: 10;
}

/* 等长保守 */
.gene-present-square.sq-conserved {
  height: 16px;
  border-radius: 1px;
  opacity: 1.0;
}

/* 缺失截短变异 */
.gene-present-square.sq-truncated {
  height: 16px;
  border-radius: 1px;
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.6) 0,
    rgba(255, 255, 255, 0.6) 1.5px,
    transparent 1.5px,
    transparent 3px
  );
  border: 0.5px dashed rgba(0, 0, 0, 0.3);
}

/* 插入延长变异 */
.gene-present-square.sq-extended {
  height: 18px;
  border-radius: 1.5px;
  border-top: 1.5px solid #0f172a;
  border-bottom: 1.5px solid #0f172a;
}

.gene-absent-dot {
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background-color: #cbd5e1;
  margin: 0 auto;
  opacity: 0.6;
}

/* 图注形状示例 */
.sq-legend-conserved {
  background-color: #0284c7;
}

.sq-legend-truncated {
  background-color: #0284c7;
  background-image: repeating-linear-gradient(
    -45deg,
    rgba(255, 255, 255, 0.6) 0,
    rgba(255, 255, 255, 0.6) 1.5px,
    transparent 1.5px,
    transparent 3px
  );
  border: 0.5px dashed rgba(0, 0, 0, 0.3);
}

.sq-legend-extended {
  background-color: #0284c7;
  border-top: 1.5px solid #0f172a;
  border-bottom: 1.5px solid #0f172a;
}

/* 悬停信息提示条 */
.cluster-hover-info-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  padding: 5px 12px;
  font-size: 11px;
  color: #334155;
  min-height: 28px;
  box-sizing: border-box;
}

.cluster-hover-info-strip.active {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.strip-placeholder-txt {
  color: #94a3b8;
  font-size: 11px;
}

.chip-cat {
  font-size: 9.5px;
  font-weight: 700;
  color: #ffffff;
  padding: 1.5px 6px;
  border-radius: 3px;
}

.strip-prod-txt {
  color: #0f172a;
  font-weight: 600;
}

.hover-sample-tag {
  color: #2563eb;
  font-size: 10.5px;
}

.text-slate {
  color: #64748b;
}

/* 多密度档位动态样式 */
.density-spacious .composite-row {
  height: 36px;
  min-height: 36px;
  max-height: 36px;
}
.density-spacious .td-sample-name-col,
.density-spacious .td-meta-col,
.density-spacious .td-cluster-block {
  height: 36px;
  line-height: 36px;
}
.density-spacious .th-ani-col,
.density-spacious .td-ani-val-cell {
  width: 36px !important;
  min-width: 36px !important;
  max-width: 36px !important;
  height: 36px !important;
  min-height: 36px !important;
  max-height: 36px !important;
  line-height: 36px !important;
}
.density-spacious .th-rot-label {
  max-width: 36px;
  font-size: 9px;
}
.density-spacious .gene-present-square {
  height: 24px;
}
.density-spacious .gene-present-square.sq-conserved,
.density-spacious .gene-present-square.sq-truncated {
  height: 24px;
}
.density-spacious .gene-present-square.sq-extended {
  height: 28px;
}

.density-compact .composite-row {
  height: 17px;
  min-height: 17px;
  max-height: 17px;
}
.density-compact .td-sample-name-col,
.density-compact .td-meta-col,
.density-compact .td-cluster-block {
  height: 17px;
  line-height: 17px;
  font-size: 9.5px;
}
.density-compact .th-ani-col,
.density-compact .td-ani-val-cell {
  width: 17px !important;
  min-width: 17px !important;
  max-width: 17px !important;
  height: 17px !important;
  min-height: 17px !important;
  max-height: 17px !important;
  line-height: 17px !important;
  font-size: 7.5px;
}
.density-compact .th-rot-label {
  max-width: 17px;
  font-size: 7px;
}
.density-compact .gene-present-square {
  height: 12px;
}
.density-compact .gene-present-square.sq-conserved,
.density-compact .gene-present-square.sq-truncated {
  height: 12px;
}
.density-compact .gene-present-square.sq-extended {
  height: 14px;
}

.density-ultra .composite-row {
  height: 11px;
  min-height: 11px;
  max-height: 11px;
}
.density-ultra .td-sample-name-col,
.density-ultra .td-meta-col,
.density-ultra .td-cluster-block {
  height: 11px;
  line-height: 11px;
  font-size: 8px;
  padding: 0 2px;
}
.density-ultra .th-ani-col,
.density-ultra .td-ani-val-cell {
  width: 11px !important;
  min-width: 11px !important;
  max-width: 11px !important;
  height: 11px !important;
  min-height: 11px !important;
  max-height: 11px !important;
  line-height: 11px !important;
  font-size: 6.5px;
  padding: 0;
}
.density-ultra .th-rot-label {
  max-width: 11px;
}
.density-ultra .gene-present-square {
  height: 8px;
  width: 2.5px;
}
.density-ultra .gene-present-square.sq-conserved,
.density-ultra .gene-present-square.sq-truncated {
  height: 8px;
}
.density-ultra .gene-present-square.sq-extended {
  height: 10px;
}
</style>
