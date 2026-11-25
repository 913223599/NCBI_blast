import type { JournalPaletteType, LabelFormatType, NodeMetadata, SortMode } from '../types/phylo'
import { buildTopGenusColorMap, JOURNAL_THEMES, mapHostToPhylum } from './JournalTheme'

const REDUNDANT_DESC_SUFFIX_RE =
  /(?:,\s*(?:complete|partial)\s+(?:genome|cds|sequence)|\b(?:complete|partial)\s+(?:genome|cds|sequence))\s*\.?$/i

export function cleanPhageDescription(desc?: string): string {
  const txt = (desc || '').replace(/\s+/g, ' ').trim()
  if (!txt) return ''
  return txt.replace(REDUNDANT_DESC_SUFFIX_RE, '').replace(/[,;.\s]+$/, '').trim() || txt
}

export function formatNodeDisplayLabel(
  node: Pick<PhyloTreeNode, 'name' | 'meta'>,
  format: LabelFormatType = 'name_acc'
): string {
  const acc = (node.name || '').trim()
  if (!acc) return 'unnamed'
  if (format === 'accession' || node.meta?.role === 'query') {
    return acc
  }
  const desc = cleanPhageDescription(node.meta?.description)
  if (!desc || desc.toLowerCase() === acc.toLowerCase()) {
    return acc
  }
  if (format === 'name') {
    return desc
  }
  return desc.includes(acc) ? desc : `${desc} (${acc})`
}

const GENUS_PALETTE = JOURNAL_THEMES.nature.taxonColors

export interface PhyloTreeNode {
  id: string
  name: string
  support: number | null
  alrt: number | null
  ufboot: number | null
  supportLabel: string
  branchLength: number
  children: PhyloTreeNode[]
  parent: PhyloTreeNode | null
  isLeaf: boolean
  collapsed: boolean
  leafCount: number
  minTaxon: string
  maxDistToLeaf: number
  depth: number
  heightFromRoot: number
  parseIndex: number
  cladeColor?: string
  meta?: NodeMetadata
  // 布局坐标
  x: number
  y: number
  angle: number
  radius: number
}

function parseSupportValue(label: string): {
  name: string
  support: number | null
  alrt: number | null
  ufboot: number | null
  supportLabel: string
} {
  const clean = label.trim()
  if (!clean) {
    return { name: '', support: null, alrt: null, ufboot: null, supportLabel: '' }
  }
  if (clean.includes('/')) {
    const [rawA, rawB] = clean.split('/', 2)
    const a = Number(rawA?.trim())
    const b = Number(rawB?.trim())
    if (Number.isFinite(a) && Number.isFinite(b) && a >= 0 && a <= 100 && b >= 0 && b <= 100) {
      return {
        name: clean,
        support: b,
        alrt: Math.round(a * 10) / 10,
        ufboot: Math.round(b * 10) / 10,
        supportLabel: clean,
      }
    }
  }
  const num = Number(clean)
  if (!Number.isNaN(num) && Number.isFinite(num)) {
    const pct = num > 0 && num <= 1 && clean.includes('.') ? Math.round(num * 100) : Math.round(num * 10) / 10
    return {
      name: clean,
      support: pct,
      alrt: null,
      ufboot: pct,
      supportLabel: String(Math.round(pct)),
    }
  }
  return { name: clean, support: null, alrt: null, ufboot: null, supportLabel: '' }
}

function quoteNewickLabel(label: string): string {
  if (!label) return ''
  if (/[():,;\[\]'\s]/.test(label)) {
    return "'" + label.replace(/'/g, "''") + "'"
  }
  return label
}

export class PhyloTreeModel {
  root: PhyloTreeNode | null = null
  leaves: PhyloTreeNode[] = []
  nodesById: Map<string, PhyloTreeNode> = new Map()
  maxDepth = 0
  maxHeight = 0
  version = 0
  cladeColors: Map<string, string> = new Map()
  collapsedIds: Set<string> = new Set()
  hasNodeMetadata = false
  hasHostMetadata = false
  maxGenomeLength = 0
  genusColors: Map<string, string> = new Map()
  otherGenera: Set<string> = new Set()
  private metadataMap: Record<string, NodeMetadata> = {}
  private paletteTheme: JournalPaletteType = 'nature'

  parse(newick: string): PhyloTreeNode | null {
    const raw = (newick || '').trim()
    if (!raw) return null
    const input = raw.endsWith(';') ? raw.slice(0, -1).trim() : raw
    let pos = 0
    const len = input.length

    const readLabel = (): string => {
      while (pos < len && /\s/.test(input[pos]!)) pos++
      if (pos >= len) return ''
      if (input[pos] === "'") {
        pos++
        let out = ''
        while (pos < len) {
          const ch = input[pos]!
          if (ch === "'") {
            if (pos + 1 < len && input[pos + 1] === "'") {
              out += "'"
              pos += 2
              continue
            }
            pos++
            break
          }
          out += ch
          pos++
        }
        return out
      }
      const start = pos
      while (pos < len && !'(),:;'.includes(input[pos]!)) pos++
      return input.slice(start, pos).trim()
    }

    const parseNode = (parent: PhyloTreeNode | null, parseIndex: number): PhyloTreeNode => {
      const node: PhyloTreeNode = {
        id: '',
        name: '',
        support: null,
        alrt: null,
        ufboot: null,
        supportLabel: '',
        branchLength: 0,
        children: [],
        parent,
        isLeaf: false,
        collapsed: false,
        leafCount: 1,
        minTaxon: 'zzz',
        maxDistToLeaf: 0,
        depth: 0,
        heightFromRoot: 0,
        parseIndex,
        x: 0,
        y: 0,
        angle: 0,
        radius: 0,
      }

      while (pos < len && /\s/.test(input[pos]!)) pos++
      if (pos < len && input[pos] === '(') {
        pos++
        let cIdx = 0
        while (pos < len) {
          const child = parseNode(node, cIdx++)
          node.children.push(child)
          while (pos < len && /\s/.test(input[pos]!)) pos++
          if (pos < len && input[pos] === ',') {
            pos++
            continue
          }
          if (pos < len && input[pos] === ')') {
            pos++
            break
          }
          break
        }
      }

      const rawLabel = readLabel()
      if (node.children.length === 0) {
        node.name = rawLabel
      } else {
        const parsed = parseSupportValue(rawLabel)
        node.name = parsed.name
        node.support = parsed.support
        node.alrt = parsed.alrt
        node.ufboot = parsed.ufboot
        node.supportLabel = parsed.supportLabel
      }

      while (pos < len && /\s/.test(input[pos]!)) pos++
      if (pos < len && input[pos] === ':') {
        pos++
        const lenStart = pos
        while (pos < len && !'(),;'.includes(input[pos]!)) pos++
        const parsedLen = parseFloat(input.slice(lenStart, pos).trim())
        node.branchLength = Number.isFinite(parsedLen) ? Math.max(0, parsedLen) : 0
      }

      return node
    }

    this.root = parseNode(null, 0)
    this.collapsedIds.clear()
    this.cladeColors.clear()
    this.metadataMap = {}
    this.genusColors.clear()
    this.hasNodeMetadata = false
    this.hasHostMetadata = false
    this.maxGenomeLength = 0
    this.rebuildIndex()
    return this.root
  }

  rebuildIndex(): void {
    this.version++
    this.leaves = []
    this.nodesById.clear()
    this.maxDepth = 0
    this.maxHeight = 0
    if (!this.root) return

    let counter = 0
    const walk = (node: PhyloTreeNode, depth: number, height: number, parent: PhyloTreeNode | null) => {
      node.id = `n_${counter++}`
      node.depth = depth
      node.heightFromRoot = height
      node.parent = parent
      node.isLeaf = node.children.length === 0
      this.nodesById.set(node.id, node)

      if (node.isLeaf || node.collapsed) {
        this.leaves.push(node)
        if (depth > this.maxDepth) this.maxDepth = depth
        if (height > this.maxHeight) this.maxHeight = height
        node.leafCount = node.isLeaf ? 1 : this.countSubtreeLeaves(node)
        node.minTaxon = node.name || 'zzz'
        node.maxDistToLeaf = 0
        return
      }

      let totalLeaves = 0
      let minTax = 'zzz'
      let maxD = 0
      for (const ch of node.children) {
        walk(ch, depth + 1, height + ch.branchLength, node)
        totalLeaves += ch.leafCount
        if (ch.minTaxon < minTax) minTax = ch.minTaxon
        maxD = Math.max(maxD, ch.maxDistToLeaf + ch.branchLength)
      }
      node.leafCount = totalLeaves
      node.minTaxon = minTax
      node.maxDistToLeaf = maxD
    }

    walk(this.root, 0, 0, null)
    if (Object.keys(this.metadataMap).length > 0) {
      this.bindMetadataToNodes()
    }
  }

  private bindMetadataToNodes(): void {
    this.genusColors.clear()
    this.otherGenera.clear()
    this.maxGenomeLength = 0
    this.hasHostMetadata = false
    let matched = 0
    const walk = (node: PhyloTreeNode) => {
      if (node.isLeaf && node.name && this.metadataMap[node.name]) {
        const m = this.metadataMap[node.name]!
        node.meta = m
        matched++
        if (m.genome_length && m.genome_length > this.maxGenomeLength) {
          this.maxGenomeLength = m.genome_length
        }
        if (mapHostToPhylum(m.host)) {
          this.hasHostMetadata = true
        }
      }
      for (const c of node.children) walk(c)
    }
    if (this.root) walk(this.root)
    const { genusColors, otherGenera } = buildTopGenusColorMap(this.leaves, this.paletteTheme, 12)
    this.genusColors = genusColors
    this.otherGenera = otherGenera
    this.hasNodeMetadata = matched > 0
  }

  applyJournalTheme(theme: JournalPaletteType): void {
    if (this.paletteTheme === theme) return
    this.paletteTheme = theme
    if (Object.keys(this.metadataMap).length > 0) {
      this.bindMetadataToNodes()
      this.version++
    }
  }

  applyNodeMetadata(metaMap: Record<string, NodeMetadata>): void {
    this.metadataMap = { ...metaMap }
    this.bindMetadataToNodes()
    this.version++
  }

  private countSubtreeLeaves(node: PhyloTreeNode): number {
    if (node.children.length === 0) return 1
    let sum = 0
    for (const c of node.children) sum += this.countSubtreeLeaves(c)
    return sum
  }

  toggleCollapse(nodeId: string): void {
    const node = this.nodesById.get(nodeId)
    if (!node || node.children.length === 0) return
    node.collapsed = !node.collapsed
    if (node.collapsed) this.collapsedIds.add(nodeId)
    else this.collapsedIds.delete(nodeId)
    this.rebuildIndex()
  }

  setCladeColor(nodeId: string, color: string | null): void {
    const node = this.nodesById.get(nodeId)
    if (!node) return
    const apply = (n: PhyloTreeNode) => {
      if (color) n.cladeColor = color
      else delete n.cladeColor
      for (const c of n.children) apply(c)
    }
    apply(node)
    this.version++
  }

  applySorting(mode: SortMode): void {
    if (!this.root) return
    const sortNode = (node: PhyloTreeNode) => {
      if (node.children.length === 0) return
      for (const c of node.children) sortNode(c)
      node.children.sort((a, b) => {
        if (mode === 'ladder-right') return a.leafCount - b.leafCount || a.parseIndex - b.parseIndex
        if (mode === 'ladder-left') return b.leafCount - a.leafCount || a.parseIndex - b.parseIndex
        if (mode === 'taxonomic') return a.minTaxon.localeCompare(b.minTaxon)
        if (mode === 'distance') return b.maxDistToLeaf - a.maxDistToLeaf
        return a.parseIndex - b.parseIndex
      })
    }
    sortNode(this.root)
    this.rebuildIndex()
  }

  private farthestFrom(start: PhyloTreeNode): {
    node: PhyloTreeNode
    dist: number
    prev: Map<PhyloTreeNode, PhyloTreeNode>
  } {
    const visited = new Set<PhyloTreeNode>([start])
    const distMap = new Map<PhyloTreeNode, number>([[start, 0]])
    const prev = new Map<PhyloTreeNode, PhyloTreeNode>()
    const stack: PhyloTreeNode[] = [start]
    let bestNode = start
    let bestDist = 0

    while (stack.length > 0) {
      const cur = stack.pop()!
      const curDist = distMap.get(cur) || 0
      if (curDist > bestDist) {
        bestDist = curDist
        bestNode = cur
      }
      const neighbors: Array<[PhyloTreeNode, number]> = []
      if (cur.parent) neighbors.push([cur.parent, cur.branchLength])
      for (const ch of cur.children) neighbors.push([ch, ch.branchLength])

      for (const [nb, w] of neighbors) {
        if (!visited.has(nb)) {
          visited.add(nb)
          distMap.set(nb, curDist + Math.max(0, w))
          prev.set(nb, cur)
          stack.push(nb)
        }
      }
    }
    return { node: bestNode, dist: bestDist, prev }
  }

  private reorientAt(target: PhyloTreeNode): void {
    const path: PhyloTreeNode[] = []
    let cur: PhyloTreeNode | null = target
    while (cur) {
      path.push(cur)
      cur = cur.parent
    }
    for (let i = path.length - 1; i > 0; i--) {
      const oldP = path[i]!
      const child = path[i - 1]!
      oldP.children = oldP.children.filter((c) => c !== child)
      const edgeLen = child.branchLength
      const childWasLeaf = child.children.length === 0
      const edgeSup = childWasLeaf ? null : child.support
      const edgeAlrt = childWasLeaf ? null : child.alrt
      const edgeUfboot = childWasLeaf ? null : child.ufboot
      const edgeSupLabel = childWasLeaf ? '' : child.supportLabel
      const edgeName = childWasLeaf ? '' : child.name
      child.children.push(oldP)
      oldP.parent = child
      oldP.branchLength = edgeLen
      if (oldP.children.length > 0) {
        oldP.support = edgeSup
        oldP.alrt = edgeAlrt
        oldP.ufboot = edgeUfboot
        oldP.supportLabel = edgeSupLabel
        oldP.name = edgeName
      }
      child.parent = null
      child.branchLength = 0
      if (!childWasLeaf) {
        child.support = null
        child.alrt = null
        child.ufboot = null
        child.supportLabel = ''
        child.name = ''
      }
    }
  }

  private splitEdgeRoot(uNode: PhyloTreeNode, vNode: PhyloTreeNode, distFromU: number): void {
    let u = uNode
    let v = vNode
    const edgeLen = v.parent === u ? v.branchLength : u.branchLength
    let dFromU = distFromU

    const uIsLeaf = u.children.length === 0
    const vIsLeaf = v.children.length === 0

    if (uIsLeaf && vIsLeaf) {
      const newRoot: PhyloTreeNode = {
        id: 'root',
        name: '',
        support: null,
        alrt: null,
        ufboot: null,
        supportLabel: '',
        branchLength: 0,
        children: [u, v],
        parent: null,
        isLeaf: false,
        collapsed: false,
        leafCount: 2,
        minTaxon: 'zzz',
        maxDistToLeaf: 0,
        depth: 0,
        heightFromRoot: 0,
        parseIndex: 0,
        x: 0,
        y: 0,
        angle: 0,
        radius: 0,
      }
      u.parent = newRoot
      v.parent = newRoot
      u.branchLength = Math.max(0, Math.min(edgeLen, dFromU))
      v.branchLength = Math.max(0, edgeLen - u.branchLength)
      this.root = newRoot
      this.rebuildIndex()
      return
    }

    if (uIsLeaf && !vIsLeaf) {
      const tmp = u
      u = v
      v = tmp
      dFromU = edgeLen - dFromU
    }

    this.reorientAt(u)
    u.children = u.children.filter((c) => c !== v)
    const lenUV = v.branchLength
    const dU = Math.max(0, Math.min(lenUV, dFromU))
    const dV = Math.max(0, lenUV - dU)

    const newRoot: PhyloTreeNode = {
      id: 'root',
      name: '',
      support: null,
      alrt: null,
      ufboot: null,
      supportLabel: '',
      branchLength: 0,
      children: [],
      parent: null,
      isLeaf: false,
      collapsed: false,
      leafCount: 0,
      minTaxon: 'zzz',
      maxDistToLeaf: 0,
      depth: 0,
      heightFromRoot: 0,
      parseIndex: 0,
      x: 0,
      y: 0,
      angle: 0,
      radius: 0,
    }
    u.parent = newRoot
    u.branchLength = dU
    v.parent = newRoot
    v.branchLength = dV
    newRoot.children = [u, v]

    // 折叠退化单子节点
    newRoot.children = newRoot.children.map((side) => {
      if (side.children.length === 1) {
        const only = side.children[0]!
        only.branchLength += side.branchLength
        only.parent = newRoot
        return only
      }
      return side
    })

    this.root = newRoot
    this.rebuildIndex()
  }

  rerootMidpoint(): void {
    if (!this.root || this.leaves.length < 2) return
    const tipA = this.farthestFrom(this.leaves[0]!).node
    const { node: tipB, dist: totalDist, prev } = this.farthestFrom(tipA)
    if (totalDist <= 0) return

    const path: PhyloTreeNode[] = []
    let cur: PhyloTreeNode | undefined = tipB
    while (cur) {
      path.push(cur)
      cur = prev.get(cur)
    }
    path.reverse()

    const half = totalDist / 2
    let acc = 0
    for (let i = 0; i < path.length - 1; i++) {
      const u = path[i]!
      const v = path[i + 1]!
      const edgeLen = v.parent === u ? v.branchLength : u.branchLength
      if (acc + edgeLen >= half || i === path.length - 2) {
        this.splitEdgeRoot(u, v, half - acc)
        return
      }
      acc += edgeLen
    }
  }

  rerootOutgroup(nodeId: string): void {
    const target = this.nodesById.get(nodeId)
    if (!target || !target.parent) return
    this.splitEdgeRoot(target.parent, target, target.branchLength * 0.5)
  }

  toNewick(): string {
    if (!this.root) return ''
    const serialize = (node: PhyloTreeNode, isRoot: boolean): string => {
      if (node.children.length === 0) {
        const lbl = quoteNewickLabel(node.name)
        return isRoot ? lbl : `${lbl}:${node.branchLength.toFixed(6)}`
      }
      const inner = node.children.map((c) => serialize(c, false)).join(',')
      const lbl = node.supportLabel
        ? node.supportLabel
        : node.support !== null
          ? String(node.support)
          : quoteNewickLabel(node.name)
      if (isRoot) return `(${inner})${lbl};`
      return `(${inner})${lbl}:${node.branchLength.toFixed(6)}`
    }
    return serialize(this.root, true)
  }
}
