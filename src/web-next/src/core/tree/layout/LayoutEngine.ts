import type { TreeModel, TreeNode } from '../models/TreeModel'

export interface LayoutSettings {
    mode: 'rect' | 'circular' | 'unrooted'
    branchStyle: 'square' | 'slanted' | 'curved'
    rotation: number
    arc: number
    invert: boolean
    useBranchLengths: boolean
    showLabels: boolean
    showInternalLabels: boolean
    showBranchLengths: boolean
    labelShiftX: number
    scaleX: number
    scaleY: number
    fontSize: number
    branchWidth: number
    branchColor: string
    dashed: boolean
    leafSpacing: number
    datasetLaneWidth: number
    datasetGap: number
    alignLabels: boolean
    showGuideLines: boolean
    centerOffset: number

    // Computed during layout
    maxLayoutX?: number
    maxLayoutRadius?: number
}

export const DEFAULT_SETTINGS: LayoutSettings = {
    mode: 'rect',
    branchStyle: 'square',
    rotation: 0,
    arc: 350,
    invert: false,
    useBranchLengths: true,
    showLabels: true,
    showInternalLabels: false,
    showBranchLengths: false,
    labelShiftX: 0,
    scaleX: 1,
    scaleY: 1,
    fontSize: 12,
    branchWidth: 1,
    branchColor: '#000000',
    dashed: false,
    leafSpacing: 20,
    datasetLaneWidth: 15,
    datasetGap: 2,
    alignLabels: false,
    showGuideLines: true,
    centerOffset: 0
}

export class LayoutEngine {
    model: TreeModel
    settings: LayoutSettings

    canvasWidth: number = 0
    canvasHeight: number = 0

    constructor(model: TreeModel, settings: Partial<LayoutSettings> = {}) {
        this.model = model
        this.settings = { ...DEFAULT_SETTINGS, ...settings }
    }

    calculateCoordinates(): void {
        if (this.settings.mode === 'circular') {
            this._layoutCircular()
        } else if (this.settings.mode === 'unrooted') {
            this._layoutUnrooted()
        } else {
            this._layoutRectangular() // Default
        }
        this._calculateSubtreeBBoxes()
    }

    // --- Implementations (Ported from legacy JS) ---

    private _layoutRectangular() {
        const spacing = this.settings.leafSpacing * this.settings.scaleY
        const leaves = this.model.leaves

        // 1. Assign leaf Y
        leaves.forEach((leaf, i) => {
            leaf.y = i * spacing
        })

        // 2. Internal Nodes Post-order
        const resultStack: TreeNode[] = []

        // DFS
        const traverse = (n: TreeNode) => {
            if (n.children?.length) {
                n.children.forEach(traverse)
            }
            resultStack.push(n)
        }
        if (this.model.root) traverse(this.model.root)

        while (resultStack.length > 0) {
            const node = resultStack.pop()!
            if (node.isLeaf) {
                const metric = this.settings.useBranchLengths ? node.heightFromRoot : node.depth
                node.x = metric * this.settings.scaleX
            } else if (node.children?.length) {
                const childYs = node.children.map(c => c.y || 0)
                node.y = childYs.reduce((a, b) => a + b, 0) / childYs.length
                const metric = this.settings.useBranchLengths ? node.heightFromRoot : node.depth
                node.x = metric * this.settings.scaleX
            }
        }

        const maxD = this.settings.useBranchLengths ? this.model.maxHeight : this.model.maxDepth
        this.settings.maxLayoutX = maxD * this.settings.scaleX
        this.canvasWidth = (this.settings.maxLayoutX || 0) + 400
        this.canvasHeight = leaves.length * spacing + 100
    }

    private _layoutCircular() {
        const totalLeaves = this.model.getLeafCount()
        const sweepRadians = (this.settings.arc / 360) * 2 * Math.PI
        const startAngle = (this.settings.rotation / 360) * 2 * Math.PI
        const INNER_RADIUS = this.settings.centerOffset

        let maxRadius = 0
        const divisor = (this.settings.arc >= 360) ? totalLeaves : (totalLeaves - 1 || 1)

        this.model.leaves.forEach((leaf, i) => {
            leaf.angle = startAngle + (i / divisor) * sweepRadians
        })

        // Post-order
        const resultStack: TreeNode[] = []
        const traverse = (n: TreeNode) => {
            if (n.children?.length) n.children.forEach(traverse)
            resultStack.push(n)
        }
        if (this.model.root) traverse(this.model.root)

        while (resultStack.length > 0) {
            const node = resultStack.pop()!
            const depth = this.settings.useBranchLengths ? node.heightFromRoot : node.depth
            node.radius = INNER_RADIUS + (depth * this.settings.scaleX)

            if (!node.isLeaf && node.children?.length) {
                const avgAngle = node.children.reduce((a, b) => a + (b.angle || 0), 0) / node.children.length
                node.angle = avgAngle
            }

            node.cartX = (node.radius || 0) * Math.cos(node.angle || 0)
            node.cartY = (node.radius || 0) * Math.sin(node.angle || 0)
            if ((node.radius || 0) > maxRadius) maxRadius = node.radius || 0
        }

        this.settings.maxLayoutRadius = maxRadius
        this.canvasWidth = maxRadius * 2 + 300
        this.canvasHeight = maxRadius * 2 + 300
    }

    private _layoutUnrooted() {
        // Simplified Star layout logic for brevity in this step, expanding later if needed
        this._layoutCircular() // Fallback for now to get compiled
        // Ideally implement N-body or Equal Angle
    }

    private _calculateSubtreeBBoxes() {
        // Bounding box logic
        // Skipped for brevity, can add later
    }
}
