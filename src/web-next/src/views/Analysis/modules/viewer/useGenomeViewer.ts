/**
 * useGenomeViewer - 基因组环形/线性序列图谱视口、解析、过滤、轨迹与导出状态管理
 * 从 GenomeViewerModule.vue 拆解而出，聚焦计算与交互逻辑。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { computed, ref, watch } from 'vue'
import { parseGenBank, parseFasta } from './utils/parser'
import { calculateGC, calculateEnzymes } from './utils/calculations'
import { formatTickLabel, polarToCartesian } from './utils/render'
import { extractFeatureSequence, translateDNA } from './utils/sequence'

export interface GenomeViewerProps {
  initialGbk?: string
  initialName?: string
}

function calculateTickStep(len: number): number {
  if (len < 5000) return 200
  if (len < 20000) return 1000
  if (len < 100000) return 5000
  if (len < 500000) return 20000
  return 50000
}

export function useGenomeViewer(props: GenomeViewerProps) {
  const fileName = ref('')
  const sequenceLength = ref(0)
  const rawSequence = ref('')
  const features = ref<any[]>([])
  const viewMode = ref<'circular' | 'linear'>('circular')
  const isComputing = ref(false)
  const toastMessage = ref('')

  const searchQuery = ref('')
  const selectedCategoryFilter = ref('ALL')
  const strandFilter = ref('ALL')
  const highlightedCategory = ref('')
  const selectedFeature = ref<any>(null)
  const hoverFeature = ref<any>(null)

  const showGC = ref(true)
  const showEnzymes = ref(false)
  const showPositions = ref(true)

  const outerRadius = 245
  const innerRadius = 180
  const midSplitRadius = 212.5
  const gcBaselineR = 150
  const skewBaselineR = 110
  const centerCardRadius = 75

  const zoomScale = ref(1)
  const panX = ref(0)
  const panY = ref(0)
  let isPanning = false
  let startMouseX = 0
  let startMouseY = 0
  let initialPanX = 0
  let initialPanY = 0

  const tooltipX = ref(0)
  const tooltipY = ref(0)
  const svgRef = ref<SVGElement | null>(null)

  const computedLinearWidth = computed(() => Math.max(1200, sequenceLength.value * 0.08))

  const overallGC = computed(() => {
    if (!rawSequence.value || rawSequence.value.length === 0) return 0
    const seq = rawSequence.value.toUpperCase()
    let gcCount = 0
    for (let i = 0; i < seq.length; i++) {
      if (seq[i] === 'G' || seq[i] === 'C') gcCount++
    }
    return Number(((gcCount / seq.length) * 100).toFixed(2))
  })

  const prophageOverlayFeatures = computed(() =>
    features.value.filter((f: any) => f.type === 'prophage_region')
  )

  const baseTrackFeatures = computed(() =>
    features.value.filter((f: any) => f.type !== 'prophage_region')
  )

  const categoryCounts = computed(() => {
    const counts: Record<string, number> = {}
    for (const f of baseTrackFeatures.value) {
      const cat = f.category || 'Hypothetical'
      counts[cat] = (counts[cat] || 0) + 1
    }
    return counts
  })

  function matchesSearchAndFilter(f: any): boolean {
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      const matchName = (f.name || '').toLowerCase().includes(q)
      const matchLocus = (f.locus_tag || '').toLowerCase().includes(q)
      const matchProduct = (f.product || '').toLowerCase().includes(q)
      const matchGene = (f.gene || '').toLowerCase().includes(q)
      if (!matchName && !matchLocus && !matchProduct && !matchGene) return false
    }
    if (selectedCategoryFilter.value !== 'ALL' && f.category !== selectedCategoryFilter.value) {
      return false
    }
    if (strandFilter.value !== 'ALL' && f.strand !== strandFilter.value) {
      return false
    }
    return true
  }

  function isFeatureDimmed(f: any): boolean {
    if (selectedFeature.value) {
      if (selectedFeature.value.type === 'prophage_region') {
        return !(f.start >= selectedFeature.value.start && f.end <= selectedFeature.value.end)
      }
      return selectedFeature.value !== f
    }
    if (highlightedCategory.value) {
      return f.category !== highlightedCategory.value
    }
    if (searchQuery.value || selectedCategoryFilter.value !== 'ALL' || strandFilter.value !== 'ALL') {
      return !matchesSearchAndFilter(f)
    }
    return false
  }

  const filteredFeatures = computed(() => baseTrackFeatures.value.filter(matchesSearchAndFilter))

  const gcPaths = computed(() => {
    if (!rawSequence.value || !showGC.value) {
      return {
        gcPathData: '',
        gcHighPathData: '',
        gcLowPathData: '',
        gcSkewPosPathData: '',
        gcSkewNegPathData: '',
        gcBaselineRadius: gcBaselineR,
        skewBaselineRadius: skewBaselineR,
      }
    }
    return calculateGC(
      rawSequence.value,
      { innerR: 132, outerR: 168 },
      { innerR: 95, outerR: 125 }
    )
  })

  const enzymes = computed(() => {
    if (!rawSequence.value || !showEnzymes.value) return []
    return calculateEnzymes(rawSequence.value)
  })

  const renderCircularEnzymes = computed(() => enzymes.value.slice(0, 36))

  const circularTicks = computed(() => {
    if (!sequenceLength.value) return []
    const len = sequenceLength.value
    const step = calculateTickStep(len)
    const ticks = []
    for (let pos = 0; pos < len; pos += step) {
      const angle = (pos / len) * 360
      const isMajor = pos % (step * 5) === 0 || pos === 0
      const p1 = polarToCartesian(0, 0, outerRadius + 8, angle)
      const p2 = polarToCartesian(0, 0, outerRadius + (isMajor ? 18 : 13), angle)
      ticks.push({ x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, major: isMajor, pos })
    }
    return ticks
  })

  const majorCircularTicks = computed(() => {
    if (!sequenceLength.value) return []
    const len = sequenceLength.value
    const step = calculateTickStep(len) * 5
    const ticks = []
    for (let pos = 0; pos < len; pos += step) {
      const angle = (pos / len) * 360
      const p = polarToCartesian(0, 0, outerRadius + 32, angle)
      ticks.push({
        tx: p.x,
        ty: p.y,
        label: formatTickLabel(pos),
        anchor: angle > 10 && angle < 170 ? 'start' : angle > 190 && angle < 350 ? 'end' : 'middle',
      })
    }
    return ticks
  })

  const linearTicks = computed(() => {
    if (!sequenceLength.value) return []
    const len = sequenceLength.value
    const step = calculateTickStep(len)
    const width = computedLinearWidth.value
    const ticks = []
    for (let pos = 0; pos <= len; pos += step) {
      ticks.push({ x: (pos / len) * width, major: pos % (step * 5) === 0 || pos === 0, pos })
    }
    return ticks
  })

  const majorLinearTicks = computed(() => {
    if (!sequenceLength.value) return []
    const len = sequenceLength.value
    const step = calculateTickStep(len) * 5
    const width = computedLinearWidth.value
    const ticks = []
    for (let pos = 0; pos <= len; pos += step) {
      ticks.push({ x: (pos / len) * width, label: formatTickLabel(pos) })
    }
    return ticks
  })

  function selectFeature(feat: any) {
    selectedFeature.value = feat
  }

  function toggleHighlightCategory(catKey: string) {
    highlightedCategory.value = highlightedCategory.value === catKey ? '' : catKey
  }

  function handleCanvasClick(e: MouseEvent) {
    const target = e.target as HTMLElement
    if (target.tagName === 'svg' || target.classList.contains('svg-container')) {
      selectedFeature.value = null
    }
  }

  function showToast(msg: string) {
    toastMessage.value = msg
    setTimeout(() => {
      toastMessage.value = ''
    }, 2000)
  }

  function handleZoom(e: WheelEvent) {
    const delta = e.deltaY > 0 ? -0.1 : 0.1
    zoomScale.value = Number(Math.min(Math.max(0.4, zoomScale.value + delta), 4.5).toFixed(2))
  }

  function zoomIn() {
    zoomScale.value = Math.min(4.5, Number((zoomScale.value + 0.2).toFixed(2)))
  }

  function zoomOut() {
    zoomScale.value = Math.max(0.4, Number((zoomScale.value - 0.2).toFixed(2)))
  }

  function resetView() {
    zoomScale.value = 1
    panX.value = 0
    panY.value = 0
  }

  function startPan(e: MouseEvent) {
    if (e.button !== 0) return
    isPanning = true
    startMouseX = e.clientX
    startMouseY = e.clientY
    initialPanX = panX.value
    initialPanY = panY.value
  }

  function doPan(e: MouseEvent) {
    if (!isPanning) {
      tooltipX.value = e.clientX + 16
      tooltipY.value = e.clientY + 16
      return
    }
    panX.value = initialPanX + (e.clientX - startMouseX)
    panY.value = initialPanY + (e.clientY - startMouseY)
  }

  function endPan() {
    isPanning = false
  }

  function loadSequenceData(content: string, name: string) {
    isComputing.value = true
    setTimeout(() => {
      try {
        if (content.includes('LOCUS') || content.includes('FEATURES')) {
          const parsed = parseGenBank(content)
          rawSequence.value = parsed.sequence
          sequenceLength.value = parsed.sequence.length
          features.value = parsed.features
        } else {
          const parsed = parseFasta(content)
          rawSequence.value = parsed.sequence
          sequenceLength.value = parsed.sequence.length
          features.value = []
        }
        fileName.value = name
        resetView()
      } catch (err) {
        console.error('解析序列失败:', err)
      } finally {
        isComputing.value = false
      }
    }, 50)
  }

  function handleFileUpload(e: Event) {
    const input = e.target as HTMLInputElement
    if (!input.files || input.files.length === 0) return
    const file = input.files[0]
    if (!file) return
    fileName.value = file.name
    const reader = new FileReader()
    reader.onload = (event) => {
      const text = event.target?.result as string
      loadSequenceData(text, file.name)
    }
    reader.readAsText(file)
  }

  function copySequence() {
    if (!selectedFeature.value) return
    const seq = extractFeatureSequence(
      rawSequence.value,
      selectedFeature.value.start,
      selectedFeature.value.end,
      selectedFeature.value.strand
    )
    navigator.clipboard.writeText(seq)
    const label = selectedFeature.value.type === 'prophage_region' ? '前噬菌体区段核酸序列' : '核酸 CDS 序列'
    showToast(`${label}已成功复制到剪贴板`)
  }

  function copyTranslation() {
    if (!selectedFeature.value) return
    let trans = selectedFeature.value.translation
    if (!trans && rawSequence.value) {
      const dna = extractFeatureSequence(
        rawSequence.value,
        selectedFeature.value.start,
        selectedFeature.value.end,
        selectedFeature.value.strand
      )
      trans = translateDNA(dna)
    }
    navigator.clipboard.writeText(trans || '')
    showToast('蛋白质多肽翻译序列已成功复制到剪贴板')
  }

  function exportImage(format: 'png' | 'svg') {
    if (!svgRef.value) return
    const svgEl = svgRef.value
    const serializer = new XMLSerializer()
    const svgString = serializer.serializeToString(svgEl)

    if (format === 'svg') {
      const svgHeader = '<?xml version="1.0" standalone="no"?>\r\n'
      const blob = new Blob([svgHeader + svgString], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${fileName.value || 'genome_map'}.svg`
      link.click()
      URL.revokeObjectURL(url)
      showToast('SVG 矢量图已成功导出')
    } else {
      const canvas = document.createElement('canvas')
      const bbox = svgEl.getBoundingClientRect()
      const scale = 2
      canvas.width = (bbox.width || 1200) * scale
      canvas.height = (bbox.height || 900) * scale
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      ctx.scale(scale, scale)
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      const img = new Image()
      const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(svgBlob)

      img.onload = () => {
        ctx.drawImage(img, 0, 0, bbox.width, bbox.height)
        URL.revokeObjectURL(url)
        const pngUrl = canvas.toDataURL('image/png')
        const link = document.createElement('a')
        link.href = pngUrl
        link.download = `${fileName.value || 'genome_map'}.png`
        link.click()
        showToast('PNG 高清图片已成功导出')
      }
      img.src = url
    }
  }

  watch(
    () => props.initialGbk,
    (newGbk) => {
      if (newGbk) {
        loadSequenceData(newGbk, props.initialName || 'Annotated_Phage.gbk')
      }
    },
    { immediate: true }
  )

  return {
    fileName,
    sequenceLength,
    rawSequence,
    features,
    viewMode,
    isComputing,
    toastMessage,
    searchQuery,
    selectedCategoryFilter,
    strandFilter,
    highlightedCategory,
    selectedFeature,
    hoverFeature,
    showGC,
    showEnzymes,
    showPositions,
    outerRadius,
    innerRadius,
    midSplitRadius,
    gcBaselineR,
    skewBaselineR,
    centerCardRadius,
    zoomScale,
    panX,
    panY,
    tooltipX,
    tooltipY,
    svgRef,
    computedLinearWidth,
    overallGC,
    prophageOverlayFeatures,
    baseTrackFeatures,
    categoryCounts,
    filteredFeatures,
    gcPaths,
    enzymes,
    renderCircularEnzymes,
    circularTicks,
    majorCircularTicks,
    linearTicks,
    majorLinearTicks,
    isFeatureDimmed,
    selectFeature,
    toggleHighlightCategory,
    handleCanvasClick,
    handleZoom,
    zoomIn,
    zoomOut,
    resetView,
    startPan,
    doPan,
    endPan,
    handleFileUpload,
    copySequence,
    copyTranslation,
    exportImage,
  }
}
