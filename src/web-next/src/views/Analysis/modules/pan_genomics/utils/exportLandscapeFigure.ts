/**
 * exportLandscapeFigure.ts - Figure 1 系统发育与泛基因组同源矩阵整体完整导出门面
 *
 * 拓扑布局已抽离至 ./exportLandscapeTree.ts，SVG 矢量渲染已抽离至 ./exportLandscapeSvg.ts。
 */
import { FUNCTIONAL_CATEGORIES } from '../../viewer/utils/render'
import { computeExportTreeLayout, getAniColor } from './exportLandscapeTree'
import { buildFigureSvg, type ExportFigureDimensions, type ExportFigureOptions } from './exportLandscapeSvg'

export type { ExportFigureOptions }

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
  fill = true,
  stroke = false
): void {
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

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function drawTitleHeader(
  ctx: CanvasRenderingContext2D,
  options: ExportFigureOptions,
  dims: ExportFigureDimensions,
  curY: number
): void {
  const { title, visibleSampleIds, sortedGeneClusters, sortOrder = 'cluster' } = options
  const { paddingX } = dims

  ctx.save()
  ctx.fillStyle = '#eff6ff'
  ctx.strokeStyle = '#bfdbfe'
  ctx.lineWidth = 1
  roundRect(ctx, paddingX, curY + 2, 52, 20, 4, true, true)
  ctx.fillStyle = '#1d4ed8'
  ctx.font = 'bold 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('Figure 1', paddingX + 26, curY + 12)

  ctx.fillStyle = '#0f172a'
  ctx.font = 'bold 15px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.textAlign = 'left'
  const titleX = paddingX + 60
  ctx.fillText(title, titleX, curY + 12)
  const titleWidth = ctx.measureText(title).width

  const sortModeLabel = sortOrder === 'cluster' ? '进化聚类排序' : '自然编号排序'
  const badgeText = `${visibleSampleIds.length} 株系 · ${sortedGeneClusters.length} 基因家族 · ${sortModeLabel}`
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
}

function drawLegendDeck(ctx: CanvasRenderingContext2D, dims: ExportFigureDimensions, curY: number): void {
  const { paddingX, totalWidth, legendHeight } = dims
  ctx.save()
  ctx.fillStyle = '#f8fafc'
  ctx.strokeStyle = '#e2e8f0'
  ctx.lineWidth = 1
  roundRect(ctx, paddingX, curY, totalWidth - paddingX * 2, legendHeight - 6, 5, true, true)

  let legX = paddingX + 10
  const legY = curY + (legendHeight - 6) / 2
  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#475569'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('CDS 功能分类:', legX, legY)
  legX += ctx.measureText('CDS 功能分类:').width + 6

  ctx.font = '500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  for (const [, cat] of Object.entries(FUNCTIONAL_CATEGORIES)) {
    ctx.fillStyle = cat.color
    ctx.fillRect(legX, legY - 3.5, 7, 7)
    legX += 9
    ctx.fillStyle = '#334155'
    const lbl = cat.label.split(' ')[0] || ''
    ctx.fillText(lbl, legX, legY)
    legX += ctx.measureText(lbl).width + 8
  }

  legX += 12
  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#475569'
  ctx.fillText('变异形态:', legX, legY)
  legX += ctx.measureText('变异形态:').width + 6

  ctx.font = '500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  ctx.fillStyle = '#0284c7'
  roundRect(ctx, legX, legY - 6, 3.2, 12, 0.5, true, false)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('等长保守', legX, legY)
  legX += ctx.measureText('等长保守').width + 8

  ctx.fillStyle = '#f59e0b'
  roundRect(ctx, legX, legY - 3.5, 3.2, 7, 0.5, true, false)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('序列截短', legX, legY)
  legX += ctx.measureText('序列截短').width + 8

  ctx.fillStyle = '#10b981'
  roundRect(ctx, legX, legY - 6, 3.2, 12, 0.5, true, false)
  ctx.fillStyle = '#065f46'
  ctx.fillRect(legX, legY - 7.5, 3.2, 2)
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('序列延伸', legX, legY)
  legX += ctx.measureText('序列延伸').width + 8

  ctx.fillStyle = '#cbd5e1'
  ctx.beginPath()
  ctx.arc(legX + 2, legY, 1.2, 0, Math.PI * 2)
  ctx.fill()
  legX += 6
  ctx.fillStyle = '#334155'
  ctx.fillText('基因缺失', legX, legY)
  ctx.restore()
}

function drawTableHeader(
  ctx: CanvasRenderingContext2D,
  options: ExportFigureOptions,
  dims: ExportFigureDimensions,
  tableWidth: number,
  curY: number
): void {
  const {
    visibleSampleIds,
    sampleNames,
    sortedGeneClusters,
    isPhylogenyTrackVisible,
    isMetadataTrackVisible,
    isAniTrackVisible,
    isGeneMatrixTrackVisible,
  } = options
  const { paddingX, tableHeaderHeight, treeColWidth, sampleNameColWidth, metaColWidth, aniColWidth } = dims

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
  if (isPhylogenyTrackVisible) {
    ctx.textAlign = 'center'
    ctx.fillText('系统发育', thX + treeColWidth / 2, curY + tableHeaderHeight / 2)
    thX += treeColWidth
  }

  ctx.textAlign = 'left'
  ctx.fillText('样本编号', thX + 6, curY + tableHeaderHeight / 2)
  thX += sampleNameColWidth

  if (isMetadataTrackVisible) {
    ctx.textAlign = 'center'
    ctx.fillText('生活周期', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
    ctx.fillText('生物安全', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
    ctx.fillText('抗CRISPR', thX + metaColWidth / 2, curY + tableHeaderHeight / 2)
    thX += metaColWidth
  }

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
}

function drawSampleRows(
  ctx: CanvasRenderingContext2D,
  options: ExportFigureOptions,
  dims: ExportFigureDimensions,
  tableWidth: number,
  curY: number
): void {
  const {
    visibleSampleIds,
    sampleNames,
    sortedGeneClusters,
    lifestyles = [],
    isPhylogenyTrackVisible,
    isMetadataTrackVisible,
    isAniTrackVisible,
    isGeneMatrixTrackVisible,
    activeSimilarityMatrix,
  } = options
  const { paddingX, rowHeight, treeColWidth, sampleNameColWidth, metaColWidth, aniColWidth, geneColWidth, barWidth } =
    dims

  for (let rIdx = 0; rIdx < visibleSampleIds.length; rIdx++) {
    const rowId = visibleSampleIds[rIdx]
    if (!rowId) continue
    const rowY = curY + rIdx * rowHeight

    ctx.strokeStyle = '#f1f5f9'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(paddingX, rowY + rowHeight)
    ctx.lineTo(paddingX + tableWidth, rowY + rowHeight)
    ctx.stroke()

    let cellX = paddingX + (isPhylogenyTrackVisible ? treeColWidth : 0)

    ctx.save()
    ctx.font = '600 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    ctx.fillStyle = '#334155'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(sampleNames[rowId] || rowId, cellX + 6, rowY + rowHeight / 2)
    cellX += sampleNameColWidth
    ctx.restore()

    if (isMetadataTrackVisible) {
      const lifeInfo = lifestyles.find((l) => l.sample_id === rowId)
      const isLytic = lifeInfo?.lifestyle?.toLowerCase() === 'lytic'
      const isSafe = lifeInfo?.is_safe_for_therapy !== false

      ctx.save()
      ctx.fillStyle = isLytic ? '#10b981' : '#f59e0b'
      roundRect(ctx, cellX + (metaColWidth - 32) / 2, rowY + (rowHeight - 15) / 2, 32, 15, 2.5, true, false)
      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 8px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(isLytic ? '烈性' : '温和', cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth

      ctx.fillStyle = isSafe ? '#0284c7' : '#f43f5e'
      roundRect(ctx, cellX + (metaColWidth - 32) / 2, rowY + (rowHeight - 15) / 2, 32, 15, 2.5, true, false)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(isSafe ? '安全' : '警示', cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth

      ctx.fillStyle = '#334155'
      ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      ctx.fillText(String(lifeInfo?.anti_crispr_count ?? 0), cellX + metaColWidth / 2, rowY + rowHeight / 2)
      cellX += metaColWidth
      ctx.restore()
    }

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

    if (isGeneMatrixTrackVisible) {
      ctx.save()
      for (const cluster of sortedGeneClusters) {
        const item = cluster.presence_map?.[rowId]
        const barX = cellX + (geneColWidth - barWidth) / 2
        if (item) {
          const varInfo = cluster._variantMap?.[rowId]
          const catColor = varInfo?.style?.backgroundColor || '#94a3b8'
          if (varInfo?.type === 'truncated') {
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
          } else {
            const barH = 17
            const barY = rowY + (rowHeight - barH) / 2
            ctx.fillStyle = catColor
            roundRect(ctx, barX, barY, barWidth, barH, 0.5, true, false)
            if (varInfo?.type === 'extended') {
              ctx.fillStyle = '#0f172a'
              ctx.fillRect(barX, barY, barWidth, 2.5)
            }
          }
        } else {
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
}

/**
 * 完整导出 Figure 1 图表 (高密度柱状条形码模式)
 */
export async function exportCompleteFigure(options: ExportFigureOptions): Promise<void> {
  const sampleCount = options.visibleSampleIds.length
  if (sampleCount === 0) return

  const paddingX = 16
  const paddingY = 16
  const headerHeight = 36
  const legendHeight = 38
  const tableHeaderHeight = 26
  const rowHeight = 22
  const treeColWidth = options.isPhylogenyTrackVisible ? 60 : 0
  const sampleNameColWidth = 140
  const metaColWidth = options.isMetadataTrackVisible ? 52 : 0
  const totalMetaWidth = options.isMetadataTrackVisible ? metaColWidth * 3 : 0
  const aniColWidth = 22
  const totalAniWidth = options.isAniTrackVisible ? aniColWidth * sampleCount : 0
  const geneColWidth = 4.2
  const barWidth = 3.0
  const totalGeneWidth = options.isGeneMatrixTrackVisible ? geneColWidth * options.sortedGeneClusters.length : 0

  const tableWidth = treeColWidth + sampleNameColWidth + totalMetaWidth + totalAniWidth + totalGeneWidth
  const totalWidth = Math.max(960, Math.round(paddingX * 2 + tableWidth))
  const totalHeight = Math.round(paddingY * 2 + headerHeight + legendHeight + tableHeaderHeight + rowHeight * sampleCount)

  const dims: ExportFigureDimensions = {
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
    barWidth,
  }

  if (options.format === 'svg') {
    const svgString = buildFigureSvg(options, dims)
    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
    downloadBlob(blob, `Figure1_PanGenome_Matrix_${Date.now()}.svg`)
    return
  }

  const scale = 2.0
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(totalWidth * scale)
  canvas.height = Math.round(totalHeight * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.scale(scale, scale)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, totalWidth, totalHeight)

  let curY = paddingY
  drawTitleHeader(ctx, options, dims, curY)
  curY += headerHeight
  drawLegendDeck(ctx, dims, curY)
  curY += legendHeight
  drawTableHeader(ctx, options, dims, tableWidth, curY)
  curY += tableHeaderHeight

  const treeLayout = options.isPhylogenyTrackVisible
    ? computeExportTreeLayout({
        visibleSampleIds: options.visibleSampleIds,
        treeRoot: options.treeRoot,
        sortOrder: options.sortOrder,
        similarityMatrix: options.activeSimilarityMatrix,
        startX: paddingX,
        startY: curY,
        treeColWidth,
        rowHeight,
      })
    : { branches: [], tips: [] }

  drawSampleRows(ctx, options, dims, tableWidth, curY)

  if (options.isPhylogenyTrackVisible) {
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

  canvas.toBlob((blob) => {
    if (blob) {
      downloadBlob(blob, `Figure1_PanGenome_Matrix_${Date.now()}.png`)
    }
  }, 'image/png')
}
