import { PhyloTreeLayout, type LayoutBounds } from './TreeLayout'
import { formatNodeDisplayLabel, type PhyloTreeModel, type PhyloTreeNode } from './TreeModel'
import type { TreeVisualSettings } from '../types/phylo'

const SVG_NS = 'http://www.w3.org/2000/svg'
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

    // 左下角比例尺（纯 DOM 构建）
    this.scaleBarEl = document.createElement('div')
    this.scaleBarEl.style.cssText =
      'display:none;position:absolute;left:16px;bottom:14px;pointer-events:none;font-size:11px;color:#475569;font-family:monospace;background:rgba(255,255,255,0.86);padding:4px 8px;border-radius:6px;border:1px solid #e2e8f0;'
    this.scaleBarLineEl = document.createElement('div')
    this.scaleBarLineEl.style.cssText = 'height:2px;background:#334155;margin-bottom:3px;'
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
        const nextScale = Math.max(0.08, Math.min(18, this.transform.scale * factor))
        const ratio = nextScale / this.transform.scale
        this.transform.tx = mx - (mx - this.transform.tx) * ratio
        this.transform.ty = my - (my - this.transform.ty) * ratio
        this.transform.scale = nextScale
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
    const barPx = 80
    const distPerPx = (this.bounds?.scaleUnitsPerPx || 1) / Math.max(0.01, this.transform.scale)
    const rawVal = barPx * distPerPx
    const exp = Math.pow(10, Math.floor(Math.log10(Math.max(1e-8, rawVal))))
    const niceStep = [1, 2, 5, 10].find((m) => m * exp >= rawVal * 0.7) || 1
    const unitVal = niceStep * exp
    const pxWidth = Math.max(24, Math.min(140, unitVal / distPerPx))
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
    this.scaleBarTextEl.textContent = `演化距离: ${unitVal.toPrecision(2)}`
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

  private drawCanvasEdges(): void {
    if (!this.ctx || !this.canvas || !this.model?.root || !this.settings) return
    const dpr = window.devicePixelRatio || 1
    const ctx = this.ctx
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
    ctx.lineWidth = Math.max(0.8, 1.4 / this.transform.scale)
    ctx.lineCap = 'round'

    const drawNode = (node: PhyloTreeNode) => {
      if (node.collapsed) return
      for (const ch of node.children) {
        ctx.beginPath()
        ctx.strokeStyle = ch.cladeColor || '#64748b'
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
  }

  private createSvgEdgesGroup(model: PhyloTreeModel, settings: TreeVisualSettings): SVGGElement {
    const edgeGroup = document.createElementNS(SVG_NS, 'g')
    edgeGroup.setAttribute('class', 'phylo-edges')
    if (!model.root) return edgeGroup

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
        path.setAttribute('d', d)
        path.setAttribute('fill', 'none')
        path.setAttribute('stroke', ch.cladeColor || '#64748b')
        path.setAttribute('stroke-width', '1.6')
        path.setAttribute('stroke-linecap', 'round')
        edgeGroup.appendChild(path)
        walk(ch)
      }
    }
    walk(model.root)
    return edgeGroup
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
        tri.setAttribute('fill', node.cladeColor || '#3b82f6')
        tri.setAttribute('opacity', '0.85')
        bindClick(tri, node)
        frag.appendChild(tri)
      }

      if (visible && !isTerminal && node.parent) {
        const dot = document.createElementNS(SVG_NS, 'circle')
        dot.setAttribute('cx', node.x.toFixed(2))
        dot.setAttribute('cy', node.y.toFixed(2))
        const ufVal = node.ufboot ?? node.support
        const isStrongUf = Boolean(settings.highlightStrongUfboot && ufVal !== null && ufVal >= 95)
        dot.setAttribute('r', isStrongUf ? '4.4' : '3.4')
        let fillColor = '#94a3b8'
        if (isStrongUf) {
          fillColor = '#0f766e'
        } else if (ufVal !== null) {
          fillColor = ufVal >= settings.supportThreshold ? '#16a34a' : '#f59e0b'
        }
        dot.setAttribute('fill', fillColor)
        dot.setAttribute('stroke', '#ffffff')
        dot.setAttribute('stroke-width', '1')
        bindClick(dot, node)
        frag.appendChild(dot)

        if (settings.showSupport && ufVal !== null && ufVal >= settings.supportThreshold) {
          const isCircular = settings.layout === 'circular' || settings.layout === 'unrooted'
          if (!isCircular || node.radius > 16 || ufVal >= 95) {
            const supTxt = document.createElementNS(SVG_NS, 'text')
            if (isCircular) {
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
            supTxt.setAttribute('font-family', 'Inter, system-ui, sans-serif')
            supTxt.setAttribute('fill', isStrongUf ? '#0f766e' : '#475569')
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
        let tipFill = node.cladeColor || '#2563eb'
        let labelFill = node.cladeColor || '#1e293b'
        if (role === 'query') {
          tipFill = '#dc2626'
          labelFill = '#b91c1c'
        } else if (role === 'outgroup') {
          tipFill = '#64748b'
          labelFill = '#475569'
        } else if (!node.cladeColor && genusColor) {
          tipFill = genusColor
          labelFill = genusColor
        }

        const tip = document.createElementNS(SVG_NS, 'circle')
        tip.setAttribute('cx', node.x.toFixed(2))
        tip.setAttribute('cy', node.y.toFixed(2))
        tip.setAttribute('r', isMatch || role === 'query' ? '5' : '3.2')
        tip.setAttribute('fill', isMatch ? '#ef4444' : tipFill)
        bindClick(tip, node)
        frag.appendChild(tip)

        if (settings.showLabels) {
          const label = document.createElementNS(SVG_NS, 'text')
          label.textContent = node.collapsed
            ? `[折叠支系: ${node.leafCount} 条]`
            : displayText
          label.setAttribute('font-size', `${settings.fontSize}`)
          label.setAttribute('font-family', 'Inter, system-ui, sans-serif')
          label.setAttribute('fill', isMatch ? '#dc2626' : labelFill)
          if (isMatch || role === 'query') label.setAttribute('font-weight', '700')
          if (role === 'outgroup') label.setAttribute('font-style', 'italic')

          if (settings.layout === 'circular' || settings.layout === 'unrooted') {
            const deg = ((node.angle * 180) / Math.PI + 360) % 360
            const flip = deg > 90 && deg < 270
            const offset = node.collapsed ? 22 : 10
            const lx = node.x + offset * Math.cos(node.angle)
            const ly = node.y + offset * Math.sin(node.angle)
            label.setAttribute('x', lx.toFixed(2))
            label.setAttribute('y', ly.toFixed(2))
            label.setAttribute('dominant-baseline', 'middle')
            label.setAttribute('text-anchor', flip ? 'end' : 'start')
            const rot = flip ? deg - 180 : deg
            label.setAttribute('transform', `rotate(${rot.toFixed(2)}, ${lx.toFixed(2)}, ${ly.toFixed(2)})`)
          } else {
            const offset = node.collapsed ? 22 : 10
            const lx = node.x + offset
            if (role === 'query') {
              const bgPill = document.createElementNS(SVG_NS, 'rect')
              const estW = Math.max(48, displayText.length * settings.fontSize * 0.62 + 12)
              bgPill.setAttribute('x', (lx - 4).toFixed(2))
              bgPill.setAttribute('y', (node.y - settings.fontSize * 0.68).toFixed(2))
              bgPill.setAttribute('width', estW.toFixed(1))
              bgPill.setAttribute('height', (settings.fontSize * 1.36).toFixed(1))
              bgPill.setAttribute('rx', '4')
              bgPill.setAttribute('fill', '#fee2e2')
              frag.appendChild(bgPill)
            }
            label.setAttribute('x', lx.toFixed(2))
            label.setAttribute('y', node.y.toFixed(2))
            label.setAttribute('dominant-baseline', 'middle')

            // 矩形布局右侧对齐元数据条带 (ICTV 属色块 + 基因组长度柱状图)
            if (
              settings.showMetadataStrips &&
              model.hasNodeMetadata &&
              !node.collapsed &&
              this.bounds?.labelEndX
            ) {
              const stripX = this.bounds.labelEndX + 8
              const rowH = Math.max(10, Math.min(18, settings.rowSpacing * 0.7))
              const stripColor =
                role === 'query'
                  ? '#dc2626'
                  : role === 'outgroup'
                    ? '#64748b'
                    : genusColor || '#cbd5e1'
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
              gTxt.setAttribute('x', (stripX + 18).toFixed(1))
              gTxt.setAttribute('y', node.y.toFixed(2))
              gTxt.setAttribute('dominant-baseline', 'middle')
              gTxt.setAttribute('font-size', `${Math.max(9, settings.fontSize - 2)}`)
              gTxt.setAttribute('font-family', 'Inter, system-ui, sans-serif')
              gTxt.setAttribute('fill', '#475569')
              frag.appendChild(gTxt)

              const gLen = node.meta?.genome_length || 0
              if (gLen > 0 && model.maxGenomeLength > 0) {
                const barStart = stripX + 118
                const barMaxW = 64
                const barW = Math.max(4, (gLen / model.maxGenomeLength) * barMaxW)
                const barRect = document.createElementNS(SVG_NS, 'rect')
                barRect.setAttribute('x', barStart.toFixed(1))
                barRect.setAttribute('y', (node.y - rowH * 0.35).toFixed(1))
                barRect.setAttribute('width', barW.toFixed(1))
                barRect.setAttribute('height', (rowH * 0.7).toFixed(1))
                barRect.setAttribute('rx', '2')
                barRect.setAttribute('fill', '#0ea5e9')
                barRect.setAttribute('opacity', '0.8')
                frag.appendChild(barRect)

                const kbTxt = document.createElementNS(SVG_NS, 'text')
                kbTxt.textContent = `${(gLen / 1000).toFixed(1)}k`
                kbTxt.setAttribute('x', (barStart + barW + 4).toFixed(1))
                kbTxt.setAttribute('y', node.y.toFixed(2))
                kbTxt.setAttribute('dominant-baseline', 'middle')
                kbTxt.setAttribute('font-size', `${Math.max(8, settings.fontSize - 3)}`)
                kbTxt.setAttribute('font-family', 'monospace')
                kbTxt.setAttribute('fill', '#64748b')
                frag.appendChild(kbTxt)
              }
            }
          }

          bindClick(label, node)
          frag.appendChild(label)
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
   * 构建完整无裁切的自包含矢量 SVG（涵盖全部拓扑边与标签，不受缩放与 1500 叶 Canvas 分层影响）。
   */
  buildExportSvg(): SVGSVGElement | null {
    if (!this.model || !this.settings || !this.bounds || !this.model.root) return null

    const pad = 24
    const vx = this.bounds.minX - pad
    const vy = this.bounds.minY - pad
    const vw = Math.max(200, Math.ceil(this.bounds.maxX - this.bounds.minX + pad * 2))
    const vh = Math.max(160, Math.ceil(this.bounds.maxY - this.bounds.minY + pad * 2))

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

    exportSvg.appendChild(this.createSvgEdgesGroup(this.model, this.settings))
    exportSvg.appendChild(this.createSvgNodesGroup(this.model, this.settings, null, false))

    if (this.settings.useBranchLengths) {
      const barPx = 80
      const distPerPx = this.bounds.scaleUnitsPerPx
      const rawVal = barPx * distPerPx
      const exp = Math.pow(10, Math.floor(Math.log10(Math.max(1e-8, rawVal))))
      const niceStep = [1, 2, 5, 10].find((m) => m * exp >= rawVal * 0.7) || 1
      const unitVal = niceStep * exp
      const actualPx = Math.max(24, Math.min(160, unitVal / distPerPx))

      const sx = vx + 16
      const sy = vy + vh - 20
      const line = document.createElementNS(SVG_NS, 'line')
      line.setAttribute('x1', sx.toFixed(1))
      line.setAttribute('y1', sy.toFixed(1))
      line.setAttribute('x2', (sx + actualPx).toFixed(1))
      line.setAttribute('y2', sy.toFixed(1))
      line.setAttribute('stroke', '#334155')
      line.setAttribute('stroke-width', '2')
      exportSvg.appendChild(line)

      const txt = document.createElementNS(SVG_NS, 'text')
      txt.setAttribute('x', sx.toFixed(1))
      txt.setAttribute('y', (sy - 6).toFixed(1))
      txt.setAttribute('font-size', '11')
      txt.setAttribute('font-family', 'monospace')
      txt.setAttribute('fill', '#475569')
      txt.textContent = `演化距离: ${unitVal.toPrecision(2)}`
      exportSvg.appendChild(txt)
    }

    if (this.model.hasNodeMetadata || this.settings.highlightStrongUfboot) {
      const lx = vx + vw - 310
      const ly = vy + vh - 20
      const legend = document.createElementNS(SVG_NS, 'text')
      legend.setAttribute('x', lx.toFixed(1))
      legend.setAttribute('y', ly.toFixed(1))
      legend.setAttribute('font-size', '10')
      legend.setAttribute('font-family', 'Inter, system-ui, sans-serif')
      legend.setAttribute('fill', '#64748b')
      legend.textContent = '图例: 红色=新测序株  |  灰蓝斜体=外群  |  深青节点=UFBoot >= 95%'
      exportSvg.appendChild(legend)
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
