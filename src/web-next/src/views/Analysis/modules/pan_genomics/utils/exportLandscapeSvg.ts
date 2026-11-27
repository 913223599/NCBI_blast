/**
 * exportLandscapeSvg.ts - Figure 1 矢量 SVG 导出构建器
 */
import type { ClusteringTreeNodeLike, OrthologCluster, PhageLifestyleEntry } from '../types'
import { computeExportTreeLayout, getAniColor } from './exportLandscapeTree'

export interface ExportFigureDimensions {
  totalWidth: number
  totalHeight: number
  paddingX: number
  paddingY: number
  headerHeight: number
  legendHeight: number
  tableHeaderHeight: number
  rowHeight: number
  treeColWidth: number
  sampleNameColWidth: number
  metaColWidth: number
  aniColWidth: number
  geneColWidth: number
  barWidth: number
}

export interface ExportFigureOptions {
  title: string
  subtitle: string
  visibleSampleIds: string[]
  orderedSampleIds: string[]
  sampleNames: Record<string, string>
  sortedGeneClusters: OrthologCluster[]
  aniMatrix?: Record<string, Record<string, number | null>>
  lifestyles?: PhageLifestyleEntry[]
  treeRoot?: ClusteringTreeNodeLike | null
  sortOrder?: 'natural' | 'cluster'
  isPhylogenyTrackVisible: boolean
  isMetadataTrackVisible: boolean
  isAniTrackVisible: boolean
  isGeneMatrixTrackVisible: boolean
  activeSimilarityMatrix?: Record<string, Record<string, number | null>>
  format: 'png' | 'svg'
}

export function buildFigureSvg(options: ExportFigureOptions, dims: ExportFigureDimensions): string {
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
    barWidth,
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

  let curY = paddingY + headerHeight + legendHeight
  const startX = paddingX
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

  visibleSampleIds.forEach((rowId, rIdx) => {
    const rowY = curY + rIdx * rowHeight
    svg += `  <line x1="${startX}" y1="${rowY + rowHeight}" x2="${startX + totalWidth - paddingX * 2}" y2="${rowY + rowHeight}" stroke="#f1f5f9" stroke-width="1" />\n`

    let rowX = startX
    if (isPhylogenyTrackVisible) rowX += treeColWidth
    svg += `  <text x="${rowX + 6}" y="${rowY + 15}" class="f-row-name">${sampleNames[rowId] || rowId}</text>\n`
    rowX += sampleNameColWidth

    if (isMetadataTrackVisible) {
      const life = lifestyles.find((l: PhageLifestyleEntry) => l.sample_id === rowId)
      const isLytic = life?.lifestyle?.toLowerCase() === 'lytic'
      const isSafe = life?.is_safe_for_therapy !== false
      svg += `  <rect x="${rowX + (metaColWidth - 32) / 2}" y="${rowY + 3.5}" width="32" height="15" rx="2.5" fill="${isLytic ? '#10b981' : '#f59e0b'}" />\n`
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 14}" class="f-pill-txt">${isLytic ? '烈性' : '温和'}</text>\n`
      rowX += metaColWidth
      svg += `  <rect x="${rowX + (metaColWidth - 32) / 2}" y="${rowY + 3.5}" width="32" height="15" rx="2.5" fill="${isSafe ? '#0284c7' : '#f43f5e'}" />\n`
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 14}" class="f-pill-txt">${isSafe ? '安全' : '警示'}</text>\n`
      rowX += metaColWidth
      svg += `  <text x="${rowX + metaColWidth / 2}" y="${rowY + 15}" text-anchor="middle" class="f-row-name">${life?.anti_crispr_count ?? 0}</text>\n`
      rowX += metaColWidth
    }

    if (isAniTrackVisible) {
      visibleSampleIds.forEach((colId) => {
        const aniVal = activeSimilarityMatrix?.[rowId]?.[colId] ?? (rowId === colId ? 100 : null)
        const color = getAniColor(aniVal)
        svg += `  <rect x="${rowX + 0.5}" y="${rowY + 0.5}" width="${aniColWidth - 1}" height="${rowHeight - 1}" fill="${color.bg}" />\n`
        if (aniVal !== null && aniVal !== undefined) {
          svg += `  <text x="${rowX + aniColWidth / 2}" y="${rowY + 14.5}" text-anchor="middle" class="f-ani-txt" fill="${color.text}">${aniVal >= 100 ? '100' : aniVal.toFixed(0)}</text>\n`
        }
        rowX += aniColWidth
      })
    }

    if (isGeneMatrixTrackVisible) {
      sortedGeneClusters.forEach((c) => {
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

  if (isPhylogenyTrackVisible) {
    const treeLayout = computeExportTreeLayout({
      visibleSampleIds,
      treeRoot,
      sortOrder,
      similarityMatrix: activeSimilarityMatrix,
      startX: paddingX,
      startY: curY,
      treeColWidth,
      rowHeight,
    })
    for (const b of treeLayout.branches) {
      svg += `  <line x1="${b.x1.toFixed(1)}" y1="${b.y1.toFixed(1)}" x2="${b.x2.toFixed(1)}" y2="${b.y2.toFixed(1)}" stroke="#475569" stroke-width="1.2" stroke-linecap="round" />\n`
    }
    for (const tip of treeLayout.tips) {
      svg += `  <circle cx="${tip.x.toFixed(1)}" cy="${tip.y.toFixed(1)}" r="2.2" fill="#2563eb" stroke="#ffffff" stroke-width="0.8" />\n`
    }
  }

  svg += `</svg>`
  return svg
}
