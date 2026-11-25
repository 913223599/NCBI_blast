import { PhyloTreeLayout, type LayoutBounds } from './TreeLayout'
import { formatNodeDisplayLabel, type PhyloTreeModel, type PhyloTreeNode } from './TreeModel'
import {
  buildStarPolygonPoints,
  computeNiceScaleValue,
  detectMonophyleticClades,
  getHostPhylumColor,
  isFormalTaxonName,
  JOURNAL_THEMES,
  mapHostToPhylum,
  splitTaxonomicLabelSegments,
  type JournalThemeConfig,
} from './JournalTheme'
import type { TreeVisualSettings } from '../types/phylo'

const SVG_NS = 'http://www.w3.org/2000/svg'
const FONT_STACK = 'Arial, Helvetica, "Microsoft YaHei", sans-serif'
const HYBRID_THRESHOLD_LEAVES = 1500

export interface ViewportTransform {
  scale: number
  tx: number
  ty: number
}

interface WorldBox {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

function createAnnularSectorPath(
  rIn: number,
  rOut: number,
  startAng: number,
  endAng: number
): string {
  const largeArc = Math.abs(endAng - startAng) > Math.PI ? 1 : 0
  const x1 = rIn * Math.cos(startAng)
  const y1 = rIn * Math.sin(startAng)
  const x2 = rOut * Math.cos(startAng)
  const y2 = rOut * Math.sin(startAng)
  const x3 = rOut * Math.cos(endAng)
  const y3 = rOut * Math.sin(endAng)
  const x4 = rIn * Math.cos(endAng)
  const y4 = rIn * Math.sin(endAng)
  return [
    `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    `L ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    `A ${rOut.toFixed(2)} ${rOut.toFixed(2)} 0 ${largeArc} 1 ${x3.toFixed(2)} ${y3.toFixed(2)}`,
    `L ${x4.toFixed(2)} ${y4.toFixed(2)}`,
    `A ${rIn.toFixed(2)} ${rIn.toFixed(2)} 0 ${largeArc} 0 ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    'Z',
  ].join(' ')
}

export class PhyloTreeCanvas {
  private container: HTMLElement | null = null
  private svg: SVGSVGElement | null = null
  private rootGroup: SVGGElement | null = null
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null
  private scaleBarEl: HTMLDivElement | null = null
  private scaleBarLineEl: HTMLDivElement | null = null
  private scaleBarTextEl: HTMLDivElement | null = null
  private resizeObserver: ResizeObserver | null = null
  private labelCullTimer: ReturnType<typeof setTimeout> | null = null

  private model: PhyloTreeModel | null = null
  private settings: TreeVisualSettings | null = null
  private bounds: LayoutBounds | null = null
  private transform: ViewportTransform = { scale: 1, tx: 40, ty: 40 }

  private isPanning = false
  private dragStart = { x: 0, y: 0 }
  private dragMoved = false

  onNodeClick: ((node: PhyloTreeNode, clientX: number, clientY: number) => void) | null = null

  private getTheme(settings?: TreeVisualSettings | null): JournalThemeConfig {
    return JOURNAL_THEMES[settings?.journalTheme || 'nature'] || JOURNAL_THEMES.nature
  }

  mount(container: HTMLElement): void {
    this.dispose()
    this.container = container
    this.container.innerHTML = ''
    this.container.style.position = 'relative'
    this.container.style.overflow = 'hidden'
    this.container.style.userSelect = 'none'

    // 底层 Canvas（超大规模树时绘制枝干）
    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.inset = '0'
    this.canvas.style.pointerEvents = 'none'
    this.ctx = this.canvas.getContext('2d')
    this.container.appendChild(this.canvas)

    // 矢量交互 SVG 层
    this.svg = document.createElementNS(SVG_NS, 'svg')
    this.svg.setAttribute('width', '100%')
    this.svg.setAttribute('height', '100%')
    this.svg.style.position = 'absolute'
    this.svg.style.inset = '0'
    this.svg.style.cursor = 'grab'

    this.rootGroup = document.createElementNS(SVG_NS, 'g')
    this.svg.appendChild(this.rootGroup)
    this.container.appendChild(this.svg)

    // 左下角科学比例尺（纯 DOM 构建）
    this.scaleBarEl = document.createElement('div')
    this.scaleBarEl.style.cssText =
      'display:none;position:absolute;left:16px;bottom:14px;pointer-events:none;font-size:11px;color:#334155;font-family:Arial,Helvetica,sans-serif;background:rgba(255,255,255,0.92);padding:5px 9px;border-radius:6px;border:1px solid #e2e8f0;'
    this.scaleBarLineEl = document.createElement('div')
    this.scaleBarLineEl.style.cssText =
      'height:2px;background:#0f172a;margin-bottom:4px;border-left:1.5px solid #0f172a;border-right:1.5px solid #0f172a;'
    this.scaleBarTextEl = document.createElement('div')
    this.scaleBarEl.appendChild(this.scaleBarLineEl)
    this.scaleBarEl.appendChild(this.scaleBarTextEl)
    this.container.appendChild(this.scaleBarEl)

    this.bindInteractions()
    this.syncCanvasSize()
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => {
        this.syncCanvasSize()
        this.redraw()
      })
      this.resizeObserver.observe(this.container)
    }
  }

  private syncCanvasSize(): void {
    if (!this.container || !this.canvas) return
    const rect = this.container.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    this.canvas.style.width = `${rect.width}px`
    this.canvas.style.height = `${rect.height}px`
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr))
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr))
  }

  private bindInteractions(): void {
    if (!this.svg) return
    this.svg.addEventListener(
      'wheel',
      (e: WheelEvent) => {
        e.preventDefault()
        if (!this.svg) return
        const rect = this.svg.getBoundingClientRect()
        const mx = e.clientX - rect.left
        const my = e.clientY - rect.top
        const factor = e.deltaY < 0 ? 1.12 : 0.89
        const prevScale = this.transform.scale
        const nextScale = Math.max(0.08, Math.min(18, prevScale * factor))
        const ratio = nextScale / prevScale
        this.transform.tx = mx - (mx - this.transform.tx) * ratio
        this.transform.ty = my - (my - this.transform.ty) * ratio
        this.transform.scale = nextScale
        if (
          this.model &&
          this.settings?.layout === 'circular' &&
          this.settings.smartLabelCull &&
          this.model.leaves.length > 90 &&
          ((prevScale < 2.2 && nextScale >= 2.2) || (prevScale >= 2.2 && nextScale < 2.2))
        ) {
          this.redraw()
          return
        }
        this.applyTransformOnly()
        this.scheduleHybridLabelRefresh()
      },
      { passive: false }
    )

    this.svg.addEventListener('mousedown', (e: MouseEvent) => {
      if (e.button !== 0) return
      this.isPanning = true
      this.dragMoved = false
      this.dragStart = { x: e.clientX, y: e.clientY }
      if (this.svg) this.svg.style.cursor = 'grabbing'
    })

    window.addEventListener('mousemove', this.handleMouseMove)
    window.addEventListener('mouseup', this.handleMouseUp)
  }

  private handleMouseMove = (e: MouseEvent): void => {
    if (!this.isPanning) return
    const dx = e.clientX - this.dragStart.x
    const dy = e.clientY - this.dragStart.y
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this.dragMoved = true
    this.transform.tx += dx
    this.transform.ty += dy
    this.dragStart = { x: e.clientX, y: e.clientY }
    this.applyTransformOnly()
  }

  private handleMouseUp = (): void => {
    if (!this.isPanning) return
    this.isPanning = false
    if (this.svg) this.svg.style.cursor = 'grab'
    if (this.dragMoved) {
      this.scheduleHybridLabelRefresh()
    }
  }

  private scheduleHybridLabelRefresh(): void {
    if (!this.model || this.model.leaves.length <= HYBRID_THRESHOLD_LEAVES) return
    if (this.labelCullTimer) clearTimeout(this.labelCullTimer)
    this.labelCullTimer = setTimeout(() => {
      this.redraw()
    }, 60)
  }

  clear(): void {
    this.model = null
    this.bounds = null
    if (this.rootGroup) {
      while (this.rootGroup.firstChild) this.rootGroup.removeChild(this.rootGroup.firstChild)
    }
    if (this.ctx && this.canvas) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
    if (this.scaleBarEl) {
      this.scaleBarEl.style.display = 'none'
    }
  }

  render(model: PhyloTreeModel, settings: TreeVisualSettings, fit = false, relayout = true): void {
    model.applyJournalTheme(settings.journalTheme || 'nature')
    this.model = model
    this.settings = { ...settings }
    if (relayout || !this.bounds) {
      this.bounds = PhyloTreeLayout.compute(model, settings)
    }
    if (fit) this.fitView()
    else this.redraw()
  }

  fitView(): void {
    if (!this.container || !this.bounds) return
    const rect = this.container.getBoundingClientRect()
    const w = Math.max(200, rect.width)
    const h = Math.max(200, rect.height)
    const bw = Math.max(50, this.bounds.maxX - this.bounds.minX)
    const bh = Math.max(50, this.bounds.maxY - this.bounds.minY)
    const scale = Math.max(0.12, Math.min(2.2, Math.min((w - 48) / bw, (h - 48) / bh)))
    this.transform.scale = scale
    this.transform.tx = (w - bw * scale) * 0.5 - this.bounds.minX * scale
    this.transform.ty = (h - bh * scale) * 0.5 - this.bounds.minY * scale
    this.redraw()
  }

  zoomBy(factor: number): void {
    if (!this.container) return
    const rect = this.container.getBoundingClientRect()
    const cx = rect.width * 0.5
    const cy = rect.height * 0.5
    const nextScale = Math.max(0.08, Math.min(18, this.transform.scale * factor))
    const ratio = nextScale / this.transform.scale
    this.transform.tx = cx - (cx - this.transform.tx) * ratio
    this.transform.ty = cy - (cy - this.transform.ty) * ratio
    this.transform.scale = nextScale
    this.applyTransformOnly()
    this.scheduleHybridLabelRefresh()
  }

  private applyTransformOnly(): void {
    if (this.rootGroup) {
      this.rootGroup.setAttribute(
        'transform',
        `translate(${this.transform.tx.toFixed(2)},${this.transform.ty.toFixed(2)}) scale(${this.transform.scale.toFixed(4)})`
      )
    }
    if (this.model && this.settings && this.model.leaves.length > HYBRID_THRESHOLD_LEAVES) {
      this.drawCanvasEdges()
    }
    this.updateScaleBar()
  }

  private computeNiceScaleBar(): { unitVal: number; pxWidth: number } {
    const barPx = 84
    const distPerPx = (this.bounds?.scaleUnitsPerPx || 1) / Math.max(0.01, this.transform.scale)
    const unitVal = computeNiceScaleValue(barPx * distPerPx)
    const pxWidth = Math.max(28, Math.min(150, unitVal / distPerPx))
    return { unitVal, pxWidth }
  }

  private updateScaleBar(): void {
    if (!this.scaleBarEl || !this.scaleBarLineEl || !this.scaleBarTextEl || !this.bounds || !this.settings) return
    if (!this.settings.useBranchLengths) {
      this.scaleBarEl.style.display = 'none'
      return
    }
    this.scaleBarEl.style.display = 'block'
    const { unitVal, pxWidth } = this.computeNiceScaleBar()
    this.scaleBarLineEl.style.width = `${pxWidth.toFixed(0)}px`
    this.scaleBarTextEl.textContent = `${unitVal} substitutions/site`
  }

  private getViewportWorldBox(): WorldBox | null {
    if (!this.container || !this.model || this.model.leaves.length <= HYBRID_THRESHOLD_LEAVES) {
      return null
    }
    const rect = this.container.getBoundingClientRect()
    const padPx = 180
    const s = Math.max(0.01, this.transform.scale)
    return {
      minX: (-padPx - this.transform.tx) / s,
      maxX: (rect.width + padPx - this.transform.tx) / s,
      minY: (-padPx - this.transform.ty) / s,
      maxY: (rect.height + padPx - this.transform.ty) / s,
    }
  }

  private redraw(): void {
    if (!this.model || !this.settings || !this.rootGroup || !this.model.root) return
    while (this.rootGroup.firstChild) this.rootGroup.removeChild(this.rootGroup.firstChild)
    if (this.ctx && this.canvas) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }

    if (this.settings.showCladeShading && this.settings.layout !== 'unrooted') {
      this.rootGroup.appendChild(this.createSvgCladesGroup(this.model, this.settings))
    }

    const useCanvasEdges = this.model.leaves.length > HYBRID_THRESHOLD_LEAVES
    if (useCanvasEdges) {
      this.drawCanvasEdges()
    } else {
      this.rootGroup.appendChild(this.createSvgEdgesGroup(this.model, this.settings))
    }

    const cullBox = this.getViewportWorldBox()
    this.rootGroup.appendChild(this.createSvgNodesGroup(this.model, this.settings, cullBox, true))
    this.applyTransformOnly()
  }

  private resolveEdgeStroke(
    node: PhyloTreeNode,
    theme: JournalThemeConfig
  ): { color: string; width: number; dashed: boolean } {
    if (node.cladeColor) {
      return { color: node.cladeColor, width: 1.7, dashed: false }
    }
    if (node.isLeaf) {
      const role = node.meta?.role
      if (role === 'query') return { color: theme.queryColor, width: 1.9, dashed: false }
      if (role === 'outgroup') return { color: theme.outgroupColor, width: 1.25, dashed: true }
    }
    return { color: theme.backboneColor, width: 1.3, dashed: false }
  }

  private computeCircularLabelSpan(model: PhyloTreeModel, settings: TreeVisualSettings): number {
    if (!settings.showLabels) return 18
    if (settings.smartLabelCull && model.leaves.length > 90) {
      return 20
    }
    let maxChars = 10
    for (const lf of model.leaves) {
      const len = formatNodeDisplayLabel(lf, settings.labelFormat).length
      if (len > maxChars) maxChars = len
    }
    return Math.min(280, Math.max(85, Math.ceil(maxChars * settings.fontSize * 0.54)))
  }

  private createSvgCladesGroup(model: PhyloTreeModel, settings: TreeVisualSettings): SVGGElement {
    const cladeGroup = document.createElementNS(SVG_NS, 'g')
    cladeGroup.setAttribute('class', 'phylo-clades')
    if (!model.root || !this.bounds || !model.hasNodeMetadata) return cladeGroup

    const allClades = detectMonophyleticClades(model.root, model.leaves, model.genusColors)
    const hasAnyQuery = model.leaves.some((lf) => lf.meta?.role === 'query')
    const clades = hasAnyQuery ? allClades.filter((c) => c.containsQuery) : allClades
    if (clades.length === 0) return cladeGroup

    const theme = this.getTheme(settings)
    if (settings.layout === 'rect') {
      const rowStep = Math.max(12, settings.rowSpacing)
      const rightX = (this.bounds.labelEndX || this.bounds.maxX) - 6
      for (const cl of clades) {
        const firstLeaf = model.leaves[cl.leafStartIdx]
        const lastLeaf = model.leaves[cl.leafEndIdx]
        if (!firstLeaf || !lastLeaf) continue
        const xLeft = Math.max(0, cl.node.x - 4)
        const yTop = firstLeaf.y - rowStep * 0.44
        const yBot = lastLeaf.y + rowStep * 0.44
        const rect = document.createElementNS(SVG_NS, 'rect')
        rect.setAttribute('x', xLeft.toFixed(1))
        rect.setAttribute('y', yTop.toFixed(1))
        rect.setAttribute('width', Math.max(16, rightX - xLeft).toFixed(1))
        rect.setAttribute('height', Math.max(8, yBot - yTop).toFixed(1))
        rect.setAttribute('rx', '4')
        rect.setAttribute('fill', cl.color)
        rect.setAttribute('fill-opacity', String(theme.cladeOpacity))
        cladeGroup.appendChild(rect)

        if (!settings.showMetadataStrips) {
          const bx = rightX + 10
          const bracket = document.createElementNS(SVG_NS, 'line')
          bracket.setAttribute('x1', bx.toFixed(1))
          bracket.setAttribute('y1', (yTop + 2).toFixed(1))
          bracket.setAttribute('x2', bx.toFixed(1))
          bracket.setAttribute('y2', (yBot - 2).toFixed(1))
          bracket.setAttribute('stroke', cl.color)
          bracket.setAttribute('stroke-width', '2')
          cladeGroup.appendChild(bracket)

          const bTxt = document.createElementNS(SVG_NS, 'text')
          bTxt.setAttribute('x', (bx + 6).toFixed(1))
          bTxt.setAttribute('y', ((yTop + yBot) * 0.5).toFixed(1))
          bTxt.setAttribute('dominant-baseline', 'middle')
          bTxt.setAttribute('font-family', FONT_STACK)
          bTxt.setAttribute('font-size', `${Math.max(10, settings.fontSize - 1)}`)
          bTxt.setAttribute('font-weight', '700')
          if (isFormalTaxonName(cl.taxonName)) bTxt.setAttribute('font-style', 'italic')
          bTxt.setAttribute('fill', cl.color)
          bTxt.textContent = cl.taxonName
          cladeGroup.appendChild(bTxt)
        }
      }
    } else if (settings.layout === 'circular') {
      const nLeaves = Math.max(1, model.leaves.length)
      const halfStep = ((Math.PI * 1.92) / nLeaves) * 0.46
      const outerR = (this.bounds.outerRadius || 240) + this.computeCircularLabelSpan(model, settings) + 6

      // 绘制极淡同心演化距离参考虚线圆
      if (settings.useBranchLengths && nLeaves > 24 && this.bounds.outerRadius) {
        for (const frac of [0.33, 0.67]) {
          const rRing = this.bounds.outerRadius * frac
          const ringCircle = document.createElementNS(SVG_NS, 'circle')
          ringCircle.setAttribute('cx', '0')
          ringCircle.setAttribute('cy', '0')
          ringCircle.setAttribute('r', rRing.toFixed(1))
          ringCircle.setAttribute('fill', 'none')
          ringCircle.setAttribute('stroke', '#e2e8f0')
          ringCircle.setAttribute('stroke-width', '0.8')
          ringCircle.setAttribute('stroke-dasharray', '4 4')
          cladeGroup.appendChild(ringCircle)
        }
      }

      for (const cl of clades) {
        const firstLeaf = model.leaves[cl.leafStartIdx]
        const lastLeaf = model.leaves[cl.leafEndIdx]
        if (!firstLeaf || !lastLeaf) continue
        const rIn = Math.max(10, cl.node.radius - 6)
        const a1 = firstLeaf.angle - halfStep
        const a2 = lastLeaf.angle + halfStep
        if (a2 > a1 && outerR > rIn) {
          const path = document.createElementNS(SVG_NS, 'path')
          path.setAttribute('d', createAnnularSectorPath(rIn, outerR, a1, a2))
          path.setAttribute('fill', cl.color)
          path.setAttribute('fill-opacity', String(theme.cladeOpacity))
          cladeGroup.appendChild(path)
        }
      }
    }

    return cladeGroup
  }

  private drawCanvasEdges(): void {
    if (!this.ctx || !this.canvas || !this.model?.root || !this.settings) return
    const dpr = window.devicePixelRatio || 1
    const ctx = this.ctx
    const theme = this.getTheme(this.settings)
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    ctx.setTransform(
      this.transform.scale * dpr,
      0,
      0,
      this.transform.scale * dpr,
      this.transform.tx * dpr,
      this.transform.ty * dpr
    )
    ctx.lineCap = 'round'

    const drawNode = (node: PhyloTreeNode) => {
      if (node.collapsed) return
      for (const ch of node.children) {
        const style = this.resolveEdgeStroke(ch, theme)
        ctx.beginPath()
        ctx.strokeStyle = style.color
        ctx.lineWidth = Math.max(0.75, style.width / this.transform.scale)
        ctx.setLineDash(style.dashed ? [4, 3] : [])
        if (this.settings!.layout === 'rect') {
          ctx.moveTo(node.x, node.y)
          ctx.lineTo(node.x, ch.y)
          ctx.lineTo(ch.x, ch.y)
        } else if (this.settings!.layout === 'circular') {
          const rParent = node.radius
          const xArcStart = rParent * Math.cos(ch.angle)
          const yArcStart = rParent * Math.sin(ch.angle)
          ctx.moveTo(node.x, node.y)
          ctx.arc(0, 0, rParent, node.angle, ch.angle, ch.angle < node.angle)
          ctx.moveTo(xArcStart, yArcStart)
          ctx.lineTo(ch.x, ch.y)
        } else {
          ctx.moveTo(node.x, node.y)
          ctx.lineTo(ch.x, ch.y)
        }
        ctx.stroke()
        drawNode(ch)
      }
    }
    drawNode(this.model.root)
    ctx.setLineDash([])
  }

  private createSvgEdgesGroup(model: PhyloTreeModel, settings: TreeVisualSettings): SVGGElement {
    const edgeGroup = document.createElementNS(SVG_NS, 'g')
    edgeGroup.setAttribute('class', 'phylo-edges')
    if (!model.root) return edgeGroup

    const theme = this.getTheme(settings)
    const walk = (node: PhyloTreeNode) => {
      if (node.collapsed) return
      for (const ch of node.children) {
        const path = document.createElementNS(SVG_NS, 'path')
        let d = ''
        if (settings.layout === 'rect') {
          d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} L ${node.x.toFixed(2)} ${ch.y.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
        } else if (settings.layout === 'circular') {
          const r = node.radius
          const x1 = r * Math.cos(ch.angle)
          const y1 = r * Math.sin(ch.angle)
          const sweep = ch.angle >= node.angle ? 1 : 0
          const largeArc = Math.abs(ch.angle - node.angle) > Math.PI ? 1 : 0
          d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} A ${r.toFixed(2)} ${r.toFixed(2)} 0 ${largeArc} ${sweep} ${x1.toFixed(2)} ${y1.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
        } else {
          d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
        }
        const style = this.resolveEdgeStroke(ch, theme)
        path.setAttribute('d', d)
        path.setAttribute('fill', 'none')
        path.setAttribute('stroke', style.color)
        path.setAttribute('stroke-width', style.width.toFixed(2))
        path.setAttribute('stroke-linecap', 'round')
        if (style.dashed) {
          path.setAttribute('stroke-dasharray', '4 3')
        }
        edgeGroup.appendChild(path)
        walk(ch)
      }
    }
    walk(model.root)
    return edgeGroup
  }

  private appendStyledLabelText(
    labelEl: SVGTextElement,
    displayText: string,
    italicize: boolean,
    isOutgroup: boolean
  ): void {
    if (!italicize || isOutgroup) {
      labelEl.textContent = displayText
      if (isOutgroup) labelEl.setAttribute('font-style', 'italic')
      return
    }
    const segments = splitTaxonomicLabelSegments(displayText)
    if (segments.length === 1 && !segments[0]?.italic) {
      labelEl.textContent = displayText
      return
    }
    for (const seg of segments) {
      const tspan = document.createElementNS(SVG_NS, 'tspan')
      tspan.textContent = seg.text
      if (seg.italic) tspan.setAttribute('font-style', 'italic')
      labelEl.appendChild(tspan)
    }
  }

  private createSvgNodesGroup(
    model: PhyloTreeModel,
    settings: TreeVisualSettings,
    cullBox: WorldBox | null,
    interactive: boolean
  ): SVGGElement {
    const group = document.createElementNS(SVG_NS, 'g')
    group.setAttribute('class', 'phylo-nodes')
    if (!model.root) return group

    const theme = this.getTheme(settings)
    const query = (settings.searchQuery || '').trim().toLowerCase()
    const frag = document.createDocumentFragment()

    const inViewport = (x: number, y: number): boolean => {
      if (!cullBox) return true
      return x >= cullBox.minX && x <= cullBox.maxX && y >= cullBox.minY && y <= cullBox.maxY
    }

    const bindClick = (el: SVGElement, node: PhyloTreeNode) => {
      if (!interactive) return
      el.style.cursor = 'pointer'
      el.addEventListener('click', (ev) => {
        ev.stopPropagation()
        if (!this.dragMoved) this.onNodeClick?.(node, ev.clientX, ev.clientY)
      })
    }

    // 矩形模式右侧轨道表头
    if (
      settings.layout === 'rect' &&
      settings.showMetadataStrips &&
      model.hasNodeMetadata &&
      this.bounds?.labelEndX
    ) {
      const stripX = this.bounds.labelEndX + 8
      const headerY = -12
      const addHeader = (x: number, text: string, color: string) => {
        const h = document.createElementNS(SVG_NS, 'text')
        h.setAttribute('x', x.toFixed(1))
        h.setAttribute('y', headerY.toFixed(1))
        h.setAttribute('font-size', '10')
        h.setAttribute('font-weight', '700')
        h.setAttribute('font-family', FONT_STACK)
        h.setAttribute('fill', color)
        h.textContent = text
        frag.appendChild(h)
      }
      addHeader(stripX, 'Genus', '#0f172a')
      let sizeStart = stripX + 118
      if (model.hasHostMetadata) {
        addHeader(stripX + 114, 'Host', '#334155')
        sizeStart = stripX + 156
      }
      if (model.maxGenomeLength > 0) {
        addHeader(sizeStart, 'Size (kb)', theme.sizeBarColor)
      }
    }

    // 环形模式外圈同心环参数预计算
    const isCircular = settings.layout === 'circular'
    const isMacroCircular =
      isCircular && Boolean(settings.smartLabelCull) && model.leaves.length > 90
    const hideBgCircularLabels =
      isMacroCircular && (!interactive || this.transform.scale < 2.2)
    const circOuterR = this.bounds?.outerRadius || 240
    const circLabelSpan = isCircular ? this.computeCircularLabelSpan(model, settings) : 0
    const circRingR = circOuterR + (isMacroCircular ? 12 : 16 + circLabelSpan)
    const circHalfAng =
      ((Math.PI * 1.92) / Math.max(1, model.leaves.length)) *
      (model.leaves.length > 100 ? 0.5 : 0.44)
    if (isCircular && settings.showMetadataStrips && model.hasNodeMetadata) {
      const addRingTag = (rMid: number, text: string, color: string) => {
        const t = document.createElementNS(SVG_NS, 'text')
        t.setAttribute('x', rMid.toFixed(1))
        t.setAttribute('y', '-8')
        t.setAttribute('text-anchor', 'middle')
        t.setAttribute('font-size', '9')
        t.setAttribute('font-weight', '700')
        t.setAttribute('font-family', FONT_STACK)
        t.setAttribute('fill', color)
        t.textContent = text
        frag.appendChild(t)
      }
      addRingTag(circRingR + 8, 'Genus', '#0f172a')
      if (model.hasHostMetadata) {
        addRingTag(circRingR + 27, 'Host', '#334155')
      }
    }

    const walk = (node: PhyloTreeNode) => {
      const isTerminal = node.isLeaf || node.collapsed
      const displayText = node.isLeaf ? formatNodeDisplayLabel(node, settings.labelFormat) : node.name
      const isMatch = Boolean(
        query &&
          (node.name.toLowerCase().includes(query) || displayText.toLowerCase().includes(query))
      )
      const visible = isMatch || inViewport(node.x, node.y)

      if (visible && node.collapsed) {
        const tri = document.createElementNS(SVG_NS, 'polygon')
        const s = 9
        tri.setAttribute(
          'points',
          `${node.x},${node.y} ${node.x + s * 1.6},${node.y - s} ${node.x + s * 1.6},${node.y + s}`
        )
        tri.setAttribute('fill', node.cladeColor || theme.taxonColors[0]!)
        tri.setAttribute('opacity', '0.85')
        bindClick(tri, node)
        frag.appendChild(tri)
      }

      if (visible && !isTerminal && node.parent) {
        const ufVal = node.ufboot ?? node.support
        const isStrongUf = Boolean(settings.highlightStrongUfboot && ufVal !== null && ufVal >= 95)
        const isModerateUf = Boolean(
          ufVal !== null && ufVal >= settings.supportThreshold && !isStrongUf
        )

        if (isStrongUf || isModerateUf) {
          const dot = document.createElementNS(SVG_NS, 'circle')
          dot.setAttribute('cx', node.x.toFixed(2))
          dot.setAttribute('cy', node.y.toFixed(2))
          if (isStrongUf) {
            dot.setAttribute('r', '4.1')
            dot.setAttribute('fill', theme.strongDotColor)
            dot.setAttribute('stroke', '#ffffff')
            dot.setAttribute('stroke-width', '0.9')
          } else {
            dot.setAttribute('r', '3.6')
            dot.setAttribute('fill', '#ffffff')
            dot.setAttribute('stroke', theme.moderateDotEdge)
            dot.setAttribute('stroke-width', '1.4')
          }
          bindClick(dot, node)
          frag.appendChild(dot)
        } else if (interactive) {
          // 交互视图下保留透明点击热区，导出 SVG 时保持整洁不画点
          const hit = document.createElementNS(SVG_NS, 'circle')
          hit.setAttribute('cx', node.x.toFixed(2))
          hit.setAttribute('cy', node.y.toFixed(2))
          hit.setAttribute('r', '5')
          hit.setAttribute('fill', 'transparent')
          bindClick(hit, node)
          frag.appendChild(hit)
        }

        if (settings.showSupport && ufVal !== null && ufVal >= settings.supportThreshold) {
          const isRad = settings.layout === 'circular' || settings.layout === 'unrooted'
          if (!isRad || node.radius > 16 || ufVal >= 95) {
            const supTxt = document.createElementNS(SVG_NS, 'text')
            if (isRad) {
              supTxt.setAttribute('x', node.x.toFixed(2))
              supTxt.setAttribute('y', (node.y - 6).toFixed(2))
              supTxt.setAttribute('text-anchor', 'middle')
              supTxt.setAttribute('font-size', `${Math.max(7, settings.fontSize - 4)}`)
            } else {
              supTxt.setAttribute('x', (node.x - 6).toFixed(2))
              supTxt.setAttribute('y', (node.y - 5).toFixed(2))
              supTxt.setAttribute('text-anchor', 'end')
              supTxt.setAttribute('font-size', `${Math.max(8, settings.fontSize - 3)}`)
            }
            supTxt.setAttribute('font-family', FONT_STACK)
            supTxt.setAttribute('fill', isStrongUf ? '#0f172a' : '#475569')
            if (isStrongUf) supTxt.setAttribute('font-weight', '700')
            supTxt.textContent = node.supportLabel || String(Math.round(ufVal))
            frag.appendChild(supTxt)
          }
        }
      }

      if (visible && isTerminal) {
        const role = node.meta?.role
        const genusColor =
          node.meta?.genus && model.genusColors.get(node.meta.genus)
            ? model.genusColors.get(node.meta.genus)!
            : null
        let tipFill = node.cladeColor || theme.backboneColor
        let labelFill = node.cladeColor || '#0f172a'
        if (role === 'query') {
          tipFill = theme.queryColor
          labelFill = theme.queryTextColor
        } else if (role === 'outgroup') {
          tipFill = theme.outgroupColor
          labelFill = '#475569'
        } else if (genusColor) {
          tipFill = genusColor
        }

        // 查询株绘矢量五角星，普通参考株在导出时保持干净末端（交互视图仅留透明拾取区）
        if (role === 'query' && !isMatch) {
          const star = document.createElementNS(SVG_NS, 'polygon')
          star.setAttribute('points', buildStarPolygonPoints(node.x, node.y, 6.2, 2.7))
          star.setAttribute('fill', theme.queryColor)
          star.setAttribute('stroke', '#ffffff')
          star.setAttribute('stroke-width', '0.8')
          bindClick(star, node)
          frag.appendChild(star)
        } else if (isMatch) {
          const tip = document.createElementNS(SVG_NS, 'circle')
          tip.setAttribute('cx', node.x.toFixed(2))
          tip.setAttribute('cy', node.y.toFixed(2))
          tip.setAttribute('r', '5')
          tip.setAttribute('fill', '#ef4444')
          bindClick(tip, node)
          frag.appendChild(tip)
        } else if (interactive) {
          const hitTip = document.createElementNS(SVG_NS, 'circle')
          hitTip.setAttribute('cx', node.x.toFixed(2))
          hitTip.setAttribute('cy', node.y.toFixed(2))
          hitTip.setAttribute('r', '4')
          hitTip.setAttribute('fill', 'transparent')
          bindClick(hitTip, node)
          frag.appendChild(hitTip)
        }

        const shouldRenderLabel =
          settings.showLabels &&
          (!hideBgCircularLabels || role === 'query' || isMatch)

        if (shouldRenderLabel) {
          const label = document.createElementNS(SVG_NS, 'text')
          const rawLabel = node.collapsed
            ? `[折叠支系: ${node.leafCount} 条]`
            : displayText
          this.appendStyledLabelText(
            label,
            rawLabel,
            Boolean(settings.italicizeTaxa) && !node.collapsed,
            role === 'outgroup'
          )
          label.setAttribute('font-size', `${settings.fontSize}`)
          label.setAttribute('font-family', FONT_STACK)
          label.setAttribute('fill', isMatch ? '#dc2626' : labelFill)
          if (isMatch || role === 'query') label.setAttribute('font-weight', '700')

          if (settings.layout === 'circular' || settings.layout === 'unrooted') {
            const deg = ((node.angle * 180) / Math.PI + 360) % 360
            const flip = deg > 90 && deg < 270
            const useAlignedR =
              isCircular &&
              settings.alignTipLabels &&
              settings.useBranchLengths &&
              !node.collapsed &&
              this.bounds?.outerRadius !== undefined
            const macroCalloutR =
              isMacroCircular && hideBgCircularLabels
                ? circRingR + (model.hasHostMetadata && settings.showMetadataStrips ? 44 : 24)
                : null
            const anchorR = macroCalloutR ?? (useAlignedR ? this.bounds!.outerRadius! : node.radius)
            if ((useAlignedR || macroCalloutR !== null) && node.radius < anchorR - 1) {
              const guide = document.createElementNS(SVG_NS, 'line')
              guide.setAttribute('x1', node.x.toFixed(2))
              guide.setAttribute('y1', node.y.toFixed(2))
              guide.setAttribute('x2', (anchorR * Math.cos(node.angle)).toFixed(2))
              guide.setAttribute('y2', (anchorR * Math.sin(node.angle)).toFixed(2))
              guide.setAttribute('stroke', role === 'query' ? theme.queryColor : '#cbd5e1')
              guide.setAttribute('stroke-width', role === 'query' ? '1.1' : '0.85')
              guide.setAttribute('stroke-dasharray', role === 'query' ? '3 2' : '2 2.5')
              frag.appendChild(guide)
            }
            const offset = node.collapsed ? 22 : 10
            const lx =
              settings.layout === 'circular'
                ? (anchorR + offset) * Math.cos(node.angle)
                : node.x + offset * Math.cos(node.angle)
            const ly =
              settings.layout === 'circular'
                ? (anchorR + offset) * Math.sin(node.angle)
                : node.y + offset * Math.sin(node.angle)
            label.setAttribute('x', lx.toFixed(2))
            label.setAttribute('y', ly.toFixed(2))
            label.setAttribute('dominant-baseline', 'middle')
            label.setAttribute('text-anchor', flip ? 'end' : 'start')
            const rot = flip ? deg - 180 : deg
            label.setAttribute('transform', `rotate(${rot.toFixed(2)}, ${lx.toFixed(2)}, ${ly.toFixed(2)})`)
          } else {
            const useAlignedX =
              settings.alignTipLabels &&
              settings.useBranchLengths &&
              !node.collapsed &&
              this.bounds?.tipAlignX !== undefined
            const anchorX = useAlignedX ? this.bounds!.tipAlignX! : node.x
            if (useAlignedX && node.x < anchorX - 1) {
              const guide = document.createElementNS(SVG_NS, 'line')
              guide.setAttribute('x1', node.x.toFixed(2))
              guide.setAttribute('y1', node.y.toFixed(2))
              guide.setAttribute('x2', (anchorX + 5).toFixed(2))
              guide.setAttribute('y2', node.y.toFixed(2))
              guide.setAttribute('stroke', '#cbd5e1')
              guide.setAttribute('stroke-width', '0.85')
              guide.setAttribute('stroke-dasharray', '2 2.5')
              frag.appendChild(guide)
            }
            const offset = node.collapsed ? 22 : 10
            const lx = anchorX + offset
            label.setAttribute('x', lx.toFixed(2))
            label.setAttribute('y', node.y.toFixed(2))
            label.setAttribute('dominant-baseline', 'middle')

            // 矩形布局右侧对齐元数据条带 (ICTV 属 + Host 门 + 基因组大小柱状条)
            if (
              settings.showMetadataStrips &&
              model.hasNodeMetadata &&
              !node.collapsed &&
              this.bounds?.labelEndX
            ) {
              const stripX = this.bounds.labelEndX + 8
              const rowH = Math.max(10, Math.min(18, settings.rowSpacing * 0.68))
              const stripColor =
                role === 'query'
                  ? theme.queryColor
                  : role === 'outgroup'
                    ? theme.outgroupColor
                    : genusColor ||
                      (node.meta?.genus && model.otherGenera.has(node.meta.genus)
                        ? '#94a3b8'
                        : theme.unclassifiedColor)
              const swatch = document.createElementNS(SVG_NS, 'rect')
              swatch.setAttribute('x', stripX.toFixed(1))
              swatch.setAttribute('y', (node.y - rowH * 0.5).toFixed(1))
              swatch.setAttribute('width', '12')
              swatch.setAttribute('height', rowH.toFixed(1))
              swatch.setAttribute('rx', '2')
              swatch.setAttribute('fill', stripColor)
              frag.appendChild(swatch)

              const gTxt = document.createElementNS(SVG_NS, 'text')
              const genusStr =
                role === 'query'
                  ? 'Query'
                  : role === 'outgroup'
                    ? 'Outgroup'
                    : node.meta?.genus || 'Unclassified'
              gTxt.textContent = genusStr.length > 15 ? `${genusStr.slice(0, 14)}..` : genusStr
              gTxt.setAttribute('x', (stripX + 17).toFixed(1))
              gTxt.setAttribute('y', node.y.toFixed(2))
              gTxt.setAttribute('dominant-baseline', 'middle')
              gTxt.setAttribute('font-size', `${Math.max(9, settings.fontSize - 2)}`)
              gTxt.setAttribute('font-family', FONT_STACK)
              if (isFormalTaxonName(genusStr)) gTxt.setAttribute('font-style', 'italic')
              gTxt.setAttribute('fill', '#475569')
              frag.appendChild(gTxt)

              let barStart = stripX + 118
              if (model.hasHostMetadata) {
                const phylum = mapHostToPhylum(node.meta?.host)
                const hostSwatch = document.createElementNS(SVG_NS, 'rect')
                hostSwatch.setAttribute('x', (stripX + 114).toFixed(1))
                hostSwatch.setAttribute('y', (node.y - rowH * 0.5).toFixed(1))
                hostSwatch.setAttribute('width', '26')
                hostSwatch.setAttribute('height', rowH.toFixed(1))
                hostSwatch.setAttribute('rx', '2')
                hostSwatch.setAttribute('fill', phylum ? getHostPhylumColor(phylum, theme.id) : '#f1f5f9')
                frag.appendChild(hostSwatch)
                barStart = stripX + 156
              }

              const gLen = node.meta?.genome_length || 0
              if (gLen > 0 && model.maxGenomeLength > 0) {
                const barMaxW = 68
                const trackBg = document.createElementNS(SVG_NS, 'rect')
                trackBg.setAttribute('x', barStart.toFixed(1))
                trackBg.setAttribute('y', (node.y - rowH * 0.34).toFixed(1))
                trackBg.setAttribute('width', String(barMaxW))
                trackBg.setAttribute('height', (rowH * 0.68).toFixed(1))
                trackBg.setAttribute('rx', '2')
                trackBg.setAttribute('fill', '#f1f5f9')
                frag.appendChild(trackBg)

                const barW = Math.max(4, (gLen / model.maxGenomeLength) * barMaxW)
                const barRect = document.createElementNS(SVG_NS, 'rect')
                barRect.setAttribute('x', barStart.toFixed(1))
                barRect.setAttribute('y', (node.y - rowH * 0.34).toFixed(1))
                barRect.setAttribute('width', barW.toFixed(1))
                barRect.setAttribute('height', (rowH * 0.68).toFixed(1))
                barRect.setAttribute('rx', '2')
                barRect.setAttribute('fill', theme.sizeBarColor)
                barRect.setAttribute('opacity', '0.88')
                frag.appendChild(barRect)

                const kbTxt = document.createElementNS(SVG_NS, 'text')
                kbTxt.textContent = `${(gLen / 1000).toFixed(1)}`
                kbTxt.setAttribute('x', (barStart + barMaxW + 5).toFixed(1))
                kbTxt.setAttribute('y', node.y.toFixed(2))
                kbTxt.setAttribute('dominant-baseline', 'middle')
                kbTxt.setAttribute('font-size', `${Math.max(8, settings.fontSize - 3)}`)
                kbTxt.setAttribute('font-family', FONT_STACK)
                kbTxt.setAttribute('fill', '#64748b')
                frag.appendChild(kbTxt)
              }
            }
          }

          bindClick(label, node)
          frag.appendChild(label)
        }

        // 环形外圈双色带环独立于背景文字显示状态（确保智能精简背景标签时色环照常绘制）
        if (
          isCircular &&
          settings.showMetadataStrips &&
          model.hasNodeMetadata &&
          !node.collapsed
        ) {
          const gCol =
            role === 'query'
              ? theme.queryColor
              : role === 'outgroup'
                ? theme.outgroupColor
                : genusColor ||
                  (node.meta?.genus && model.otherGenera.has(node.meta.genus)
                    ? '#94a3b8'
                    : theme.unclassifiedColor)
          const gPath = document.createElementNS(SVG_NS, 'path')
          gPath.setAttribute(
            'd',
            createAnnularSectorPath(circRingR, circRingR + 15, node.angle - circHalfAng, node.angle + circHalfAng)
          )
          gPath.setAttribute('fill', gCol)
          if (model.leaves.length <= 100) {
            gPath.setAttribute('stroke', '#ffffff')
            gPath.setAttribute('stroke-width', '0.6')
          }
          frag.appendChild(gPath)

          if (model.hasHostMetadata) {
            const phylum = mapHostToPhylum(node.meta?.host)
            const hCol = phylum ? getHostPhylumColor(phylum, theme.id) : '#f1f5f9'
            const hPath = document.createElementNS(SVG_NS, 'path')
            hPath.setAttribute(
              'd',
              createAnnularSectorPath(
                circRingR + 19,
                circRingR + 33,
                node.angle - circHalfAng,
                node.angle + circHalfAng
              )
            )
            hPath.setAttribute('fill', hCol)
            if (model.leaves.length <= 100) {
              hPath.setAttribute('stroke', '#ffffff')
              hPath.setAttribute('stroke-width', '0.6')
            }
            frag.appendChild(hPath)
          }
        }
      }

      if (!node.collapsed) {
        for (const ch of node.children) walk(ch)
      }
    }

    walk(model.root)
    group.appendChild(frag)
    return group
  }

  /**
   * 构建完整无裁切的自包含矢量 SVG（涵盖底层单系支系阴影、全部拓扑边、对齐引导线、矢量星标与发表图例）。
   */
  buildExportSvg(): SVGSVGElement | null {
    if (!this.model || !this.settings || !this.bounds || !this.model.root) return null

    const theme = this.getTheme(this.settings)
    const pad = 28
    const vx = this.bounds.minX - pad
    const vy = this.bounds.minY - pad
    const vw = Math.max(240, Math.ceil(this.bounds.maxX - this.bounds.minX + pad * 2))
    const vh = Math.max(180, Math.ceil(this.bounds.maxY - this.bounds.minY + pad * 2 + 24))

    const exportSvg = document.createElementNS(SVG_NS, 'svg')
    exportSvg.setAttribute('xmlns', SVG_NS)
    exportSvg.setAttribute('viewBox', `${vx.toFixed(1)} ${vy.toFixed(1)} ${vw} ${vh}`)
    exportSvg.setAttribute('width', String(vw))
    exportSvg.setAttribute('height', String(vh))

    const bg = document.createElementNS(SVG_NS, 'rect')
    bg.setAttribute('x', vx.toFixed(1))
    bg.setAttribute('y', vy.toFixed(1))
    bg.setAttribute('width', String(vw))
    bg.setAttribute('height', String(vh))
    bg.setAttribute('fill', '#ffffff')
    exportSvg.appendChild(bg)

    if (this.settings.showCladeShading && this.settings.layout !== 'unrooted') {
      exportSvg.appendChild(this.createSvgCladesGroup(this.model, this.settings))
    }
    exportSvg.appendChild(this.createSvgEdgesGroup(this.model, this.settings))
    exportSvg.appendChild(this.createSvgNodesGroup(this.model, this.settings, null, false))

    const footerY = vy + vh - 18
    if (this.settings.useBranchLengths) {
      const barPx = 84
      const distPerPx = this.bounds.scaleUnitsPerPx
      const unitVal = computeNiceScaleValue(barPx * distPerPx)
      const actualPx = Math.max(28, Math.min(160, unitVal / distPerPx))

      const sx = vx + 20
      const line = document.createElementNS(SVG_NS, 'line')
      line.setAttribute('x1', sx.toFixed(1))
      line.setAttribute('y1', footerY.toFixed(1))
      line.setAttribute('x2', (sx + actualPx).toFixed(1))
      line.setAttribute('y2', footerY.toFixed(1))
      line.setAttribute('stroke', '#0f172a')
      line.setAttribute('stroke-width', '1.6')
      exportSvg.appendChild(line)

      for (const tx of [sx, sx + actualPx]) {
        const tick = document.createElementNS(SVG_NS, 'line')
        tick.setAttribute('x1', tx.toFixed(1))
        tick.setAttribute('y1', (footerY - 3).toFixed(1))
        tick.setAttribute('x2', tx.toFixed(1))
        tick.setAttribute('y2', (footerY + 3).toFixed(1))
        tick.setAttribute('stroke', '#0f172a')
        tick.setAttribute('stroke-width', '1.2')
        exportSvg.appendChild(tick)
      }

      const txt = document.createElementNS(SVG_NS, 'text')
      txt.setAttribute('x', sx.toFixed(1))
      txt.setAttribute('y', (footerY - 7).toFixed(1))
      txt.setAttribute('font-size', '10')
      txt.setAttribute('font-family', FONT_STACK)
      txt.setAttribute('fill', '#334155')
      txt.textContent = `${unitVal} substitutions/site`
      exportSvg.appendChild(txt)
    }

    if (this.model.hasNodeMetadata || this.settings.highlightStrongUfboot) {
      let curX = vx + vw - 355
      const addLegendLabel = (labelStr: string) => {
        const t = document.createElementNS(SVG_NS, 'text')
        t.setAttribute('x', curX.toFixed(1))
        t.setAttribute('y', footerY.toFixed(1))
        t.setAttribute('dominant-baseline', 'middle')
        t.setAttribute('font-size', '10')
        t.setAttribute('font-family', FONT_STACK)
        t.setAttribute('fill', '#475569')
        t.textContent = labelStr
        exportSvg.appendChild(t)
        curX += labelStr.length * 5.6 + 14
      }

      const star = document.createElementNS(SVG_NS, 'polygon')
      star.setAttribute('points', buildStarPolygonPoints(curX, footerY, 5.2, 2.2))
      star.setAttribute('fill', theme.queryColor)
      exportSvg.appendChild(star)
      curX += 9
      addLegendLabel('Query')

      const ogLine = document.createElementNS(SVG_NS, 'line')
      ogLine.setAttribute('x1', curX.toFixed(1))
      ogLine.setAttribute('y1', footerY.toFixed(1))
      ogLine.setAttribute('x2', (curX + 16).toFixed(1))
      ogLine.setAttribute('y2', footerY.toFixed(1))
      ogLine.setAttribute('stroke', theme.outgroupColor)
      ogLine.setAttribute('stroke-width', '1.4')
      ogLine.setAttribute('stroke-dasharray', '3 2')
      exportSvg.appendChild(ogLine)
      curX += 20
      addLegendLabel('Outgroup')

      const strongDot = document.createElementNS(SVG_NS, 'circle')
      strongDot.setAttribute('cx', curX.toFixed(1))
      strongDot.setAttribute('cy', footerY.toFixed(1))
      strongDot.setAttribute('r', '3.8')
      strongDot.setAttribute('fill', theme.strongDotColor)
      exportSvg.appendChild(strongDot)
      curX += 8
      addLegendLabel('UFBoot >= 95%')

      const modDot = document.createElementNS(SVG_NS, 'circle')
      modDot.setAttribute('cx', curX.toFixed(1))
      modDot.setAttribute('cy', footerY.toFixed(1))
      modDot.setAttribute('r', '3.5')
      modDot.setAttribute('fill', '#ffffff')
      modDot.setAttribute('stroke', theme.moderateDotEdge)
      modDot.setAttribute('stroke-width', '1.3')
      exportSvg.appendChild(modDot)
      curX += 8
      addLegendLabel(`>= ${this.settings.supportThreshold}%`)
    }

    return exportSvg
  }

  dispose(): void {
    if (this.labelCullTimer) {
      clearTimeout(this.labelCullTimer)
      this.labelCullTimer = null
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    window.removeEventListener('mousemove', this.handleMouseMove)
    window.removeEventListener('mouseup', this.handleMouseUp)
    if (this.container) this.container.innerHTML = ''
    this.svg = null
    this.rootGroup = null
    this.canvas = null
    this.ctx = null
    this.scaleBarEl = null
    this.scaleBarLineEl = null
    this.scaleBarTextEl = null
  }
}
