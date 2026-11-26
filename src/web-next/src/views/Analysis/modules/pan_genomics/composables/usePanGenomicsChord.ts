import { computed, ref } from 'vue'
import * as d3 from 'd3'
import {
  getCatColor,
  inferClusterCategory,
  normalizeCategoryName,
} from '../utils/pangenomeVariants'

export interface ChordClusterItem {
  cluster_id?: string
  product?: string
  category?: string
  presence_map?: Record<string, boolean | number | string | null | undefined>
  [key: string]: unknown
}

export interface ChordHoveredEntity {
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
  sharedClusters?: ChordClusterItem[]
}

export interface PanGenomicsChordProps {
  clusters: ChordClusterItem[]
  sampleNames: Record<string, string>
  visibleSampleIds: string[]
  aniMatrix?: Record<string, Record<string, number | null>>
  tailMatrix?: Record<string, Record<string, number>>
  lifestyles?: Record<string, unknown>[]
  selectedPair?: [string, string] | null
}

export interface PanGenomicsChordEmits {
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
  (e: 'open-cluster-drawer', cluster: ChordClusterItem): void
}

export const CHORD_OUTER_RADIUS = 250
export const CHORD_INNER_RADIUS = CHORD_OUTER_RADIUS - 20

export const FUNCTION_DEFS: Record<string, { label: string; short: string; desc: string }> = {
  'Tail & Host Interaction': { label: '尾部与尾丝吸附', short: '尾丝/受体吸附', desc: '尾丝、刺突、受体结合蛋白 (RBP) 与吸附结构' },
  'Lysis': { label: '宿主裂解系统', short: '宿主裂解', desc: '内溶素 (Endolysin)、穿孔素 (Holin) 与跨膜裂解酶' },
  'Defense & Host Interaction': { label: '宿主防御与互作', short: '防御互作 (Acr)', desc: '抗 CRISPR (Acr)、抗限制修饰系统与宿主逃逸元件' },
  'Head & Packaging': { label: '头部与衣壳包装', short: '头衣壳包装', desc: '主衣壳、末端酶 (Terminase) 与门户连接器' },
  'Integration & Excision': { label: '溶原整合与切除', short: '整合切除', desc: '整合酶 (Integrase)、切除酶 (Excisionase) 与重组方向因子' },
  'Replication & Repair': { label: 'DNA复制与重组修复', short: 'DNA复制修复', desc: 'DNA 聚合酶、解旋酶、引物酶、单链结合蛋白与连接酶' },
  'Transcription & Regulation': { label: '转录调控与开关', short: '转录调控', desc: '转录阻遏蛋白、转录激活因子与休眠开关' },
  'Metabolism & AMG': { label: '辅助代谢基因', short: '辅助代谢 (AMG)', desc: '核苷酸合成、碳代谢与能量辅助代谢基因' },
  'Other Functional': { label: '其他功能蛋白', short: '其他功能', desc: '转运通道、分子伴侣、膜蛋白与通用功能分子' },
  'Hypothetical': { label: '假定蛋白与未表征', short: '假定蛋白', desc: '假定蛋白、未知功能结构域 (DUF) 与未表征基因' },
}

export const FUNCTION_KEYS = Object.keys(FUNCTION_DEFS)

const SAMPLE_PALETTE = [
  '#2563eb', '#3b82f6', '#60a5fa', '#0d9488', '#14b8a6', '#059669', '#10b981',
  '#f59e0b', '#d97706', '#ea580c', '#f43f5e', '#e11d48', '#8b5cf6', '#7c3aed',
  '#6366f1', '#4f46e5', '#0284c7', '#0369a1', '#475569', '#64748b', '#0891b2', '#0e7490',
]

export function getSampleColor(index: number): string {
  return SAMPLE_PALETTE[index % SAMPLE_PALETTE.length] || '#3b82f6'
}

export function usePanGenomicsChord(
  props: PanGenomicsChordProps,
  emit: PanGenomicsChordEmits
) {
  const chordMode = ref<'sample-sample' | 'sample-function'>('sample-sample')
  const minSharedThreshold = ref<number>(5)
  const legendSearch = ref<string>('')
  const hoveredEntity = ref<ChordHoveredEntity | null>(null)

  function getSampleShortName(sid: string): string {
    const fullName = props.sampleNames[sid] || sid
    const bcMatch = fullName.match(/^(BC\d+)[-_]contig_?(\d+)/i)
    if (bcMatch) return `${bcMatch[1]}-c${bcMatch[2]}`
    const simpleBc = fullName.match(/^(BC\d+)/i)
    if (simpleBc) return simpleBc[1]!
    const ahyMatch = fullName.match(/phage\s*([A-Za-z0-9]+)/i)
    if (ahyMatch) return ahyMatch[1]!
    return fullName.length > 10 ? `${fullName.slice(0, 8)}..` : fullName
  }

  const sampleMatrixData = computed(() => {
    const ids = props.visibleSampleIds
    const n = ids.length
    if (n < 2 || !props.clusters || props.clusters.length === 0) {
      return { matrix: [] as number[][], ids: [] as string[], sharedMap: {} as Record<string, ChordClusterItem[]> }
    }
    const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0))
    const sharedMap: Record<string, ChordClusterItem[]> = {}

    props.clusters.forEach((c) => {
      const presentIds = ids.filter((sid) => Boolean(c.presence_map?.[sid]))
      for (let i = 0; i < presentIds.length; i += 1) {
        for (let j = i; j < presentIds.length; j += 1) {
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

  const sampleStatsMap = computed(() => {
    const allClust = props.clusters || []
    const map: Record<string, { total: number; unique: number }> = {}
    props.visibleSampleIds.forEach((sid) => {
      const total = allClust.filter((c) => Boolean(c.presence_map?.[sid])).length
      const unique = allClust.filter((c) => {
        if (!c.presence_map?.[sid]) return false
        return Object.values(c.presence_map).filter(Boolean).length === 1
      }).length
      map[sid] = { total, unique }
    })
    return map
  })

  const maxSharedValue = computed(() => {
    let mx = 10
    const m = sampleMatrixData.value.matrix
    for (let i = 0; i < m.length; i += 1) {
      for (let j = i + 1; j < m.length; j += 1) {
        const v = m[i]?.[j] ?? 0
        if (v > mx) mx = v
      }
    }
    return mx
  })

  const arcGenerator = d3.arc<d3.ChordGroup>().innerRadius(CHORD_INNER_RADIUS).outerRadius(CHORD_OUTER_RADIUS)
  const ribbonGenerator = d3.ribbon<d3.Chord, d3.ChordSubgroup>().radius(CHORD_INNER_RADIUS - 2)

  const sampleChordLayout = computed(() => {
    const { matrix, ids } = sampleMatrixData.value
    if (!matrix.length) return null
    const thresh = minSharedThreshold.value
    const filteredMatrix = matrix.map((row, i) =>
      row.map((val, j) => {
        if (i === j) return Math.max(15, sampleStatsMap.value[ids[i]!]?.total || 15)
        return val >= thresh ? val : 0
      })
    )
    const chords = d3.chord().padAngle(0.035).sortSubgroups(d3.descending)(filteredMatrix)
    const validChords = chords.filter((c) => c.source.index !== c.target.index && c.source.value >= thresh)
    return { chords, validChords, ids }
  })

  function getRibbonPath(d: d3.Chord): string {
    return ribbonGenerator(d) ?? ''
  }

  function getArcPath(group: d3.ChordGroup): string {
    return arcGenerator(group) ?? ''
  }

  const bipartiteMatrixData = computed(() => {
    const sIds = props.visibleSampleIds
    const fKeys = FUNCTION_KEYS
    const totalDim = sIds.length + fKeys.length
    if (sIds.length === 0 || !props.clusters) return null

    const matrix: number[][] = Array.from({ length: totalDim }, () => Array(totalDim).fill(0))
    props.clusters.forEach((c) => {
      const normCat = normalizeCategoryName(inferClusterCategory(c))
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

  const bipartiteChordLayout = computed(() => {
    const data = bipartiteMatrixData.value
    if (!data) return null
    const chords = d3.chord().padAngle(0.025).sortSubgroups(d3.descending)(data.matrix)
    const validChords = chords.filter((c) => c.source.index !== c.target.index && c.source.value > 0)
    return { chords, validChords, ...data }
  })

  function buildFunctionHover(fKey: string): ChordHoveredEntity {
    const def = FUNCTION_DEFS[fKey] || { label: fKey, short: fKey, desc: '' }
    const catClusters = (props.clusters || []).filter(
      (c) => normalizeCategoryName(inferClusterCategory(c)) === fKey
    )
    const coveredSids = new Set<string>()
    catClusters.forEach((c) => {
      props.visibleSampleIds.forEach((sid) => {
        if (c.presence_map?.[sid]) coveredSids.add(sid)
      })
    })
    return {
      type: 'function',
      id: fKey,
      name: def.label,
      totalClustersInCat: catClusters.length,
      coveredSamples: coveredSids.size,
    }
  }

  function handleGroupMouseEnter(index: number): void {
    if (chordMode.value === 'sample-sample') {
      const sid = sampleChordLayout.value?.ids[index]
      if (!sid) return
      const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }
      hoveredEntity.value = {
        type: 'sample',
        id: sid,
        name: props.sampleNames[sid] || sid,
        totalGenes: stat.total,
        uniqueGenes: stat.unique,
      }
      return
    }
    const layout = bipartiteChordLayout.value
    if (!layout) return
    if (index < layout.sIds.length) {
      const sid = layout.sIds[index]!
      const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }
      hoveredEntity.value = {
        type: 'sample',
        id: sid,
        name: props.sampleNames[sid] || sid,
        totalGenes: stat.total,
      }
    } else {
      hoveredEntity.value = buildFunctionHover(layout.fKeys[index - layout.sIds.length]!)
    }
  }

  function handleRibbonMouseEnter(chordItem: d3.Chord): void {
    if (chordMode.value === 'sample-sample') {
      const s1 = sampleChordLayout.value?.ids[chordItem.source.index]
      const s2 = sampleChordLayout.value?.ids[chordItem.target.index]
      if (!s1 || !s2) return
      const shared = sampleMatrixData.value.sharedMap[`${s1}|${s2}`] || []
      hoveredEntity.value = {
        type: 'ribbon',
        id: s1,
        name: props.sampleNames[s1] || s1,
        targetId: s2,
        targetName: props.sampleNames[s2] || s2,
        value: shared.length,
        ani: props.aniMatrix?.[s1]?.[s2] ?? 0,
        tailSim: props.tailMatrix?.[s1]?.[s2] ?? 0,
        sharedClusters: shared,
      }
      return
    }
    const layout = bipartiteChordLayout.value
    if (!layout) return
    const sIdx = chordItem.source.index < layout.sIds.length ? chordItem.source.index : chordItem.target.index
    const fIdx =
      chordItem.source.index >= layout.sIds.length
        ? chordItem.source.index - layout.sIds.length
        : chordItem.target.index - layout.sIds.length
    const sid = layout.sIds[sIdx]!
    const fKey = layout.fKeys[fIdx]!
    const def = FUNCTION_DEFS[fKey] || { label: fKey, short: fKey, desc: '' }
    hoveredEntity.value = {
      type: 'ribbon',
      id: sid,
      name: props.sampleNames[sid] || sid,
      targetId: fKey,
      targetName: def.label,
      value: chordItem.source.value,
    }
  }

  function handleMouseLeave(): void {
    hoveredEntity.value = null
  }

  function handleGroupClick(index: number): void {
    if (chordMode.value === 'sample-sample') {
      const sid = sampleChordLayout.value?.ids[index]
      if (sid) emit('select-sample', sid)
    }
  }

  function handleRibbonClick(chordItem: d3.Chord): void {
    if (chordMode.value === 'sample-sample') {
      const s1 = sampleChordLayout.value?.ids[chordItem.source.index]
      const s2 = sampleChordLayout.value?.ids[chordItem.target.index]
      if (s1 && s2 && s1 !== s2) emit('select-pair', [s1, s2])
    }
  }

  function handleLegendMouseEnter(sid: string): void {
    const stat = sampleStatsMap.value[sid] || { total: 0, unique: 0 }
    hoveredEntity.value = {
      type: 'sample',
      id: sid,
      name: props.sampleNames[sid] || sid,
      totalGenes: stat.total,
      uniqueGenes: stat.unique,
    }
  }

  function handleLegendFunctionMouseEnter(fKey: string): void {
    hoveredEntity.value = buildFunctionHover(fKey)
  }

  const filteredLegendSampleIds = computed(() => {
    const q = legendSearch.value.trim().toLowerCase()
    if (!q) return props.visibleSampleIds
    return props.visibleSampleIds.filter((sid) => {
      const fullName = (props.sampleNames[sid] || sid).toLowerCase()
      return fullName.includes(q) || getSampleShortName(sid).toLowerCase().includes(q)
    })
  })

  return {
    chordMode,
    minSharedThreshold,
    legendSearch,
    hoveredEntity,
    sampleStatsMap,
    maxSharedValue,
    sampleChordLayout,
    bipartiteChordLayout,
    filteredLegendSampleIds,
    getSampleShortName,
    getRibbonPath,
    getArcPath,
    getCatColor,
    handleGroupMouseEnter,
    handleRibbonMouseEnter,
    handleMouseLeave,
    handleGroupClick,
    handleRibbonClick,
    handleLegendMouseEnter,
    handleLegendFunctionMouseEnter,
  }
}
