import type { JournalPaletteType } from '../types/phylo'
import type { PhyloTreeNode } from './TreeModel'

export interface JournalThemeConfig {
  id: JournalPaletteType
  label: string
  taxonColors: string[]
  backboneColor: string
  queryColor: string
  queryTextColor: string
  queryBgColor: string
  outgroupColor: string
  unclassifiedColor: string
  sizeBarColor: string
  gcBarColor: string
  strongDotColor: string
  moderateDotEdge: string
  cladeOpacity: number
}

export const JOURNAL_THEMES: Record<JournalPaletteType, JournalThemeConfig> = {
  nature: {
    id: 'nature',
    label: 'Nature (NPG)',
    taxonColors: [
      '#3C5488',
      '#00A087',
      '#4DBBD5',
      '#F39B7F',
      '#8491B4',
      '#91D1C2',
      '#7E6148',
      '#B09C85',
      '#E64B35',
      '#2E6B9E',
      '#E69F00',
      '#6A4C93',
    ],
    backboneColor: '#1E293B',
    queryColor: '#DC0000',
    queryTextColor: '#991B1B',
    queryBgColor: '#FEE2E2',
    outgroupColor: '#64748B',
    unclassifiedColor: '#E2E8F0',
    sizeBarColor: '#3C5488',
    gcBarColor: '#00A087',
    strongDotColor: '#0F172A',
    moderateDotEdge: '#334155',
    cladeOpacity: 0.13,
  },
  lancet: {
    id: 'lancet',
    label: 'The Lancet',
    taxonColors: [
      '#00468B',
      '#42B540',
      '#0099B4',
      '#925E9F',
      '#FDAF91',
      '#AD002A',
      '#ADB6B6',
      '#1B1919',
      '#3B7A9E',
      '#6F99AD',
      '#E18727',
      '#20854E',
    ],
    backboneColor: '#1B1919',
    queryColor: '#ED0000',
    queryTextColor: '#991B1B',
    queryBgColor: '#FEE2E2',
    outgroupColor: '#6B7280',
    unclassifiedColor: '#E2E8F0',
    sizeBarColor: '#00468B',
    gcBarColor: '#0099B4',
    strongDotColor: '#1B1919',
    moderateDotEdge: '#4B5563',
    cladeOpacity: 0.12,
  },
  okabe_ito: {
    id: 'okabe_ito',
    label: 'Okabe-Ito (Colorblind Safe)',
    taxonColors: [
      '#0072B2',
      '#009E73',
      '#E69F00',
      '#56B4E9',
      '#CC79A7',
      '#D55E00',
      '#F0E442',
      '#332288',
      '#44AA99',
      '#882255',
      '#117733',
      '#999933',
    ],
    backboneColor: '#1E293B',
    queryColor: '#D55E00',
    queryTextColor: '#9A3412',
    queryBgColor: '#FFEDD5',
    outgroupColor: '#64748B',
    unclassifiedColor: '#E2E8F0',
    sizeBarColor: '#0072B2',
    gcBarColor: '#009E73',
    strongDotColor: '#0F172A',
    moderateDotEdge: '#334155',
    cladeOpacity: 0.13,
  },
  monochrome: {
    id: 'monochrome',
    label: 'MBE Monochrome',
    taxonColors: [
      '#1F2937',
      '#4B5563',
      '#6B7280',
      '#9CA3AF',
      '#374151',
      '#D1D5DB',
      '#111827',
      '#52525B',
    ],
    backboneColor: '#111827',
    queryColor: '#111827',
    queryTextColor: '#111827',
    queryBgColor: '#E5E7EB',
    outgroupColor: '#6B7280',
    unclassifiedColor: '#E5E7EB',
    sizeBarColor: '#374151',
    gcBarColor: '#6B7280',
    strongDotColor: '#111827',
    moderateDotEdge: '#374151',
    cladeOpacity: 0.10,
  },
}

export const HOST_PHYLUM_COLORS: Record<string, string> = {
  Pseudomonadota: '#4C956C',
  Actinomycetota: '#577590',
  Bacillota: '#7B6D8D',
  Bacteroidota: '#C08552',
  Cyanobacteriota: '#2A9D8F',
  Campylobacterota: '#D4A373',
  Mycoplasmatota: '#457B9D',
  Fusobacteriota: '#B56576',
  Spirochaetota: '#9A6B99',
  Chlamydiota: '#6D597A',
  Deinococcota: '#4A7C9B',
  Verrucomicrobiota: '#6B9080',
  Archaea: '#6C757D',
  Others: '#CBD5E1',
}

const HOST_GENUS_TO_PHYLUM: Record<string, string> = {
  escherichia: 'Pseudomonadota',
  vibrio: 'Pseudomonadota',
  klebsiella: 'Pseudomonadota',
  pseudomonas: 'Pseudomonadota',
  salmonella: 'Pseudomonadota',
  enterobacteria: 'Pseudomonadota',
  acinetobacter: 'Pseudomonadota',
  ralstonia: 'Pseudomonadota',
  erwinia: 'Pseudomonadota',
  aeromonas: 'Pseudomonadota',
  yersinia: 'Pseudomonadota',
  shigella: 'Pseudomonadota',
  xanthomonas: 'Pseudomonadota',
  burkholderia: 'Pseudomonadota',
  enterobacter: 'Pseudomonadota',
  serratia: 'Pseudomonadota',
  citrobacter: 'Pseudomonadota',
  proteus: 'Pseudomonadota',
  cronobacter: 'Pseudomonadota',
  shewanella: 'Pseudomonadota',
  pseudoalteromonas: 'Pseudomonadota',
  caulobacter: 'Pseudomonadota',
  rhizobium: 'Pseudomonadota',
  agrobacterium: 'Pseudomonadota',
  bordetella: 'Pseudomonadota',
  proteobacteria: 'Pseudomonadota',
  pseudomonadota: 'Pseudomonadota',
  mycobacterium: 'Actinomycetota',
  gordonia: 'Actinomycetota',
  microbacterium: 'Actinomycetota',
  arthrobacter: 'Actinomycetota',
  streptomyces: 'Actinomycetota',
  propionibacterium: 'Actinomycetota',
  cutibacterium: 'Actinomycetota',
  rhodococcus: 'Actinomycetota',
  corynebacterium: 'Actinomycetota',
  bifidobacterium: 'Actinomycetota',
  actinobacteria: 'Actinomycetota',
  actinomycetota: 'Actinomycetota',
  streptococcus: 'Bacillota',
  staphylococcus: 'Bacillota',
  bacillus: 'Bacillota',
  lactococcus: 'Bacillota',
  enterococcus: 'Bacillota',
  listeria: 'Bacillota',
  clostridium: 'Bacillota',
  lactobacillus: 'Bacillota',
  paenibacillus: 'Bacillota',
  clostridioides: 'Bacillota',
  firmicutes: 'Bacillota',
  bacillota: 'Bacillota',
  flavobacterium: 'Bacteroidota',
  bacteroides: 'Bacteroidota',
  cellulophaga: 'Bacteroidota',
  chryseobacterium: 'Bacteroidota',
  prevotella: 'Bacteroidota',
  tenacibaculum: 'Bacteroidota',
  bacteroidetes: 'Bacteroidota',
  bacteroidota: 'Bacteroidota',
  synechococcus: 'Cyanobacteriota',
  prochlorococcus: 'Cyanobacteriota',
  microcystis: 'Cyanobacteriota',
  anabaena: 'Cyanobacteriota',
  cyanobacteria: 'Cyanobacteriota',
  cyanobacteriota: 'Cyanobacteriota',
  campylobacter: 'Campylobacterota',
  helicobacter: 'Campylobacterota',
  mycoplasma: 'Mycoplasmatota',
  fusobacterium: 'Fusobacteriota',
  borrelia: 'Spirochaetota',
  leptospira: 'Spirochaetota',
  treponema: 'Spirochaetota',
  chlamydia: 'Chlamydiota',
  thermus: 'Deinococcota',
  deinococcus: 'Deinococcota',
  akkermansia: 'Verrucomicrobiota',
  sulfolobus: 'Archaea',
  halobacterium: 'Archaea',
  pyrococcus: 'Archaea',
  archaea: 'Archaea',
}

const UNKNOWN_TOKENS = new Set([
  '',
  'unspecified',
  'unclassified',
  'unknown',
  'na',
  'n/a',
  'none',
  'nan',
  '-',
  'uncultured',
  'metagenome',
])

const CJK_RE = /[\u2e80-\u9fff\uf900-\ufaff\ufe30-\ufe4f]/

export function mapHostToPhylum(host?: string): string {
  const raw = (host || '').trim()
  if (UNKNOWN_TOKENS.has(raw.toLowerCase())) return ''
  const tokens = raw
    .split(/\s+/)
    .map((t) => t.replace(/^[[\](),;]+|[[\](),;]+$/g, ''))
    .filter(Boolean)
  if (tokens.length === 0) return ''
  const target =
    tokens[0]!.toLowerCase() === 'candidatus' && tokens.length > 1
      ? tokens[1]!.toLowerCase()
      : tokens[0]!.toLowerCase()
  if (UNKNOWN_TOKENS.has(target)) return ''
  return HOST_GENUS_TO_PHYLUM[target] || 'Others'
}

export function getHostPhylumColor(phylum: string, themeId: JournalPaletteType = 'nature'): string {
  if (themeId === 'monochrome') {
    return '#6B7280'
  }
  return HOST_PHYLUM_COLORS[phylum] || '#6b7280'
}

export function isFormalTaxonName(label: string): boolean {
  const clean = (label || '').replace(/\s*\(\d+\)\s*$/, '').trim()
  if (!clean || CJK_RE.test(clean)) return false
  const low = clean.toLowerCase()
  if (
    low === 'unclassified' ||
    low === 'unknown' ||
    low === 'others' ||
    low === 'query' ||
    low === 'query phage' ||
    low === 'archaea' ||
    low.startsWith('outgroup')
  ) {
    return false
  }
  return /^[A-Za-z][A-Za-z0-9._\-\s]*$/.test(clean)
}

export interface LabelSegment {
  text: string
  italic: boolean
}

export function splitTaxonomicLabelSegments(label: string): LabelSegment[] {
  const txt = label || ''
  if (!txt || CJK_RE.test(txt)) {
    return [{ text: txt, italic: false }]
  }
  const candMatch = txt.match(/^(Candidatus\s+[A-Z][a-z]{2,})(\s+.*)$/)
  if (candMatch) {
    return [
      { text: candMatch[1]!, italic: true },
      { text: candMatch[2]!, italic: false },
    ]
  }
  const genusMatch = txt.match(/^([A-Z][a-z]{2,})(\s+.*)$/)
  if (genusMatch && isFormalTaxonName(genusMatch[1]!)) {
    return [
      { text: genusMatch[1]!, italic: true },
      { text: genusMatch[2]!, italic: false },
    ]
  }
  return [{ text: txt, italic: false }]
}

export function computeNiceScaleValue(rawTarget: number): number {
  if (!Number.isFinite(rawTarget) || rawTarget <= 0) return 0.1
  const exp = Math.pow(10, Math.floor(Math.log10(Math.max(1e-12, rawTarget))))
  const niceStep = [1, 2, 5, 10].find((m) => m * exp >= rawTarget * 0.7) || 1
  return Number((niceStep * exp).toPrecision(6))
}

export function buildStarPolygonPoints(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number
): string {
  const pts: string[] = []
  for (let i = 0; i < 10; i++) {
    const r = i % 2 === 0 ? outerR : innerR
    const angle = -Math.PI / 2 + (i * Math.PI) / 5
    const x = cx + r * Math.cos(angle)
    const y = cy + r * Math.sin(angle)
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`)
  }
  return pts.join(' ')
}

export interface MonophyleticCladeInfo {
  node: PhyloTreeNode
  taxonName: string
  color: string
  leafStartIdx: number
  leafEndIdx: number
  containsQuery: boolean
}

function collectVisibleLeaves(node: PhyloTreeNode): PhyloTreeNode[] {
  if (node.isLeaf || node.collapsed) return [node]
  const res: PhyloTreeNode[] = []
  for (const ch of node.children) {
    res.push(...collectVisibleLeaves(ch))
  }
  return res
}

export function detectMonophyleticClades(
  root: PhyloTreeNode,
  leaves: PhyloTreeNode[],
  genusColors: Map<string, string>
): MonophyleticCladeInfo[] {
  const leafIdxMap = new Map<string, number>()
  leaves.forEach((lf, idx) => leafIdxMap.set(lf.id, idx))

  const clades: MonophyleticCladeInfo[] = []

  const inspect = (node: PhyloTreeNode) => {
    if (node.isLeaf || node.collapsed) return
    if (node.parent !== null) {
      const subLeaves = collectVisibleLeaves(node)
      if (subLeaves.length >= 2) {
        let hasOutgroup = false
        let hasQuery = false
        const genera = new Set<string>()
        const indices: number[] = []

        for (const lf of subLeaves) {
          const role = (lf.meta?.role || '').toLowerCase()
          if (role === 'outgroup') {
            hasOutgroup = true
            break
          }
          if (role === 'query') hasQuery = true
          const g = (lf.meta?.genus || '').trim()
          if (g && !UNKNOWN_TOKENS.has(g.toLowerCase())) {
            genera.add(g)
          }
          const idx = leafIdxMap.get(lf.id)
          if (idx !== undefined) indices.push(idx)
        }

        if (!hasOutgroup && genera.size === 1 && indices.length > 0) {
          const taxonName = Array.from(genera)[0]!
          const col = genusColors.get(taxonName)
          if (col) {
            clades.push({
              node,
              taxonName,
              color: col,
              leafStartIdx: Math.min(...indices),
              leafEndIdx: Math.max(...indices),
              containsQuery: hasQuery,
            })
          }
          return
        }
      }
    }

    for (const ch of node.children) {
      inspect(ch)
    }
  }

  inspect(root)
  return clades
}

export interface TopGenusColorResult {
  genusColors: Map<string, string>
  otherGenera: Set<string>
}

export function buildTopGenusColorMap(
  leaves: Pick<PhyloTreeNode, 'name' | 'meta'>[],
  themeId: JournalPaletteType = 'nature',
  topK = 12
): TopGenusColorResult {
  const theme = JOURNAL_THEMES[themeId] || JOURNAL_THEMES.nature
  const counts = new Map<string, number>()
  const minQueryDist = new Map<string, number>()

  const queryIndices: number[] = []
  leaves.forEach((lf, idx) => {
    if ((lf.meta?.role || '').toLowerCase() === 'query') queryIndices.push(idx)
  })

  leaves.forEach((lf, idx) => {
    const g = (lf.meta?.genus || '').trim()
    if (!g || UNKNOWN_TOKENS.has(g.toLowerCase())) return
    counts.set(g, (counts.get(g) || 0) + 1)
    if (queryIndices.length > 0) {
      let minD = Infinity
      for (const qi of queryIndices) {
        const d = Math.abs(idx - qi)
        if (d < minD) minD = d
      }
      if (minD <= 4) {
        const prev = minQueryDist.get(g)
        if (prev === undefined || minD < prev) minQueryDist.set(g, minD)
      }
    }
  })

  const limit = Math.min(Math.max(1, topK), theme.taxonColors.length)
  const orderedPriority = Array.from(minQueryDist.keys()).sort(
    (a, b) =>
      minQueryDist.get(a)! - minQueryDist.get(b)! ||
      (counts.get(b) || 0) - (counts.get(a) || 0) ||
      a.localeCompare(b)
  )
  const orderedAll = Array.from(counts.keys()).sort(
    (a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || a.localeCompare(b)
  )

  const chosen: string[] = []
  for (const g of orderedPriority) {
    if (chosen.length < limit && !chosen.includes(g)) chosen.push(g)
  }
  for (const g of orderedAll) {
    if (chosen.length < limit && !chosen.includes(g)) chosen.push(g)
  }

  const genusColors = new Map<string, string>()
  chosen.forEach((g, idx) => {
    genusColors.set(g, theme.taxonColors[idx]!)
  })
  const otherGenera = new Set<string>()
  for (const g of counts.keys()) {
    if (!genusColors.has(g)) otherGenera.add(g)
  }
  return { genusColors, otherGenera }
}

