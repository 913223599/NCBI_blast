/**
 * exportLandscapeTree.ts - Figure 1 导出进化树剪枝与几何布局计算
 */
import type { ClusteringTreeNodeLike } from '../types'

export interface TreeBranch {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface TreeTip {
  x: number
  y: number
  id: string
}

export interface TreeLayoutResult {
  branches: TreeBranch[]
  tips: TreeTip[]
}

interface PrunedNode {
  id: string
  x: number
  y: number
  isLeaf: boolean
  depth: number
  left?: PrunedNode
  right?: PrunedNode
}

function pruneTreeForVisibleIds(
  node: ClusteringTreeNodeLike | null | undefined,
  visibleSet: Set<string>,
  yMap: Map<string, number>,
  tipX: number
): PrunedNode | null {
  if (!node) return null
  if (!node.left && !node.right) {
    if (!visibleSet.has(node.id)) return null
    return {
      id: node.id,
      x: tipX,
      y: yMap.get(node.id) ?? 0,
      isLeaf: true,
      depth: 0,
    }
  }
  const left = pruneTreeForVisibleIds(node.left, visibleSet, yMap, tipX)
  const right = pruneTreeForVisibleIds(node.right, visibleSet, yMap, tipX)
  if (left && right) {
    return {
      id: node.id || 'internal',
      x: 0,
      y: (left.y + right.y) / 2,
      isLeaf: false,
      depth: 1 + Math.max(left.depth, right.depth),
      left,
      right,
    }
  }
  return left || right
}

function collectPrunedLeaves(node: PrunedNode, out: string[]): void {
  if (node.isLeaf) {
    out.push(node.id)
    return
  }
  if (node.left) collectPrunedLeaves(node.left, out)
  if (node.right) collectPrunedLeaves(node.right, out)
}

function layoutPrunedTree(
  node: PrunedNode,
  currentDepth: number,
  maxDepth: number,
  startX: number,
  tipX: number,
  treeColWidth: number,
  branches: TreeBranch[]
): { x: number; y: number } {
  if (node.isLeaf) return { x: node.x, y: node.y }
  const leftRes = node.left
    ? layoutPrunedTree(node.left, currentDepth + 1, maxDepth, startX, tipX, treeColWidth, branches)
    : null
  const rightRes = node.right
    ? layoutPrunedTree(node.right, currentDepth + 1, maxDepth, startX, tipX, treeColWidth, branches)
    : null
  if (!leftRes || !rightRes) {
    return leftRes || rightRes || { x: tipX, y: 0 }
  }

  const depthFromLeaves = maxDepth - currentDepth
  const nodeX = Math.max(startX + 4, tipX - (depthFromLeaves / maxDepth) * (treeColWidth - 14))
  const nodeY = (leftRes.y + rightRes.y) / 2

  branches.push({ x1: nodeX, y1: leftRes.y, x2: leftRes.x, y2: leftRes.y })
  branches.push({ x1: nodeX, y1: rightRes.y, x2: rightRes.x, y2: rightRes.y })
  branches.push({
    x1: nodeX,
    y1: Math.min(leftRes.y, rightRes.y),
    x2: nodeX,
    y2: Math.max(leftRes.y, rightRes.y),
  })
  return { x: nodeX, y: nodeY }
}

function buildAdjacentUpgmaBranches(
  ids: string[],
  similarityMatrix: Record<string, Record<string, number | null>> | undefined,
  startX: number,
  startY: number,
  tipX: number,
  treeColWidth: number,
  rowHeight: number,
  branches: TreeBranch[]
): void {
  interface AdjCluster {
    ids: string[]
    y: number
    x: number
    depth: number
  }

  const clusters: AdjCluster[] = ids.map((id, idx) => ({
    ids: [id],
    y: startY + (idx + 0.5) * rowHeight,
    x: tipX,
    depth: 0,
  }))
  const maxSteps = Math.max(1, ids.length - 1)
  let currentStep = 0

  while (clusters.length > 1) {
    let bestI = 0
    let maxSim = -1
    for (let i = 0; i < clusters.length - 1; i++) {
      const c1 = clusters[i]
      const c2 = clusters[i + 1]
      if (!c1 || !c2) continue
      let sumSim = 0
      let count = 0
      for (const s1 of c1.ids) {
        for (const s2 of c2.ids) {
          const raw = similarityMatrix?.[s1]?.[s2]
          sumSim += raw !== null && raw !== undefined ? raw : s1 === s2 ? 100 : 0
          count++
        }
      }
      const avgSim = count > 0 ? sumSim / count : 0
      if (avgSim > maxSim) {
        maxSim = avgSim
        bestI = i
      }
    }

    const cA = clusters[bestI]
    const cB = clusters[bestI + 1]
    if (!cA || !cB) break

    currentStep++
    const newDepth = 1 + Math.max(cA.depth, cB.depth)
    const newX = Math.max(startX + 4, tipX - (currentStep / maxSteps) * (treeColWidth - 14))
    const newY = (cA.y + cB.y) / 2

    branches.push({ x1: newX, y1: cA.y, x2: cA.x, y2: cA.y })
    branches.push({ x1: newX, y1: cB.y, x2: cB.x, y2: cB.y })
    branches.push({
      x1: newX,
      y1: Math.min(cA.y, cB.y),
      x2: newX,
      y2: Math.max(cA.y, cB.y),
    })

    clusters.splice(bestI, 2, {
      ids: [...cA.ids, ...cB.ids],
      y: newY,
      x: newX,
      depth: newDepth,
    })
  }

  const finalRoot = clusters[0]
  if (finalRoot) {
    branches.push({ x1: startX + 2, y1: finalRoot.y, x2: finalRoot.x, y2: finalRoot.y })
  }
}

/**
 * 严格按照当前界面的排序与聚类配置计算系统发育拓扑树几何连线
 */
export function computeExportTreeLayout(params: {
  visibleSampleIds: string[]
  treeRoot?: ClusteringTreeNodeLike | null
  sortOrder?: 'natural' | 'cluster'
  similarityMatrix?: Record<string, Record<string, number | null>>
  startX: number
  startY: number
  treeColWidth: number
  rowHeight: number
}): TreeLayoutResult {
  const { visibleSampleIds: ids, treeRoot, sortOrder, similarityMatrix, startX, startY, treeColWidth, rowHeight } =
    params
  const n = ids.length
  if (n === 0) return { branches: [], tips: [] }

  const tipX = startX + treeColWidth - 8
  const tips: TreeTip[] = ids.map((id, idx) => ({
    x: tipX,
    y: startY + (idx + 0.5) * rowHeight,
    id,
  }))

  if (n === 1) {
    const tip0 = tips[0]
    return {
      branches: tip0 ? [{ x1: startX + 4, y1: tip0.y, x2: tipX, y2: tip0.y }] : [],
      tips,
    }
  }

  const branches: TreeBranch[] = []
  const yMap = new Map<string, number>()
  ids.forEach((id, idx) => {
    yMap.set(id, startY + (idx + 0.5) * rowHeight)
  })

  let usedBackendTree = false
  if (treeRoot && sortOrder !== 'natural') {
    const prunedRoot = pruneTreeForVisibleIds(treeRoot, new Set(ids), yMap, tipX)
    if (prunedRoot) {
      const prunedLeafOrder: string[] = []
      collectPrunedLeaves(prunedRoot, prunedLeafOrder)
      const isOrderConsistent =
        prunedLeafOrder.length === ids.length && prunedLeafOrder.every((sid, i) => sid === ids[i])
      if (isOrderConsistent) {
        usedBackendTree = true
        const rootPos = layoutPrunedTree(
          prunedRoot,
          0,
          prunedRoot.depth || 1,
          startX,
          tipX,
          treeColWidth,
          branches
        )
        branches.push({ x1: startX + 2, y1: rootPos.y, x2: rootPos.x, y2: rootPos.y })
      }
    }
  }

  if (!usedBackendTree) {
    buildAdjacentUpgmaBranches(ids, similarityMatrix, startX, startY, tipX, treeColWidth, rowHeight, branches)
  }

  return { branches, tips }
}

/**
 * 获取 ANI 色块的背景颜色与文字颜色
 */
export function getAniColor(val: number | null | undefined): { bg: string; text: string } {
  if (val === null || val === undefined) return { bg: '#f8fafc', text: '#94a3b8' }
  if (val >= 100) return { bg: '#1e3a8a', text: '#ffffff' }
  if (val >= 95) return { bg: '#2563eb', text: '#ffffff' }
  if (val >= 90) return { bg: '#60a5fa', text: '#ffffff' }
  if (val >= 80) return { bg: '#93c5fd', text: '#1e3a8a' }
  if (val >= 70) return { bg: '#bfdbfe', text: '#1e3a8a' }
  return { bg: '#eff6ff', text: '#1e3a8a' }
}
