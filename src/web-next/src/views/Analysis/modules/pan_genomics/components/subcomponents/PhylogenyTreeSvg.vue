<script setup lang="ts">
/**
 * PhylogenyTreeSvg.vue - 系统发育拓扑树独立矢量渲染组件
 * 基于全基因组 ANI 矩阵进行 UPGMA 层次聚类几何布局，严格与表格行高进行物理级对齐。
 */
import { computed } from 'vue'

const props = defineProps<{
  visibleSampleIds: string[]
  aniMatrix?: Record<string, Record<string, number | null>>
  rowHeight: number
  displayDensity: 'spacious' | 'comfortable' | 'compact' | 'ultra'
  treeRoot?: any
  sortOrder?: 'natural' | 'cluster'
}>()

interface TreeBranch {
  x1: number
  y1: number
  x2: number
  y2: number
}

interface TreeTip {
  x: number
  y: number
  r: number
  id: string
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

const treeSvgLayout = computed(() => {
  const ids = props.visibleSampleIds
  const n = ids.length
  const currentHeight = props.rowHeight

  if (n === 0) {
    return { width: 44, height: currentHeight, branches: [] as TreeBranch[], tips: [] as TreeTip[] }
  }

  const totalHeight = n * currentHeight
  const baseRadius =
    props.displayDensity === 'spacious'
      ? 3.0
      : props.displayDensity === 'ultra'
      ? 1.5
      : props.displayDensity === 'compact'
      ? 2.0
      : 2.5

  const tips: TreeTip[] = ids.map((id, idx) => ({
    x: 36,
    y: (idx + 0.5) * currentHeight,
    r: baseRadius,
    id
  }))

  if (n === 1) {
    const tip0 = tips[0]
    return {
      width: 44,
      height: totalHeight,
      branches: tip0 ? [{ x1: 6, y1: tip0.y, x2: 36, y2: tip0.y }] : [],
      tips
    }
  }

  const branches: TreeBranch[] = []
  const yMap = new Map<string, number>()
  ids.forEach((id, idx) => {
    yMap.set(id, (idx + 0.5) * currentHeight)
  })

  // 检查是否可以使用后端预计算的 TreeRoot 进行剪枝与平面布局
  let usedBackendTree = false

  if (props.treeRoot && props.sortOrder !== 'natural') {
    const visibleSet = new Set(ids)

    // 1. 剪枝递归: 过滤掉已隐藏样本，折叠单子树节点
    function prune(node: any): PrunedNode | null {
      if (!node) return null
      const isLeafNode = !node.left && !node.right
      if (isLeafNode) {
        if (visibleSet.has(node.id)) {
          const yVal = yMap.get(node.id) ?? 0
          return {
            id: node.id,
            x: 36,
            y: yVal,
            isLeaf: true,
            depth: 0
          }
        }
        return null
      }

      const l = prune(node.left)
      const r = prune(node.right)

      if (l && r) {
        return {
          id: node.id || 'internal',
          x: 0,
          y: (l.y + r.y) / 2,
          isLeaf: false,
          depth: 1 + Math.max(l.depth, r.depth),
          left: l,
          right: r
        }
      } else if (l) {
        return l
      } else if (r) {
        return r
      }
      return null
    }

    const prunedRoot = prune(props.treeRoot)

    if (prunedRoot) {
      // 收集剪枝后的叶序，验证是否与当前表格 visibleSampleIds 一致 (确保平面无交叉)
      const prunedLeafOrder: string[] = []
      function collectLeaves(n: PrunedNode) {
        if (n.isLeaf) {
          prunedLeafOrder.push(n.id)
        } else {
          if (n.left) collectLeaves(n.left)
          if (n.right) collectLeaves(n.right)
        }
      }
      collectLeaves(prunedRoot)

      // 验证顺序一致性: 若当前表格样本顺序与剪枝叶序完全一致，则天然严格平面
      const isOrderConsistent =
        prunedLeafOrder.length === ids.length &&
        prunedLeafOrder.every((sid, i) => sid === ids[i])

      if (isOrderConsistent) {
        usedBackendTree = true
        const maxDepth = prunedRoot.depth || 1

        function layoutNode(n: PrunedNode, currentDepth: number): { x: number; y: number } {
          if (n.isLeaf) {
            return { x: n.x, y: n.y }
          }
          const leftRes = n.left ? layoutNode(n.left, currentDepth + 1) : null
          const rightRes = n.right ? layoutNode(n.right, currentDepth + 1) : null

          if (!leftRes || !rightRes) {
            return leftRes || rightRes || { x: 36, y: 0 }
          }

          // 计算内部节点的横向深度 (根节点偏左至 6px，叶节点在 36px)
          const depthFromLeaves = maxDepth - currentDepth
          const nodeX = Math.max(6, 36 - (depthFromLeaves / maxDepth) * 28)
          const nodeY = (leftRes.y + rightRes.y) / 2

          // 绘制到左子节点的直角分支
          branches.push({ x1: nodeX, y1: leftRes.y, x2: leftRes.x, y2: leftRes.y })
          // 绘制到右子节点的直角分支
          branches.push({ x1: nodeX, y1: rightRes.y, x2: rightRes.x, y2: rightRes.y })
          // 绘制垂直主干连接线 (左右子节点垂直区间)
          branches.push({
            x1: nodeX,
            y1: Math.min(leftRes.y, rightRes.y),
            x2: nodeX,
            y2: Math.max(leftRes.y, rightRes.y)
          })

          return { x: nodeX, y: nodeY }
        }

        const rootPos = layoutNode(prunedRoot, 0)
        // 根节点向左主干线
        branches.push({ x1: 2, y1: rootPos.y, x2: rootPos.x, y2: rootPos.y })
      }
    }
  }

  // 若未启用后端树或因重排序打乱叶序，平滑降级至自适应相邻约束平面层次聚类 (Adjacent-Constrained UPGMA)
  if (!usedBackendTree) {
    interface AdjCluster {
      ids: string[]
      y: number
      x: number
      depth: number
    }

    let clusters: AdjCluster[] = ids.map((id, idx) => ({
      ids: [id],
      y: (idx + 0.5) * currentHeight,
      x: 36,
      depth: 0
    }))

    const maxSteps = Math.max(1, n - 1)
    let currentStep = 0

    while (clusters.length > 1) {
      let bestI = 0
      let maxSim = -1

      // 关键: 仅在当前物理相邻的簇 i 与 i + 1 之间搜寻最大相似度合并
      // 该约束在拓扑学上保证了簇的 Y 轴区间始终连续，绝不产生跨行刺穿
      for (let i = 0; i < clusters.length - 1; i++) {
        const c1 = clusters[i]
        const c2 = clusters[i + 1]
        if (!c1 || !c2) continue

        let sumSim = 0
        let count = 0
        for (const s1 of c1.ids) {
          for (const s2 of c2.ids) {
            const raw = props.aniMatrix?.[s1]?.[s2]
            const sim = raw !== null && raw !== undefined ? raw : s1 === s2 ? 100 : 0
            sumSim += sim
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
      const newX = Math.max(6, 36 - (currentStep / maxSteps) * 28)
      const newY = (cA.y + cB.y) / 2

      // 水平分支到 A
      branches.push({ x1: newX, y1: cA.y, x2: cA.x, y2: cA.y })
      // 水平分支到 B
      branches.push({ x1: newX, y1: cB.y, x2: cB.x, y2: cB.y })
      // 垂直线连接 A 和 B (由于 A 和 B 相邻，此垂直线内部无任何其他行经过)
      branches.push({
        x1: newX,
        y1: Math.min(cA.y, cB.y),
        x2: newX,
        y2: Math.max(cA.y, cB.y)
      })

      const merged: AdjCluster = {
        ids: [...cA.ids, ...cB.ids],
        y: newY,
        x: newX,
        depth: newDepth
      }

      clusters.splice(bestI, 2, merged)
    }

    const finalRoot = clusters[0]
    if (finalRoot) {
      branches.push({ x1: 2, y1: finalRoot.y, x2: finalRoot.x, y2: finalRoot.y })
    }
  }

  return {
    width: 44,
    height: totalHeight,
    branches,
    tips
  }
})
</script>

<template>
  <div class="tree-absolute-wrapper">
    <svg
      class="tree-composite-svg"
      :viewBox="`0 0 ${treeSvgLayout.width} ${treeSvgLayout.height}`"
      preserveAspectRatio="none"
    >
      <!-- 进化树分支线 -->
      <line
        v-for="(b, bIdx) in treeSvgLayout.branches"
        :key="'branch-' + bIdx"
        :x1="b.x1"
        :y1="b.y1"
        :x2="b.x2"
        :y2="b.y2"
        stroke="#475569"
        stroke-width="1.2"
        vector-effect="non-scaling-stroke"
        stroke-linecap="round"
      />
      <!-- 叶子节点末端指示圆点 (精准对齐每行中线) -->
      <circle
        v-for="tip in treeSvgLayout.tips"
        :key="'tip-' + tip.id"
        :cx="tip.x"
        :cy="tip.y"
        :r="tip.r"
        fill="#2563eb"
        stroke="#ffffff"
        stroke-width="0.8"
        vector-effect="non-scaling-stroke"
      />
    </svg>
  </div>
</template>

<style scoped>
.tree-absolute-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.tree-composite-svg {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
