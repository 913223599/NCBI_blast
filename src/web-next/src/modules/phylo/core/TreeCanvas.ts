/**
 * TreeCanvas.ts - 系统发育树视口、Canvas 混合底图与缩放拖拽控制器
 * SVG 矢量节点/枝干绘制已抽离至 ./TreeSvgRenderer.ts，导出 SVG 构建已抽离至 ./TreeExportBuilder.ts。
 */
import { PhyloTreeLayout, type LayoutBounds } from './TreeLayout'
import type { PhyloTreeModel, PhyloTreeNode } from './TreeModel'
import { computeNiceScaleValue, JOURNAL_THEMES, type JournalThemeConfig } from './JournalTheme'
import {
  createSvgCladesGroup,
  createSvgEdgesGroup,
  createSvgNodesGroup,
  resolveEdgeStroke,
  SVG_NS,
  type WorldBox,
} from './TreeSvgRenderer'
import { buildPhyloExportSvg } from './TreeExportBuilder'
import type { TreeVisualSettings } from '../types/phylo'

const HYBRID_THRESHOLD_LEAVES = 1500

export interface ViewportTransform {
  scale: number
  tx: number
  ty: number
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
    this.container.replaceChildren()
    this.container.style.position = 'relative'
    this.container.style.overflow = 'hidden'
    this.container.style.userSelect = 'none'

    this.canvas = document.createElement('canvas')
    this.canvas.style.position = 'absolute'
    this.canvas.style.inset = '0'
    this.canvas.style.pointerEvents = 'none'
    this.ctx = this.canvas.getContext('2d')
    this.container.appendChild(this.canvas)

    this.svg = document.createElementNS(SVG_NS, 'svg')
    this.svg.setAttribute('width', '100%')
    this.svg.setAttribute('height', '100%')
    this.svg.style.position = 'absolute'
    this.svg.style.inset = '0'
    this.svg.style.cursor = 'grab'

    this.rootGroup = document.createElementNS(SVG_NS, 'g')
    this.svg.appendChild(this.rootGroup)
    this.container.appendChild(this.svg)

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
    if (this.rootGroup) this.rootGroup.replaceChildren()
    if (this.ctx && this.canvas) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
    if (this.scaleBarEl) this.scaleBarEl.style.display = 'none'
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

  private bindNodeClick = (el: SVGElement, node: PhyloTreeNode): void => {
    el.style.cursor = 'pointer'
    el.addEventListener('click', (ev) => {
      ev.stopPropagation()
      if (!this.dragMoved) this.onNodeClick?.(node, ev.clientX, ev.clientY)
    })
  }

  private redraw(): void {
    if (!this.model || !this.settings || !this.rootGroup || !this.model.root) return
    this.rootGroup.replaceChildren()
    if (this.ctx && this.canvas) {
      this.ctx.setTransform(1, 0, 0, 1, 0, 0)
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }

    const theme = this.getTheme(this.settings)
    if (this.settings.showCladeShading && this.settings.layout !== 'unrooted') {
      this.rootGroup.appendChild(createSvgCladesGroup(this.model, this.settings, this.bounds, theme))
    }

    const useCanvasEdges = this.model.leaves.length > HYBRID_THRESHOLD_LEAVES
    if (useCanvasEdges) {
      this.drawCanvasEdges()
    } else {
      this.rootGroup.appendChild(createSvgEdgesGroup(this.model, this.settings, theme))
    }

    this.rootGroup.appendChild(
      createSvgNodesGroup({
        model: this.model,
        settings: this.settings,
        bounds: this.bounds,
        theme,
        cullBox: this.getViewportWorldBox(),
        interactive: true,
        transformScale: this.transform.scale,
        onBindClick: this.bindNodeClick,
      })
    )
    this.applyTransformOnly()
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
        const style = resolveEdgeStroke(ch, theme)
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
          ctx.moveTo(node.x, node.y)
          ctx.arc(0, 0, rParent, node.angle, ch.angle, ch.angle < node.angle)
          ctx.moveTo(rParent * Math.cos(ch.angle), rParent * Math.sin(ch.angle))
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

  buildExportSvg(): SVGSVGElement | null {
    if (!this.model || !this.settings || !this.bounds || !this.model.root) return null
    return buildPhyloExportSvg(
      this.model,
      this.settings,
      this.bounds,
      this.getTheme(this.settings),
      this.transform.scale
    )
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
    if (this.container) this.container.replaceChildren()
    this.svg = null
    this.rootGroup = null
    this.canvas = null
    this.ctx = null
    this.scaleBarEl = null
    this.scaleBarLineEl = null
    this.scaleBarTextEl = null
  }
}
