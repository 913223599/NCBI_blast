import type { TreeModel, TreeNode } from '../models/TreeModel'
import type { LayoutSettings } from '../layout/LayoutEngine'

export class HybridRenderer {
    container: HTMLElement | null = null
    canvas: HTMLCanvasElement | null = null
    ctx: CanvasRenderingContext2D | null = null
    svg: SVGSVGElement | null = null
    g: SVGGElement | null = null

    matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
    isDragging = false
    startX = 0
    startY = 0
    ticking = false

    onNodeClick: ((node: TreeNode, event: MouseEvent) => void) | null = null
    resizeObserver: ResizeObserver | null = null
    resizeTimeout: any = null
    
    lastModel: TreeModel | null = null
    lastSettings: LayoutSettings | null = null

    constructor() { }

    mount(container: HTMLElement) {
        this.container = container
        this.container.innerHTML = ''
        this.container.style.position = 'relative'
        this.container.style.overflow = 'hidden'

        this.canvas = document.createElement('canvas')
        this.canvas.style.position = 'absolute'
        this.canvas.style.top = '0'
        this.canvas.style.left = '0'
        this.canvas.style.pointerEvents = 'none'
        this.ctx = this.canvas.getContext('2d')
        this.container.appendChild(this.canvas)

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
            if (e.button === 0) { 
                this.isDragging = true
                this.startX = e.clientX
                this.startY = e.clientY
                this.svg!.style.cursor = "grabbing"
            }
        }
        window.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return
            this.matrix.e += e.clientX - this.startX
            this.matrix.f += e.clientY - this.startY
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
        if (!this.ticking) {
            window.requestAnimationFrame(() => {
                if (this.g) this.g.setAttribute("transform", `matrix(${this.matrix.a},0,0,${this.matrix.d},${this.matrix.e},${this.matrix.f})`)
                if (this.lastModel && this.lastSettings) this.render(this.lastModel, this.lastSettings)
                this.ticking = false
            })
            this.ticking = true
        }
    }

    fitView(model: TreeModel) {
        if (!this.container || !model.root) return
        const rect = this.container.getBoundingClientRect()
        const padding = 100
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
        Object.values(model.nodesById).forEach(node => {
            const nx = node.x || 0, ny = node.y || 0
            minX = Math.min(minX, nx); minY = Math.min(minY, ny)
            maxX = Math.max(maxX, nx); maxY = Math.max(maxY, ny)
        })
        if (minX === Infinity) return
        const sc = Math.min((rect.width - padding * 4) / (maxX - minX || 1), (rect.height - padding * 2) / (maxY - minY || 1))
        this.matrix.a = this.matrix.d = sc
        this.matrix.e = (rect.width / 2) - ((minX + maxX) / 2 * sc) - padding
        this.matrix.f = (rect.height / 2) - ((minY + maxY) / 2 * sc)
        this.applyTransform()
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

    render(model: TreeModel, settings: LayoutSettings) {
        const isModelChanged = (this.lastModel !== model) || !this.lastModel
        const isSettingsChanged = (this.lastSettings?.sortMode !== settings.sortMode) || 
                                (this.lastSettings?.mode !== settings.mode) ||
                                (this.lastSettings?.useBranchLengths !== settings.useBranchLengths)

        this.lastModel = model; this.lastSettings = { ...settings }
        if (!this.ctx || !this.canvas || !this.g || !model.root) return

        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
        const dpr = window.devicePixelRatio || 1
        this.ctx.setTransform(this.matrix.a * dpr, 0, 0, this.matrix.d * dpr, this.matrix.e * dpr, this.matrix.f * dpr)

        this.ctx.beginPath()
        this.ctx.strokeStyle = settings.branchColor
        this.ctx.lineWidth = settings.branchWidth / Math.sqrt(this.matrix.a)
        this.ctx.lineCap = 'round'; this.ctx.lineJoin = 'round'
        this.drawEdgesRecursive(model.root, settings)
        this.ctx.stroke()

        if (isModelChanged || isSettingsChanged) {
            while (this.g.firstChild) { this.g.removeChild(this.g.firstChild) }
            if (settings.showLabels) {
                const fragment = document.createDocumentFragment()
                this.drawLabelsRecursive(model.root, settings, fragment)
                this.g.appendChild(fragment)
            }
        }
        this.g.setAttribute("transform", `matrix(${this.matrix.a},0,0,${this.matrix.d},${this.matrix.e},${this.matrix.f})`)
        this.renderScaleBar()
    }

    private renderScaleBar() {
        if (!this.ctx || !this.canvas) return
        const dpr = window.devicePixelRatio || 1
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        const scale = this.matrix.a
        const units = Math.pow(10, Math.floor(Math.log10(100 / scale)))
        const pw = units * scale
        const x = 60, y = (this.canvas.height / dpr) - 60

        // Background pod for premium look
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.7)'
        this.ctx.beginPath()
        this.ctx.roundRect(x - 10, y - 25, pw + 20, 45, 8)
        this.ctx.fill()

        this.ctx.strokeStyle = '#1e293b'
        this.ctx.lineWidth = 1.5
        this.ctx.beginPath()
        this.ctx.moveTo(x, y); this.ctx.lineTo(x + pw, y)
        this.ctx.moveTo(x, y - 4); this.ctx.lineTo(x, y + 4)
        this.ctx.moveTo(x + pw, y - 4); this.ctx.lineTo(x + pw, y + 4)
        this.ctx.stroke()
        this.ctx.fillStyle = '#1e293b'
        this.ctx.font = 'bold 11px Inter, sans-serif'
        this.ctx.textAlign = 'center'
        this.ctx.fillText(`${units.toFixed(units < 0.1 ? 3 : 2)} sub/site`, x + pw / 2, y - 8)
    }

    private drawEdgesRecursive(node: TreeNode, s: LayoutSettings) {
        if (!node.children || node.children.length === 0 || !this.ctx) return
        
        if (s.mode === 'circular' || s.mode === 'unrooted') {
            const pr = node.radius || 0
            if (node.children.length > 0) {
                const angles = node.children.map(c => c.angle || 0)
                const minA = Math.min(...angles)
                const maxA = Math.max(...angles)
                this.ctx.moveTo(pr * Math.cos(minA), pr * Math.sin(minA))
                this.ctx.arc(0, 0, pr, minA, maxA, false)
            }
            node.children.forEach(child => {
                if (this.ctx) {
                    this.ctx.moveTo(pr * Math.cos(child.angle || 0), pr * Math.sin(child.angle || 0))
                    this.ctx.lineTo(child.x || 0, child.y || 0)
                }
                this.drawEdgesRecursive(child, s)
            })
        } else {
            const cx = node.x || 0
            const childYs = node.children.map(c => c.y || 0)
            this.ctx.moveTo(cx, Math.min(...childYs))
            this.ctx.lineTo(cx, Math.max(...childYs))
            node.children.forEach(child => {
                if (this.ctx) {
                    this.ctx.moveTo(cx, child.y || 0)
                    this.ctx.lineTo(child.x || 0, child.y || 0)
                }
                this.drawEdgesRecursive(child, s)
            })
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
            text.textContent = node.name || ""
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
    }
}
