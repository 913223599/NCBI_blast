<script setup lang="ts">
/**
 * PanGenomicsChordDiagram.vue - 泛基因组学术级群体拓扑弦图
 * 特性：
 * 1. 零画面跳动 (Zero Layout Shift)：左侧弦图视窗尺寸绝对恒定；
 * 2. 圆心通透无遮挡：所有交互探针与功能剖面统一整合至右侧固定 HUD；
 * 3. 外圆周精简学术短标，右侧独立滚动图注，支持双向高亮；
 * 4. 关联阈值支持快捷阶梯过滤与动态滑块。
 */
import { ref, computed } from 'vue'
import * as d3 from 'd3'
import {
  normalizeCategoryName,
  inferClusterCategory,
  getCatColor
} from '../../utils/pangenomeVariants'

const props = defineProps<{
  clusters: any[]
  sampleNames: Record<string, string>
  visibleSampleIds: string[]
  aniMatrix?: Record<string, Record<string, number>>
  tailMatrix?: Record<string, Record<string, number>>
  lifestyles?: any[]
  selectedPair?: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
  (e: 'open-cluster-drawer', cluster: any): void
}>()

// 弦图模式: 'sample-sample' (两两样本共享流) | 'sample-function' (样本与功能模块关联)
const chordMode = ref<'sample-sample' | 'sample-function'>('sample-sample')

// 共享基因数阈值过滤
const minSharedThreshold = ref<number>(5)

// 图注搜索关键词
const legendSearch = ref<string>('')

// 功能分类中英文对照与说明
const FUNCTION_DEFS: Record<string, { label: string; short: string; desc: string }> = {
  'Tail & Host Interaction': { label: '尾部与宿主吸附系统', short: '尾丝/受体吸附', desc: '尾丝、刺突、受体结合蛋白 (RBP) 与吸附结构' },
  'Lysis': { label: '宿主裂解系统', short: '宿主裂解', desc: '内溶素 (Endolysin)、穿孔素 (Holin) 与跨膜裂解酶' },
  'Defense & Host Interaction': { label: '宿主防御与互作 (Acr)', short: '防御互作 (Acr)', desc: '抗 CRISPR (Acr)、抗限制修饰系统与宿主逃逸元件' },
  'Head & Packaging': { label: '头部与衣壳包装系统', short: '头衣壳包装', desc: '主衣壳、末端酶 (Terminase) 与头尾连接器' },
  'Integration & Excision': { label: '溶源整合与切除系统', short: '整合切除', desc: '整合酶 (Integrase)、切除酶 (Excisionase) 与重组元件' },
  'Replication & Repair': { label: 'DNA 复制与重组修复', short: 'DNA复制修复', desc: 'DNA 聚合酶、解旋酶、引物酶、单链结合蛋白与连接酶' },
  'Transcription & Regulation': { label: '转录调控与开关', short: '转录调控', desc: '转录阻遏蛋白、转录激活因子与休眠开关' },
  'Metabolism & AMG': { label: '辅助代谢基因 (AMG)', short: '代谢 (AMG)', desc: '核苷酸合成、碳代谢与能量辅助代谢基因' },
  'Other Functional': { label: '其他功能蛋白', short: '其他功能', desc: '次要酶系、膜蛋白与特化代谢分子' },
  'Hypothetical': { label: '假定蛋白与未表征', short: '假定蛋白', desc: '未命名的新颖噬菌体 ORF 与未表征功能基因' }
}

const FUNCTION_KEYS = Object.keys(FUNCTION_DEFS)

// 样本色系分配
const SAMPLE_PALETTE = [
  '#2563eb', '#3b82f6', '#60a5fa', '#0d9488', '#14b8a6', '#059669', '#10b981',
  '#f59e0b', '#d97706', '#ea580c', '#f43f5e', '#e11d48', '#8b5cf6', '#7c3aed',
  '#6366f1', '#4f46e5', '#0284c7', '#0369a1', '#475569', '#64748b', '#0891b2', '#0e7490'
]

function getSampleColor(index: number): string {
  return SAMPLE_PALETTE[index % SAMPLE_PALETTE.length] || '#3b82f6'
}

// 样本精简学术短标提取
function getSampleShortName(sid: string): string {
  const fullName = props.sampleNames[sid] || sid
  const bcMatch = fullName.match(/^(BC\d+)[-_]contig_?(\d+)/i)
  if (bcMatch) {
    return `${bcMatch[1]}-c${bcMatch[2]}`
  }
  const simpleBc = fullName.match(/^(BC\d+)/i)
  if (simpleBc) {
    return simpleBc[1]!
  }
  const ahyMatch = fullName.match(/phage\s*([A-Za-z0-9]+)/i)
  if (ahyMatch) {
    return ahyMatch[1]!
  }
  return fullName.length > 10 ? fullName.slice(0, 8) + '..' : fullName
}

// 尺寸计算
const outerRadius = 250
const innerRadius = outerRadius - 20

// 悬停聚焦状态
const hoveredEntity = ref<{
  type: 'sample' | 'function' | 'ribbon'
  id: string
  name: string
  targetId?: string
  targetName?: string
  value?: number
  ani?: number
  tailSim?: number
  uniqueGenes?: number
  totalGenes?: number
  coveredSamples?: number
  totalClustersInCat?: number
  sharedClusters?: any[]
} | null>(null)

// ─────────────────────────────────────────────────────────────────────────────
// 模式 1: 样本间同源基因共享矩阵计算 (Sample-to-Sample)
// ─────────────────────────────────────────────────────────────────────────────
const sampleMatrixData = computed(() => {
  const ids = props.visibleSampleIds
  const n = ids.length
  if (n < 2 || !props.clusters || props.clusters.length === 0) {
    return { matrix: [], ids: [], sharedMap: {} }
  }

  const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0))
  const sharedMap: Record<string, any[]> = {}

  props.clusters.forEach(c => {
    const presentIds = ids.filter(sid => !!c.presence_map?.[sid])
    for (let i = 0; i < presentIds.length; i++) {
      for (let j = i; j < presentIds.length; j++) {
        const u = ids.indexOf(presentIds[i]!)
        const v = ids.indexOf(presentIds[j]!)
        if (u !== -1 && v !== -1) {
          matrix[u]![v]! += 1
          if (u !== v) {
            matrix[v]![u]! += 1
            const pairKey = `${ids[u]}|${ids[v]}`
            const revKey = `${ids[v]}|${ids[u]}`
            if (!sharedMap[pairKey]) sharedMap[pairKey] = []
            if (!sharedMap[revKey]) sharedMap[revKey] = []
            sharedMap[pairKey]!.push(c)
            sharedMap[revKey]!.push(c)
          }
        }
      }
    }
  })

  return { matrix, ids, sharedMap }
})

// 样本自身基因总数与独有基因统计
const sampleStatsMap = computed(() => {
  const allClust = props.clusters || []
  const map: Record<string, { total: number; unique: number }> = {}
  props.visibleSampleIds.forEach(sid => {
    const total = allClust.filter(c => !!c.presence_map?.[sid]).length
    const unique = allClust.filter(c => {
      if (!c.presence_map?.[sid]) return false
      return Object.values(c.presence_map).filter(Boolean).length === 1
    }).length
    map[sid] = { total, unique }
  })
  return map
})

// 最大两两共享基因数
const maxSharedValue = computed(() => {
  let mx = 10
  const m = sampleMatrixData.value.matrix
  for (let i = 0; i < m.length; i++) {
    for (let j = i + 1; j < m.length; j++) {
      const v = m[i]?.[j] ?? 0
      if (v > mx) mx = v
    }
  }
  return mx
})

// 模式 1 D3 弦布局计算
const sampleChordLayout = computed(() => {
  const { matrix, ids } = sampleMatrixData.value
  if (!matrix.length) return null

  const thresh = minSharedThreshold.value
  const filteredMatrix = matrix.map((row, i) =>
    row.map((val, j) => {
      if (i === j) {
        return Math.max(15, sampleStatsMap.value[ids[i]!]?.total || 15)
      }
      return val >= thresh ? val : 0
    })
  )

  const chord = d3.chord()
    .padAngle(0.035)
    .sortSubgroups(d3.descending)

  const chords = chord(filteredMatrix)
  const validChords = chords.filter(c => c.source.index !== c.target.index && c.source.value >= thresh)

  const arcGen = d3.arc<any>()
    .innerRadius(innerRadius)
    .outerRadius(outerRadius)

  const ribbonGen = d3.ribbon<any, any>()
    .radius(innerRadius - 2)

  return { chords, validChords, arcGen, ribbonGen, ids }
})

function getSampleRibbonPath(d: any): string {
  if (!sampleChordLayout.value) return ''
  const gen = sampleChordLayout.value.ribbonGen as (datum: any) => string | null
  return gen(d) ?? ''
}

function getSampleArcPath(group: any): string {
  if (!sampleChordLayout.value) return ''
  const gen = sampleChordLayout.value.arcGen as (datum: any) => string | null
  return gen(group) ?? ''
}

// ─────────────────────────────────────────────────────────────────────────────
// 模式 2: 样本 ↔ 10 大功能模块二分矩阵计算 (Sample-to-Function Bipartite)
// ─────────────────────────────────────────────────────────────────────────────
const bipartiteMatrixData = computed(() => {
  const sIds = props.visibleSampleIds
  const fKeys = FUNCTION_KEYS
  const totalDim = sIds.length + fKeys.length
  if (sIds.length === 0 || !props.clusters) return null

  const matrix: number[][] = Array.from({ length: totalDim }, () => Array(totalDim).fill(0))

  props.clusters.forEach(c => {
    const cat = inferClusterCategory(c)
    const normCat = normalizeCategoryName(cat)
    const fIdx = fKeys.indexOf(normCat)
    if (fIdx === -1) return

    sIds.forEach((sid, sIdx) => {
      if (c.presence_map?.[sid]) {
        const col = sIds.length + fIdx
        matrix[sIdx]![col]! += 1
        matrix[col]![sIdx]! += 1
      }
    })
  })

  return { matrix, sIds, fKeys }
})

// 模式 2 D3 弦布局计算
const bipartiteChordLayout = computed(() => {
  const data = bipartiteMatrixData.value
  if (!data) return null

  const chord = d3.chord()
    .padAngle(0.025)
    .sortSubgroups(d3.descending)

  const chords = chord(data.matrix)
  const validChords = chords.filter(c => c.source.index !== c.target.index && c.source.value > 0)
  const arcGen = d3.arc<any>()
    .innerRadius(innerRadius)
    .outerRadius(outerRadius)

  const ribbonGen = d3.ribbon<any, any>()
    .radius(innerRadius - 2)

  return { chords, validChords, arcGen, ribbonGen, ...data }
})

function getBipartiteRibbonPath(d: any): string {
  if (!bipartiteChordLayout.value) return ''
  const gen = bipartiteChordLayout.value.ribbonGen as (datum: any) => string | null
  return gen(d) ?? ''
}

function getBipartiteArcPath(group: any): string {
  if (!bipartiteChordLayout.value) return ''
  const gen = bipartiteChordLayout.value.arcGen as (datum: any) => string | null
  return gen(group) ?? ''
}

// ─────────────────────────────────────────────────────────────────────────────
// 复合联动：当前聚焦对象的功能操纵子构成剖面 (Functional Breakdown Profile)
// ─────────────────────────────────────────────────────────────────────────────
const activeFunctionalBreakdown = computed(() => {
  const allClust = props.clusters || []
  let targetClusters: any[] = []

  if (hoveredEntity.value) {
    if (hoveredEntity.value.type === 'ribbon') {
      if (chordMode.value === 'sample-sample') {
        const s1 = hoveredEntity.value.id
        const s2 = hoveredEntity.value.targetId
        if (s1 && s2) {
          targetClusters = allClust.filter(c => !!c.presence_map?.[s1] && !!c.presence_map?.[s2])
        }
      }
    } else if (hoveredEntity.value.type === 'sample') {
      const sid = hoveredEntity.value.id
      targetClusters = allClust.filter(c => !!c.presence_map?.[sid])
    }
  } else if (props.selectedPair && chordMode.value === 'sample-sample') {
    const [s1, s2] = props.selectedPair
    targetClusters = allClust.filter(c => !!c.presence_map?.[s1] && !!c.presence_map?.[s2])
  }

  if (targetClusters.length === 0) return null

  const counts: Record<string, number> = {}
  FUNCTION_KEYS.forEach(k => counts[k] = 0)

  targetClusters.forEach(c => {
    const norm = normalizeCategoryName(inferClusterCategory(c))
    if (counts[norm] !== undefined) {
      counts[norm]! += 1
    }
  })

  return FUNCTION_KEYS
    .map(k => ({ key: k, count: counts[k] || 0, label: FUNCTION_DEFS[k]?.short || k, color: getCatColor(k) }))
    .filter(e => e.count > 0)
    .sort((a, b) => b.count - a.count)
})

// ─────────────────────────────────────────────────────────────────────────────
// 悬停交互事件处理
// ─────────────────────────────────────────────────────────────────────────────
function handleGroupMouseEnter(index: number) {
  if (chordMode.value === 'sample-sample') {
    const sid = sampleChordLayout.value?.ids[index]
    if (!sid) return
    const sname = props.sampleNames[sid] || sid
    const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }

    hoveredEntity.value = {
      type: 'sample',
      id: sid,
      name: sname,
      totalGenes: stat.total,
      uniqueGenes: stat.unique
    }
  } else {
    const layout = bipartiteChordLayout.value
    if (!layout) return
    if (index < layout.sIds.length) {
      const sid = layout.sIds[index]!
      const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }
      hoveredEntity.value = {
        type: 'sample',
        id: sid,
        name: props.sampleNames[sid] || sid,
        totalGenes: stat.total
      }
    } else {
      const fKey = layout.fKeys[index - layout.sIds.length]!
      const def = FUNCTION_DEFS[fKey] || { label: fKey, short: fKey, desc: '' }
      const allClust = props.clusters || []
      const catClusters = allClust.filter(c => normalizeCategoryName(inferClusterCategory(c)) === fKey)
      const coveredSids = new Set<string>()
      catClusters.forEach(c => {
        props.visibleSampleIds.forEach(sid => {
          if (c.presence_map?.[sid]) coveredSids.add(sid)
        })
      })

      hoveredEntity.value = {
        type: 'function',
        id: fKey,
        name: def.label,
        totalClustersInCat: catClusters.length,
        coveredSamples: coveredSids.size
      }
    }
  }
}

function handleRibbonMouseEnter(chordItem: d3.Chord) {
  if (chordMode.value === 'sample-sample') {
    const s1 = sampleChordLayout.value?.ids[chordItem.source.index]
    const s2 = sampleChordLayout.value?.ids[chordItem.target.index]
    if (!s1 || !s2) return
    const pairKey = `${s1}|${s2}`
    const shared = sampleMatrixData.value.sharedMap[pairKey] || []
    const ani = props.aniMatrix?.[s1]?.[s2] ?? 0
    const tailSim = props.tailMatrix?.[s1]?.[s2] ?? 0

    hoveredEntity.value = {
      type: 'ribbon',
      id: s1,
      name: props.sampleNames[s1] || s1,
      targetId: s2,
      targetName: props.sampleNames[s2] || s2,
      value: shared.length,
      ani,
      tailSim,
      sharedClusters: shared
    }
  } else {
    const layout = bipartiteChordLayout.value
    if (!layout) return
    const sIdx = chordItem.source.index < layout.sIds.length ? chordItem.source.index : chordItem.target.index
    const fIdx = chordItem.source.index >= layout.sIds.length ? chordItem.source.index - layout.sIds.length : chordItem.target.index - layout.sIds.length
    const sid = layout.sIds[sIdx]!
    const fKey = layout.fKeys[fIdx]!
    const def = FUNCTION_DEFS[fKey] || { label: fKey, short: fKey, desc: '' }

    hoveredEntity.value = {
      type: 'ribbon',
      id: sid,
      name: props.sampleNames[sid] || sid,
      targetId: fKey,
      targetName: def.label,
      value: chordItem.source.value
    }
  }
}

function handleMouseLeave() {
  hoveredEntity.value = null
}

function handleGroupClick(index: number) {
  if (chordMode.value === 'sample-sample') {
    const sid = sampleChordLayout.value?.ids[index]
    if (sid) emit('select-sample', sid)
  }
}

function handleRibbonClick(chordItem: d3.Chord) {
  if (chordMode.value === 'sample-sample') {
    const s1 = sampleChordLayout.value?.ids[chordItem.source.index]
    const s2 = sampleChordLayout.value?.ids[chordItem.target.index]
    if (s1 && s2 && s1 !== s2) {
      emit('select-pair', [s1, s2])
    }
  }
}

// 侧边图注联动
function handleLegendMouseEnter(sid: string, idx: number) {
  const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }
  hoveredEntity.value = {
    type: 'sample',
    id: sid,
    name: props.sampleNames[sid] || sid,
    totalGenes: stat.total,
    uniqueGenes: stat.unique
  }
}

function handleLegendFunctionMouseEnter(fKey: string) {
  const def = FUNCTION_DEFS[fKey] || { label: fKey, short: fKey, desc: '' }
  const allClust = props.clusters || []
  const catClusters = allClust.filter(c => normalizeCategoryName(inferClusterCategory(c)) === fKey)
  const coveredSids = new Set<string>()
  catClusters.forEach(c => {
    props.visibleSampleIds.forEach(sid => {
      if (c.presence_map?.[sid]) coveredSids.add(sid)
    })
  })

  hoveredEntity.value = {
    type: 'function',
    id: fKey,
    name: def.label,
    totalClustersInCat: catClusters.length,
    coveredSamples: coveredSids.size
  }
}

// 过滤后的样本列表
const filteredLegendSampleIds = computed(() => {
  const q = legendSearch.value.trim().toLowerCase()
  if (!q) return props.visibleSampleIds
  return props.visibleSampleIds.filter(sid => {
    const fullName = (props.sampleNames[sid] || sid).toLowerCase()
    const shortCode = getSampleShortName(sid).toLowerCase()
    return fullName.includes(q) || shortCode.includes(q)
  })
})
</script>

<template>
  <div class="chord-diagram-container">
    <!-- 顶部控制与过滤栏 -->
    <div class="chord-toolbar">
      <div class="left-controls">
        <div class="mode-switch-group">
          <span class="toolbar-label">拓扑视角:</span>
          <div class="segmented-pill">
            <button
              class="seg-item"
              :class="{ active: chordMode === 'sample-sample' }"
              @click="chordMode = 'sample-sample'"
            >
              样本间基因共享流 (两两互联)
            </button>
            <button
              class="seg-item"
              :class="{ active: chordMode === 'sample-function' }"
              @click="chordMode = 'sample-function'"
            >
              样本 ↔ 10 大功能系统关联
            </button>
          </div>
        </div>

        <!-- 关联阈值快捷梯度与滑块 -->
        <div v-if="chordMode === 'sample-sample'" class="filter-slider-group">
          <span class="toolbar-label">关联阈值:</span>
          <div class="step-buttons">
            <button
              v-for="st in [0, 5, 15, 30]"
              :key="st"
              class="step-btn"
              :class="{ active: minSharedThreshold === st }"
              @click="minSharedThreshold = st"
            >
              {{ st === 0 ? '全部' : `&ge;${st}` }}
            </button>
          </div>
          <input
            type="range"
            min="0"
            :max="maxSharedValue"
            step="1"
            v-model.number="minSharedThreshold"
            class="mini-range"
            title="拖动微调共享基因数过滤阈值"
          />
          <span class="threshold-tag">&ge; {{ minSharedThreshold }} 基因</span>
        </div>
      </div>

      <div class="status-summary-pill">
        <span v-if="chordMode === 'sample-sample'">
          当前显示 <strong>{{ sampleChordLayout?.validChords.length || 0 }}</strong> 条跨样本共享流
        </span>
        <span v-else>
          当前显示 <strong>{{ bipartiteChordLayout?.validChords.length || 0 }}</strong> 条功能操纵子映射
        </span>
      </div>
    </div>

    <!-- 主体双栏布局: 左侧大画幅居中弦图(零跳动) + 右侧独立可滚动样本图注列表(含固定高HUD) -->
    <div class="chord-main-layout">
      <!-- 1. 左侧大画幅居中弦图画布区域 (尺寸 100% 恒定，绝不跳动) -->
      <div class="chord-svg-viewport">
        <svg
          viewBox="-350 -350 700 700"
          class="chord-main-svg"
        >
          <!-- 模式 1: 样本间共享流 (Sample-to-Sample) -->
          <template v-if="chordMode === 'sample-sample' && sampleChordLayout">
            <!-- 内部平滑色带 Ribbons (纯净圆心、无遮挡流动) -->
            <g class="ribbons-layer">
              <path
                v-for="(d, i) in sampleChordLayout.validChords"
                :key="i"
                :d="getSampleRibbonPath(d)"
                :fill="getSampleColor(d.source.index)"
                :class="[
                  'chord-ribbon',
                  {
                    faded: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && hoveredEntity.id !== sampleChordLayout.ids[d.source.index] && hoveredEntity.id !== sampleChordLayout.ids[d.target.index]) ||
                      (hoveredEntity.type === 'ribbon' && (hoveredEntity.id !== sampleChordLayout.ids[d.source.index] || hoveredEntity.targetId !== sampleChordLayout.ids[d.target.index]))
                    ),
                    active: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && (hoveredEntity.id === sampleChordLayout.ids[d.source.index] || hoveredEntity.id === sampleChordLayout.ids[d.target.index])) ||
                      (hoveredEntity.type === 'ribbon' && (hoveredEntity.id === sampleChordLayout.ids[d.source.index] && hoveredEntity.targetId === sampleChordLayout.ids[d.target.index]))
                    )
                  }
                ]"
                @mouseenter="handleRibbonMouseEnter(d)"
                @mouseleave="handleMouseLeave"
                @click="handleRibbonClick(d)"
              />
            </g>

            <!-- 外圈弧段 Groups (仅渲染学术短标，例如 BC10-c5) -->
            <g class="groups-layer">
              <g
                v-for="(group, i) in sampleChordLayout.chords.groups"
                :key="i"
                class="chord-arc-group"
                @mouseenter="handleGroupMouseEnter(i)"
                @mouseleave="handleMouseLeave"
                @click="handleGroupClick(i)"
              >
                <path
                  :d="getSampleArcPath(group)"
                  :fill="getSampleColor(i)"
                  class="arc-path"
                />
                <g
                  :transform="`
                    rotate(${((group.startAngle + group.endAngle) / 2) * (180 / Math.PI) - 90})
                    translate(${outerRadius + 8}, 0)
                  `"
                >
                  <text
                    :text-anchor="((group.startAngle + group.endAngle) / 2) > Math.PI ? 'end' : 'start'"
                    :transform="((group.startAngle + group.endAngle) / 2) > Math.PI ? 'rotate(180)' : ''"
                    class="arc-label"
                  >
                    {{ getSampleShortName(sampleChordLayout.ids[i]!) }}
                  </text>
                </g>
              </g>
            </g>
          </template>

          <!-- 模式 2: 样本 ↔ 10 大功能模块二分关联 (Sample-to-Function) -->
          <template v-else-if="chordMode === 'sample-function' && bipartiteChordLayout">
            <g class="ribbons-layer">
              <path
                v-for="(d, i) in bipartiteChordLayout.validChords"
                :key="i"
                :d="getBipartiteRibbonPath(d)"
                :fill="d.source.index < bipartiteChordLayout.sIds.length ? getSampleColor(d.source.index) : getCatColor(bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length]!)"
                :class="[
                  'chord-ribbon',
                  {
                    faded: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && hoveredEntity.id !== bipartiteChordLayout.sIds[d.source.index] && hoveredEntity.id !== bipartiteChordLayout.sIds[d.target.index]) ||
                      (hoveredEntity.type === 'function' && hoveredEntity.id !== bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length] && hoveredEntity.id !== bipartiteChordLayout.fKeys[d.target.index - bipartiteChordLayout.sIds.length])
                    ),
                    active: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && (hoveredEntity.id === bipartiteChordLayout.sIds[d.source.index] || hoveredEntity.id === bipartiteChordLayout.sIds[d.target.index])) ||
                      (hoveredEntity.type === 'function' && (hoveredEntity.id === bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length] || hoveredEntity.id === bipartiteChordLayout.fKeys[d.target.index - bipartiteChordLayout.sIds.length]))
                    )
                  }
                ]"
                @mouseenter="handleRibbonMouseEnter(d)"
                @mouseleave="handleMouseLeave"
              />
            </g>

            <!-- 外圈弧段 -->
            <g class="groups-layer">
              <g
                v-for="(group, i) in bipartiteChordLayout.chords.groups"
                :key="i"
                class="chord-arc-group"
                @mouseenter="handleGroupMouseEnter(i)"
                @mouseleave="handleMouseLeave"
              >
                <path
                  :d="getBipartiteArcPath(group)"
                  :fill="i < bipartiteChordLayout.sIds.length ? getSampleColor(i) : getCatColor(bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]!)"
                  class="arc-path"
                />
                <g
                  :transform="`
                    rotate(${((group.startAngle + group.endAngle) / 2) * (180 / Math.PI) - 90})
                    translate(${outerRadius + 8}, 0)
                  `"
                >
                  <text
                    :text-anchor="((group.startAngle + group.endAngle) / 2) > Math.PI ? 'end' : 'start'"
                    :transform="((group.startAngle + group.endAngle) / 2) > Math.PI ? 'rotate(180)' : ''"
                    class="arc-label"
                    :class="{ 'func-label': i >= bipartiteChordLayout.sIds.length }"
                  >
                    {{ i < bipartiteChordLayout.sIds.length ? getSampleShortName(bipartiteChordLayout.sIds[i]!) : (FUNCTION_DEFS[bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]!]?.short || bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]) }}
                  </text>
                </g>
              </g>
            </g>
          </template>
        </svg>
      </div>

      <!-- 2. 右侧【即时拓扑指标探针 (固定高度 HUD) + 样本学术图注栏】 -->
      <div class="chord-legend-sidebar">
        <!-- 顶部: 即时拓扑指标探针面板 (高度严格固定为 116px，内部平滑切换，绝不跳动) -->
        <div class="inspector-hud-panel">
          <!-- 悬停样本探针 -->
          <template v-if="hoveredEntity?.type === 'sample'">
            <div class="hud-header">
              <span class="hud-badge sample">噬菌体分离株</span>
              <span class="hud-code">{{ getSampleShortName(hoveredEntity.id) }}</span>
            </div>
            <div class="hud-name" :title="hoveredEntity.name">{{ hoveredEntity.name }}</div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">拥有家族</span>
                <strong class="hud-stat-val">{{ hoveredEntity.totalGenes }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">独有特异</span>
                <strong class="hud-stat-val c-amber">{{ hoveredEntity.uniqueGenes }}</strong>
              </div>
            </div>
          </template>

          <!-- 悬停功能系统探针 -->
          <template v-else-if="hoveredEntity?.type === 'function'">
            <div class="hud-header">
              <span class="hud-badge func">生物学功能系统</span>
            </div>
            <div class="hud-name">{{ hoveredEntity.name }}</div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">泛基因家族数</span>
                <strong class="hud-stat-val">{{ hoveredEntity.totalClustersInCat }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">覆盖株系</span>
                <strong class="hud-stat-val highlight">{{ hoveredEntity.coveredSamples }}/{{ props.visibleSampleIds.length }}</strong>
              </div>
            </div>
          </template>

          <!-- 悬停跨株连线探针 -->
          <template v-else-if="hoveredEntity?.type === 'ribbon'">
            <div class="hud-header">
              <span class="hud-badge ribbon">
                {{ chordMode === 'sample-sample' ? '跨株同源共享流' : '样本 ↔ 功能映射' }}
              </span>
            </div>
            <div class="hud-pair-row">
              <span class="pair-tag">{{ getSampleShortName(hoveredEntity.id) }}</span>
              <span class="pair-arrow">↔</span>
              <span class="pair-tag">{{ chordMode === 'sample-sample' ? getSampleShortName(hoveredEntity.targetId || '') : hoveredEntity.targetName }}</span>
            </div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">{{ chordMode === 'sample-sample' ? '共享家族数' : '所含基因' }}</span>
                <strong class="hud-stat-val highlight">{{ hoveredEntity.value }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">{{ hoveredEntity.ani ? '全蛋白 ANI' : '拓扑状态' }}</span>
                <strong class="hud-stat-val">{{ hoveredEntity.ani ? `${hoveredEntity.ani.toFixed(1)}%` : '已连接' }}</strong>
              </div>
            </div>
          </template>

          <!-- 默认全局概况 -->
          <template v-else>
            <div class="hud-header">
              <span class="hud-badge overview">群体拓扑概览</span>
              <span class="hud-code">{{ props.visibleSampleIds.length }} 株</span>
            </div>
            <div class="hud-default-txt">
              悬停或点击任意弧段/连线，即时检视同源共享与功能构成。
            </div>
          </template>
        </div>

        <!-- 侧栏图注头部 -->
        <div class="legend-sidebar-head">
          <span class="sidebar-title">
            {{ chordMode === 'sample-sample' ? '样本色系图注' : '噬菌体与功能图注' }}
          </span>
          <span class="sidebar-count">{{ props.visibleSampleIds.length }} 样本</span>
        </div>

        <!-- 样本搜索过滤 -->
        <div class="legend-search-box">
          <input
            v-model="legendSearch"
            placeholder="搜索样本全称或短标..."
            class="legend-search-input"
          />
        </div>

        <!-- 样本列表 (支持顺畅滚动，卡片高度固定不压缩) -->
        <div class="legend-scroll-wrap">
          <!-- 模式 2 时的功能系统分组 -->
          <div v-if="chordMode === 'sample-function'" class="legend-section-title">
            10 大生物学功能操纵子
          </div>
          <div v-if="chordMode === 'sample-function'" class="func-legend-grid">
            <div
              v-for="fKey in FUNCTION_KEYS"
              :key="fKey"
              class="func-legend-chip"
              :class="{ active: hoveredEntity && hoveredEntity.id === fKey }"
              @mouseenter="handleLegendFunctionMouseEnter(fKey)"
              @mouseleave="handleMouseLeave"
            >
              <i class="func-dot" :style="{ backgroundColor: getCatColor(fKey) }"></i>
              <span class="func-lbl">{{ FUNCTION_DEFS[fKey]?.label }}</span>
            </div>
          </div>

          <div v-if="chordMode === 'sample-function'" class="legend-section-title" style="margin-top: 10px;">
            噬菌体分离株列表
          </div>

          <!-- 样本卡片列表 (flex-shrink: 0, min-height: 46px 确保名称清晰完整) -->
          <div
            v-for="(sid, idx) in filteredLegendSampleIds"
            :key="sid"
            class="legend-sample-card"
            :class="{
              active: hoveredEntity && (hoveredEntity.id === sid || hoveredEntity.targetId === sid),
              selected: selectedPair && (selectedPair[0] === sid || selectedPair[1] === sid)
            }"
            @mouseenter="handleLegendMouseEnter(sid, idx)"
            @mouseleave="handleMouseLeave"
            @click="emit('select-sample', sid)"
          >
            <div class="card-left-bar" :style="{ backgroundColor: getSampleColor(props.visibleSampleIds.indexOf(sid)) }"></div>
            <div class="card-content">
              <div class="card-top-row">
                <span class="card-short-tag" :style="{ color: getSampleColor(props.visibleSampleIds.indexOf(sid)) }">
                  {{ getSampleShortName(sid) }}
                </span>
                <span class="card-genes-badge">
                  {{ sampleStatsMap[sid]?.total || 0 }} CDS
                </span>
              </div>
              <div class="card-fullname" :title="props.sampleNames[sid] || sid">
                {{ props.sampleNames[sid] || sid }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chord-diagram-container {
  display: flex;
  flex-direction: column;
  height: 680px;
  max-height: 680px;
  background: #ffffff;
  border-radius: 10px;
  overflow: hidden;
  position: relative;
}

/* 顶部工具栏 */
.chord-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  gap: 12px;
  flex-shrink: 0;
}

.left-controls {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mode-switch-group, .filter-slider-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
}

.segmented-pill {
  display: flex;
  background: #e2e8f0;
  padding: 2px;
  border-radius: 6px;
}

.seg-item {
  background: transparent;
  border: none;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.seg-item.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}

.step-buttons {
  display: flex;
  gap: 3px;
}

.step-btn {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.68rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}

.step-btn:hover {
  background: #f1f5f9;
}

.step-btn.active {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.mini-range {
  width: 80px;
  cursor: pointer;
}

.threshold-tag {
  font-size: 0.7rem;
  font-weight: 700;
  color: #2563eb;
  font-family: 'JetBrains Mono', monospace;
}

.status-summary-pill {
  font-size: 0.7rem;
  color: #64748b;
  background: #f1f5f9;
  padding: 3px 10px;
  border-radius: 6px;
}

.status-summary-pill strong {
  color: #0f172a;
}

/* 主体双栏布局 */
.chord-main-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左侧弦图区域 (绝对零抖动) */
.chord-svg-viewport {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 10px;
  background: #ffffff;
}

.chord-main-svg {
  width: 100%;
  height: 100%;
  max-width: 580px;
  max-height: 580px;
  display: block;
}

/* 弦与弧段样式 */
.chord-ribbon {
  fill-opacity: 0.55;
  transition: fill-opacity 0.2s, stroke 0.2s;
  cursor: pointer;
}

.chord-ribbon:hover,
.chord-ribbon.active {
  fill-opacity: 0.9;
  stroke: #0f172a;
  stroke-width: 1px;
}

.chord-ribbon.faded {
  fill-opacity: 0.04;
}

.chord-arc-group {
  cursor: pointer;
}

.arc-path {
  transition: transform 0.15s;
}

.chord-arc-group:hover .arc-path {
  filter: brightness(1.15);
}

.arc-label {
  font-size: 8.5px;
  font-family: 'JetBrains Mono', -apple-system, BlinkMacSystemFont, monospace;
  fill: #334155;
  font-weight: 700;
  pointer-events: none;
}

.arc-label.func-label {
  font-weight: 800;
  fill: #0f172a;
  font-size: 9px;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 2. 右侧【即时拓扑探针 (Inspector HUD) + 样本图注栏】
 * ───────────────────────────────────────────────────────────────────────────── */
.chord-legend-sidebar {
  width: 280px;
  background: #f8fafc;
  border-left: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;
}

/* 顶部即时探针 HUD: 高度严格固定 116px，绝不产生高度跳动 */
.inspector-hud-panel {
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  height: 116px;
  min-height: 116px;
  max-height: 116px;
  box-sizing: border-box;
  justify-content: center;
  flex-shrink: 0;
}

.hud-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hud-badge {
  font-size: 0.62rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}

.hud-badge.sample {
  background: #eff6ff;
  color: #2563eb;
}

.hud-badge.func {
  background: #f0fdf4;
  color: #16a34a;
}

.hud-badge.ribbon {
  background: #faf5ff;
  color: #9333ea;
}

.hud-badge.overview {
  background: #f1f5f9;
  color: #475569;
}

.hud-code {
  font-size: 0.75rem;
  font-weight: 700;
  color: #2563eb;
  font-family: 'JetBrains Mono', monospace;
}

.hud-name {
  font-size: 0.74rem;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hud-pair-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  font-weight: 700;
  color: #0f172a;
}

.pair-tag {
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
}

.pair-arrow {
  color: #94a3b8;
}

.hud-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  background: #f8fafc;
  border-radius: 4px;
  padding: 4px 8px;
}

.hud-stat-cell {
  display: flex;
  flex-direction: column;
}

.hud-stat-lbl {
  font-size: 0.58rem;
  color: #64748b;
}

.hud-stat-val {
  font-size: 0.8rem;
  color: #0f172a;
  font-family: 'JetBrains Mono', monospace;
}

.hud-stat-val.highlight {
  color: #2563eb;
}

.hud-stat-val.c-amber {
  color: #d97706;
}

.hud-default-txt {
  font-size: 0.68rem;
  color: #64748b;
  line-height: 1.4;
}

/* 图注头部 */
.legend-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.sidebar-title {
  font-size: 0.72rem;
  font-weight: 700;
  color: #1e293b;
}

.sidebar-count {
  font-size: 0.65rem;
  font-weight: 600;
  background: #eff6ff;
  color: #2563eb;
  padding: 1px 5px;
  border-radius: 4px;
}

.legend-search-box {
  padding: 5px 10px;
  background: #ffffff;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}

.legend-search-input {
  width: 100%;
  padding: 3px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 0.7rem;
  box-sizing: border-box;
}

.legend-search-input:focus {
  outline: none;
  border-color: #2563eb;
}

.legend-scroll-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.legend-scroll-wrap::-webkit-scrollbar {
  width: 5px;
}

.legend-scroll-wrap::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.legend-scroll-wrap::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

.legend-section-title {
  font-size: 0.65rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  margin-bottom: 2px;
  flex-shrink: 0;
}

.func-legend-grid {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex-shrink: 0;
}

.func-legend-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-size: 0.68rem;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
  min-height: 24px;
}

.func-legend-chip:hover, .func-legend-chip.active {
  background: #f1f5f9;
  border-color: #94a3b8;
  font-weight: 600;
}

.func-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}

.func-lbl {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 样本卡片 */
.legend-sample-card {
  display: flex;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
  min-height: 46px;
}

.legend-sample-card:hover, .legend-sample-card.active {
  border-color: #2563eb;
  background: #eff6ff;
  transform: translateX(-1px);
}

.card-left-bar {
  width: 4px;
  flex-shrink: 0;
}

.card-content {
  flex: 1;
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  min-width: 0;
}

.card-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-short-tag {
  font-size: 0.72rem;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}

.card-genes-badge {
  font-size: 0.62rem;
  color: #64748b;
  font-weight: 600;
}

.card-fullname {
  font-size: 0.66rem;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}
</style>
