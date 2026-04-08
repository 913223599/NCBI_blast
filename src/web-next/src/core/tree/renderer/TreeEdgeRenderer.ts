import type { TreeNode } from '../models/TreeModel'
import type { LayoutSettings } from '../layout/LayoutEngine'

/**
 * 树枝渲染器 - 负责在 Canvas 上绘制树的边
 */
export class TreeEdgeRenderer {
    private ctx: CanvasRenderingContext2D | null = null

    constructor(ctx: CanvasRenderingContext2D) {
        this.ctx = ctx
    }

    drawEdges(root: TreeNode, settings: LayoutSettings) {
        if (!this.ctx || !root) return
        this.ctx.beginPath()
        this.ctx.strokeStyle = settings.branchColor
        this.ctx.lineWidth = settings.branchWidth / Math.sqrt(1) // scale handled by caller
        this.ctx.lineCap = 'round'
        this.ctx.lineJoin = 'round'
        this._drawRecursive(root, settings)
        this.ctx.stroke()
    }

    private _drawRecursive(node: TreeNode, s: LayoutSettings) {
        if (!this.ctx || !node.children || node.children.length === 0) return

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
                this._drawRecursive(child, s)
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
                this._drawRecursive(child, s)
            })
        }
    }

    dispose() {
        this.ctx = null
    }
}
