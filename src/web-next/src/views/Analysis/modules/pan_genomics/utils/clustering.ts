/**
 * clustering.ts - 泛基因组与系统发育层次聚类工具模块
 *
 * 单一职责:
 * 1. 泛基因组直系同源基因家族 (CDS) Jaccard 相似度矩阵计算
 * 2. 论文级 UPGMA (Unweighted Pair Group Method with Arithmetic Mean) 层次聚类算法
 * 3. 严格二叉树拓扑构建与单调叶序展开 (Ordered IDs)
 */

export interface ClusteringTreeNode {
  id: string
  leaves: string[]
  height: number
  left: ClusteringTreeNode | null
  right: ClusteringTreeNode | null
}

export interface HierarchicalClusteringResult {
  ordered_ids: string[]
  root: ClusteringTreeNode | null
}

/**
 * 计算所有样本之间的 CDS 功能谱 Jaccard 相似度矩阵与统计数据
 */
export function computeCdsJaccardMatrix(
  sampleIds: string[],
  clusters: any[]
): {
  matrix: Record<string, Record<string, number | null>>
  mat: Record<string, Record<string, number | null>>
  stats: Record<string, Record<string, { shared: number; union: number; s1Unique: number; s2Unique: number }>>
} {
  const matrix: Record<string, Record<string, number | null>> = {}
  const stats: Record<string, Record<string, { shared: number; union: number; s1Unique: number; s2Unique: number }>> = {}

  if (!sampleIds || sampleIds.length === 0) {
    return { matrix, mat: matrix, stats }
  }

  // 构建样本直系同源群集合
  const sampleSets: Record<string, Set<string>> = {}
  sampleIds.forEach(sid => {
    sampleSets[sid] = new Set<string>()
  })

  if (clusters && clusters.length > 0) {
    clusters.forEach(c => {
      if (c && c.presence_map) {
        Object.entries(c.presence_map).forEach(([sid, val]) => {
          if (val && sampleSets[sid]) {
            sampleSets[sid].add(c.group_id)
          }
        })
      }
    })
  }

  sampleIds.forEach(s1 => {
    const rowMat: Record<string, number | null> = {}
    const rowStat: Record<string, { shared: number; union: number; s1Unique: number; s2Unique: number }> = {}
    matrix[s1] = rowMat
    stats[s1] = rowStat
    const set1 = sampleSets[s1] || new Set()

    sampleIds.forEach(s2 => {
      if (s1 === s2) {
        rowMat[s2] = 100.0
        rowStat[s2] = { shared: set1.size, union: set1.size, s1Unique: 0, s2Unique: 0 }
        return
      }

      const set2 = sampleSets[s2] || new Set()
      if (set1.size === 0 && set2.size === 0) {
        rowMat[s2] = null
        rowStat[s2] = { shared: 0, union: 0, s1Unique: 0, s2Unique: 0 }
        return
      }

      let shared = 0
      set1.forEach(gid => {
        if (set2.has(gid)) shared++
      })

      const union = set1.size + set2.size - shared
      const s1Unique = set1.size - shared
      const s2Unique = set2.size - shared
      const score = union > 0 ? (shared / union) * 100.0 : 0.0

      rowMat[s2] = Number(score.toFixed(1))
      rowStat[s2] = { shared, union, s1Unique, s2Unique }
    })
  })

  return { matrix, mat: matrix, stats }
}

/**
 * 基于成对相似度矩阵执行 UPGMA 层次聚类，并输出单调叶序列与标准二叉树
 */
export function computeUpgmaClustering(
  sampleIds: string[],
  similarityMatrix: Record<string, Record<string, number | null>>
): HierarchicalClusteringResult {
  const n = sampleIds.length
  if (n === 0) {
    return { ordered_ids: [], root: null }
  }
  if (n === 1) {
    const singleId = sampleIds[0] as string
    const singleRoot: ClusteringTreeNode = {
      id: singleId,
      leaves: [singleId],
      height: 0,
      left: null,
      right: null
    }
    return { ordered_ids: [singleId], root: singleRoot }
  }

  // 初始化叶子簇
  let activeClusters: ClusteringTreeNode[] = sampleIds.map(sid => ({
    id: sid,
    leaves: [sid],
    height: 0,
    left: null,
    right: null
  }))

  let nodeCounter = 0

  while (activeClusters.length > 1) {
    let bestI = 0
    let bestJ = 1
    let maxSim = -1.0

    // 寻找平均相似度最高的簇对
    for (let i = 0; i < activeClusters.length; i++) {
      const cA = activeClusters[i]
      if (!cA) continue
      for (let j = i + 1; j < activeClusters.length; j++) {
        const cB = activeClusters[j]
        if (!cB) continue

        let sumSim = 0
        let count = 0
        for (const u of cA.leaves) {
          for (const v of cB.leaves) {
            const raw = similarityMatrix[u]?.[v]
            const sim = raw !== null && raw !== undefined ? raw : u === v ? 100.0 : 0.0
            sumSim += sim
            count++
          }
        }
        const avgSim = count > 0 ? sumSim / count : 0.0
        if (avgSim > maxSim) {
          maxSim = avgSim
          bestI = i
          bestJ = j
        }
      }
    }

    const cA = activeClusters[bestI]
    const cB = activeClusters[bestJ]
    if (!cA || !cB) break

    nodeCounter++
    const mergedNode: ClusteringTreeNode = {
      id: `NODE_CDS_${nodeCounter}`,
      leaves: [...cA.leaves, ...cB.leaves],
      height: Math.max(0, 100.0 - maxSim),
      left: cA,
      right: cB
    }

    activeClusters = activeClusters.filter((_, idx) => idx !== bestI && idx !== bestJ)
    activeClusters.push(mergedNode)
  }

  const root = activeClusters[0] || null
  const ordered_ids: string[] = []

  function traverseTree(node: ClusteringTreeNode | null) {
    if (!node) return
    if (!node.left && !node.right) {
      ordered_ids.push(node.id)
      return
    }
    if (node.left) traverseTree(node.left)
    if (node.right) traverseTree(node.right)
  }

  traverseTree(root)

  return { ordered_ids, root }
}
