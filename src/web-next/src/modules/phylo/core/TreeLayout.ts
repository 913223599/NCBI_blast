import { formatNodeDisplayLabel, type PhyloTreeModel, type PhyloTreeNode } from './TreeModel'
import type { TreeVisualSettings } from '../types/phylo'

export interface LayoutBounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
  scaleUnitsPerPx: number
  labelEndX?: number
  tipAlignX?: number
  outerRadius?: number
}

export class PhyloTreeLayout {
  static compute(model: PhyloTreeModel, settings: TreeVisualSettings): LayoutBounds {
    if (!model.root || model.leaves.length === 0) {
      return { minX: 0, maxX: 600, minY: 0, maxY: 400, scaleUnitsPerPx: 1 }
    }

    if (settings.layout === 'circular') {
      return this.computeCircular(model, settings)
    }
    if (settings.layout === 'unrooted') {
      return this.computeUnrooted(model, settings)
    }
    return this.computeRectangular(model, settings)
  }

  private static computeRectangular(
    model: PhyloTreeModel,
    settings: TreeVisualSettings
  ): LayoutBounds {
    const root = model.root!
    const widthTarget = 720
    const rowStep = Math.max(12, settings.rowSpacing)
    const maxVal = settings.useBranchLengths ? Math.max(1e-6, model.maxHeight) : Math.max(1, model.maxDepth)
    const xScale = widthTarget / maxVal

    let leafRow = 0
    const assignY = (node: PhyloTreeNode): number => {
      if (node.isLeaf || node.collapsed) {
        node.y = leafRow * rowStep
        leafRow++
        return node.y
      }
      const ys = node.children.map(assignY)
      node.y = (Math.min(...ys) + Math.max(...ys)) * 0.5
      return node.y
    }

    const assignX = (node: PhyloTreeNode) => {
      if (settings.useBranchLengths) {
        node.x = node.heightFromRoot * xScale
      } else {
        node.x = (node.isLeaf || node.collapsed) ? widthTarget : node.depth * xScale
      }
      if (!node.collapsed) {
        for (const ch of node.children) assignX(ch)
      }
    }

    assignY(root)
    assignX(root)

    let maxChars = 12
    if (settings.showLabels) {
      for (const leaf of model.leaves) {
        const len = formatNodeDisplayLabel(leaf, settings.labelFormat).length
        if (len > maxChars) maxChars = len
      }
    }
    const maxLabelWidth = settings.showLabels
      ? Math.min(580, Math.max(180, Math.ceil(maxChars * settings.fontSize * 0.62) + 40))
      : 40
    const labelEndX = widthTarget + maxLabelWidth
    const stripExtra =
      settings.showMetadataStrips && model.hasNodeMetadata
        ? model.hasHostMetadata
          ? 275
          : 230
        : settings.showCladeShading && model.hasNodeMetadata
          ? 90
          : 0

    return {
      minX: -20,
      maxX: labelEndX + stripExtra,
      minY: -26,
      maxY: Math.max(120, (leafRow - 1) * rowStep + 48),
      scaleUnitsPerPx: maxVal / widthTarget,
      labelEndX,
      tipAlignX: widthTarget,
    }
  }

  private static computeCircular(
    model: PhyloTreeModel,
    settings: TreeVisualSettings
  ): LayoutBounds {
    const root = model.root!
    const visibleLeaves = model.leaves.length
    const baseRadius = Math.max(220, Math.min(560, visibleLeaves * settings.rowSpacing * 0.19))
    const maxVal = settings.useBranchLengths ? Math.max(1e-6, model.maxHeight) : Math.max(1, model.maxDepth)
    const rScale = baseRadius / maxVal

    let leafIdx = 0
    const totalAngle = Math.PI * 1.92 // 留出小缺口放置比例尺
    const angleStep = totalAngle / Math.max(1, visibleLeaves)

    const assignPolar = (node: PhyloTreeNode): number => {
      if (node.isLeaf || node.collapsed) {
        node.angle = leafIdx * angleStep
        leafIdx++
      } else {
        const angles = node.children.map(assignPolar)
        node.angle = (Math.min(...angles) + Math.max(...angles)) * 0.5
      }
      node.radius = settings.useBranchLengths
        ? node.heightFromRoot * rScale
        : (node.isLeaf || node.collapsed ? baseRadius : node.depth * rScale)
      node.x = node.radius * Math.cos(node.angle)
      node.y = node.radius * Math.sin(node.angle)
      return node.angle
    }

    assignPolar(root)

    let maxChars = 10
    const isMacroCircular = Boolean(settings.smartLabelCull && visibleLeaves > 90)
    if (settings.showLabels && !isMacroCircular) {
      for (const leaf of model.leaves) {
        const len = formatNodeDisplayLabel(leaf, settings.labelFormat).length
        if (len > maxChars) maxChars = len
      }
    }
    const labelSpace = settings.showLabels
      ? isMacroCircular
        ? 44
        : Math.min(340, Math.max(110, Math.ceil(maxChars * settings.fontSize * 0.56) + 24))
      : 30
    const ringSpace =
      settings.showMetadataStrips && model.hasNodeMetadata
        ? model.hasHostMetadata
          ? 84
          : 54
        : 0
    const calloutSpace = isMacroCircular ? 130 : 48
    const bound = baseRadius + labelSpace + ringSpace + calloutSpace
    return {
      minX: -bound,
      maxX: bound,
      minY: -bound,
      maxY: bound,
      scaleUnitsPerPx: maxVal / baseRadius,
      outerRadius: baseRadius,
    }
  }

  private static computeUnrooted(
    model: PhyloTreeModel,
    settings: TreeVisualSettings
  ): LayoutBounds {
    const root = model.root!
    const maxVal = settings.useBranchLengths ? Math.max(1e-6, model.maxHeight) : Math.max(1, model.maxDepth)
    const lenScale = 440 / maxVal

    root.x = 0
    root.y = 0
    root.angle = 0

    let minX = 0
    let maxX = 0
    let minY = 0
    let maxY = 0

    const layoutSubtree = (
      node: PhyloTreeNode,
      startAngle: number,
      sweepAngle: number
    ) => {
      if (node.collapsed || node.children.length === 0) return
      let curAngle = startAngle
      const subTotal = node.children.reduce((acc, c) => acc + c.leafCount, 0) || 1
      for (const ch of node.children) {
        const chSweep = (ch.leafCount / subTotal) * sweepAngle
        const midAngle = curAngle + chSweep * 0.5
        const edgeLen = settings.useBranchLengths
          ? Math.max(4, ch.branchLength * lenScale)
          : 440 / Math.max(1, model.maxDepth)

        ch.angle = midAngle
        ch.x = node.x + edgeLen * Math.cos(midAngle)
        ch.y = node.y + edgeLen * Math.sin(midAngle)
        minX = Math.min(minX, ch.x)
        maxX = Math.max(maxX, ch.x)
        minY = Math.min(minY, ch.y)
        maxY = Math.max(maxY, ch.y)

        layoutSubtree(ch, curAngle, chSweep)
        curAngle += chSweep
      }
    }

    layoutSubtree(root, 0, Math.PI * 2)
    const pad = 160
    return {
      minX: minX - pad,
      maxX: maxX + pad,
      minY: minY - pad,
      maxY: maxY + pad,
      scaleUnitsPerPx: 1 / lenScale,
    }
  }
}
