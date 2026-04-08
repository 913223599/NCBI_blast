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
    sortMode: 'original' | 'ladder-right' | 'ladder-left' | 'taxonomic' | 'distance'
    labelDisplayMode: 'replace' | 'append' | 'original'
    visualGain: number // 0 to 1, 调节短分枝的视觉可见度补偿

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
    scaleX: 250,
    scaleY: 1,
    fontSize: 13,
    branchWidth: 1.5,
    branchColor: '#0f172a',
    dashed: false,
    leafSpacing: 35,
    datasetLaneWidth: 15,
    datasetGap: 2,
    alignLabels: false,
    showGuideLines: true,
    centerOffset: 0,
    sortMode: 'original',
    labelDisplayMode: 'replace',
    visualGain: 0.1
}

// 布局常量配置
const LAYOUT_CONSTANTS = {
    TARGET_HEIGHT: 1600, // 目标画布最大逻辑高度
    MIN_SPACING: 8,
    MAX_SPACING: 35,
    WIDTH_RATIO: 0.8, // 宽度与高度的视觉平衡比例
    MIN_METRIC: 0.0001,
    INNER_RADIUS_OFFSET: 0
}

export class LayoutEngine {
    model: TreeModel
    settings: LayoutSettings

    constructor(model: TreeModel, settings: Partial<LayoutSettings> = {}) {
        this.model = model
        this.settings = { ...DEFAULT_SETTINGS, ...settings }
    }

    calculateCoordinates(): void {
        if (!this.model.root) return
        
        if (this.settings.mode === 'circular') {
            this._layoutCircular()
        } else if (this.settings.mode === 'unrooted') {
            this._layoutUnrooted()
        } else {
            this._layoutRectangular() // Default
        }
    }

    private _layoutRectangular() {
        const root = this.model.root
        if (!root) return

        // 核心修复：动态调整 Y 轴叶子间距。
        const leafCount = this.model.getLeafCount()
        const spacing = Math.min(LAYOUT_CONSTANTS.MAX_SPACING, 
            Math.max(LAYOUT_CONSTANTS.MIN_SPACING, LAYOUT_CONSTANTS.TARGET_HEIGHT / (leafCount || 1)))
        
        // 1. ORDERED LEAF DFS
        let leafCounter = 0
        const assignY = (node: TreeNode) => {
            if (node.isLeaf) {
                node.y = leafCounter * spacing
                leafCounter++
            } else if (node.children) {
                node.children.forEach(child => assignY(child))
                const childYs = node.children.map(c => c.y || 0)
                node.y = (Math.min(...childYs) + Math.max(...childYs)) / 2
            }
        }
        assignY(root)

        // 2. CALCULATE X
        const resultStack: TreeNode[] = []
        const traverse = (n: TreeNode) => {
            if (n.children?.length) n.children.forEach(traverse)
            resultStack.push(n)
        }
        traverse(root)

        const maxD = this.settings.useBranchLengths ? 
            Math.max(LAYOUT_CONSTANTS.MIN_METRIC, this.model.maxHeight) : 
            Math.max(1, this.model.maxDepth)
        
        // 动态计算 X 轴像素步进，确保树的宽度与高度视觉平衡
        const targetWidth = LAYOUT_CONSTANTS.TARGET_HEIGHT * LAYOUT_CONSTANTS.WIDTH_RATIO
        const dynamicScaleX = targetWidth / maxD

        while (resultStack.length > 0) {
            const node = resultStack.pop()!
            const metric = this.settings.useBranchLengths ? (node.heightFromRoot || 0) : node.depth
            node.x = metric * dynamicScaleX
        }

        this.settings.maxLayoutX = maxD * dynamicScaleX
    }

    private _layoutCircular() {
        const totalLeaves = this.model.getLeafCount()
        const sweepRadians = (this.settings.arc / 360) * 2 * Math.PI
        const startAngle = (this.settings.rotation / 360) * 2 * Math.PI
        const INNER_RADIUS = LAYOUT_CONSTANTS.INNER_RADIUS_OFFSET + this.settings.centerOffset

        let maxRadius = 0
        const divisor = (this.settings.arc >= 360) ? totalLeaves : (totalLeaves - 1 || 1)
        const root = this.model.root
        if (!root) return

        // DFS for Angle ordering
        let leafCounter = 0
        const assignAngle = (node: TreeNode) => {
            if (node.isLeaf) {
                node.angle = startAngle + (leafCounter / divisor) * sweepRadians
                leafCounter++
            } else if (node.children) {
                node.children.forEach(assignAngle)
                node.angle = node.children.reduce((a, b) => a + (b.angle || 0), 0) / node.children.length
            }
        }
        assignAngle(root)

        // Post-order for radius and cartesian
        const resultStack: TreeNode[] = []
        const traverse = (n: TreeNode) => {
            if (n.children?.length) n.children.forEach(traverse)
            resultStack.push(n)
        }
        traverse(root)

        while (resultStack.length > 0) {
            const node = resultStack.pop()!
            const depth = this.settings.useBranchLengths ? node.heightFromRoot : node.depth
            node.radius = INNER_RADIUS + (depth * this.settings.scaleX)
            node.cartX = (node.radius || 0) * Math.cos(node.angle || 0)
            node.cartY = (node.radius || 0) * Math.sin(node.angle || 0)
            node.x = node.cartX
            node.y = node.cartY
            if ((node.radius || 0) > maxRadius) maxRadius = node.radius || 0
        }

        this.settings.maxLayoutRadius = maxRadius
    }

    private _layoutUnrooted() {
        this._layoutCircular() 
    }
}
