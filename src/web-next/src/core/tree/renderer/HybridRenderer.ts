import type { TreeModel, TreeNode } from '../models/TreeModel'
import type { LayoutSettings } from '../layout/LayoutEngine'
import { ViewportController } from './ViewportController'
import { ScaleBarRenderer } from './ScaleBarRenderer'
import { TreeEdgeRenderer } from './TreeEdgeRenderer'

/**
 * HybridRenderer - 进化树混合渲染器 (协调器)
 * 职责：容器管理、ResizeObserver、标签渲染、渲染循环调度
 * 绘图和交互已拆分到独立组件
 */
export class HybridRenderer {
    container: HTMLElement | null = null
    canvas: HTMLCanvasElement | null = null
    ctx: CanvasRenderingContext2D | null = null
    svg: SVGSVGElement | null = null
    g: SVGGElement | null = null

    // 委托给子组件
    private viewport: ViewportController | null = null
    private scaleBar: ScaleBarRenderer | null = null
    private edgeRenderer: TreeEdgeRenderer | null = null

    onNodeClick: ((node: TreeNode, event: MouseEvent) => void) | null = null
    resizeObserver: ResizeObserver | null = null
    resizeTimeout: any = null

    lastModel: TreeModel | null = null
    lastVersion: number = -1
    lastSettings: LayoutSettings | null = null
    private annotations: Record<string, string> = {}

    constructor() { }

    mount(container: HTMLElement) {
        this.lastVersion = -1
        this.container = container
        this.container.innerHTML = ''
        this.container.style.position = 'relative'
        this.container.style.overflow = 'hidden'

        // Canvas 层 - 画树枝
        this.canvas = document.createElement('canvas')
        this.canvas.style.position = 'absolute'
        this.canvas.style.top = '0'
        this.canvas.style.left = '0'
        this.canvas.style.pointerEvents = 'none'
        this.ctx = this.canvas.getContext('2d')
        this.container.appendChild(this.canvas)

        // SVG 层 - 画标签
        this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        this.svg.setAttribute("width", "100%")
        this.svg.setAttribute("height", "100%")
        this.svg.style.position = 'absolute'
        this.svg.style.top = '0'
        this.svg.style.left = '0'

        this.g = document.createElementNS("http://www.w3.org/2000/svg", "g")
        this.svg.appendChild(this.g)
        this.container.appendChild(this.svg)

        // 初始化子组件
        if (this.ctx && this.svg && this.canvas) {
            this.edgeRenderer = new TreeEdgeRenderer(this.ctx)
            this.scaleBar = new ScaleBarRenderer(this.canvas)
            this.viewport = new ViewportController(this.svg, () => {
                // 视口变换后重新渲染
                if (this.lastModel && this.lastSettings) this.render(this.lastModel, this.lastSettings)
            })
        }

        this.setupResizeObserver()
    }

    setupResizeObserver() {
        if (typeof ResizeObserver !== 'undefined' && this.container) {
            this.resizeObserver = new ResizeObserver(() => {
                if (this.resizeTimeout) clearTimeout(this.resizeTimeout)
                this.resizeTimeout = setTimeout(() => {
                    this.handleResizeInternal()
                    if (this.lastModel) {
                        this.fitView(this.lastModel)
                    }
                }, 100)
            })
            this.resizeObserver.observe(this.container)
        }
    }

    private handleResizeInternal() {
        if (!this.container || !this.canvas || !this.ctx) return
        const rect = this.container.getBoundingClientRect()
        const dpr = window.devicePixelRatio || 1
        this.canvas.style.width = `${rect.width}px`
        this.canvas.style.height = `${rect.height}px`
        this.canvas.width = rect.width * dpr
        this.canvas.height = rect.height * dpr
        this.ctx.scale(dpr, dpr)
    }

    fitView(model: TreeModel) {
        this.viewport?.fitView(this.container, model)
    }

    render(model: TreeModel, settings: LayoutSettings) {
        const isModelChanged = (this.lastModel !== model) || (this.lastVersion !== model.version) || !this.lastModel
        const isSettingsChanged = (this.lastSettings?.sortMode !== settings.sortMode) ||
            (this.lastSettings?.mode !== settings.mode) ||
            (this.lastSettings?.useBranchLengths !== settings.useBranchLengths) ||
            (this.lastSettings?.labelDisplayMode !== settings.labelDisplayMode)

        this.lastModel = model
        this.lastVersion = model.version
        this.lastSettings = { ...settings }
        if (!this.ctx || !this.canvas || !this.g || !model.root || !this.edgeRenderer || !this.scaleBar || !this.viewport) return

        // 树枝渲染 (Canvas)
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
        const dpr = window.devicePixelRatio || 1
        this.ctx.setTransform(this.viewport.matrix.a * dpr, 0, 0, this.viewport.matrix.d * dpr,
            this.viewport.matrix.e * dpr, this.viewport.matrix.f * dpr)
        this.edgeRenderer.drawEdges(model.root, settings)

        // 标签渲染 (SVG)
        if (isModelChanged || isSettingsChanged) {
            while (this.g.firstChild) { this.g.removeChild(this.g.firstChild) }
            if (settings.showLabels) {
                const fragment = document.createDocumentFragment()
                this.drawLabelsRecursive(model.root, settings, fragment)
                this.g.appendChild(fragment)
            }
        }
        this.g.setAttribute("transform",
            `matrix(${this.viewport.matrix.a},0,0,${this.viewport.matrix.d},${this.viewport.matrix.e},${this.viewport.matrix.f})`)

        // 比例尺渲染
        this.scaleBar.render(this.viewport.matrix.a)
    }

    updateAnnotations(map: Record<string, string>) {
        this.annotations = map
        if (this.lastModel && this.lastSettings) {
            // 强制触发标签重绘循环
            this.lastVersion = -1
            this.render(this.lastModel, this.lastSettings)
        }
    }

    private drawLabelsRecursive(node: TreeNode, s: LayoutSettings, parentElement: Element | DocumentFragment) {
        if (node.isLeaf) {
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text")

            if (s.mode === 'circular' || s.mode === 'unrooted') {
                const angleDeg = (node.angle || 0) * 180 / Math.PI
                const x = (node.x || 0) + 12 * Math.cos(node.angle || 0)
                const y = (node.y || 0) + 12 * Math.sin(node.angle || 0)
                text.setAttribute("x", x.toString())
                text.setAttribute("y", y.toString())

                let rot = angleDeg
                if (angleDeg > 90 && angleDeg < 270) {
                    rot -= 180
                    text.setAttribute("text-anchor", "end")
                    const offset = 24
                    text.setAttribute("x", (x - offset * Math.cos(node.angle || 0)).toString())
                    text.setAttribute("y", (y - offset * Math.sin(node.angle || 0)).toString())
                } else {
                    text.setAttribute("text-anchor", "start")
                }
                text.setAttribute("transform", `rotate(${rot}, ${text.getAttribute('x')}, ${text.getAttribute('y')})`)
                text.setAttribute("alignment-baseline", "middle")
            } else {
                text.setAttribute("x", ((node.x || 0) + 10).toString())
                text.setAttribute("y", ((node.y || 0) + 4).toString())
                text.setAttribute("alignment-baseline", "middle")
            }

            let displayName = node.name || ""
            const annotation = this.annotations[node.name || ""]
            
            // Debug: Log label rendering
            if (node.name && (node.name === 'SEQ001' || node.name.includes('SEQ'))) {
                console.log(`[HybridRenderer] Node: ${node.name}, Mode: ${s.labelDisplayMode}, Annotation: ${annotation}, DisplayName: ${displayName}`)
            }
            
            // Apply labelDisplayMode
            if (annotation) {
                if (s.labelDisplayMode === 'replace') {
                    displayName = annotation
                } else if (s.labelDisplayMode === 'append') {
                    displayName = `[${annotation}] ${node.name}`
                }
                // 'original' mode: keep the ID as-is
            }

            text.textContent = displayName
            text.setAttribute("fill", "#334155")
            text.setAttribute("font-size", `${s.fontSize}px`)
            text.setAttribute("font-family", "Inter, sans-serif")
            text.style.userSelect = "none"
            parentElement.appendChild(text)
        }
        if (node.children) node.children.forEach(c => this.drawLabelsRecursive(c, s, parentElement))
    }

    dispose() {
        if (this.resizeObserver) this.resizeObserver.disconnect()
        this.viewport?.dispose()
        this.edgeRenderer?.dispose()
        this.scaleBar?.dispose()
    }
}
