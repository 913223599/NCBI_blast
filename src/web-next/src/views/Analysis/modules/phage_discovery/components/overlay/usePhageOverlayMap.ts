/**
 * PhageOverlayMap 线性/环形基因组叠加视图状态与几何投影 Composable
 * 负责视口缩放平移、底图特征抽样与检索、概率/GC 曲线投影、悬浮提示与 SVG 快照导出
 */
import { computed, ref, watch } from 'vue'
import { shouldSubmitOnEnter } from '../../../../../../utils/ime'
import type {
  PhageBaseFeature,
  PhageBaseTrackBin,
  PhageContigOverlayData,
  PhageContigSummary,
  PhageRegionItem,
  PhageRejectedCandidate,
  PhageScoreTrackBin,
} from '../../types'

export interface PhageOverlayMapProps {
  contigs: PhageContigSummary[]
  selectedContigId: string
  overlayData: PhageContigOverlayData | null
  isLoading: boolean
  selectedRegionIndex: number
}

export interface PhageOverlayMapEmits {
  (e: 'update:selectedContigId', contigId: string): void
  (e: 'select-region', region: PhageRegionItem): void
  (e: 'open-overlay-viewer', contigId: string): void
  (e: 'open-region-viewer', regionIndex: number): void
  (e: 'open-annotation', regionIndex?: number): void
}

export interface LinearRenderedFeature {
  feat: PhageBaseFeature
  x1: number
  x2: number
  pathD: string
  color: string
  opacity: number
  isMatched: boolean
}

export const LIN_W = 920
export const LIN_H = 368
export const LIN_PAD_L = 48
export const LIN_PAD_R = 20
export const LIN_PLOT_W = LIN_W - LIN_PAD_L - LIN_PAD_R

export const CIRC_W = 640
export const CIRC_H = 520
export const CIRC_CX = 320
export const CIRC_CY = 260

export function formatBpAxis(bp: number): string {
  if (bp >= 1_000_000) return `${(bp / 1_000_000).toFixed(2)} Mb`
  if (bp >= 1_000) return `${(bp / 1_000).toFixed(1)} kb`
  return `${bp} bp`
}

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

export function usePhageOverlayMap(props: PhageOverlayMapProps, emit: PhageOverlayMapEmits) {
  const viewMode = ref<'linear' | 'circular'>('linear')
  const showBaseFeatures = ref<boolean>(true)
  const showScoreCurve = ref<boolean>(true)
  const showGcTrack = ref<boolean>(true)
  const showGcSkew = ref<boolean>(true)
  const showRejected = ref<boolean>(true)

  const featureSearch = ref<string>('')
  const searchCursor = ref<number>(0)
  const inspectedFeature = ref<PhageBaseFeature | null>(null)

  function onFeatureSearchKeydown(event: KeyboardEvent) {
    if (shouldSubmitOnEnter(event)) {
      jumpToMatchedFeature(0)
    }
  }

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

  const viewStartBp = ref<number>(0)
  const viewEndBp = ref<number>(1000)

  const circScale = ref<number>(1)
  const circPanX = ref<number>(0)
  const circPanY = ref<number>(0)

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

  const isGenbankSource = computed(() => props.overlayData?.source_format === 'genbank')
  const hasIntegraseOrTransposase = computed(
    () =>
      isGenbankSource.value &&
      allBaseFeatures.value.some((f) =>
        /(integrase|transposase|recombinase|excisionase)/.test(
          `${f.gene || ''} ${f.product || ''} ${f.note || ''}`.toLowerCase()
        )
      )
  )
  const hasRnaFeatures = computed(
    () =>
      isGenbankSource.value &&
      allBaseFeatures.value.some((f) => {
        const t = (f.type || '').toLowerCase()
        return t === 'trna' || t === 'rrna'
      })
  )
  const baseLayerLabel = computed(() => {
    if (hasRnaFeatures.value) return '底图基因 (CDS/tRNA)'
    if (isGenbankSource.value) return '底图基因 (CDS)'
    return '底图特征 (ORF)'
  })
  const searchPlaceholder = computed(() => {
    if (hasIntegraseOrTransposase.value || hasRnaFeatures.value) {
      return '检索底图基因 (如 gene / product / locus_tag)...'
    }
    if (isGenbankSource.value) {
      return '检索底图基因 (如 locus_tag / gene / product)...'
    }
    return '检索底图 ORF 编号或坐标 (如 ORF_0010)...'
  })
  const activeRegion = computed<PhageRegionItem | null>(() => {
    if (allRegions.value.length === 0) return null
    return (
      allRegions.value.find((r) => r.index === props.selectedRegionIndex) ??
      allRegions.value[0] ??
      null
    )
  })

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

  const visibleLinearFeatures = computed<LinearRenderedFeature[]>(() => {
    if (!showBaseFeatures.value) return []
    const vs = viewStartBp.value
    const ve = viewEndBp.value
    const inView = allBaseFeatures.value.filter((f) => f.end_bp >= vs && f.start_bp <= ve)

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
      const ang = ((0.5 * (b.start_bp + b.end_bp)) / len) * 360
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
      const ang = ((0.5 * (b.start_bp + b.end_bp)) / len) * 360
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
      const ang = ((0.5 * (b.start_bp + b.end_bp)) / len) * 360
      const sk = Math.max(-0.5, Math.min(0.5, b.gc_skew))
      const r = 78 + (sk / 0.5) * 12
      const p = polarPoint(0, 0, r, ang)
      pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    }
    return pts.length > 2 ? `M ${pts.join(' L ')} Z` : ''
  })

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

  return {
    viewMode,
    showBaseFeatures,
    showScoreCurve,
    showGcTrack,
    showGcSkew,
    showRejected,
    featureSearch,
    searchCursor,
    inspectedFeature,
    onFeatureSearchKeydown,
    hoverTip,
    viewStartBp,
    viewEndBp,
    circScale,
    circPanX,
    circPanY,
    svgCanvasRef,
    totalLenBp,
    avgGcPct,
    allRegions,
    allRejected,
    allBaseFeatures,
    allScoreBins,
    allBaseBins,
    isGenbankSource,
    hasIntegraseOrTransposase,
    hasRnaFeatures,
    baseLayerLabel,
    searchPlaceholder,
    activeRegion,
    matchedFeatureIndices,
    matchedFeatureList,
    jumpToMatchedFeature,
    focusInterval,
    focusRegion,
    resetView,
    zoomLinear,
    zoomCircular,
    linearZoomFactor,
    getBaseFeatureColor,
    linX,
    linearTicks,
    visibleLinearFeatures,
    visibleLinearRegions,
    visibleLinearRejected,
    linearScoreGeometry,
    linearBaseGeometry,
    circularTicks,
    circularBaseFeatures,
    circularRegions,
    circularRejected,
    circularScoreRingPath,
    circularGcRingPath,
    circularSkewRingPath,
    onCanvasWheel,
    onCanvasMouseDown,
    onCanvasMouseMove,
    onCanvasMouseUp,
    showFeatureTip,
    showRegionTip,
    hideHoverTip,
    selectFeatureItem,
    exportSvgSnapshot,
    minimapIndicator,
    onMinimapClick,
    LIN_W,
    LIN_H,
    LIN_PAD_L,
    LIN_PAD_R,
    LIN_PLOT_W,
    CIRC_W,
    CIRC_H,
    CIRC_CX,
    CIRC_CY,
    formatBpAxis,
  }
}
