/**
 * TreeExportBuilder.ts - 构建完整无裁切的系统发育树发表级导出 SVG
 */
import type { LayoutBounds } from './TreeLayout'
import type { PhyloTreeModel } from './TreeModel'
import { buildStarPolygonPoints, computeNiceScaleValue, type JournalThemeConfig } from './JournalTheme'
import {
  createSvgCladesGroup,
  createSvgEdgesGroup,
  createSvgNodesGroup,
  FONT_STACK,
  SVG_NS,
} from './TreeSvgRenderer'
import type { TreeVisualSettings } from '../types/phylo'

export function buildPhyloExportSvg(
  model: PhyloTreeModel,
  settings: TreeVisualSettings,
  bounds: LayoutBounds,
  theme: JournalThemeConfig,
  transformScale: number
): SVGSVGElement | null {
  if (!model.root) return null

  const pad = 28
  const vx = bounds.minX - pad
  const vy = bounds.minY - pad
  const vw = Math.max(240, Math.ceil(bounds.maxX - bounds.minX + pad * 2))
  const vh = Math.max(180, Math.ceil(bounds.maxY - bounds.minY + pad * 2 + 24))

  const exportSvg = document.createElementNS(SVG_NS, 'svg')
  exportSvg.setAttribute('xmlns', SVG_NS)
  exportSvg.setAttribute('viewBox', `${vx.toFixed(1)} ${vy.toFixed(1)} ${vw} ${vh}`)
  exportSvg.setAttribute('width', String(vw))
  exportSvg.setAttribute('height', String(vh))

  const bg = document.createElementNS(SVG_NS, 'rect')
  bg.setAttribute('x', vx.toFixed(1))
  bg.setAttribute('y', vy.toFixed(1))
  bg.setAttribute('width', String(vw))
  bg.setAttribute('height', String(vh))
  bg.setAttribute('fill', '#ffffff')
  exportSvg.appendChild(bg)

  if (settings.showCladeShading && settings.layout !== 'unrooted') {
    exportSvg.appendChild(createSvgCladesGroup(model, settings, bounds, theme))
  }
  exportSvg.appendChild(createSvgEdgesGroup(model, settings, theme))
  exportSvg.appendChild(
    createSvgNodesGroup({
      model,
      settings,
      bounds,
      theme,
      cullBox: null,
      interactive: false,
      transformScale,
      onBindClick: () => {},
    })
  )

  const footerY = vy + vh - 18
  if (settings.useBranchLengths) {
    const barPx = 84
    const distPerPx = bounds.scaleUnitsPerPx
    const unitVal = computeNiceScaleValue(barPx * distPerPx)
    const actualPx = Math.max(28, Math.min(160, unitVal / distPerPx))

    const sx = vx + 20
    const line = document.createElementNS(SVG_NS, 'line')
    line.setAttribute('x1', sx.toFixed(1))
    line.setAttribute('y1', footerY.toFixed(1))
    line.setAttribute('x2', (sx + actualPx).toFixed(1))
    line.setAttribute('y2', footerY.toFixed(1))
    line.setAttribute('stroke', '#0f172a')
    line.setAttribute('stroke-width', '1.6')
    exportSvg.appendChild(line)

    for (const tx of [sx, sx + actualPx]) {
      const tick = document.createElementNS(SVG_NS, 'line')
      tick.setAttribute('x1', tx.toFixed(1))
      tick.setAttribute('y1', (footerY - 3).toFixed(1))
      tick.setAttribute('x2', tx.toFixed(1))
      tick.setAttribute('y2', (footerY + 3).toFixed(1))
      tick.setAttribute('stroke', '#0f172a')
      tick.setAttribute('stroke-width', '1.2')
      exportSvg.appendChild(tick)
    }

    const txt = document.createElementNS(SVG_NS, 'text')
    txt.setAttribute('x', sx.toFixed(1))
    txt.setAttribute('y', (footerY - 7).toFixed(1))
    txt.setAttribute('font-size', '10')
    txt.setAttribute('font-family', FONT_STACK)
    txt.setAttribute('fill', '#334155')
    txt.textContent = `${unitVal} substitutions/site`
    exportSvg.appendChild(txt)
  }

  if (model.hasNodeMetadata || settings.highlightStrongUfboot) {
    let curX = vx + vw - 355
    const addLegendLabel = (labelStr: string) => {
      const t = document.createElementNS(SVG_NS, 'text')
      t.setAttribute('x', curX.toFixed(1))
      t.setAttribute('y', footerY.toFixed(1))
      t.setAttribute('dominant-baseline', 'middle')
      t.setAttribute('font-size', '10')
      t.setAttribute('font-family', FONT_STACK)
      t.setAttribute('fill', '#475569')
      t.textContent = labelStr
      exportSvg.appendChild(t)
      curX += labelStr.length * 5.6 + 14
    }

    const star = document.createElementNS(SVG_NS, 'polygon')
    star.setAttribute('points', buildStarPolygonPoints(curX, footerY, 5.2, 2.2))
    star.setAttribute('fill', theme.queryColor)
    exportSvg.appendChild(star)
    curX += 9
    addLegendLabel('Query')

    const ogLine = document.createElementNS(SVG_NS, 'line')
    ogLine.setAttribute('x1', curX.toFixed(1))
    ogLine.setAttribute('y1', footerY.toFixed(1))
    ogLine.setAttribute('x2', (curX + 16).toFixed(1))
    ogLine.setAttribute('y2', footerY.toFixed(1))
    ogLine.setAttribute('stroke', theme.outgroupColor)
    ogLine.setAttribute('stroke-width', '1.4')
    ogLine.setAttribute('stroke-dasharray', '3 2')
    exportSvg.appendChild(ogLine)
    curX += 20
    addLegendLabel('Outgroup')

    const strongDot = document.createElementNS(SVG_NS, 'circle')
    strongDot.setAttribute('cx', curX.toFixed(1))
    strongDot.setAttribute('cy', footerY.toFixed(1))
    strongDot.setAttribute('r', '3.8')
    strongDot.setAttribute('fill', theme.strongDotColor)
    exportSvg.appendChild(strongDot)
    curX += 8
    addLegendLabel('UFBoot >= 95%')

    const modDot = document.createElementNS(SVG_NS, 'circle')
    modDot.setAttribute('cx', curX.toFixed(1))
    modDot.setAttribute('cy', footerY.toFixed(1))
    modDot.setAttribute('r', '3.5')
    modDot.setAttribute('fill', '#ffffff')
    modDot.setAttribute('stroke', theme.moderateDotEdge)
    modDot.setAttribute('stroke-width', '1.3')
    exportSvg.appendChild(modDot)
    curX += 8
    addLegendLabel(`>= ${settings.supportThreshold}%`)
  }

  return exportSvg
}
