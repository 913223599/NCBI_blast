<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  PhageBaseFeature,
  PhageBaseTrackBin,
  PhageContigOverlayData,
  PhageContigSummary,
  PhageRegionItem,
  PhageRejectedCandidate,
  PhageScoreTrackBin,
} from '../types'

const props = defineProps<{
  contigs: PhageContigSummary[]
  selectedContigId: string
  overlayData: PhageContigOverlayData | null
  isLoading: boolean
  selectedRegionIndex: number
}>()

const emit = defineEmits<{
  (e: 'update:selectedContigId', contigId: string): void
  (e: 'select-region', region: PhageRegionItem): void
  (e: 'open-overlay-viewer', contigId: string): void
  (e: 'open-region-viewer', regionIndex: number): void
  (e: 'open-annotation', regionIndex?: number): void
}>()

// ─── 视图模式与图层显隐状态 ───
const viewMode = ref<'linear' | 'circular'>('linear')
const showBaseFeatures = ref<boolean>(true)
const showScoreCurve = ref<boolean>(true)
const showGcTrack = ref<boolean>(true)
const showGcSkew = ref<boolean>(true)
const showRejected = ref<boolean>(true)

// ─── 底图搜索与检视状态 ───
const featureSearch = ref<string>('')
const searchCursor = ref<number>(0)
const inspectedFeature = ref<PhageBaseFeature | null>(null)
const hoverTip = ref<{
  visible: boolean
  x: number
  y: number
  title: string
  subtitle: string
  meta: string
  accent: string
}>({
  visible: false,
  x: 0,
  y: 0,
  title: '',
  subtitle: '',
  meta: '',
  accent: '#2563eb',
})

// ─── 线性视图坐标范围 [viewStart, viewEnd] ───
const viewStartBp = ref<number>(0)
const viewEndBp = ref<number>(1000)

// ─── 环形视图变换 (缩放 & 平移) ───
const circScale = ref<number>(1)
const circPanX = ref<number>(0)
const circPanY = ref<number>(0)

// 拖拽交互状态
const svgCanvasRef = ref<SVGSVGElement | null>(null)
let dragActive = false
let dragStartX = 0
let dragStartY = 0
let dragOriginStartBp = 0
let dragOriginEndBp = 0
let dragOriginPanX = 0
let dragOriginPanY = 0

const totalLenBp = computed(() => Math.max(1, Number(props.overlayData?.length_bp || 1)))
const avgGcPct = computed(() => Number(props.overlayData?.gc_percent || 50))
const allRegions = computed<PhageRegionItem[]>(() => props.overlayData?.regions || [])
const allRejected = computed<PhageRejectedCandidate[]>(
  () => props.overlayData?.rejected_candidates || []
)
const allBaseFeatures = computed<PhageBaseFeature[]>(() => props.overlayData?.base_features || [])
const allScoreBins = computed<PhageScoreTrackBin[]>(() => props.overlayData?.score_tracks || [])
const allBaseBins = computed<PhageBaseTrackBin[]>(() => props.overlayData?.base_tracks || [])

// 切换 Contig 或新数据到达时重置视口
watch(
  () => [props.overlayData?.contig_id, props.overlayData?.length_bp],
  ([cid, len]) => {
    if (!cid || !len) return
    viewStartBp.value = 0
    viewEndBp.value = Number(len)
    circScale.value = 1
    circPanX.value = 0
    circPanY.value = 0
    inspectedFeature.value = null
  },
  { immediate: true }
)

// 搜索匹配特征计算
const matchedFeatureIndices = computed<Set<number>>(() => {
  const kw = featureSearch.value.trim().toLowerCase()
  const out = new Set<number>()
  if (!kw) return out
  for (const f of allBaseFeatures.value) {
    const text = `${f.type} ${f.locus_tag} ${f.gene} ${f.product} ${f.note} ${f.overlay_region_id || ''}`.toLowerCase()
    if (text.includes(kw)) {
      out.add(f.index)
    }
  }
  return out
})

const matchedFeatureList = computed<PhageBaseFeature[]>(() => {
  if (matchedFeatureIndices.value.size === 0) return []
  return allBaseFeatures.value.filter((f) => matchedFeatureIndices.value.has(f.index))
})

watch(featureSearch, () => {
  searchCursor.value = 0
})

function jumpToMatchedFeature(step: number): void {
  const list = matchedFeatureList.value
  if (list.length === 0) return
  const nextIdx = (searchCursor.value + step + list.length) % list.length
  searchCursor.value = nextIdx
  const feat = list[nextIdx]
  if (feat) {
    inspectedFeature.value = feat
    focusInterval(feat.start_bp, feat.end_bp, 6000)
  }
}

function focusInterval(startBp: number, endBp: number, flankBp = 5000): void {
  const len = totalLenBp.value
  const s = Math.max(0, startBp - flankBp)
  const e = Math.min(len, endBp + flankBp)
  if (e - s < 2000 && len >= 2000) {
    const mid = 0.5 * (startBp + endBp)
    viewStartBp.value = Math.max(0, Math.round(mid - 1000))
    viewEndBp.value = Math.min(len, Math.round(mid + 1000))
  } else {
    viewStartBp.value = Math.round(s)
    viewEndBp.value = Math.round(e)
  }
  if (viewMode.value === 'circular') {
    viewMode.value = 'linear'
  }
}

function focusRegion(region: PhageRegionItem): void {
  emit('select-region', region)
  const pad = Math.max(4000, Math.round(region.length_bp * 0.35))
  focusInterval(region.start_bp, region.end_bp, pad)
}

function resetView(): void {
  viewStartBp.value = 0
  viewEndBp.value = totalLenBp.value
  circScale.value = 1
  circPanX.value = 0
  circPanY.value = 0
}

function zoomLinear(factor: number, anchorRatio = 0.5): void {
  const len = totalLenBp.value
  const span = Math.max(1000, viewEndBp.value - viewStartBp.value)
  const nextSpan = Math.max(Math.min(len, 1500), Math.min(len, span / factor))
  const anchorBp = viewStartBp.value + span * anchorRatio
  let ns = anchorBp - nextSpan * anchorRatio
  let ne = ns + nextSpan
  if (ns < 0) {
    ne -= ns
    ns = 0
  }
  if (ne > len) {
    ns -= ne - len
    ne = len
  }
  viewStartBp.value = Math.max(0, Math.round(ns))
  viewEndBp.value = Math.min(len, Math.round(ne))
}

function zoomCircular(factor: number): void {
  circScale.value = Math.max(0.6, Math.min(8.0, circScale.value * factor))
}

const linearZoomFactor = computed(() => {
  const span = Math.max(1, viewEndBp.value - viewStartBp.value)
  return totalLenBp.value / span
})

// ─── 颜色与语义样式判定 ───
function getBaseFeatureColor(f: PhageBaseFeature): string {
  if (matchedFeatureIndices.value.has(f.index)) return '#eab308'
  const t = (f.type || '').toLowerCase()
  if (t === 'trna') return '#0d9488'
  if (t === 'rrna') return '#6366f1'
  const text = `${f.gene} ${f.product} ${f.note}`.toLowerCase()
  if (/(integrase|transposase|recombinase|excisionase)/.test(text)) return '#9333ea'
  if (f.in_prophage) return '#1d4ed8'
  return '#94a3b8'
}

// ─── 线性模式 SVG 几何常量与投影 ───
const LIN_W = 920
const LIN_H = 368
const LIN_PAD_L = 48
const LIN_PAD_R = 20
const LIN_PLOT_W = LIN_W - LIN_PAD_L - LIN_PAD_R

function linX(bp: number): number {
  const s = viewStartBp.value
  const span = Math.max(1, viewEndBp.value - s)
  return LIN_PAD_L + ((bp - s) / span) * LIN_PLOT_W
}

const linearTicks = computed(() => {
  const s = viewStartBp.value
  const e = viewEndBp.value
  const span = Math.max(1, e - s)
  const roughStep = span / 6
  const mag = Math.pow(10, Math.floor(Math.log10(roughStep)))
  const norm = roughStep / mag
  let nice = 1
  if (norm >= 5) nice = 5
  else if (norm >= 2) nice = 2
  const step = Math.max(100, Math.round(nice * mag))
  const firstTick = Math.ceil(s / step) * step
  const ticks: { x: number; label: string; bp: number }[] = []
  for (let bp = firstTick; bp <= e; bp += step) {
    ticks.push({
      bp,
      x: linX(bp),
      label: formatBpAxis(bp),
    })
  }
  return ticks
})

function formatBpAxis(bp: number): string {
  if (bp >= 1_000_000) return `${(bp / 1_000_000).toFixed(2)} Mb`
  if (bp >= 1_000) return `${(bp / 1_000).toFixed(1)} kb`
  return `${bp} bp`
}

// 视口过滤后的线性底图特征（超密全基因组视口下智能合并普通宿主基因，保留关键/匹配特征以防 SVG DOM 过重）
interface LinearRenderedFeature {
  feat: PhageBaseFeature
  x1: number
  x2: number
  pathD: string
  color: string
  opacity: number
  isMatched: boolean
}

const visibleLinearFeatures = computed<LinearRenderedFeature[]>(() => {
  if (!showBaseFeatures.value) return []
  const vs = viewStartBp.value
  const ve = viewEndBp.value
  const inView = allBaseFeatures.value.filter((f) => f.end_bp >= vs && f.start_bp <= ve)

  // 若当前窗口内特征数 <= 750 全部精细绘箭头；若大于则保留前噬菌体内部+非CDS+整合酶+搜索匹配，普通宿主基因按步长抽样代表
  let selected: PhageBaseFeature[] = inView
  if (inView.length > 750) {
    const stride = Math.ceil(inView.length / 650)
    selected = inView.filter((f, idx) => {
      if (f.in_prophage || matchedFeatureIndices.value.has(f.index)) return true
      if ((f.type || '').toLowerCase() !== 'cds') return true
      const prod = (f.product || '').toLowerCase()
      if (/(integrase|transposase|recombinase)/.test(prod)) return true
      return idx % stride === 0
    })
  }

  return selected.map((feat) => {
    const rawX1 = Math.max(LIN_PAD_L, Math.min(LIN_W - LIN_PAD_R, linX(feat.start_bp)))
    const rawX2 = Math.max(rawX1 + 2.2, Math.min(LIN_W - LIN_PAD_R, linX(feat.end_bp)))
    const w = rawX2 - rawX1
    const isPlus = feat.strand >= 0
    const yTop = isPlus ? 76 : 108
    const yBot = isPlus ? 96 : 128
    const yMid = 0.5 * (yTop + yBot)
    const aw = w >= 6 ? Math.min(6, w * 0.32) : 0
    let pathD = ''
    if (aw <= 0.1) {
      pathD = `M ${rawX1.toFixed(1)} ${yTop} L ${rawX2.toFixed(1)} ${yTop} L ${rawX2.toFixed(1)} ${yBot} L ${rawX1.toFixed(1)} ${yBot} Z`
    } else if (isPlus) {
      pathD = `M ${rawX1.toFixed(1)} ${yTop} L ${(rawX2 - aw).toFixed(1)} ${yTop} L ${rawX2.toFixed(1)} ${yMid} L ${(rawX2 - aw).toFixed(1)} ${yBot} L ${rawX1.toFixed(1)} ${yBot} Z`
    } else {
      pathD = `M ${rawX1.toFixed(1)} ${yMid} L ${(rawX1 + aw).toFixed(1)} ${yTop} L ${rawX2.toFixed(1)} ${yTop} L ${rawX2.toFixed(1)} ${yBot} L ${(rawX1 + aw).toFixed(1)} ${yBot} Z`
    }
    const isMatched = matchedFeatureIndices.value.has(feat.index)
    return {
      feat,
      x1: rawX1,
      x2: rawX2,
      pathD,
      color: getBaseFeatureColor(feat),
      opacity: feat.in_prophage || isMatched ? 0.95 : 0.72,
      isMatched,
    }
  })
})

const visibleLinearRegions = computed(() => {
  const vs = viewStartBp.value
  const ve = viewEndBp.value
  return allRegions.value
    .filter((r) => r.end_bp >= vs && r.start_bp <= ve)
    .map((reg) => {
      const x1 = Math.max(LIN_PAD_L, Math.min(LIN_W - LIN_PAD_R, linX(reg.start_bp)))
      const x2 = Math.max(x1 + 4, Math.min(LIN_W - LIN_PAD_R, linX(reg.end_bp)))
      return {
        reg,
        x1,
        x2,
        w: x2 - x1,
        cx: 0.5 * (x1 + x2),
        active: reg.index === props.selectedRegionIndex,
      }
    })
})

const visibleLinearRejected = computed(() => {
  if (!showRejected.value) return []
  const vs = viewStartBp.value
  const ve = viewEndBp.value
  return allRejected.value
    .filter((r) => r.end_bp >= vs && r.start_bp <= ve)
    .map((rej, idx) => {
      const x1 = Math.max(LIN_PAD_L, Math.min(LIN_W - LIN_PAD_R, linX(rej.start_bp)))
      const x2 = Math.max(x1 + 3, Math.min(LIN_W - LIN_PAD_R, linX(rej.end_bp)))
      return { rej, idx, x1, w: x2 - x1 }
    })
})

// 线性 V4.2 概率景观曲线 (y: 152..228, baseline=228)
const linearScoreGeometry = computed(() => {
  const bins = allScoreBins.value
  if (!showScoreCurve.value || bins.length === 0) return null
  const vs = viewStartBp.value
  const ve = viewEndBp.value
  const inView = bins.filter((b) => b.end_bp >= vs && b.start_bp <= ve)
  const useBins = inView.length >= 2 ? inView : bins
  const yTop = 152
  const yBase = 228
  const h = yBase - yTop
  const pts: string[] = []
  const meanPts: string[] = []
  for (const b of useBins) {
    const midBp = Math.max(vs, Math.min(ve, 0.5 * (b.start_bp + b.end_bp)))
    const x = linX(midBp).toFixed(1)
    const yMax = (yBase - Math.max(0, Math.min(1, b.max_prob)) * h).toFixed(1)
    const yMean = (yBase - Math.max(0, Math.min(1, b.mean_prob)) * h).toFixed(1)
    pts.push(`${x},${yMax}`)
    meanPts.push(`${x},${yMean}`)
  }
  const firstPt = pts[0]
  const lastPt = pts[pts.length - 1]
  if (!firstPt || !lastPt) return null
  const firstX = firstPt.split(',')[0]
  const lastX = lastPt.split(',')[0]
  const areaD = `M ${firstX} ${yBase} L ${pts.join(' L ')} L ${lastX} ${yBase} Z`
  return {
    polylineMax: pts.join(' '),
    polylineMean: meanPts.join(' '),
    areaD,
    yHalf: yBase - 0.5 * h,
  }
})

// 线性 GC% 与 GC Skew 曲线 (GC y: 248..296 mid=272; Skew y: 304..348 mid=326)
const linearBaseGeometry = computed(() => {
  const bins = allBaseBins.value
  if (bins.length === 0) return null
  const vs = viewStartBp.value
  const ve = viewEndBp.value
  const inView = bins.filter((b) => b.end_bp >= vs && b.start_bp <= ve)
  const useBins = inView.length >= 2 ? inView : bins

  const gcMidY = 272
  const skewMidY = 326
  const gcPts: string[] = []
  const skewPts: string[] = []
  const meanGc = avgGcPct.value

  for (const b of useBins) {
    const midBp = Math.max(vs, Math.min(ve, 0.5 * (b.start_bp + b.end_bp)))
    const x = linX(midBp).toFixed(1)
    const gcDelta = Math.max(-22, Math.min(22, b.gc_pct - meanGc))
    const gcY = (gcMidY - (gcDelta / 22) * 20).toFixed(1)
    gcPts.push(`${x},${gcY}`)

    const sk = Math.max(-0.5, Math.min(0.5, b.gc_skew))
    const skY = (skewMidY - (sk / 0.5) * 18).toFixed(1)
    skewPts.push(`${x},${skY}`)
  }

  const fGc = gcPts[0]
  const lGc = gcPts[gcPts.length - 1]
  const fSk = skewPts[0]
  const lSk = skewPts[skewPts.length - 1]
  if (!fGc || !lGc || !fSk || !lSk) return null

  return {
    gcPolyline: gcPts.join(' '),
    gcAreaD: `M ${fGc.split(',')[0]} ${gcMidY} L ${gcPts.join(' L ')} L ${lGc.split(',')[0]} ${gcMidY} Z`,
    skewPolyline: skewPts.join(' '),
    skewAreaD: `M ${fSk.split(',')[0]} ${skewMidY} L ${skewPts.join(' L ')} L ${lSk.split(',')[0]} ${skewMidY} Z`,
  }
})

// ─── 环形图谱几何辅助函数 ───
const CIRC_W = 640
const CIRC_H = 520
const CIRC_CX = 320
const CIRC_CY = 260

function polarPoint(cx: number, cy: number, r: number, angleDeg: number): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function buildArcBandPath(
  startBp: number,
  endBp: number,
  totalLen: number,
  innerR: number,
  outerR: number,
  withArrow = false,
  strand = 1
): string {
  const sAng = (startBp / totalLen) * 360
  const eAng = Math.min(359.95, Math.max(sAng + 0.15, (endBp / totalLen) * 360))
  const diff = eAng - sAng
  const large = diff > 180 ? 1 : 0

  if (!withArrow || diff < 0.7) {
    const p1 = polarPoint(0, 0, outerR, sAng)
    const p2 = polarPoint(0, 0, outerR, eAng)
    const p3 = polarPoint(0, 0, innerR, eAng)
    const p4 = polarPoint(0, 0, innerR, sAng)
    return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${outerR} ${outerR} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)} L ${p3.x.toFixed(2)} ${p3.y.toFixed(2)} A ${innerR} ${innerR} 0 ${large} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)} Z`
  }

  const arrowAng = Math.min(2.2, diff * 0.35)
  const midR = 0.5 * (innerR + outerR)
  if (strand >= 0) {
    const p1 = polarPoint(0, 0, outerR, sAng)
    const p2 = polarPoint(0, 0, outerR, eAng - arrowAng)
    const pTip = polarPoint(0, 0, midR, eAng)
    const p3 = polarPoint(0, 0, innerR, eAng - arrowAng)
    const p4 = polarPoint(0, 0, innerR, sAng)
    return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${outerR} ${outerR} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)} L ${pTip.x.toFixed(2)} ${pTip.y.toFixed(2)} L ${p3.x.toFixed(2)} ${p3.y.toFixed(2)} A ${innerR} ${innerR} 0 ${large} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)} Z`
  }
  const pTip = polarPoint(0, 0, midR, sAng)
  const p1 = polarPoint(0, 0, outerR, sAng + arrowAng)
  const p2 = polarPoint(0, 0, outerR, eAng)
  const p3 = polarPoint(0, 0, innerR, eAng)
  const p4 = polarPoint(0, 0, innerR, sAng + arrowAng)
  return `M ${pTip.x.toFixed(2)} ${pTip.y.toFixed(2)} L ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${outerR} ${outerR} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)} L ${p3.x.toFixed(2)} ${p3.y.toFixed(2)} A ${innerR} ${innerR} 0 ${large} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)} Z`
}

const circularTicks = computed(() => {
  const len = totalLenBp.value
  const step = Math.max(1000, Math.round(len / 8))
  const list: { x1: number; y1: number; x2: number; y2: number; tx: number; ty: number; label: string; anchor: string }[] = []
  for (let pos = 0; pos < len; pos += step) {
    const ang = (pos / len) * 360
    const p1 = polarPoint(0, 0, 210, ang)
    const p2 = polarPoint(0, 0, 217, ang)
    const pt = polarPoint(0, 0, 229, ang)
    let anchor = 'middle'
    if (ang > 12 && ang < 168) anchor = 'start'
    else if (ang > 192 && ang < 348) anchor = 'end'
    list.push({
      x1: p1.x,
      y1: p1.y,
      x2: p2.x,
      y2: p2.y,
      tx: pt.x,
      ty: pt.y,
      label: pos === 0 ? '0' : formatBpAxis(pos),
      anchor,
    })
  }
  return list
})

const circularBaseFeatures = computed(() => {
  if (!showBaseFeatures.value) return []
  const len = totalLenBp.value
  const feats = allBaseFeatures.value
  let subset = feats
  if (feats.length > 900) {
    const stride = Math.ceil(feats.length / 750)
    subset = feats.filter((f, idx) => {
      if (f.in_prophage || matchedFeatureIndices.value.has(f.index)) return true
      if ((f.type || '').toLowerCase() !== 'cds') return true
      return idx % stride === 0
    })
  }
  return subset.map((feat) => {
    const innerR = feat.strand >= 0 ? 186 : 168
    const outerR = feat.strand >= 0 ? 199 : 181
    return {
      feat,
      d: buildArcBandPath(feat.start_bp, feat.end_bp, len, innerR, outerR, feats.length < 400, feat.strand),
      color: getBaseFeatureColor(feat),
      isMatched: matchedFeatureIndices.value.has(feat.index),
    }
  })
})

const circularRegions = computed(() => {
  const len = totalLenBp.value
  return allRegions.value.map((reg) => {
    const midBp = 0.5 * (reg.start_bp + reg.end_bp)
    const midAng = (midBp / len) * 360
    const p1 = polarPoint(0, 0, 206, midAng)
    const p2 = polarPoint(0, 0, 232, midAng)
    const anchor = midAng >= 180 ? 'end' : 'start'
    return {
      reg,
      d: buildArcBandPath(reg.start_bp, reg.end_bp, len, 163, 204),
      lineD: `M ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} L ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`,
      tx: p2.x + (anchor === 'start' ? 4 : -4),
      ty: p2.y,
      anchor,
      active: reg.index === props.selectedRegionIndex,
    }
  })
})

const circularRejected = computed(() => {
  if (!showRejected.value) return []
  const len = totalLenBp.value
  return allRejected.value.map((rej, idx) => ({
    rej,
    idx,
    d: buildArcBandPath(rej.start_bp, rej.end_bp, len, 164, 203),
  }))
})

const circularScoreRingPath = computed(() => {
  if (!showScoreCurve.value || allScoreBins.value.length === 0) return ''
  const len = totalLenBp.value
  const pts: string[] = []
  for (const b of allScoreBins.value) {
    const ang = (0.5 * (b.start_bp + b.end_bp) / len) * 360
    const r = 128 + Math.max(0, Math.min(1, b.max_prob)) * 28
    const p = polarPoint(0, 0, r, ang)
    pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
  }
  return pts.length > 2 ? `M ${pts.join(' L ')} Z` : ''
})

const circularGcRingPath = computed(() => {
  if (!showGcTrack.value || allBaseBins.value.length === 0) return ''
  const len = totalLenBp.value
  const meanGc = avgGcPct.value
  const pts: string[] = []
  for (const b of allBaseBins.value) {
    const ang = (0.5 * (b.start_bp + b.end_bp) / len) * 360
    const delta = Math.max(-22, Math.min(22, b.gc_pct - meanGc))
    const r = 104 + (delta / 22) * 16
    const p = polarPoint(0, 0, r, ang)
    pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
  }
  return pts.length > 2 ? `M ${pts.join(' L ')} Z` : ''
})

const circularSkewRingPath = computed(() => {
  if (!showGcSkew.value || allBaseBins.value.length === 0) return ''
  const len = totalLenBp.value
  const pts: string[] = []
  for (const b of allBaseBins.value) {
    const ang = (0.5 * (b.start_bp + b.end_bp) / len) * 360
    const sk = Math.max(-0.5, Math.min(0.5, b.gc_skew))
    const r = 78 + (sk / 0.5) * 12
    const p = polarPoint(0, 0, r, ang)
    pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
  }
  return pts.length > 2 ? `M ${pts.join(' L ')} Z` : ''
})

// ─── 鼠标拖拽/滚轮缩放交互 ───
function onCanvasWheel(e: WheelEvent): void {
  const factor = e.deltaY < 0 ? 1.28 : 1 / 1.28
  if (viewMode.value === 'circular') {
    zoomCircular(factor)
    return
  }
  const rect = svgCanvasRef.value?.getBoundingClientRect()
  let ratio = 0.5
  if (rect && rect.width > 0) {
    const relX = ((e.clientX - rect.left) / rect.width) * LIN_W
    ratio = Math.max(0, Math.min(1, (relX - LIN_PAD_L) / LIN_PLOT_W))
  }
  zoomLinear(factor, ratio)
}

function onCanvasMouseDown(e: MouseEvent): void {
  if (e.button !== 0) return
  dragActive = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragOriginStartBp = viewStartBp.value
  dragOriginEndBp = viewEndBp.value
  dragOriginPanX = circPanX.value
  dragOriginPanY = circPanY.value
}

function onCanvasMouseMove(e: MouseEvent): void {
  if (hoverTip.value.visible) {
    hoverTip.value.x = e.clientX + 14
    hoverTip.value.y = e.clientY + 14
  }
  if (!dragActive) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  if (viewMode.value === 'circular') {
    circPanX.value = dragOriginPanX + dx
    circPanY.value = dragOriginPanY + dy
    return
  }
  const rect = svgCanvasRef.value?.getBoundingClientRect()
  const pxSpan = rect && rect.width > 0 ? rect.width * (LIN_PLOT_W / LIN_W) : LIN_PLOT_W
  const spanBp = dragOriginEndBp - dragOriginStartBp
  const deltaBp = Math.round((-dx / Math.max(10, pxSpan)) * spanBp)
  const len = totalLenBp.value
  let ns = dragOriginStartBp + deltaBp
  let ne = dragOriginEndBp + deltaBp
  if (ns < 0) {
    ne -= ns
    ns = 0
  }
  if (ne > len) {
    ns -= ne - len
    ne = len
  }
  viewStartBp.value = Math.max(0, ns)
  viewEndBp.value = Math.min(len, ne)
}

function onCanvasMouseUp(): void {
  dragActive = false
}

function showFeatureTip(e: MouseEvent, f: PhageBaseFeature): void {
  const strandLabel = f.strand >= 0 ? '+ 正链' : '- 负链'
  const nameText = f.gene ? `${f.gene} (${f.locus_tag})` : f.locus_tag || `${f.type}_${f.index}`
  const prophageTag = f.overlay_region_id ? `归属前噬菌体: ${f.overlay_region_id}` : `宿主底图 (${f.source})`
  hoverTip.value = {
    visible: true,
    x: e.clientX + 14,
    y: e.clientY + 14,
    title: `[${f.type}] ${nameText}`,
    subtitle: f.product || 'hypothetical protein',
    meta: `${(f.start_bp + 1).toLocaleString()} - ${f.end_bp.toLocaleString()} bp | ${strandLabel} | ${prophageTag}`,
    accent: f.in_prophage ? '#2563eb' : '#0f766e',
  }
}

function showRegionTip(e: MouseEvent, r: PhageRegionItem): void {
  hoverTip.value = {
    visible: true,
    x: e.clientX + 14,
    y: e.clientY + 14,
    title: `${r.region_id} (${r.completeness_label})`,
    subtitle: `${r.contig_id}:${r.start_1based.toLocaleString()}-${r.end_1based.toLocaleString()} (${r.length_bp.toLocaleString()} bp)`,
    meta: `Peak ${r.peak_score.toFixed(3)} | Mean ${r.mean_score.toFixed(3)} | ORF ${r.orf_count} | GC ${r.gc_percent}%`,
    accent: '#2563eb',
  }
}

function hideHoverTip(): void {
  hoverTip.value.visible = false
}

function selectFeatureItem(f: PhageBaseFeature): void {
  inspectedFeature.value = f
  if (f.overlay_region_id) {
    const reg = allRegions.value.find((r) => r.region_id === f.overlay_region_id)
    if (reg) emit('select-region', reg)
  }
}

function exportSvgSnapshot(): void {
  if (!svgCanvasRef.value) return
  const serializer = new XMLSerializer()
  const raw = serializer.serializeToString(svgCanvasRef.value)
  const blob = new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n${raw}`], {
    type: 'image/svg+xml;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.overlayData?.contig_id || 'contig'}_phage_overlay_${viewMode.value}.svg`
  a.click()
  URL.revokeObjectURL(url)
}

// 底部 Minimap 指示盒定位
const minimapIndicator = computed(() => {
  const len = totalLenBp.value
  const leftPct = (viewStartBp.value / len) * 100
  const widthPct = Math.max(1.2, ((viewEndBp.value - viewStartBp.value) / len) * 100)
  return { left: `${leftPct.toFixed(2)}%`, width: `${widthPct.toFixed(2)}%` }
})

function onMinimapClick(e: MouseEvent): void {
  const target = e.currentTarget as HTMLElement | null
  if (!target) return
  const rect = target.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)))
  const centerBp = ratio * totalLenBp.value
  const halfSpan = 0.5 * (viewEndBp.value - viewStartBp.value)
  const len = totalLenBp.value
  let ns = Math.round(centerBp - halfSpan)
  let ne = Math.round(centerBp + halfSpan)
  if (ns < 0) {
    ne -= ns
    ns = 0
  }
  if (ne > len) {
    ns -= ne - len
    ne = len
  }
  viewStartBp.value = Math.max(0, ns)
  viewEndBp.value = Math.min(len, ne)
}
</script>

<template>
  <div class="overlay-card">
    <!-- 顶部标题栏与 Contig 切换 -->
    <div class="overlay-header">
      <div class="title-col">
        <div class="title-line">
          <h4>目标基因组底图与前噬菌体预测叠图工作台</h4>
          <span v-if="overlayData" class="fmt-tag">
            {{ overlayData.source_format === 'genbank' ? 'GenBank 原生注解底图' : 'FASTA + Pyrodigal 底图' }}
          </span>
          <span v-if="overlayData" class="stat-pill">
            {{ allBaseFeatures.length.toLocaleString() }} 底图特征 / {{ allRegions.length }} 预测噬菌体区
          </span>
        </div>
        <span class="sub-desc">
          支持滚轮缩放与拖拽漫游，点击前噬菌体区段或底图基因可精细对齐定位，并支持导出完整叠图至 GenomeViewer
        </span>
      </div>

      <div class="header-controls">
        <select
          :value="selectedContigId"
          class="contig-select"
          @change="emit('update:selectedContigId', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="c in contigs" :key="c.id" :value="c.id">
            {{ c.id }} ({{ formatBpAxis(c.length) }}, 命中 {{ c.hit_count }})
          </option>
        </select>

        <div class="mode-switch">
          <button
            type="button"
            class="mode-btn"
            :class="{ active: viewMode === 'linear' }"
            @click="viewMode = 'linear'"
          >
            线性展开叠图
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: viewMode === 'circular' }"
            @click="viewMode = 'circular'"
          >
            环形全长叠图
          </button>
        </div>
      </div>
    </div>

    <!-- 交互式图层控制、视口缩放与底图特征检索条 -->
    <div class="toolbar-row">
      <div class="layer-toggles">
        <label class="layer-chip" :class="{ on: showBaseFeatures }">
          <input v-model="showBaseFeatures" type="checkbox" />
          <span>底图基因 (CDS/tRNA)</span>
        </label>
        <label class="layer-chip" :class="{ on: showScoreCurve }">
          <input v-model="showScoreCurve" type="checkbox" />
          <span>V4.2 概率曲线</span>
        </label>
        <label class="layer-chip" :class="{ on: showGcTrack }">
          <input v-model="showGcTrack" type="checkbox" />
          <span>GC% 偏移</span>
        </label>
        <label class="layer-chip" :class="{ on: showGcSkew }">
          <input v-model="showGcSkew" type="checkbox" />
          <span>GC Skew</span>
        </label>
        <label v-if="allRejected.length > 0" class="layer-chip warn" :class="{ on: showRejected }">
          <input v-model="showRejected" type="checkbox" />
          <span>门控过滤 ({{ allRejected.length }})</span>
        </label>
      </div>

      <div class="zoom-search-group">
        <div class="search-box">
          <input
            v-model="featureSearch"
            type="text"
            class="feat-search-input"
            placeholder="检索底图基因 (如 integrase / tRNA / dnaA)..."
            @keyup.enter="jumpToMatchedFeature(0)"
          />
          <template v-if="matchedFeatureList.length > 0">
            <span class="match-count">{{ (searchCursor % matchedFeatureList.length) + 1 }}/{{ matchedFeatureList.length }}</span>
            <button type="button" class="mini-step-btn" title="上一个匹配基因" @click="jumpToMatchedFeature(-1)">&lt;</button>
            <button type="button" class="mini-step-btn" title="下一个匹配基因" @click="jumpToMatchedFeature(1)">&gt;</button>
          </template>
        </div>

        <div class="zoom-btns">
          <button
            type="button"
            class="tool-btn"
            title="放大"
            @click="viewMode === 'linear' ? zoomLinear(1.6) : zoomCircular(1.3)"
          >
            +
          </button>
          <button
            type="button"
            class="tool-btn"
            title="缩小"
            @click="viewMode === 'linear' ? zoomLinear(1 / 1.6) : zoomCircular(1 / 1.3)"
          >
            -
          </button>
          <button type="button" class="tool-btn wide" @click="resetView">
            重置 {{ viewMode === 'linear' ? `${linearZoomFactor.toFixed(1)}x` : `${circScale.toFixed(1)}x` }}
          </button>
          <button type="button" class="tool-btn wide" @click="exportSvgSnapshot">导出 SVG</button>
          <button
            type="button"
            class="viewer-launch-btn"
            :disabled="!overlayData"
            @click="overlayData && emit('open-overlay-viewer', overlayData.contig_id)"
          >
            在 GenomeViewer 打开全长叠图
          </button>
        </div>
      </div>
    </div>

    <!-- 主 SVG 交互绘布 -->
    <div v-if="isLoading" class="overlay-loading">正在组装全序列底图与 V4.2 预测叠图轨道...</div>

    <div
      v-else-if="overlayData"
      class="canvas-frame"
      @mouseleave="hideHoverTip"
      @mouseup="onCanvasMouseUp"
    >
      <!-- 图例说明栏 -->
      <div class="legend-strip">
        <span class="lg-item"><i class="sw prophage"></i>预测噬菌体区段</span>
        <span class="lg-item"><i class="sw cds-in"></i>区段内基因</span>
        <span class="lg-item"><i class="sw cds-host"></i>宿主基因</span>
        <span class="lg-item"><i class="sw integrase"></i>整合酶 / 转座酶</span>
        <span class="lg-item"><i class="sw trna"></i>tRNA / rRNA</span>
        <span v-if="featureSearch.trim()" class="lg-item"><i class="sw match"></i>检索命中高亮</span>
        <span class="viewport-range">
          当前视口: {{ (viewStartBp + 1).toLocaleString() }} - {{ viewEndBp.toLocaleString() }} bp
          (跨度 {{ formatBpAxis(viewEndBp - viewStartBp) }})
        </span>
      </div>

      <!-- 模式 A：线性多轨道对齐叠图 -->
      <svg
        v-if="viewMode === 'linear'"
        ref="svgCanvasRef"
        :viewBox="`0 0 ${LIN_W} ${LIN_H}`"
        class="overlay-svg linear-svg"
        @wheel.prevent="onCanvasWheel"
        @mousedown="onCanvasMouseDown"
        @mousemove="onCanvasMouseMove"
      >
        <!-- 轨道标题标签 (左侧固定列) -->
        <text x="6" y="34" class="track-label">坐标轴</text>
        <text x="6" y="90" class="track-label">+ 链特征</text>
        <text x="6" y="122" class="track-label">- 链特征</text>
        <text x="6" y="194" class="track-label">V4.2 分数</text>
        <text x="6" y="274" class="track-label">GC% 偏移</text>
        <text x="6" y="328" class="track-label">GC Skew</text>

        <!-- 背景分隔网格 -->
        <line :x1="LIN_PAD_L" y1="42" :x2="LIN_W - LIN_PAD_R" y2="42" stroke="#cbd5e1" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="102" :x2="LIN_W - LIN_PAD_R" y2="102" stroke="#e2e8f0" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="142" :x2="LIN_W - LIN_PAD_R" y2="142" stroke="#e2e8f0" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="228" :x2="LIN_W - LIN_PAD_R" y2="228" stroke="#cbd5e1" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="272" :x2="LIN_W - LIN_PAD_R" y2="272" stroke="#e2e8f0" stroke-dasharray="3 3" />
        <line :x1="LIN_PAD_L" y1="326" :x2="LIN_W - LIN_PAD_R" y2="326" stroke="#e2e8f0" stroke-dasharray="3 3" />

        <!-- 垂直刻度线与坐标标尺 -->
        <g v-for="tk in linearTicks" :key="tk.bp">
          <line :x1="tk.x" y1="42" :x2="tk.x" y2="352" stroke="#f1f5f9" stroke-width="1" />
          <line :x1="tk.x" y1="36" :x2="tk.x" y2="42" stroke="#64748b" stroke-width="1.2" />
          <text :x="tk.x" y="29" text-anchor="middle" class="tick-label">{{ tk.label }}</text>
        </g>

        <!-- 1. 门控拒绝候选叠图 (虚线对照带) -->
        <g v-for="item in visibleLinearRejected" :key="`rej_${item.idx}`">
          <rect
            :x="item.x1"
            y="50"
            :width="item.w"
            height="178"
            fill="#f59e0b"
            fill-opacity="0.08"
            stroke="#d97706"
            stroke-width="1.2"
            stroke-dasharray="4 3"
            rx="3"
          />
        </g>

        <!-- 2. 预测噬菌体/前噬菌体贯穿包络叠图帯 (置于底层半透明以免遮挡基因箭头交互) -->
        <g
          v-for="item in visibleLinearRegions"
          :key="`lreg_${item.reg.index}`"
          class="clickable-group"
          @click.stop="focusRegion(item.reg)"
          @mouseenter="showRegionTip($event, item.reg)"
          @mouseleave="hideHoverTip"
        >
          <rect
            :x="item.x1"
            y="46"
            :width="item.w"
            height="182"
            :fill="item.active ? '#2563eb' : '#0ea5e9'"
            :fill-opacity="item.active ? 0.14 : 0.09"
            :stroke="item.active ? '#1d4ed8' : '#0284c7'"
            :stroke-width="item.active ? 1.8 : 1"
            rx="4"
          />
          <rect
            :x="item.x1"
            y="46"
            :width="Math.max(item.w, 42)"
            height="16"
            rx="3"
            :fill="item.active ? '#1d4ed8' : '#0284c7'"
          />
          <text
            :x="item.x1 + 5"
            y="57.5"
            class="region-badge-text"
          >
            {{ item.reg.region_id }}
          </text>
        </g>

        <!-- 3. 输入序列底图特征 (+/- 链基因箭头) -->
        <g v-if="showBaseFeatures">
          <path
            v-for="item in visibleLinearFeatures"
            :key="`lf_${item.feat.index}`"
            :d="item.pathD"
            :fill="item.color"
            :fill-opacity="item.opacity"
            :stroke="inspectedFeature?.index === item.feat.index ? '#0f172a' : (item.isMatched ? '#a16207' : 'none')"
            :stroke-width="inspectedFeature?.index === item.feat.index || item.isMatched ? 1.4 : 0"
            class="clickable-group"
            @click.stop="selectFeatureItem(item.feat)"
            @mouseenter="showFeatureTip($event, item.feat)"
            @mouseleave="hideHoverTip"
          />
        </g>

        <!-- 4. V4.2 连续概率景观轨迹 -->
        <g v-if="linearScoreGeometry">
          <line
            :x1="LIN_PAD_L"
            :y1="linearScoreGeometry.yHalf"
            :x2="LIN_W - LIN_PAD_R"
            :y2="linearScoreGeometry.yHalf"
            stroke="#f59e0b"
            stroke-width="1"
            stroke-dasharray="4 4"
          />
          <path :d="linearScoreGeometry.areaD" fill="#2563eb" fill-opacity="0.16" />
          <polyline
            :points="linearScoreGeometry.polylineMax"
            fill="none"
            stroke="#2563eb"
            stroke-width="1.8"
            stroke-linejoin="round"
          />
          <polyline
            :points="linearScoreGeometry.polylineMean"
            fill="none"
            stroke="#0d9488"
            stroke-width="1.2"
            stroke-dasharray="3 2"
          />
        </g>

        <!-- 5. GC% 偏移与 GC Skew 底图波形 -->
        <g v-if="linearBaseGeometry">
          <template v-if="showGcTrack">
            <path :d="linearBaseGeometry.gcAreaD" fill="#10b981" fill-opacity="0.16" />
            <polyline
              :points="linearBaseGeometry.gcPolyline"
              fill="none"
              stroke="#059669"
              stroke-width="1.4"
            />
          </template>
          <template v-if="showGcSkew">
            <path :d="linearBaseGeometry.skewAreaD" fill="#8b5cf6" fill-opacity="0.16" />
            <polyline
              :points="linearBaseGeometry.skewPolyline"
              fill="none"
              stroke="#7c3aed"
              stroke-width="1.3"
            />
          </template>
        </g>
      </svg>

      <!-- 模式 B：环形全长叠图 -->
      <svg
        v-else
        ref="svgCanvasRef"
        :viewBox="`0 0 ${CIRC_W} ${CIRC_H}`"
        class="overlay-svg circular-svg"
        @wheel.prevent="onCanvasWheel"
        @mousedown="onCanvasMouseDown"
        @mousemove="onCanvasMouseMove"
      >
        <g :transform="`translate(${CIRC_CX + circPanX}, ${CIRC_CY + circPanY}) scale(${circScale})`">
          <!-- 参考底圆 -->
          <circle cx="0" cy="0" r="208" fill="none" stroke="#cbd5e1" stroke-width="1.2" />
          <circle cx="0" cy="0" r="184" fill="none" stroke="#e2e8f0" stroke-width="0.8" />
          <circle cx="0" cy="0" r="164" fill="none" stroke="#e2e8f0" stroke-width="0.8" />
          <circle cx="0" cy="0" r="142" fill="none" stroke="#fde68a" stroke-width="0.8" stroke-dasharray="3 3" />
          <circle cx="0" cy="0" r="128" fill="none" stroke="#cbd5e1" stroke-width="0.8" />
          <circle cx="0" cy="0" r="104" fill="none" stroke="#d1fae5" stroke-width="0.8" stroke-dasharray="2 3" />
          <circle cx="0" cy="0" r="78" fill="none" stroke="#ede9fe" stroke-width="0.8" stroke-dasharray="2 3" />

          <!-- 外围刻度 -->
          <g v-for="tk in circularTicks" :key="tk.label">
            <line :x1="tk.x1" :y1="tk.y1" :x2="tk.x2" :y2="tk.y2" stroke="#64748b" stroke-width="1.2" />
            <text :x="tk.tx" :y="tk.ty" :text-anchor="tk.anchor" dominant-baseline="middle" class="tick-label">
              {{ tk.label }}
            </text>
          </g>

          <!-- 内环 GC Skew & GC% & V4.2 景观环 -->
          <path v-if="circularSkewRingPath" :d="circularSkewRingPath" fill="#8b5cf6" fill-opacity="0.14" stroke="#7c3aed" stroke-width="1.2" />
          <path v-if="circularGcRingPath" :d="circularGcRingPath" fill="#10b981" fill-opacity="0.14" stroke="#059669" stroke-width="1.3" />
          <path v-if="circularScoreRingPath" :d="circularScoreRingPath" fill="#3b82f6" fill-opacity="0.18" stroke="#2563eb" stroke-width="1.5" />

          <!-- 预测前噬菌体环形包络高亮带 -->
          <g
            v-for="item in circularRegions"
            :key="`creg_${item.reg.index}`"
            class="clickable-group"
            @click.stop="focusRegion(item.reg)"
            @mouseenter="showRegionTip($event, item.reg)"
            @mouseleave="hideHoverTip"
          >
            <path
              :d="item.d"
              :fill="item.active ? '#2563eb' : '#0ea5e9'"
              :fill-opacity="item.active ? 0.22 : 0.14"
              :stroke="item.active ? '#1e3a8a' : '#0284c7'"
              :stroke-width="item.active ? 1.8 : 1.1"
            />
            <path :d="item.lineD" stroke="#0284c7" stroke-width="1" />
            <text
              :x="item.tx"
              :y="item.ty"
              :text-anchor="item.anchor"
              dominant-baseline="middle"
              class="circ-region-label"
            >
              {{ item.reg.region_id }}
            </text>
          </g>

          <!-- 门控拦截对照弧 -->
          <path
            v-for="rej in circularRejected"
            :key="`crej_${rej.idx}`"
            :d="rej.d"
            fill="#f59e0b"
            fill-opacity="0.1"
            stroke="#d97706"
            stroke-width="1"
            stroke-dasharray="3 2"
          />

          <!-- 底图正/负链特征弧 -->
          <path
            v-for="item in circularBaseFeatures"
            :key="`cbf_${item.feat.index}`"
            :d="item.d"
            :fill="item.color"
            :fill-opacity="item.isMatched || item.feat.in_prophage ? 0.95 : 0.72"
            :stroke="inspectedFeature?.index === item.feat.index ? '#0f172a' : 'none'"
            stroke-width="1.2"
            class="clickable-group"
            @click.stop="selectFeatureItem(item.feat)"
            @mouseenter="showFeatureTip($event, item.feat)"
            @mouseleave="hideHoverTip"
          />

          <!-- 中央信息摘要 -->
          <text x="0" y="-12" text-anchor="middle" class="circ-center-title">{{ overlayData.contig_id }}</text>
          <text x="0" y="6" text-anchor="middle" class="circ-center-sub">{{ overlayData.length_bp.toLocaleString() }} bp</text>
          <text x="0" y="22" text-anchor="middle" class="circ-center-sub">GC {{ overlayData.gc_percent }}% | {{ allRegions.length }} Prophage</text>
        </g>
      </svg>

      <!-- 线性全基因组俯瞰缩略条 (Minimap 快速跳转) -->
      <div v-if="viewMode === 'linear'" class="minimap-bar" title="点击任意位置快速跳转视口" @click="onMinimapClick">
        <div class="minimap-base-line"></div>
        <div
          v-for="r in allRegions"
          :key="`mm_${r.index}`"
          class="minimap-hit"
          :class="{ active: r.index === selectedRegionIndex }"
          :style="{
            left: `${(r.start_bp / totalLenBp) * 100}%`,
            width: `${Math.max(0.8, ((r.end_bp - r.start_bp) / totalLenBp) * 100)}%`,
          }"
        ></div>
        <div class="minimap-viewport" :style="minimapIndicator"></div>
      </div>

      <!-- 悬浮详情框 -->
      <div
        v-if="hoverTip.visible"
        class="hover-tooltip"
        :style="{ left: `${hoverTip.x}px`, top: `${hoverTip.y}px`, borderLeftColor: hoverTip.accent }"
      >
        <div class="ht-title">{{ hoverTip.title }}</div>
        <div class="ht-sub">{{ hoverTip.subtitle }}</div>
        <div class="ht-meta">{{ hoverTip.meta }}</div>
      </div>
    </div>

    <!-- 底部交互检查栏 (选中特征 + 一键区域聚焦条) -->
    <div v-if="overlayData" class="inspector-footer">
      <div v-if="inspectedFeature" class="feature-inspector">
        <span class="fi-badge">{{ inspectedFeature.type }}</span>
        <strong class="fi-name">
          {{ inspectedFeature.gene ? `${inspectedFeature.gene} / ` : '' }}{{ inspectedFeature.locus_tag || `Feature_${inspectedFeature.index}` }}
        </strong>
        <span class="fi-pos">
          {{ (inspectedFeature.start_bp + 1).toLocaleString() }}..{{ inspectedFeature.end_bp.toLocaleString() }} bp
          ({{ inspectedFeature.strand >= 0 ? '+链' : '-链' }})
        </span>
        <span class="fi-prod">{{ inspectedFeature.product }}</span>
        <span v-if="inspectedFeature.overlay_region_id" class="fi-in-phage">
          位于预测区段 {{ inspectedFeature.overlay_region_id }}
        </span>
        <button
          type="button"
          class="fi-focus-btn"
          @click="focusInterval(inspectedFeature.start_bp, inspectedFeature.end_bp, 4000)"
        >
          聚焦该基因 (+/-4kb)
        </button>
      </div>

      <div v-else class="region-pills-bar">
        <span class="pills-title">快速聚焦前噬菌体区段:</span>
        <span v-if="allRegions.length === 0" class="no-hits-note">当前 Contig 未检出高置信度前噬菌体整合区域</span>
        <button
          v-for="reg in allRegions"
          :key="`pill_${reg.index}`"
          type="button"
          class="region-pill"
          :class="{ active: reg.index === selectedRegionIndex }"
          @click="focusRegion(reg)"
        >
          {{ reg.region_id }} ({{ formatBpAxis(reg.start_bp) }} - {{ formatBpAxis(reg.end_bp) }})
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.overlay-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.title-col {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.title-line h4 {
  margin: 0;
  font-size: 15px;
  color: #0f172a;
}

.fmt-tag {
  font-size: 11px;
  font-weight: 700;
  background: #e0f2fe;
  color: #0369a1;
  padding: 2px 8px;
  border-radius: 10px;
}

.stat-pill {
  font-size: 11px;
  font-weight: 600;
  background: #f1f5f9;
  color: #475569;
  padding: 2px 8px;
  border-radius: 10px;
}

.sub-desc {
  font-size: 12px;
  color: #64748b;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.contig-select {
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  background: white;
  color: #1e293b;
}

.mode-switch {
  display: inline-flex;
  background: #f1f5f9;
  border-radius: 7px;
  padding: 2px;
  border: 1px solid #e2e8f0;
}

.mode-btn {
  border: none;
  background: transparent;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  border-radius: 5px;
  cursor: pointer;
}

.mode-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  background: #f8fafc;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.layer-toggles {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.layer-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 3px 9px;
  cursor: pointer;
  user-select: none;
}

.layer-chip input {
  display: none;
}

.layer-chip.on {
  background: #eff6ff;
  border-color: #60a5fa;
  color: #1d4ed8;
}

.layer-chip.warn.on {
  background: #fffbeb;
  border-color: #fbbf24;
  color: #b45309;
}

.zoom-search-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-box {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 2px 6px;
}

.feat-search-input {
  border: none;
  outline: none;
  font-size: 12px;
  width: 195px;
  padding: 3px 2px;
  color: #1e293b;
}

.match-count {
  font-size: 11px;
  font-weight: 700;
  color: #b45309;
  background: #fef3c7;
  padding: 1px 5px;
  border-radius: 4px;
}

.mini-step-btn {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.zoom-btns {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-btn {
  border: 1px solid #cbd5e1;
  background: white;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  min-width: 26px;
  height: 26px;
  padding: 0 7px;
  border-radius: 5px;
  cursor: pointer;
}

.tool-btn:hover {
  border-color: #94a3b8;
  background: #f1f5f9;
}

.viewer-launch-btn {
  border: none;
  background: #2563eb;
  color: white;
  font-size: 12px;
  font-weight: 700;
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
}

.viewer-launch-btn:hover {
  background: #1d4ed8;
}

.overlay-loading {
  padding: 40px 20px;
  text-align: center;
  font-size: 13px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 8px;
}

.canvas-frame {
  position: relative;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
  user-select: none;
}

.legend-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 11px;
  color: #475569;
  flex-wrap: wrap;
}

.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.sw {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.sw.prophage {
  background: rgba(14, 165, 233, 0.25);
  border: 1.5px solid #0284c7;
}

.sw.cds-in {
  background: #1d4ed8;
}

.sw.cds-host {
  background: #94a3b8;
}

.sw.integrase {
  background: #9333ea;
}

.sw.trna {
  background: #0d9488;
}

.sw.match {
  background: #eab308;
}

.viewport-range {
  margin-left: auto;
  font-family: 'Consolas', monospace;
  color: #334155;
  font-weight: 600;
}

.overlay-svg {
  width: 100%;
  display: block;
  cursor: grab;
}

.overlay-svg:active {
  cursor: grabbing;
}

.linear-svg {
  min-height: 330px;
}

.circular-svg {
  max-height: 520px;
}

.track-label {
  font-size: 10px;
  font-weight: 700;
  fill: #475569;
}

.tick-label {
  font-size: 9.5px;
  font-family: 'Consolas', monospace;
  fill: #64748b;
}

.region-badge-text {
  font-size: 10px;
  font-weight: 700;
  fill: #ffffff;
}

.circ-region-label {
  font-size: 10px;
  font-weight: 700;
  fill: #0369a1;
}

.circ-center-title {
  font-size: 13px;
  font-weight: 800;
  fill: #0f172a;
}

.circ-center-sub {
  font-size: 10.5px;
  fill: #64748b;
}

.clickable-group {
  cursor: pointer;
}

.minimap-bar {
  position: relative;
  height: 16px;
  background: #f1f5f9;
  border-top: 1px solid #e2e8f0;
  cursor: pointer;
}

.minimap-base-line {
  position: absolute;
  left: 0;
  right: 0;
  top: 7px;
  height: 2px;
  background: #cbd5e1;
}

.minimap-hit {
  position: absolute;
  top: 3px;
  height: 10px;
  background: #0ea5e9;
  border-radius: 2px;
}

.minimap-hit.active {
  background: #2563eb;
}

.minimap-viewport {
  position: absolute;
  top: 1px;
  bottom: 1px;
  border: 1.5px solid #0f172a;
  background: rgba(37, 99, 235, 0.14);
  border-radius: 2px;
  pointer-events: none;
}

.hover-tooltip {
  position: fixed;
  z-index: 9999;
  background: rgba(15, 23, 42, 0.94);
  color: white;
  padding: 8px 11px;
  border-radius: 6px;
  border-left: 4px solid #2563eb;
  font-size: 11.5px;
  max-width: 340px;
  pointer-events: none;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
}

.ht-title {
  font-weight: 700;
  margin-bottom: 2px;
}

.ht-sub {
  color: #e2e8f0;
  margin-bottom: 3px;
}

.ht-meta {
  color: #94a3b8;
  font-family: 'Consolas', monospace;
  font-size: 10.5px;
}

.inspector-footer {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
}

.feature-inspector {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.fi-badge {
  background: #e0e7ff;
  color: #3730a3;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
}

.fi-name {
  color: #0f172a;
}

.fi-pos {
  font-family: 'Consolas', monospace;
  color: #475569;
}

.fi-prod {
  color: #334155;
}

.fi-in-phage {
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
}

.fi-focus-btn {
  margin-left: auto;
  border: 1px solid #93c5fd;
  background: white;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 5px;
  cursor: pointer;
}

.region-pills-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pills-title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}

.no-hits-note {
  font-size: 12px;
  color: #94a3b8;
}

.region-pill {
  border: 1px solid #cbd5e1;
  background: white;
  color: #334155;
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 12px;
  cursor: pointer;
}

.region-pill.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}
</style>
