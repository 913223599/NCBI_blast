/**
 * exportLandscapeFigure.ts - Figure 1 系统发育与泛基因组同源矩阵整体完整导出模块
 * 
 * 职责：
 * 1. 突破视口与滚动条截断限制，以纯内存 Canvas 2D / 矢量 SVG 双引擎完整导出全景科研大图；
 * 2. 严格与当前界面配置保持一致：若选择进化聚类模式，则按照 UPGMA 层次聚类拓扑树叶序及二叉分化分支导出；若选择自然顺序模式，则按照编号自然递增及保序相邻聚类导出；
 * 3. 采用高密度柱状条（Vertical Barcode Strip）替代传统稀疏方块，压缩无意义空间，提升学术信息密度；
 * 4. 完美包含全部样本、全量直系同源基因家族列（400+ 柱状细条连续展开）、系统发育拓扑树、元数据轨道、ANI 热图及学术图注；
 * 5. 支持出版级超清 PNG（2x Retina 超采样）与无限缩放矢量 SVG 格式无损导出。
 */
import { FUNCTIONAL_CATEGORIES } from '../../viewer/utils/render'

export interface ExportFigureOptions {
  title: string
  subtitle: string
  visibleSampleIds: string[]
  orderedSampleIds: string[]
  sampleNames: Record<string, string>
  sortedGeneClusters: any[]
  aniMatrix?: Record<string, Record<string, number | null>>
  lifestyles?: any[]
  treeRoot?: any
  sortOrder?: 'natural' | 'cluster'
  isPhylogenyTrackVisible: boolean
  isMetadataTrackVisible: boolean
  isAniTrackVisible: boolean
  isGeneMatrixTrackVisible: boolean
  activeSimilarityMatrix?: Record<string, Record<string, number | null>>
  format: 'png' | 'svg'
}

interface TreeBranch {
  x1: number
  y1: number
  x2: number
  y2: number
}

interface TreeTip {
  x: number
  y: number
  id: string
}

interface TreeLayoutResult {
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

/**
 * 严格按照当前界面的排序与聚类配置计算系统发育拓扑树几何连线
 */
function computeExportTreeLayout(params: {
  visibleSampleIds: string[]
  treeRoot?: any
  sortOrder?: 'natural' | 'cluster'
  similarityMatrix?: Record<string, Record<string, number | null>>
  startX: number
  startY: number
  treeColWidth: number
  rowHeight: number
}): TreeLayoutResult {
  const { visibleSampleIds: ids, treeRoot, sortOrder, similarityMatrix, startX, startY, treeColWidth, rowHeight } = params
  const n = ids.length
  if (n === 0) return { branches: [], tips: [] }

  const tipX = startX + treeColWidth - 8
  const tips: TreeTip[] = ids.map((id, idx) => ({
    x: tipX,
    y: startY + (idx + 0.5) * rowHeight,
    id
  }))

  if (n === 1) {
    const tip0 = tips[0]
    return {
      branches: tip0 ? [{ x1: startX + 4, y1: tip0.y, x2: tipX, y2: tip0.y }] : [],
      tips
    }
  }

  const branches: TreeBranch[] = []
  const yMap = new Map<string, number>()
  ids.forEach((id, idx) => {
    yMap.set(id, startY + (idx + 0.5) * rowHeight)
  })

  let usedBackendTree = false

  // 1. 优先使用真实的聚类二叉树 TreeRoot 进行剪枝与平面几何展开 (进化聚类模式)
  if (treeRoot && sortOrder !== 'natural') {
    const visibleSet = new Set(ids)

    function prune(node: any): PrunedNode | null {
      if (!node) return null
      const isLeafNode = !node.left && !node.right
      if (isLeafNode) {
        if (visibleSet.has(node.id)) {
          const yVal = yMap.get(node.id) ?? 0
          return {
            id: node.id,
            x: tipX,
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

    const prunedRoot = prune(treeRoot)

    if (prunedRoot) {
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

      // 验证顺序一致性: 若当前可见样本与剪枝叶序完全一致，则天然严格平面展开
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
            return leftRes || rightRes || { x: tipX, y: 0 }
          }

          const depthFromLeaves = maxDepth - currentDepth
          const nodeX = Math.max(startX + 4, tipX - (depthFromLeaves / maxDepth) * (treeColWidth - 14))
          const nodeY = (leftRes.y + rightRes.y) / 2

          // 绘制直角水平分支到左子节点
          branches.push({ x1: nodeX, y1: leftRes.y, x2: leftRes.x, y2: leftRes.y })
          // 绘制直角水平分支到右子节点
          branches.push({ x1: nodeX, y1: rightRes.y, x2: rightRes.x, y2: rightRes.y })
          // 绘制垂直主干连线
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
        branches.push({ x1: startX + 2, y1: rootPos.y, x2: rootPos.x, y2: rootPos.y })
      }
    }
  }

  // 2. 若为自然排序模式或顺序降级，采用自适应相邻约束平面层次聚类 (Adjacent-Constrained UPGMA)
  if (!usedBackendTree) {
    interface AdjCluster {
      ids: string[]
      y: number
      x: number
      depth: number
    }

    let clusters: AdjCluster[] = ids.map((id, idx) => ({
      ids: [id],
      y: startY + (idx + 0.5) * rowHeight,
      x: tipX,
      depth: 0
    }))

    const maxSteps = Math.max(1, n - 1)
    let currentStep = 0

    while (clusters.length > 1) {
      let bestI = 0
      let maxSim = -1

      // 仅在当前物理相邻的簇 i 与 i + 1 之间搜寻最大相似度合并，严格保证不跨行刺穿
      for (let i = 0; i < clusters.length - 1; i++) {
        const c1 = clusters[i]
        const c2 = clusters[i + 1]
        if (!c1 || !c2) continue

        let sumSim = 0
        let count = 0
        for (const s1 of c1.ids) {
          for (const s2 of c2.ids) {
            const raw = similarityMatrix?.[s1]?.[s2]
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
      const newX = Math.max(startX + 4, tipX - (currentStep / maxSteps) * (treeColWidth - 14))
      const newY = (cA.y + cB.y) / 2

      branches.push({ x1: newX, y1: cA.y, x2: cA.x, y2: cA.y })
      branches.push({ x1: newX, y1: cB.y, x2: cB.x, y2: cB.y })
      branches.push({
        x1: newX,
        y1: Math.min(cA.y, cB.y),
        x2: newX,
        y2: Math.max(cA.y, cB.y)
      })

      clusters.splice(bestI, 2, {
        ids: [...cA.ids, ...cB.ids],
        y: newY,
        x: newX,
        depth: newDepth
      })
    }

    const finalRoot = clusters[0]
    if (finalRoot) {
      branches.push({ x1: startX + 2, y1: finalRoot.y, x2: finalRoot.x, y2: finalRoot.y })
    }
  }

  return { branches, tips }
}

/**
 * 获取 ANI 色块的背景颜色与文字颜色
 */
function getAniColor(val: number | null | undefined): { bg: string; text: string } {
  if (val === null || val === undefined) return { bg: '#f8fafc', text: '#94a3b8' }
  if (val >= 100) return { bg: '#1e3a8a', text: '#ffffff' }
  if (val >= 95) return { bg: '#2563eb', text: '#ffffff' }
  if (val >= 90) return { bg: '#60a5fa', text: '#ffffff' }
  if (val >= 80) return { bg: '#93c5fd', text: '#1e3a8a' }
  if (val >= 70) return { bg: '#bfdbfe', text: '#1e3a8a' }
  return { bg: '#eff6ff', text: '#1e3a8a' }
}

/**
 * 完整导出 Figure 1 图表 (高密度柱状条形码模式)
 */
export async function exportCompleteFigure(options: ExportFigureOptions): Promise<void> {
  const {
    title,
    visibleSampleIds,
    sampleNames,
    sortedGeneClusters,
    lifestyles = [],
    treeRoot,
    sortOrder = 'cluster',
    isPhylogenyTrackVisible,
    isMetadataTrackVisible,
    isAniTrackVisible,
    isGeneMatrixTrackVisible,
    activeSimilarityMatrix,
    format
  } = options

  const sampleCount = visibleSampleIds.length
  if (sampleCount === 0) return

  // 1. 紧凑高密度几何尺寸规划 (压缩无意义空间)
  const paddingX = 16
  const paddingY = 16
  const headerHeight = 36
  const legendHeight = 38
  const tableHeaderHeight = 26
  const rowHeight = 22

  const treeColWidth = isPhylogenyTrackVisible ? 60 : 0
  const sampleNameColWidth = 140
  const metaColWidth = isMetadataTrackVisible ? 52 : 0
  const totalMetaWidth = isMetadataTrackVisible ? metaColWidth * 3 : 0
  const aniColWidth = 22
  const totalAniWidth = isAniTrackVisible ? aniColWidth * sampleCount : 0

  // 核心：柱状条形码宽度与间距 (每列 4.2px，柱条宽 3.0px，间隙 1.2px)
  const geneColWidth = 4.2
  const barWidth = 3.0
  const totalGeneWidth = isGeneMatrixTrackVisible ? geneColWidth * sortedGeneClusters.length : 0

  const tableWidth = treeColWidth + sampleNameColWidth + totalMetaWidth + totalAniWidth + totalGeneWidth
  const totalWidth = Math.max(960, Math.round(paddingX * 2 + tableWidth))
  const totalHeight = Math.round(paddingY * 2 + headerHeight + legendHeight + tableHeaderHeight + rowHeight * sampleCount)

  // 2. 如果是 SVG 矢量导出
  if (format === 'svg') {
    const svgString = buildFigureSvg(options, {
      totalWidth,
      totalHeight,
      paddingX,
      paddingY,
      headerHeight,
      legendHeight,
      tableHeaderHeight,
      rowHeight,
      treeColWidth,
      sampleNameColWidth,
      metaColWidth,
      aniColWidth,
      geneColWidth,
      barWidth
    })

    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
    downloadBlob(blob, `Figure1_PanGenome_Matrix_${Date.now()}.svg`)
    return
  }

  // 3. 如果是 PNG 超清导出 (使用 2x Canvas 超采样抗锯齿)
  const scale = 2.0
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(totalWidth * scale)
  canvas.height = Math.round(totalHeight * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.scale(scale, scale)

  // 背景纯白
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, totalWidth, totalHeight)

  // A. 顶部标题栏
  let curY = paddingY
  ctx.save()

  // Figure 1 药丸徽章
  ctx.fillStyle = '#eff6ff'
  ctx.strokeStyle = '#bfdbfe'
  ctx.lineWidth = 1
  roundRect(ctx, paddingX, curY + 2, 52, 20, 4, true, true)
  ctx.fillStyle = '#1d4ed8'
  ctx.font = 'bold 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('Figure 1', paddingX + 26, curY + 12)

  // 标题文字 (在当前 font 下精准计算标题宽度，防止副标覆盖)
  ctx.fillStyle = '#0f172a'
  ctx.font = 'bold 15px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.textAlign = 'left'
  const titleX = paddingX + 60
  ctx.fillText(title, titleX, curY + 12)
  const titleWidth = ctx.measureText(title).width

  // 统计副标徽章 (根据当前排序配置动态标注)
  const sortModeLabel = sortOrder === 'cluster' ? '进化聚类排序' : '自然编号排序'
  const badgeText = `${sampleCount} 株系 · ${sortedGeneClusters.length} 基因家族 · ${sortModeLabel}`
  ctx.font = '500 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  const badgeTextW = ctx.measureText(badgeText).width
  const badgeBoxX = titleX + titleWidth + 12
  const badgeBoxW = badgeTextW + 16
  ctx.fillStyle = '#f1f5f9'
  ctx.strokeStyle = '#e2e8f0'
  roundRect(ctx, badgeBoxX, curY + 2, badgeBoxW, 20, 10, true, true)
  ctx.fillStyle = '#475569'
  ctx.fillText(badgeText, badgeBoxX + 8, curY + 12)
  ctx.restore()

  curY += headerHeight

  // B. 精炼紧凑图注条 (Legend Deck)
  ctx.save()
  ctx.fillStyle = '#f8fafc'
  ctx.strokeStyle = '#e2e8f0'
  ctx.lineWidth = 1
  roundRect(ctx, paddingX, curY, totalWidth - paddingX * 2, legendHeight - 6, 5, true, true)

  let legX = paddingX + 10
  const legY = curY + (legendHeight - 6) / 2

  // 功能分类图注
  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#475569'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('CDS 功能分类:', legX, legY)
  legX += ctx.measureText('CDS 功能分类:').width + 6

  ctx.font = '500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  const catEntries = Object.entries(FUNCTIONAL_CATEGORIES).slice(0, 7)
  for (const [, cat] of catEntries) {
    ctx.fillStyle = cat.color
    ctx.fillRect(legX, legY - 3.5, 7, 7)
    legX += 9
    ctx.fillStyle = '#334155'
    const lbl = cat.label.split(' ')[0] || ''
    ctx.fillText(lbl, legX, legY)
    legX += ctx.measureText(lbl).width + 8
  }

  // 变异形态图注 (柱状条形象)
  legX += 12
  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#475569'
  ctx.fillText('变异形态:', legX, legY)
  legX += ctx.measureText('变异形态:').width + 6

  // 等长保守 (细长柱状条)
  ctx.font = '500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#0284c7'
  roundRect(ctx, legX, legY - 6, 3.2, 12, 0.5, true, false)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('等长保守', legX, legY)
  legX += ctx.measureText('等长保守').width + 8

  // 序列截短 (较短柱状条)
  ctx.fillStyle = '#f59e0b'
  roundRect(ctx, legX, legY - 3.5, 3.2, 7, 0.5, true, false)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('序列截短', legX, legY)
  legX += ctx.measureText('序列截短').width + 8

  // 序列延伸 (长柱状条 + 顶标)
  ctx.fillStyle = '#10b981'
  roundRect(ctx, legX, legY - 6, 3.2, 12, 0.5, true, false)
  ctx.fillStyle = '#065f46'
  ctx.fillRect(legX, legY - 7.5, 3.2, 2)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('序列延伸', legX, legY)
  legX += ctx.measureText('序列延伸').width + 8

  // 基因缺失 (极微细灰点)
  ctx.fillStyle = '#cbd5e1'
  ctx.beginPath()
  ctx.arc(legX + 2, legY, 1.2, 0, Math.PI * 2)
  ctx.fill()
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('基因缺失', legX, legY)

  ctx.restore()

  curY += legendHeight

  // C. 表头绘制 (Table Header)
  ctx.save()
  ctx.fillStyle = '#f8fafc'
  ctx.fillRect(paddingX, curY, tableWidth, tableHeaderHeight)
  ctx.strokeStyle = '#cbd5e1'
  ctx.lineWidth = 1.2
  ctx.beginPath()
  ctx.moveTo(paddingX, curY + tableHeaderHeight)
  ctx.lineTo(paddingX + tableWidth, curY + tableHeaderHeight)
  ctx.stroke()

  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#64748b'
  ctx.textBaseline = 'middle'

  let thX = paddingX

  // 1. 系统发育列头
  if (isPhylogenyTrackVisible) {
    ctx.textAlign = 'center'
    ctx.fillText('系统发育', thX + treeColWidth / 2, curY + tableHeaderHeight / 2)
    thX += treeColWidth
  }

  // 2. 样本编号列头
  ctx.textAlign = 'left'
  ctx.fillText('样本编号', thX + 6, curY + tableHeaderHeight / 2)
  thX += sampleNameColWidth

  // 3. 元数据列头 (生活周期、生物安全、抗 CRISPR)
  if (isMetadataTrackVisible) {
    ctx.textAlign = 'center'
    ctx.fillText('生活周期', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
    ctx.fillText('生物安全', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
    ctx.fillText('抗CRISPR', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
  }

  // 4. ANI 列头
  if (isAniTrackVisible) {
    ctx.textAlign = 'center'
    ctx.font = 'bold 8px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    for (const colId of visibleSampleIds) {
      const sName = sampleNames[colId] || colId
      const shortName = sName.length > 3 ? sName.slice(0, 2) + '..' : sName
      ctx.fillText(shortName, thX + aniColWidth / 2, curY + tableHeaderHeight / 2)
      thX += aniColWidth
    }
  }

  // 5. 基因条形码矩阵列头
  if (isGeneMatrixTrackVisible) {
    ctx.textAlign = 'left'
    ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    ctx.fillStyle = '#0f172a'
    ctx.fillText(
      `泛基因组直系同源基因矩阵 (共 ${sortedGeneClusters.length} 基因家族，按功能着色)`,
      thX + 6,
      curY + tableHeaderHeight / 2
    )
  }
  ctx.restore()

  curY += tableHeaderHeight

  // D. 计算系统发育树分支与叶节点 (UPGMA 真实树/保序相邻聚类)
  const treeLayout = isPhylogenyTrackVisible
    ? computeExportTreeLayout({
        visibleSampleIds,
        treeRoot,
        sortOrder,
        similarityMatrix: activeSimilarityMatrix,
        startX: paddingX,
        startY: curY,
        treeColWidth,
        rowHeight
      })
    : { branches: [], tips: [] }

  // E. 逐行绘制样本数据与柱状条形码
  for (let rIdx = 0; rIdx < sampleCount; rIdx++) {
    const rowId = visibleSampleIds[rIdx]
    if (!rowId) continue
    const rowY = curY + rIdx * rowHeight

    // 行底边框与背景
    ctx.strokeStyle = '#f1f5f9'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(paddingX, rowY + rowHeight)
    ctx.lineTo(paddingX + tableWidth, rowY + rowHeight)
    ctx.stroke()

    let cellX = paddingX

    // 1. 跳过树列 (后续统一次层绘制)
    if (isPhylogenyTrackVisible) {
      cellX += treeColWidth
    }

    // 2. 样本名称
    ctx.save()
    ctx.font = '600 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    ctx.fillStyle = '#334155'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    const nameStr = sampleNames[rowId] || rowId
    ctx.fillText(nameStr, cellX + 6, rowY + rowHeight / 2)
    cellX += sampleNameColWidth
    ctx.restore()

    // 3. 元数据列 (生活周期、生物安全、抗 CRISPR)
    if (isMetadataTrackVisible) {
      const lifeInfo = lifestyles.find((l: any) => l.sample_id === rowId)
      const isLytic = lifeInfo?.lifestyle?.toLowerCase() === 'lytic'
      const isSafe = lifeInfo?.is_safe_for_therapy !== false

      // 生活周期胶囊 (高 15px, 宽 32px)
      ctx.save()
      ctx.fillStyle = isLytic ? '#10b981' : '#f59e0b'
      roundRect(ctx, cellX + (metaColWidth - 32) / 2, rowY + (rowHeight - 15) / 2, 32, 15, 2.5, true, false)
      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 8px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(isLytic ? '烈性' : '温和', cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth

      // 生物安全胶囊
      ctx.fillStyle = isSafe ? '#0284c7' : '#f43f5e'
      roundRect(ctx, cellX + (metaColWidth - 32) / 2, rowY + (rowHeight - 15) / 2, 32, 15, 2.5, true, false)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(isSafe ? '安全' : '警示', cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth

      // 抗 CRISPR 数量
      const acrCount = lifeInfo?.anti_crispr_count ?? 0
      ctx.fillStyle = '#334155'
      ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      ctx.fillText(String(acrCount), cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth
      ctx.restore()
    }

    // 4. ANI 热图单元格 (方形色块 22×22px)
    if (isAniTrackVisible) {
      ctx.save()
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      for (const colId of visibleSampleIds) {
        const aniVal = activeSimilarityMatrix?.[rowId]?.[colId] ?? (rowId === colId ? 100 : null)
        const color = getAniColor(aniVal)
        ctx.fillStyle = color.bg
        ctx.fillRect(cellX + 0.5, rowY + 0.5, aniColWidth - 1, rowHeight - 1)

        if (aniVal !== null && aniVal !== undefined) {
          ctx.fillStyle = color.text
          ctx.font = 'bold 7.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
          ctx.fillText(aniVal >= 100 ? '100' : aniVal.toFixed(0), cellX + aniColWidth / 2, rowY + rowHeight / 2)
        }
        cellX += aniColWidth
      }
      ctx.restore()
    }

    // 5. 核心：高密度学术柱状条形码 (Vertical Barcode Strip)
    if (isGeneMatrixTrackVisible) {
      ctx.save()
      for (const cluster of sortedGeneClusters) {
        const item = cluster.presence_map?.[rowId]
        const barX = cellX + (geneColWidth - barWidth) / 2

        if (item) {
          const varInfo = cluster._variantMap?.[rowId]
          const catColor = varInfo?.style?.backgroundColor || '#94a3b8'

          // 依据变异形态绘制不同柱状条
          if (varInfo?.type === 'truncated') {
            // 序列截短：短柱 (高度 10px，垂直居中)，内部划细微斜白线
            const barH = 10
            const barY = rowY + (rowHeight - barH) / 2
            ctx.fillStyle = catColor
            roundRect(ctx, barX, barY, barWidth, barH, 0.5, true, false)
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)'
            ctx.lineWidth = 0.8
            ctx.beginPath()
            ctx.moveTo(barX, barY + barH)
            ctx.lineTo(barX + barWidth, barY)
            ctx.stroke()
          } else if (varInfo?.type === 'extended') {
            // 序列延伸：满高长柱 (高度 17px)，且顶部带深色加长角标帽
            const barH = 17
            const barY = rowY + (rowHeight - barH) / 2
            ctx.fillStyle = catColor
            roundRect(ctx, barX, barY, barWidth, barH, 0.5, true, false)
            ctx.fillStyle = '#0f172a'
            ctx.fillRect(barX, barY, barWidth, 2.5)
          } else {
            // 等长保守：饱满柱状条 (高度 17px，宽度 3.0px)
            const barH = 17
            const barY = rowY + (rowHeight - barH) / 2
            ctx.fillStyle = catColor
            roundRect(ctx, barX, barY, barWidth, barH, 0.5, true, false)
          }
        } else {
          // 基因缺失：超微细浅灰圆点 (半径 0.75px)，不产生多余视觉噪音
          ctx.fillStyle = '#e2e8f0'
          ctx.beginPath()
          ctx.arc(cellX + geneColWidth / 2, rowY + rowHeight / 2, 0.75, 0, Math.PI * 2)
          ctx.fill()
        }
        cellX += geneColWidth
      }
      ctx.restore()
    }
  }

  // F. 绘制系统发育拓扑树 (矢量直线与叶节点圆点)
  if (isPhylogenyTrackVisible) {
    ctx.save()
    ctx.strokeStyle = '#475569'
    ctx.lineWidth = 1.2
    ctx.lineCap = 'round'
    for (const b of treeLayout.branches) {
      ctx.beginPath()
      ctx.moveTo(b.x1, b.y1)
      ctx.lineTo(b.x2, b.y2)
      ctx.stroke()
    }

    // 绘制叶子端点 (与当前行样本中线物理对齐)
    for (const tip of treeLayout.tips) {
      ctx.fillStyle = '#2563eb'
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 0.8
      ctx.beginPath()
      ctx.arc(tip.x, tip.y, 2.2, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
    }
    ctx.restore()
  }

  // 触发高清 PNG 下载
  canvas.toBlob(blob => {
    if (blob) {
      downloadBlob(blob, `Figure1_PanGenome_Matrix_${Date.now()}.png`)
    }
  }, 'image/png')
}

/**
 * 辅助构建 SVG 矢量 XML 文本 (高密度柱状条矢量版)
 */
function buildFigureSvg(options: ExportFigureOptions, dims: any): string {
  const {
    title,
    visibleSampleIds,
    sampleNames,
    sortedGeneClusters,
    lifestyles = [],
    treeRoot,
    sortOrder = 'cluster',
    isPhylogenyTrackVisible,
    isMetadataTrackVisible,
    isAniTrackVisible,
    isGeneMatrixTrackVisible,
    activeSimilarityMatrix
  } = options

  const {
    totalWidth,
    totalHeight,
    paddingX,
    paddingY,
    headerHeight,
    legendHeight,
    tableHeaderHeight,
    rowHeight,
    treeColWidth,
    sampleNameColWidth,
    metaColWidth,
    aniColWidth,
    geneColWidth,
    barWidth
  } = dims

  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="${totalHeight}" viewBox="0 0 ${totalWidth} ${totalHeight}">
  <rect width="100%" height="100%" fill="#ffffff" />
  <style>
    .f-title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; font-weight: bold; fill: #0f172a; }
    .f-badge { font-family: sans-serif; font-size: 10.5px; font-weight: bold; fill: #1d4ed8; }
    .f-stat { font-family: sans-serif; font-size: 10.5px; fill: #475569; }
    .f-th { font-family: sans-serif; font-size: 9.5px; font-weight: bold; fill: #64748b; }
    .f-row-name { font-family: sans-serif; font-size: 10px; font-weight: 600; fill: #334155; }
    .f-ani-txt { font-family: sans-serif; font-size: 7.5px; font-weight: bold; }
    .f-pill-txt { font-family: sans-serif; font-size: 8px; font-weight: bold; fill: #ffffff; text-anchor: middle; dominant-baseline: middle; }
  </style>
`

  // 1. 标题与副标 (计算安全偏移，杜绝盖字)
  const sortModeLabel = sortOrder === 'cluster' ? '进化聚类排序' : '自然编号排序'
  const badgeText = `${visibleSampleIds.length} 株系 · ${sortedGeneClusters.length} 基因家族 · ${sortModeLabel}`
  const titleEstimateW = title.length * 15 + 16
  const badgeWidth = badgeText.length * 8 + 20

  svg += `  <g transform="translate(${paddingX}, ${paddingY})">
    <rect x="0" y="2" width="52" height="20" rx="4" fill="#eff6ff" stroke="#bfdbfe" />
    <text x="26" y="16" text-anchor="middle" class="f-badge">Figure 1</text>
    <text x="60" y="17" class="f-title">${title}</text>
    <rect x="${60 + titleEstimateW}" y="2" width="${badgeWidth}" height="20" rx="10" fill="#f1f5f9" stroke="#e2e8f0" />
    <text x="${60 + titleEstimateW + badgeWidth / 2}" y="16" text-anchor="middle" class="f-stat">${badgeText}</text>
  </g>\n`

  // 2. 表头与行
  let curY = paddingY + headerHeight + legendHeight
  let startX = paddingX

  // 表头背景
  svg += `  <rect x="${startX}" y="${curY}" width="${totalWidth - paddingX * 2}" height="${tableHeaderHeight}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.2" />\n`

  let thX = startX
  if (isPhylogenyTrackVisible) {
    svg += `  <text x="${thX + treeColWidth / 2}" y="${curY + 17}" text-anchor="middle" class="f-th">系统发育</text>\n`
    thX += treeColWidth
  }

  svg += `  <text x="${thX + 6}" y="${curY + 17}" class="f-th">样本编号</text>\n`
  thX += sampleNameColWidth

  if (isMetadataTrackVisible) {
    svg += `  <text x="${thX + metaColWidth / 2}" y="${curY + 17}" text-anchor="middle" class="f-th">生活周期</text>\n`
    thX += metaColWidth
    svg += `  <text x="${thX + metaColWidth / 2}" y="${curY + 17}" text-anchor="middle" class="f-th">生物安全</text>\n`
    thX += metaColWidth
    svg += `  <text x="${thX + metaColWidth / 2}" y="${curY + 17}" text-anchor="middle" class="f-th">抗CRISPR</text>\n`
    thX += metaColWidth
  }

  if (isAniTrackVisible) {
    for (const colId of visibleSampleIds) {
      const sName = sampleNames[colId] || colId
      svg += `  <text x="${thX + aniColWidth / 2}" y="${curY + 17}" text-anchor="middle" class="f-ani-txt" fill="#64748b">${sName.slice(0, 2)}</text>\n`
      thX += aniColWidth
    }
  }

  if (isGeneMatrixTrackVisible) {
    svg += `  <text x="${thX + 6}" y="${curY + 17}" class="f-th" fill="#0f172a">泛基因组直系同源基因矩阵 (共 ${sortedGeneClusters.length} 基因家族)</text>\n`
  }

  curY += tableHeaderHeight

  // 3. 表体各行
  visibleSampleIds.forEach((rowId, rIdx) => {
    const rowY = curY + rIdx * rowHeight
    svg += `  <line x1="${startX}" y1="${rowY + rowHeight}" x2="${startX + totalWidth - paddingX * 2}" y2="${rowY + rowHeight}" stroke="#f1f5f9" stroke-width="1" />\n`

    let rowX = startX
    if (isPhylogenyTrackVisible) rowX += treeColWidth

    // 样本名
    svg += `  <text x="${rowX + 6}" y="${rowY + 15}" class="f-row-name">${sampleNames[rowId] || rowId}</text>\n`
    rowX += sampleNameColWidth

    // 元数据
    if (isMetadataTrackVisible) {
      const life = lifestyles.find((l: any) => l.sample_id === rowId)
      const isLytic = life?.lifestyle?.toLowerCase() === 'lytic'
      const isSafe = life?.is_safe_for_therapy !== false

      // 烈性/温和
      svg += `  <rect x="${rowX + (metaColWidth - 32) / 2}" y="${rowY + 3.5}" width="32" height="15" rx="2.5" fill="${isLytic ? '#10b981' : '#f59e0b'}" />\n`
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 14}" class="f-pill-txt">${isLytic ? '烈性' : '温和'}</text>\n`
      rowX += metaColWidth

      // 安全/警示
      svg += `  <rect x="${rowX + (metaColWidth - 32) / 2}" y="${rowY + 3.5}" width="32" height="15" rx="2.5" fill="${isSafe ? '#0284c7' : '#f43f5e'}" />\n`
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 14}" class="f-pill-txt">${isSafe ? '安全' : '警示'}</text>\n`
      rowX += metaColWidth

      // 抗 CRISPR
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 15}" text-anchor="middle" class="f-row-name">${life?.anti_crispr_count ?? 0}</text>\n`
      rowX += metaColWidth
    }

    // ANI 矩阵
    if (isAniTrackVisible) {
      visibleSampleIds.forEach(colId => {
        const aniVal = activeSimilarityMatrix?.[rowId]?.[colId] ?? (rowId === colId ? 100 : null)
        const color = getAniColor(aniVal)
        svg += `  <rect x="${rowX + 0.5}" y="${rowY + 0.5}" width="${aniColWidth - 1}" height="${rowHeight - 1}" fill="${color.bg}" />\n`
        if (aniVal !== null && aniVal !== undefined) {
          svg += `  <text x="${rowX + aniColWidth / 2}" y="${rowY + 14.5}" text-anchor="middle" class="f-ani-txt" fill="${color.text}">${aniVal >= 100 ? '100' : aniVal.toFixed(0)}</text>\n`
        }
        rowX += aniColWidth
      })
    }

    // 柱状条形码矩阵 (Barcode Strip)
    if (isGeneMatrixTrackVisible) {
      sortedGeneClusters.forEach(c => {
        const hasGene = !!c.presence_map?.[rowId]
        const barX = rowX + (geneColWidth - barWidth) / 2
        if (hasGene) {
          const varInfo = c._variantMap?.[rowId]
          const catColor = varInfo?.style?.backgroundColor || '#94a3b8'
          const barH = varInfo?.type === 'truncated' ? 10 : 17
          const barY = rowY + (rowHeight - barH) / 2

          svg += `  <rect x="${barX}" y="${barY}" width="${barWidth}" height="${barH}" rx="0.5" fill="${catColor}" />\n`
          if (varInfo?.type === 'truncated') {
            svg += `  <line x1="${barX}" y1="${barY + barH}" x2="${barX + barWidth}" y2="${barY}" stroke="#ffffff" stroke-width="0.8" />\n`
          } else if (varInfo?.type === 'extended') {
            svg += `  <rect x="${barX}" y="${barY}" width="${barWidth}" height="2.5" fill="#0f172a" />\n`
          }
        } else {
          svg += `  <circle cx="${rowX + geneColWidth / 2}" cy="${rowY + rowHeight / 2}" r="0.75" fill="#e2e8f0" />\n`
        }
        rowX += geneColWidth
      })
    }
  })

  // 4. 绘制系统发育拓扑树分支与叶节点 (SVG 矢量版)
  if (isPhylogenyTrackVisible) {
    const treeLayout = computeExportTreeLayout({
      visibleSampleIds,
      treeRoot,
      sortOrder,
      similarityMatrix: activeSimilarityMatrix,
      startX: paddingX,
      startY: curY,
      treeColWidth,
      rowHeight
    })

    // 分支直线
    for (const b of treeLayout.branches) {
      svg += `  <line x1="${b.x1.toFixed(1)}" y1="${b.y1.toFixed(1)}" x2="${b.x2.toFixed(1)}" y2="${b.y2.toFixed(1)}" stroke="#475569" stroke-width="1.2" stroke-linecap="round" />\n`
    }

    // 叶子端点圆点
    for (const tip of treeLayout.tips) {
      svg += `  <circle cx="${tip.x.toFixed(1)}" cy="${tip.y.toFixed(1)}" r="2.2" fill="#2563eb" stroke="#ffffff" stroke-width="0.8" />\n`
    }
  }

  svg += `</svg>`
  return svg
}

/**
 * 辅助圆角矩形绘制
 */
function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
  fill = true,
  stroke = false
) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
  if (fill) ctx.fill()
  if (stroke) ctx.stroke()
}

/**
 * 辅助触发 Blob 文件下载
 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
