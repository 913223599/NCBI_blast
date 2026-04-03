import type { TreeModel, TreeNode } from '../models/TreeModel'
import type { LayoutSettings } from '../layout/LayoutEngine'

export class HybridRenderer {
    container: HTMLElement | null = null
    canvas: HTMLCanvasElement | null = null
    ctx: CanvasRenderingContext2D | null = null
    svg: SVGSVGElement | null = null
    g: SVGGElement | null = null

    // Transform Matrix
    matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }

    // Interaction State
    isDragging = false
    startX = 0
    startY = 0
    
    // Callbacks for interactivity
    onNodeClick: ((node: TreeNode, event: MouseEvent) => void) | null = null

    // Resize Observer & Throttling
    resizeObserver: ResizeObserver | null = null
    resizeTimeout: any = null

    constructor() { }

    mount(container: HTMLElement) {
        this.container = container
        this.container.innerHTML = ''
        this.container.style.position = 'relative'
        this.container.style.overflow = 'hidden'

        // 1. Canvas Layer (Edges)
        this.canvas = document.createElement('canvas')
        this.canvas.style.position = 'absolute'
        this.canvas.style.top = '0'
        this.canvas.style.left = '0'
        this.canvas.style.pointerEvents = 'none'
        this.ctx = this.canvas.getContext('2d')
        this.container.appendChild(this.canvas)

        // 2. SVG Layer (Labels & Interaction)
        this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        this.svg.setAttribute("width", "100%")
        this.svg.setAttribute("height", "100%")
        this.svg.style.position = 'absolute'
        this.svg.style.top = '0'
        this.svg.style.left = '0'

        this.g = document.createElementNS("http://www.w3.org/2000/svg", "g")
        this.svg.appendChild(this.g)
        this.container.appendChild(this.svg)

        this.setupInteraction()
        this.setupResizeObserver()
    }

    setupInteraction() {
        if (!this.svg) return

        this.svg.onmousedown = (e) => {
            if (e.button === 0) { // Left click
                this.isDragging = true
                this.startX = e.clientX
                this.startY = e.clientY
                this.svg!.style.cursor = "grabbing"
            }
        }

        window.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return
            const dx = e.clientX - this.startX
            const dy = e.clientY - this.startY

            this.matrix.e += dx
            this.matrix.f += dy
            this.startX = e.clientX
            this.startY = e.clientY

            this.applyTransform()
        })

        window.addEventListener('mouseup', () => {
            this.isDragging = false
            if (this.svg) this.svg.style.cursor = "grab"
        })

        this.svg.onwheel = (e) => {
            e.preventDefault()
            const scaleFactor = e.deltaY > 0 ? 0.9 : 1.1

            const rect = this.svg!.getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            const contentX = (mouseX - this.matrix.e) / this.matrix.a
            const contentY = (mouseY - this.matrix.f) / this.matrix.d

            this.matrix.a *= scaleFactor
            this.matrix.d *= scaleFactor

            this.matrix.e = mouseX - contentX * this.matrix.a
            this.matrix.f = mouseY - contentY * this.matrix.d

            this.applyTransform()
        }
    }

    applyTransform() {
        if (this.g) {
            this.g.setAttribute("transform", `matrix(${this.matrix.a},${this.matrix.b},${this.matrix.c},${this.matrix.d},${this.matrix.e},${this.matrix.f})`)
        }
    }

    fitView(model: TreeModel, settings: LayoutSettings) {
        if (!this.container || !model.root) return
        const rect = this.container.getBoundingClientRect()
        const padding = 60
        
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
        
        const isCircular = settings.mode === 'circular'
        Object.values(model.nodesById).forEach(node => {
            const nx = isCircular ? (node.cartX || 0) : (node.x || 0)
            const ny = isCircular ? (node.cartY || 0) : (node.y || 0)
            minX = Math.min(minX, nx)
            minY = Math.min(minY, ny)
            maxX = Math.max(maxX, nx)
            maxY = Math.max(maxY, ny)
        })
        
        if (minX === Infinity) return
        
        const contentWidth = maxX - minX || 100
        const contentHeight = maxY - minY || 100
        
        const scaleX = (rect.width - padding * 2) / contentWidth
        const scaleY = (rect.height - padding * 2) / contentHeight
        
        // Phylogenetic trees usually need more horizontal stretch
        // If content is very narrow, allow scaleX to be much larger than scaleY
        const scale = Math.min(scaleX, scaleY)
        
        this.matrix.a = scaleX > scaleY * 2 ? scaleX * 0.8 : scale
        this.matrix.d = scale
        
        this.matrix.e = (rect.width / 2) - ((minX + maxX) / 2 * this.matrix.a) 
        this.matrix.f = (rect.height / 2) - ((minY + maxY) / 2 * this.matrix.d) 
        
        this.applyTransform()
    }

    setupResizeObserver() {
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(() => {
                if (this.resizeTimeout) return
                this.resizeTimeout = setTimeout(() => {
                    this.handleResizeInternal()
                    this.resizeTimeout = null
                }, 16)
            })
            if (this.container) this.resizeObserver.observe(this.container)
        }
    }

    private handleResizeInternal() {
        if (this.container && this.canvas && this.ctx) {
            const rect = this.container.getBoundingClientRect()
            const dpr = window.devicePixelRatio || 1
            this.canvas.style.width = `${rect.width}px`
            this.canvas.style.height = `${rect.height}px`
            this.canvas.width = rect.width * dpr
            this.canvas.height = rect.height * dpr
            this.ctx.scale(dpr, dpr)
        }
    }

    render(model: TreeModel, settings: LayoutSettings) {
        if (!this.ctx || !this.canvas || !this.g || !model.root) return

        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)

        const dpr = window.devicePixelRatio || 1
        
        this.ctx.setTransform(
            this.matrix.a * dpr, this.matrix.b * dpr,
            this.matrix.c * dpr, this.matrix.d * dpr,
            this.matrix.e * dpr, this.matrix.f * dpr
        )

        this.ctx.beginPath()
        this.ctx.strokeStyle = settings.branchColor
        // Scale linewidth inversely to prevent giant strokes when zoomed in
        this.ctx.lineWidth = settings.branchWidth / Math.sqrt(this.matrix.a)
        this.drawEdgesRecursive(model.root, settings)
        this.ctx.stroke()

        while (this.g.firstChild) {
            this.g.removeChild(this.g.firstChild)
        }

        this.g.setAttribute("transform", `matrix(${this.matrix.a},${this.matrix.b},${this.matrix.c},${this.matrix.d},${this.matrix.e},${this.matrix.f})`)

        if (settings.showLabels) {
            const fragment = document.createDocumentFragment()
            this.drawLabelsRecursive(model.root, settings, fragment)
            this.g.appendChild(fragment)
        }
    }

    private drawEdgesRecursive(node: TreeNode, s: LayoutSettings) {
        if (!node.children || node.children.length === 0) return
        if (!this.ctx) return

        const ctx = this.ctx
        const cx = s.mode === 'circular' ? (node.cartX || 0) : (node.x || 0)
        const cy = s.mode === 'circular' ? (node.cartY || 0) : (node.y || 0)

        node.children.forEach(child => {
            const chx = s.mode === 'circular' ? (child.cartX || 0) : (child.x || 0)
            const chy = s.mode === 'circular' ? (child.cartY || 0) : (child.y || 0)

            ctx.moveTo(cx, cy)
            if (s.mode === 'circular') {
                ctx.lineTo(chx, chy)
            } else {
                if (s.branchStyle === 'square') {
                    ctx.lineTo(cx, chy)
                    ctx.lineTo(chx, chy)
                } else {
                    ctx.lineTo(chx, chy)
                }
            }
            this.drawEdgesRecursive(child, s)
        })
    }

    private drawLabelsRecursive(node: TreeNode, s: LayoutSettings, parentElement: Element | DocumentFragment) {
        if (node.isLeaf) {
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text")
            const cx = s.mode === 'circular' ? (node.cartX || 0) : (node.x || 0)
            const cy = s.mode === 'circular' ? (node.cartY || 0) : (node.y || 0)

            text.setAttribute("x", (cx + 5).toString())
            text.setAttribute("y", (cy + 4).toString())
            text.textContent = node.name || ""
            text.setAttribute("fill", "#334155")
            text.setAttribute("font-size", `${s.fontSize}px`)
            text.setAttribute("font-family", "Arial, sans-serif")
            text.style.cursor = "pointer"
            text.style.userSelect = "none"

            text.onclick = (e) => {
                if (this.onNodeClick) this.onNodeClick(node, e)
            }
            
            text.onmouseenter = () => { text.setAttribute("fill", "#3b82f6") }
            text.onmouseleave = () => { text.setAttribute("fill", "#334155") }

            parentElement.appendChild(text)
        }
        if (node.children) {
            node.children.forEach(c => this.drawLabelsRecursive(c, s, parentElement))
        }
    }

    dispose() {
        if (this.resizeObserver) this.resizeObserver.disconnect()
        if (this.container) this.container.innerHTML = ''
    }
}
