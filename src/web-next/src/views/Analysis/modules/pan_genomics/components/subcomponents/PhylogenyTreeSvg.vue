<script setup lang="ts">
/**
 * PhylogenyTreeSvg.vue - 系统发育拓扑树独立矢量渲染组件
 * 基于全基因组 ANI 矩阵进行 UPGMA 层次聚类几何布局，严格与表格行高进行物理级对齐。
 */
import { computed } from 'vue'

const props = defineProps<{
  visibleSampleIds: string[]
  aniMatrix?: Record<string, Record<string, number>>
  rowHeight: number
  displayDensity: 'spacious' | 'comfortable' | 'compact' | 'ultra'
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

const treeSvgLayout = computed(() => {
  const ids = props.visibleSampleIds
  const n = ids.length
  const currentHeight = props.rowHeight

  if (n === 0) return { width: 44, height: currentHeight, branches: [] as TreeBranch[], tips: [] as TreeTip[] }

  const totalHeight = n * currentHeight
  const baseRadius =
    props.displayDensity === 'spacious'
      ? 3.2
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

  // 动态 UPGMA 聚类构建几何树 (精准物理 Y 坐标)
  let clusters: Array<{
    ids: string[]
    leaves: number[]
    y: number
    x: number
    height: number
  }> = ids.map((id, idx) => ({
    ids: [id],
    leaves: [idx],
    y: (idx + 0.5) * currentHeight,
    x: 36,
    height: 0
  }))

  const branches: TreeBranch[] = []
  let currentStep = 0
  const maxSteps = n - 1

  while (clusters.length > 1) {
    let bestI = 0
    let bestJ = 1
    let maxSimilarity = -1

    for (let i = 0; i < clusters.length; i++) {
      const ci = clusters[i]
      if (!ci) continue
      for (let j = i + 1; j < clusters.length; j++) {
        const cj = clusters[j]
        if (!cj) continue
        let sumSim = 0
        let count = 0
        for (const s1 of ci.ids) {
          for (const s2 of cj.ids) {
            sumSim += props.aniMatrix?.[s1]?.[s2] ?? (s1 === s2 ? 100 : 80)
            count++
          }
        }
        const avgSim = count > 0 ? sumSim / count : 80
        if (avgSim > maxSimilarity) {
          maxSimilarity = avgSim
          bestI = i
          bestJ = j
        }
      }
    }

    const cA = clusters[bestI]
    const cB = clusters[bestJ]
    if (!cA || !cB) break
    currentStep++

    // 计算分叉节点的 x 坐标 (深度从 36 逐渐向左推移到 6)
    const newX = Math.max(6, 36 - (currentStep / maxSteps) * 26)
    const newY = (cA.y + cB.y) / 2

    // 为子节点 A 画线: 水平线 (newX, cA.y) -> (cA.x, cA.y)
    branches.push({ x1: newX, y1: cA.y, x2: cA.x, y2: cA.y })
    // 为子节点 B 画线: 水平线 (newX, cB.y) -> (cB.x, cB.y)
    branches.push({ x1: newX, y1: cB.y, x2: cB.x, y2: cB.y })
    // 垂直连接线: (newX, min(cA.y, cB.y)) -> (newX, max(cA.y, cB.y))
    branches.push({ x1: newX, y1: Math.min(cA.y, cB.y), x2: newX, y2: Math.max(cA.y, cB.y) })

    const merged = {
      ids: [...cA.ids, ...cB.ids],
      leaves: [...cA.leaves, ...cB.leaves],
      y: newY,
      x: newX,
      height: 100 - maxSimilarity
    }

    clusters = clusters.filter((_, idx) => idx !== bestI && idx !== bestJ)
    clusters.push(merged)
  }

  // 根节点向左引一条主干根茎
  const root = clusters[0]
  if (root) {
    branches.push({ x1: 2, y1: root.y, x2: root.x, y2: root.y })
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
