/**
 * TreeSvgRenderer.ts - 系统发育树 SVG 矢量元素渲染器
 * 承载单系阴影环/矩形块、矢量枝干、节点支持率圆点、物种斜体标签与元数据条带。
 */
import type { LayoutBounds } from './TreeLayout'
import { formatNodeDisplayLabel, type PhyloTreeModel, type PhyloTreeNode } from './TreeModel'
import {
  buildStarPolygonPoints,
  detectMonophyleticClades,
  getHostPhylumColor,
  isFormalTaxonName,
  mapHostToPhylum,
  splitTaxonomicLabelSegments,
  type JournalThemeConfig,
} from './JournalTheme'
import type { TreeVisualSettings } from '../types/phylo'

export const SVG_NS = 'http://www.w3.org/2000/svg'
export const FONT_STACK = 'Arial, Helvetica, "Microsoft YaHei", sans-serif'

export interface WorldBox {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

export function createAnnularSectorPath(
  rIn: number,
  rOut: number,
  startAng: number,
  endAng: number
): string {
  const largeArc = Math.abs(endAng - startAng) > Math.PI ? 1 : 0
  const x1 = rIn * Math.cos(startAng)
  const y1 = rIn * Math.sin(startAng)
  const x2 = rOut * Math.cos(startAng)
  const y2 = rOut * Math.sin(startAng)
  const x3 = rOut * Math.cos(endAng)
  const y3 = rOut * Math.sin(endAng)
  const x4 = rIn * Math.cos(endAng)
  const y4 = rIn * Math.sin(endAng)
  return [
    `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    `L ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    `A ${rOut.toFixed(2)} ${rOut.toFixed(2)} 0 ${largeArc} 1 ${x3.toFixed(2)} ${y3.toFixed(2)}`,
    `L ${x4.toFixed(2)} ${y4.toFixed(2)}`,
    `A ${rIn.toFixed(2)} ${rIn.toFixed(2)} 0 ${largeArc} 0 ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    'Z',
  ].join(' ')
}

export function resolveEdgeStroke(
  node: PhyloTreeNode,
  theme: JournalThemeConfig
): { color: string; width: number; dashed: boolean } {
  if (node.cladeColor) {
    return { color: node.cladeColor, width: 1.7, dashed: false }
  }
  if (node.isLeaf) {
    const role = node.meta?.role
    if (role === 'query') return { color: theme.queryColor, width: 1.9, dashed: false }
    if (role === 'outgroup') return { color: theme.outgroupColor, width: 1.25, dashed: true }
  }
  return { color: theme.backboneColor, width: 1.3, dashed: false }
}

export function computeCircularLabelSpan(model: PhyloTreeModel, settings: TreeVisualSettings): number {
  if (!settings.showLabels) return 18
  if (settings.smartLabelCull && model.leaves.length > 90) {
    return 20
  }
  let maxChars = 10
  for (const lf of model.leaves) {
    const len = formatNodeDisplayLabel(lf, settings.labelFormat).length
    if (len > maxChars) maxChars = len
  }
  return Math.min(280, Math.max(85, Math.ceil(maxChars * settings.fontSize * 0.54)))
}

export function createSvgCladesGroup(
  model: PhyloTreeModel,
  settings: TreeVisualSettings,
  bounds: LayoutBounds | null,
  theme: JournalThemeConfig
): SVGGElement {
  const cladeGroup = document.createElementNS(SVG_NS, 'g')
  cladeGroup.setAttribute('class', 'phylo-clades')
  if (!model.root || !bounds || !model.hasNodeMetadata) return cladeGroup

  const allClades = detectMonophyleticClades(model.root, model.leaves, model.genusColors)
  const hasAnyQuery = model.leaves.some((lf) => lf.meta?.role === 'query')
  const clades = hasAnyQuery ? allClades.filter((c) => c.containsQuery) : allClades
  if (clades.length === 0) return cladeGroup

  if (settings.layout === 'rect') {
    const rowStep = Math.max(12, settings.rowSpacing)
    const rightX = (bounds.labelEndX || bounds.maxX) - 6
    for (const cl of clades) {
      const firstLeaf = model.leaves[cl.leafStartIdx]
      const lastLeaf = model.leaves[cl.leafEndIdx]
      if (!firstLeaf || !lastLeaf) continue
      const xLeft = Math.max(0, cl.node.x - 4)
      const yTop = firstLeaf.y - rowStep * 0.44
      const yBot = lastLeaf.y + rowStep * 0.44
      const rect = document.createElementNS(SVG_NS, 'rect')
      rect.setAttribute('x', xLeft.toFixed(1))
      rect.setAttribute('y', yTop.toFixed(1))
      rect.setAttribute('width', Math.max(16, rightX - xLeft).toFixed(1))
      rect.setAttribute('height', Math.max(8, yBot - yTop).toFixed(1))
      rect.setAttribute('rx', '4')
      rect.setAttribute('fill', cl.color)
      rect.setAttribute('fill-opacity', String(theme.cladeOpacity))
      cladeGroup.appendChild(rect)

      if (!settings.showMetadataStrips) {
        const bx = rightX + 10
        const bracket = document.createElementNS(SVG_NS, 'line')
        bracket.setAttribute('x1', bx.toFixed(1))
        bracket.setAttribute('y1', (yTop + 2).toFixed(1))
        bracket.setAttribute('x2', bx.toFixed(1))
        bracket.setAttribute('y2', (yBot - 2).toFixed(1))
        bracket.setAttribute('stroke', cl.color)
        bracket.setAttribute('stroke-width', '2')
        cladeGroup.appendChild(bracket)

        const bTxt = document.createElementNS(SVG_NS, 'text')
        bTxt.setAttribute('x', (bx + 6).toFixed(1))
        bTxt.setAttribute('y', ((yTop + yBot) * 0.5).toFixed(1))
        bTxt.setAttribute('dominant-baseline', 'middle')
        bTxt.setAttribute('font-family', FONT_STACK)
        bTxt.setAttribute('font-size', `${Math.max(10, settings.fontSize - 1)}`)
        bTxt.setAttribute('font-weight', '700')
        if (isFormalTaxonName(cl.taxonName)) bTxt.setAttribute('font-style', 'italic')
        bTxt.setAttribute('fill', cl.color)
        bTxt.textContent = cl.taxonName
        cladeGroup.appendChild(bTxt)
      }
    }
  } else if (settings.layout === 'circular') {
    const nLeaves = Math.max(1, model.leaves.length)
    const halfStep = ((Math.PI * 1.92) / nLeaves) * 0.46
    const outerR = (bounds.outerRadius || 240) + computeCircularLabelSpan(model, settings) + 6

    if (settings.useBranchLengths && nLeaves > 24 && bounds.outerRadius) {
      for (const frac of [0.33, 0.67]) {
        const rRing = bounds.outerRadius * frac
        const ringCircle = document.createElementNS(SVG_NS, 'circle')
        ringCircle.setAttribute('cx', '0')
        ringCircle.setAttribute('cy', '0')
        ringCircle.setAttribute('r', rRing.toFixed(1))
        ringCircle.setAttribute('fill', 'none')
        ringCircle.setAttribute('stroke', '#e2e8f0')
        ringCircle.setAttribute('stroke-width', '0.8')
        ringCircle.setAttribute('stroke-dasharray', '4 4')
        cladeGroup.appendChild(ringCircle)
      }
    }

    for (const cl of clades) {
      const firstLeaf = model.leaves[cl.leafStartIdx]
      const lastLeaf = model.leaves[cl.leafEndIdx]
      if (!firstLeaf || !lastLeaf) continue
      const rIn = Math.max(10, cl.node.radius - 6)
      const a1 = firstLeaf.angle - halfStep
      const a2 = lastLeaf.angle + halfStep
      if (a2 > a1 && outerR > rIn) {
        const path = document.createElementNS(SVG_NS, 'path')
        path.setAttribute('d', createAnnularSectorPath(rIn, outerR, a1, a2))
        path.setAttribute('fill', cl.color)
        path.setAttribute('fill-opacity', String(theme.cladeOpacity))
        cladeGroup.appendChild(path)
      }
    }
  }

  return cladeGroup
}

export function createSvgEdgesGroup(
  model: PhyloTreeModel,
  settings: TreeVisualSettings,
  theme: JournalThemeConfig
): SVGGElement {
  const edgeGroup = document.createElementNS(SVG_NS, 'g')
  edgeGroup.setAttribute('class', 'phylo-edges')
  if (!model.root) return edgeGroup

  const walk = (node: PhyloTreeNode) => {
    if (node.collapsed) return
    for (const ch of node.children) {
      const path = document.createElementNS(SVG_NS, 'path')
      let d = ''
      if (settings.layout === 'rect') {
        d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} L ${node.x.toFixed(2)} ${ch.y.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
      } else if (settings.layout === 'circular') {
        const r = node.radius
        const x1 = r * Math.cos(ch.angle)
        const y1 = r * Math.sin(ch.angle)
        const sweep = ch.angle >= node.angle ? 1 : 0
        const largeArc = Math.abs(ch.angle - node.angle) > Math.PI ? 1 : 0
        d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} A ${r.toFixed(2)} ${r.toFixed(2)} 0 ${largeArc} ${sweep} ${x1.toFixed(2)} ${y1.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
      } else {
        d = `M ${node.x.toFixed(2)} ${node.y.toFixed(2)} L ${ch.x.toFixed(2)} ${ch.y.toFixed(2)}`
      }
      const style = resolveEdgeStroke(ch, theme)
      path.setAttribute('d', d)
      path.setAttribute('fill', 'none')
      path.setAttribute('stroke', style.color)
      path.setAttribute('stroke-width', style.width.toFixed(2))
      path.setAttribute('stroke-linecap', 'round')
      if (style.dashed) {
        path.setAttribute('stroke-dasharray', '4 3')
      }
      edgeGroup.appendChild(path)
      walk(ch)
    }
  }
  walk(model.root)
  return edgeGroup
}

function appendStyledLabelText(
  labelEl: SVGTextElement,
  displayText: string,
  italicize: boolean,
  isOutgroup: boolean
): void {
  if (!italicize || isOutgroup) {
    labelEl.textContent = displayText
    if (isOutgroup) labelEl.setAttribute('font-style', 'italic')
    return
  }
  const segments = splitTaxonomicLabelSegments(displayText)
  if (segments.length === 1 && !segments[0]?.italic) {
    labelEl.textContent = displayText
    return
  }
  for (const seg of segments) {
    const tspan = document.createElementNS(SVG_NS, 'tspan')
    tspan.textContent = seg.text
    if (seg.italic) tspan.setAttribute('font-style', 'italic')
    labelEl.appendChild(tspan)
  }
}

function appendMetadataHeaders(
  frag: DocumentFragment,
  model: PhyloTreeModel,
  settings: TreeVisualSettings,
  bounds: LayoutBounds | null,
  theme: JournalThemeConfig,
  circRingR: number
): void {
  if (settings.layout === 'rect' && settings.showMetadataStrips && model.hasNodeMetadata && bounds?.labelEndX) {
    const stripX = bounds.labelEndX + 8
    const headerY = -12
    const addHeader = (x: number, text: string, color: string) => {
      const h = document.createElementNS(SVG_NS, 'text')
      h.setAttribute('x', x.toFixed(1))
      h.setAttribute('y', headerY.toFixed(1))
      h.setAttribute('font-size', '10')
      h.setAttribute('font-weight', '700')
      h.setAttribute('font-family', FONT_STACK)
      h.setAttribute('fill', color)
      h.textContent = text
      frag.appendChild(h)
    }
    addHeader(stripX, 'Genus', '#0f172a')
    let sizeStart = stripX + 118
    if (model.hasHostMetadata) {
      addHeader(stripX + 114, 'Host', '#334155')
      sizeStart = stripX + 156
    }
    if (model.maxGenomeLength > 0) {
      addHeader(sizeStart, 'Size (kb)', theme.sizeBarColor)
    }
  }

  if (settings.layout === 'circular' && settings.showMetadataStrips && model.hasNodeMetadata) {
    const addRingTag = (rMid: number, text: string, color: string) => {
      const t = document.createElementNS(SVG_NS, 'text')
      t.setAttribute('x', rMid.toFixed(1))
      t.setAttribute('y', '-8')
      t.setAttribute('text-anchor', 'middle')
      t.setAttribute('font-size', '9')
      t.setAttribute('font-weight', '700')
      t.setAttribute('font-family', FONT_STACK)
      t.setAttribute('fill', color)
      t.textContent = text
      frag.appendChild(t)
    }
    addRingTag(circRingR + 8, 'Genus', '#0f172a')
    if (model.hasHostMetadata) {
      addRingTag(circRingR + 27, 'Host', '#334155')
    }
  }
}

function appendRectMetadataStrips(
  frag: DocumentFragment,
  node: PhyloTreeNode,
  model: PhyloTreeModel,
  settings: TreeVisualSettings,
  bounds: LayoutBounds,
  theme: JournalThemeConfig,
  genusColor: string | null
): void {
  const role = node.meta?.role
  const stripX = (bounds.labelEndX || 0) + 8
  const rowH = Math.max(10, Math.min(18, settings.rowSpacing * 0.68))
  const stripColor =
    role === 'query'
      ? theme.queryColor
      : role === 'outgroup'
        ? theme.outgroupColor
        : genusColor ||
          (node.meta?.genus && model.otherGenera.has(node.meta.genus) ? '#94a3b8' : theme.unclassifiedColor)

  const swatch = document.createElementNS(SVG_NS, 'rect')
  swatch.setAttribute('x', stripX.toFixed(1))
  swatch.setAttribute('y', (node.y - rowH * 0.5).toFixed(1))
  swatch.setAttribute('width', '12')
  swatch.setAttribute('height', rowH.toFixed(1))
  swatch.setAttribute('rx', '2')
  swatch.setAttribute('fill', stripColor)
  frag.appendChild(swatch)

  const gTxt = document.createElementNS(SVG_NS, 'text')
  const genusStr =
    role === 'query' ? 'Query' : role === 'outgroup' ? 'Outgroup' : node.meta?.genus || 'Unclassified'
  gTxt.textContent = genusStr.length > 15 ? `${genusStr.slice(0, 14)}..` : genusStr
  gTxt.setAttribute('x', (stripX + 17).toFixed(1))
  gTxt.setAttribute('y', node.y.toFixed(2))
  gTxt.setAttribute('dominant-baseline', 'middle')
  gTxt.setAttribute('font-size', `${Math.max(9, settings.fontSize - 2)}`)
  gTxt.setAttribute('font-family', FONT_STACK)
  if (isFormalTaxonName(genusStr)) gTxt.setAttribute('font-style', 'italic')
  gTxt.setAttribute('fill', '#475569')
  frag.appendChild(gTxt)

  let barStart = stripX + 118
  if (model.hasHostMetadata) {
    const phylum = mapHostToPhylum(node.meta?.host)
    const hostSwatch = document.createElementNS(SVG_NS, 'rect')
    hostSwatch.setAttribute('x', (stripX + 114).toFixed(1))
    hostSwatch.setAttribute('y', (node.y - rowH * 0.5).toFixed(1))
    hostSwatch.setAttribute('width', '26')
    hostSwatch.setAttribute('height', rowH.toFixed(1))
    hostSwatch.setAttribute('rx', '2')
    hostSwatch.setAttribute('fill', phylum ? getHostPhylumColor(phylum, theme.id) : '#f1f5f9')
    frag.appendChild(hostSwatch)
    barStart = stripX + 156
  }

  const gLen = node.meta?.genome_length || 0
  if (gLen > 0 && model.maxGenomeLength > 0) {
    const barMaxW = 68
    const trackBg = document.createElementNS(SVG_NS, 'rect')
    trackBg.setAttribute('x', barStart.toFixed(1))
    trackBg.setAttribute('y', (node.y - rowH * 0.34).toFixed(1))
    trackBg.setAttribute('width', String(barMaxW))
    trackBg.setAttribute('height', (rowH * 0.68).toFixed(1))
    trackBg.setAttribute('rx', '2')
    trackBg.setAttribute('fill', '#f1f5f9')
    frag.appendChild(trackBg)

    const barW = Math.max(4, (gLen / model.maxGenomeLength) * barMaxW)
    const barRect = document.createElementNS(SVG_NS, 'rect')
    barRect.setAttribute('x', barStart.toFixed(1))
    barRect.setAttribute('y', (node.y - rowH * 0.34).toFixed(1))
    barRect.setAttribute('width', barW.toFixed(1))
    barRect.setAttribute('height', (rowH * 0.68).toFixed(1))
    barRect.setAttribute('rx', '2')
    barRect.setAttribute('fill', theme.sizeBarColor)
    barRect.setAttribute('opacity', '0.88')
    frag.appendChild(barRect)

    const kbTxt = document.createElementNS(SVG_NS, 'text')
    kbTxt.textContent = `${(gLen / 1000).toFixed(1)}`
    kbTxt.setAttribute('x', (barStart + barMaxW + 5).toFixed(1))
    kbTxt.setAttribute('y', node.y.toFixed(2))
    kbTxt.setAttribute('dominant-baseline', 'middle')
    kbTxt.setAttribute('font-size', `${Math.max(8, settings.fontSize - 3)}`)
    kbTxt.setAttribute('font-family', FONT_STACK)
    kbTxt.setAttribute('fill', '#64748b')
    frag.appendChild(kbTxt)
  }
}

export interface SvgNodesRenderOptions {
  model: PhyloTreeModel
  settings: TreeVisualSettings
  bounds: LayoutBounds | null
  theme: JournalThemeConfig
  cullBox: WorldBox | null
  interactive: boolean
  transformScale: number
  onBindClick: (el: SVGElement, node: PhyloTreeNode) => void
}

export function createSvgNodesGroup(opts: SvgNodesRenderOptions): SVGGElement {
  const { model, settings, bounds, theme, cullBox, interactive, transformScale, onBindClick } = opts
  const group = document.createElementNS(SVG_NS, 'g')
  group.setAttribute('class', 'phylo-nodes')
  if (!model.root) return group

  const query = (settings.searchQuery || '').trim().toLowerCase()
  const frag = document.createDocumentFragment()
  const inViewport = (x: number, y: number): boolean =>
    !cullBox || (x >= cullBox.minX && x <= cullBox.maxX && y >= cullBox.minY && y <= cullBox.maxY)

  const isCircular = settings.layout === 'circular'
  const isMacroCircular = isCircular && Boolean(settings.smartLabelCull) && model.leaves.length > 90
  const hideBgCircularLabels = isMacroCircular && (!interactive || transformScale < 2.2)
  const circOuterR = bounds?.outerRadius || 240
  const circLabelSpan = isCircular ? computeCircularLabelSpan(model, settings) : 0
  const circRingR = circOuterR + (isMacroCircular ? 12 : 16 + circLabelSpan)
  const circHalfAng = ((Math.PI * 1.92) / Math.max(1, model.leaves.length)) * (model.leaves.length > 100 ? 0.5 : 0.44)

  appendMetadataHeaders(frag, model, settings, bounds, theme, circRingR)

  const walk = (node: PhyloTreeNode) => {
    const isTerminal = node.isLeaf || node.collapsed
    const displayText = node.isLeaf ? formatNodeDisplayLabel(node, settings.labelFormat) : node.name
    const isMatch = Boolean(
      query && (node.name.toLowerCase().includes(query) || displayText.toLowerCase().includes(query))
    )
    const visible = isMatch || inViewport(node.x, node.y)

    if (visible && node.collapsed) {
      const tri = document.createElementNS(SVG_NS, 'polygon')
      const s = 9
      tri.setAttribute('points', `${node.x},${node.y} ${node.x + s * 1.6},${node.y - s} ${node.x + s * 1.6},${node.y + s}`)
      tri.setAttribute('fill', node.cladeColor || theme.taxonColors[0]!)
      tri.setAttribute('opacity', '0.85')
      onBindClick(tri, node)
      frag.appendChild(tri)
    }

    if (visible && !isTerminal && node.parent) {
      const ufVal = node.ufboot ?? node.support
      const isStrongUf = Boolean(settings.highlightStrongUfboot && ufVal !== null && ufVal >= 95)
      const isModerateUf = Boolean(ufVal !== null && ufVal >= settings.supportThreshold && !isStrongUf)
      if (isStrongUf || isModerateUf) {
        const dot = document.createElementNS(SVG_NS, 'circle')
        dot.setAttribute('cx', node.x.toFixed(2))
        dot.setAttribute('cy', node.y.toFixed(2))
        dot.setAttribute('r', isStrongUf ? '4.1' : '3.6')
        dot.setAttribute('fill', isStrongUf ? theme.strongDotColor : '#ffffff')
        dot.setAttribute('stroke', isStrongUf ? '#ffffff' : theme.moderateDotEdge)
        dot.setAttribute('stroke-width', isStrongUf ? '0.9' : '1.4')
        onBindClick(dot, node)
        frag.appendChild(dot)
      } else if (interactive) {
        const hit = document.createElementNS(SVG_NS, 'circle')
        hit.setAttribute('cx', node.x.toFixed(2))
        hit.setAttribute('cy', node.y.toFixed(2))
        hit.setAttribute('r', '5')
        hit.setAttribute('fill', 'transparent')
        onBindClick(hit, node)
        frag.appendChild(hit)
      }

      if (settings.showSupport && ufVal !== null && ufVal >= settings.supportThreshold) {
        const isRad = settings.layout === 'circular' || settings.layout === 'unrooted'
        if (!isRad || node.radius > 16 || ufVal >= 95) {
          const supTxt = document.createElementNS(SVG_NS, 'text')
          supTxt.setAttribute('x', (isRad ? node.x : node.x - 6).toFixed(2))
          supTxt.setAttribute('y', (node.y - (isRad ? 6 : 5)).toFixed(2))
          supTxt.setAttribute('text-anchor', isRad ? 'middle' : 'end')
          supTxt.setAttribute('font-size', `${Math.max(isRad ? 7 : 8, settings.fontSize - (isRad ? 4 : 3))}`)
          supTxt.setAttribute('font-family', FONT_STACK)
          supTxt.setAttribute('fill', isStrongUf ? '#0f172a' : '#475569')
          if (isStrongUf) supTxt.setAttribute('font-weight', '700')
          supTxt.textContent = node.supportLabel || String(Math.round(ufVal))
          frag.appendChild(supTxt)
        }
      }
    }

    if (visible && isTerminal) {
      const role = node.meta?.role
      const genusColor = node.meta?.genus && model.genusColors.get(node.meta.genus) ? model.genusColors.get(node.meta.genus)! : null
      const labelFill =
        role === 'query' ? theme.queryTextColor : role === 'outgroup' ? '#475569' : node.cladeColor || '#0f172a'

      if (role === 'query' && !isMatch) {
        const star = document.createElementNS(SVG_NS, 'polygon')
        star.setAttribute('points', buildStarPolygonPoints(node.x, node.y, 6.2, 2.7))
        star.setAttribute('fill', theme.queryColor)
        star.setAttribute('stroke', '#ffffff')
        star.setAttribute('stroke-width', '0.8')
        onBindClick(star, node)
        frag.appendChild(star)
      } else if (isMatch) {
        const tip = document.createElementNS(SVG_NS, 'circle')
        tip.setAttribute('cx', node.x.toFixed(2))
        tip.setAttribute('cy', node.y.toFixed(2))
        tip.setAttribute('r', '5')
        tip.setAttribute('fill', '#ef4444')
        onBindClick(tip, node)
        frag.appendChild(tip)
      } else if (interactive) {
        const hitTip = document.createElementNS(SVG_NS, 'circle')
        hitTip.setAttribute('cx', node.x.toFixed(2))
        hitTip.setAttribute('cy', node.y.toFixed(2))
        hitTip.setAttribute('r', '4')
        hitTip.setAttribute('fill', 'transparent')
        onBindClick(hitTip, node)
        frag.appendChild(hitTip)
      }

      if (settings.showLabels && (!hideBgCircularLabels || role === 'query' || isMatch)) {
        const label = document.createElementNS(SVG_NS, 'text')
        const rawLabel = node.collapsed ? `[折叠支系: ${node.leafCount} 条]` : displayText
        appendStyledLabelText(label, rawLabel, Boolean(settings.italicizeTaxa) && !node.collapsed, role === 'outgroup')
        label.setAttribute('font-size', `${settings.fontSize}`)
        label.setAttribute('font-family', FONT_STACK)
        label.setAttribute('fill', isMatch ? '#dc2626' : labelFill)
        if (isMatch || role === 'query') label.setAttribute('font-weight', '700')

        if (settings.layout === 'circular' || settings.layout === 'unrooted') {
          const deg = ((node.angle * 180) / Math.PI + 360) % 360
          const flip = deg > 90 && deg < 270
          const useAlignedR =
            isCircular &&
            settings.alignTipLabels &&
            settings.useBranchLengths &&
            !node.collapsed &&
            bounds?.outerRadius !== undefined
          const macroCalloutR =
            isMacroCircular && hideBgCircularLabels
              ? circRingR + (model.hasHostMetadata && settings.showMetadataStrips ? 44 : 24)
              : null
          const anchorR = macroCalloutR ?? (useAlignedR ? bounds!.outerRadius! : node.radius)
          if ((useAlignedR || macroCalloutR !== null) && node.radius < anchorR - 1) {
            const guide = document.createElementNS(SVG_NS, 'line')
            guide.setAttribute('x1', node.x.toFixed(2))
            guide.setAttribute('y1', node.y.toFixed(2))
            guide.setAttribute('x2', (anchorR * Math.cos(node.angle)).toFixed(2))
            guide.setAttribute('y2', (anchorR * Math.sin(node.angle)).toFixed(2))
            guide.setAttribute('stroke', role === 'query' ? theme.queryColor : '#cbd5e1')
            guide.setAttribute('stroke-width', role === 'query' ? '1.1' : '0.85')
            guide.setAttribute('stroke-dasharray', role === 'query' ? '3 2' : '2 2.5')
            frag.appendChild(guide)
          }
          const offset = node.collapsed ? 22 : 10
          const lx =
            settings.layout === 'circular'
              ? (anchorR + offset) * Math.cos(node.angle)
              : node.x + offset * Math.cos(node.angle)
          const ly =
            settings.layout === 'circular'
              ? (anchorR + offset) * Math.sin(node.angle)
              : node.y + offset * Math.sin(node.angle)
          label.setAttribute('x', lx.toFixed(2))
          label.setAttribute('y', ly.toFixed(2))
          label.setAttribute('dominant-baseline', 'middle')
          label.setAttribute('text-anchor', flip ? 'end' : 'start')
          label.setAttribute('transform', `rotate(${(flip ? deg - 180 : deg).toFixed(2)}, ${lx.toFixed(2)}, ${ly.toFixed(2)})`)
        } else {
          const useAlignedX =
            settings.alignTipLabels && settings.useBranchLengths && !node.collapsed && bounds?.tipAlignX !== undefined
          const anchorX = useAlignedX ? bounds!.tipAlignX! : node.x
          if (useAlignedX && node.x < anchorX - 1) {
            const guide = document.createElementNS(SVG_NS, 'line')
            guide.setAttribute('x1', node.x.toFixed(2))
            guide.setAttribute('y1', node.y.toFixed(2))
            guide.setAttribute('x2', (anchorX + 5).toFixed(2))
            guide.setAttribute('y2', node.y.toFixed(2))
            guide.setAttribute('stroke', '#cbd5e1')
            guide.setAttribute('stroke-width', '0.85')
            guide.setAttribute('stroke-dasharray', '2 2.5')
            frag.appendChild(guide)
          }
          label.setAttribute('x', (anchorX + (node.collapsed ? 22 : 10)).toFixed(2))
          label.setAttribute('y', node.y.toFixed(2))
          label.setAttribute('dominant-baseline', 'middle')

          if (settings.showMetadataStrips && model.hasNodeMetadata && !node.collapsed && bounds?.labelEndX) {
            appendRectMetadataStrips(frag, node, model, settings, bounds, theme, genusColor)
          }
        }
        onBindClick(label, node)
        frag.appendChild(label)
      }

      if (isCircular && settings.showMetadataStrips && model.hasNodeMetadata && !node.collapsed) {
        const gCol =
          role === 'query'
            ? theme.queryColor
            : role === 'outgroup'
              ? theme.outgroupColor
              : genusColor ||
                (node.meta?.genus && model.otherGenera.has(node.meta.genus) ? '#94a3b8' : theme.unclassifiedColor)
        const gPath = document.createElementNS(SVG_NS, 'path')
        gPath.setAttribute('d', createAnnularSectorPath(circRingR, circRingR + 15, node.angle - circHalfAng, node.angle + circHalfAng))
        gPath.setAttribute('fill', gCol)
        if (model.leaves.length <= 100) {
          gPath.setAttribute('stroke', '#ffffff')
          gPath.setAttribute('stroke-width', '0.6')
        }
        frag.appendChild(gPath)

        if (model.hasHostMetadata) {
          const phylum = mapHostToPhylum(node.meta?.host)
          const hPath = document.createElementNS(SVG_NS, 'path')
          hPath.setAttribute(
            'd',
            createAnnularSectorPath(circRingR + 19, circRingR + 33, node.angle - circHalfAng, node.angle + circHalfAng)
          )
          hPath.setAttribute('fill', phylum ? getHostPhylumColor(phylum, theme.id) : '#f1f5f9')
          if (model.leaves.length <= 100) {
            hPath.setAttribute('stroke', '#ffffff')
            hPath.setAttribute('stroke-width', '0.6')
          }
          frag.appendChild(hPath)
        }
      }
    }

    if (!node.collapsed) {
      for (const ch of node.children) walk(ch)
    }
  }

  walk(model.root)
  group.appendChild(frag)
  return group
}
