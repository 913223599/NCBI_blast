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

            // Zoom around pointer
            // Simplified logic: adjust scale (a, d) and translate (e, f)
            // Correct math requires inverse matrix transformation
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
        // Note: Canvas redraw must be triggered externally or we need to store model/settings
    }

    setupResizeObserver() {
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(() => {
                // Throttle resize events to prevent lag during sidebar animation
                if (this.resizeTimeout) return
                
                this.resizeTimeout = setTimeout(() => {
                    this.handleResizeInternal()
                    this.resizeTimeout = null
                }, 16) // ~60fps floor
            })
            if (this.container) this.resizeObserver.observe(this.container)
        }
    }

    private handleResizeInternal() {
        if (this.container && this.canvas && this.ctx) {
            const rect = this.container.getBoundingClientRect()
            const dpr = window.devicePixelRatio || 1

            // Set display size
            this.canvas.style.width = `${rect.width}px`
            this.canvas.style.height = `${rect.height}px`

            // Set actual size
            this.canvas.width = rect.width * dpr
            this.canvas.height = rect.height * dpr

            // Normalize
            this.ctx.scale(dpr, dpr)
            
            // If the tree was already rendered, we might need a signal to re-render.
            // For now, most settings watchers will handle it.
        }
    }

    resize() {
        // handled by observer
    }

    render(model: TreeModel, settings: LayoutSettings) {
        if (!this.ctx || !this.canvas || !this.g || !model.root) return

        // 1. Clear Canvas
        // Use resetTransform or setTransform identity
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        // Clear logic adapted for DPI
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)

        // 2. Prepare Draw Context
        const dpr = window.devicePixelRatio || 1
        let ox = settings.centerOffset // use offset
        let oy = (this.canvas.height / dpr) / 2

        if (settings.mode === 'rect') {
            ox = 50
            oy = 50
        }

        // Apply specific transform for canvas with DPR
        this.ctx.setTransform(
            this.matrix.a * dpr, this.matrix.b * dpr,
            this.matrix.c * dpr, this.matrix.d * dpr,
            (this.matrix.e + ox) * dpr, (this.matrix.f + oy) * dpr
        )

        // 3. Draw Edges (Canvas)
        this.ctx.beginPath()
        this.ctx.strokeStyle = settings.branchColor
        this.ctx.lineWidth = settings.branchWidth
        this.drawEdgesRecursive(model.root, settings)
        this.ctx.stroke()

        // 4. Draw Labels (SVG) with Performance Optimization
        // 4.1 Optimize: Debounce/Throttle text updates if zooming fast
        const isZoomingFast = Math.abs(this.matrix.a - 1) > 0.001; // Simplified check
        
        // Clear SVG
        while (this.g.firstChild) {
            this.g.removeChild(this.g.firstChild)
        }

        // Apply transform group
        this.g.setAttribute("transform", `matrix(${this.matrix.a},${this.matrix.b},${this.matrix.c},${this.matrix.d},${this.matrix.e + ox},${this.matrix.f + oy})`)

        if (settings.showLabels) {
            // Level-of-Detail (LOD): If there are too many nodes and we are zoomed out, skip label rendering
            const totalNodes = (model.root as any).descendants ? (model.root as any).descendants().length : 100;
            const threshold = 1.0 / this.matrix.a; // inverse scale
            
            // Only draw if zoom is high enough OR node count is low
            if (this.matrix.a > 0.5 || totalNodes < 50) {
                 const fragment = document.createDocumentFragment();
                 this.drawLabelsRecursive(model.root, settings, fragment);
                 this.g.appendChild(fragment);
            }
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
                    ctx.lineTo(cx, chy) // vertical first
                    ctx.lineTo(chx, chy) // then horizontal to child
                } else {
                    ctx.lineTo(chx, chy)
                }
            }
            this.drawEdgesRecursive(child, s)
        })
    }

    private drawLabelsRecursive(node: TreeNode, s: LayoutSettings, parentElement: Element | DocumentFragment) {
        // SVG Text Logic
        if (node.isLeaf) {
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text")
            const cx = s.mode === 'circular' ? (node.cartX || 0) : (node.x || 0)
            const cy = s.mode === 'circular' ? (node.cartY || 0) : (node.y || 0)

            text.setAttribute("x", (cx + 5).toString())
            text.setAttribute("y", (cy + 4).toString())
            text.textContent = node.name || ""
            text.setAttribute("fill", "#000")
            text.setAttribute("font-size", `${s.fontSize}px`)
            text.setAttribute("font-family", "Arial, sans-serif")
            text.style.cursor = "pointer"
            text.style.userSelect = "none"

            // Interaction
            text.onclick = (e) => {
                e.stopPropagation()
                if (this.onNodeClick) this.onNodeClick(node, e)
            }
            
            text.onmouseenter = () => { text.setAttribute("fill", "#3b82f6"); text.style.fontWeight = "bold" }
            text.onmouseleave = () => { text.setAttribute("fill", "#000"); text.style.fontWeight = "normal" }

            parentElement.appendChild(text)
        }
        if (node.children) {
            node.children.forEach(c => this.drawLabelsRecursive(c, s, parentElement))
        }
    }

    dispose() {
        if (this.resizeObserver) this.resizeObserver.disconnect()
        if (this.container) this.container.innerHTML = ''
        // remove window listeners if any
    }
}
