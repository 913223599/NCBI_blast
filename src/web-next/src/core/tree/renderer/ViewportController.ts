import type { TreeModel } from '../models/TreeModel'

/**
 * 视口控制器 - 负责树的拖拽、缩放和适应视图
 */
export class ViewportController {
    matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
    isDragging = false
    startX = 0
    startY = 0
    ticking = false

    private svg: SVGSVGElement | null = null
    private onTransformChange: (() => void) | null = null

    constructor(svg: SVGSVGElement, onTransformChange?: () => void) {
        this.svg = svg
        this.onTransformChange = onTransformChange || null
        this.setupInteraction()
    }

    private setupInteraction() {
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
                if (this.svg) {
                    this.svg.setAttribute("transform",
                        `matrix(${this.matrix.a},0,0,${this.matrix.d},${this.matrix.e},${this.matrix.f})`)
                }
                this.onTransformChange?.()
                this.ticking = false
            })
            this.ticking = true
        }
    }

    fitView(container: HTMLElement | null, model: TreeModel) {
        if (!container || !model.root) return
        const rect = container.getBoundingClientRect()
        const padding = 100
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
        Object.values(model.nodesById).forEach(node => {
            const nx = node.x || 0, ny = node.y || 0
            minX = Math.min(minX, nx); minY = Math.min(minY, ny)
            maxX = Math.max(maxX, nx); maxY = Math.max(maxY, ny)
        })
        if (minX === Infinity) return
        const sc = Math.min(
            (rect.width - padding * 4) / (maxX - minX || 1),
            (rect.height - padding * 2) / (maxY - minY || 1)
        )
        this.matrix.a = this.matrix.d = sc
        this.matrix.e = (rect.width / 2) - ((minX + maxX) / 2 * sc) - padding
        this.matrix.f = (rect.height / 2) - ((minY + maxY) / 2 * sc)
        this.applyTransform()
    }

    reset() {
        this.matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
        this.applyTransform()
    }

    dispose() {
        if (this.svg) {
            this.svg.onmousedown = null
            this.svg.onwheel = null
        }
    }
}
