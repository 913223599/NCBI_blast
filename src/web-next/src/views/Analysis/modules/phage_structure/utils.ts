import type { MorphotypeCode, StructureProteinItem, StructuralModuleMatrix } from './types'

export interface MorphotypeTheme {
  label: string
  shortLabel: string
  badgeBg: string
  badgeText: string
  badgeBorder: string
  accentColor: string
}

const MORPHOTYPE_THEMES: Record<MorphotypeCode, MorphotypeTheme> = {
  'Myoviridae-like': {
    label: '肌尾形态 (Myoviridae-like)',
    shortLabel: '肌尾 Myo',
    badgeBg: '#eff6ff',
    badgeText: '#1d4ed8',
    badgeBorder: '#bfdbfe',
    accentColor: '#2563eb',
  },
  'Siphoviridae-like': {
    label: '长尾形态 (Siphoviridae-like)',
    shortLabel: '长尾 Sipho',
    badgeBg: '#f0fdf4',
    badgeText: '#15803d',
    badgeBorder: '#bbf7d0',
    accentColor: '#16a34a',
  },
  'Podoviridae-like': {
    label: '短尾形态 (Podoviridae-like)',
    shortLabel: '短尾 Podo',
    badgeBg: '#fff7ed',
    badgeText: '#c2410c',
    badgeBorder: '#fed7aa',
    accentColor: '#ea580c',
  },
  'Non-tailed': {
    label: '非有尾 (Non-tailed)',
    shortLabel: '非有尾',
    badgeBg: '#faf5ff',
    badgeText: '#7e22ce',
    badgeBorder: '#e9d5ff',
    accentColor: '#9333ea',
  },
  Incomplete: {
    label: '证据不足 (Incomplete)',
    shortLabel: '不完整',
    badgeBg: '#f8fafc',
    badgeText: '#475569',
    badgeBorder: '#cbd5e1',
    accentColor: '#64748b',
  },
}

export function getMorphotypeTheme(code?: string): MorphotypeTheme {
  if (code && code in MORPHOTYPE_THEMES) {
    return MORPHOTYPE_THEMES[code as MorphotypeCode]
  }
  return MORPHOTYPE_THEMES.Incomplete
}

export function getRoleModuleGroup(
  role: string
): 'head' | 'connector' | 'tail_core' | 'tail_fiber' | 'lysis' | 'confounder' | 'other' {
  if (['PORTAL', 'TERL', 'TERS', 'MCP', 'HEAD_SCAFFOLD_PROTEASE'].includes(role)) {
    return 'head'
  }
  if (
    [
      'CONN_AD1',
      'CONN_AD2',
      'CONN_AD3',
      'CONN_HC1',
      'CONN_HC2',
      'CONN_HC3',
      'CONN_NECK1',
      'CONN_TAIL_TERM',
      'CONN_GENERAL',
      'COLLAR_PODO',
    ].includes(role)
  ) {
    return 'connector'
  }
  if (['TSP', 'TTP', 'MTP', 'TAP', 'TMP', 'TTPA_B', 'INTERNAL_VIRION', 'TAIL_NEEDLE', 'BASEPLATE_MYO', 'DIT', 'TAIL_OTHER'].includes(role)) {
    return 'tail_core'
  }
  if (['TAIL_FIBER_RBP', 'FIBRITIN_COLLAR'].includes(role)) {
    return 'tail_fiber'
  }
  if (['LYSIS', 'INTEGRASE'].includes(role)) {
    return 'lysis'
  }
  if (['T6SS_CONFOUNDER', 'NON_TAILED_MARKER'].includes(role)) {
    return 'confounder'
  }
  return 'other'
}

export function getRoleTrackColor(role: string): string {
  const g = getRoleModuleGroup(role)
  switch (g) {
    case 'head':
      return '#0ea5e9'
    case 'connector':
      return '#8b5cf6'
    case 'tail_core':
      if (role === 'TMP') return '#f59e0b'
      if (role === 'TSP') return '#1d4ed8'
      if (role === 'TTPA_B' || role === 'INTERNAL_VIRION' || role === 'TAIL_NEEDLE') return '#ea580c'
      return '#16a34a'
    case 'tail_fiber':
      return '#0d9488'
    case 'lysis':
      return '#e11d48'
    case 'confounder':
      return '#dc2626'
    default:
      return '#cbd5e1'
  }
}

export function formatGenomeBp(bp?: number | null): string {
  if (!bp || bp <= 0) return '0 bp'
  if (bp >= 1_000_000) return `${(bp / 1_000_000).toFixed(2)} Mb`
  if (bp >= 1_000) return `${(bp / 1_000).toFixed(2)} kb`
  return `${bp} bp`
}

export function formatTailLength(nm?: number | null, range?: number[]): string {
  if (nm === undefined || nm === null) return '不适用 / 未定标'
  if (range && range.length >= 2) {
    const low = range[0] ?? nm
    const high = range[1] ?? nm
    return `约 ${nm.toFixed(1)} nm (${low.toFixed(0)}~${high.toFixed(0)} nm)`
  }
  return `约 ${nm.toFixed(1)} nm`
}

export interface ModuleMatrixCardItem {
  key: string
  title: string
  count: number
  detail: string
  color: string
  highlighted: boolean
}

export function buildModuleMatrixCards(matrix: StructuralModuleMatrix): ModuleMatrixCardItem[] {
  return [
    {
      key: 'head',
      title: '头部/包装',
      count: matrix.head_packaging_count,
      detail: 'Portal / TerL / MCP',
      color: '#0ea5e9',
      highlighted: matrix.head_packaging_count > 0,
    },
    {
      key: 'connector',
      title: '连接器',
      count: matrix.connector_count,
      detail: 'Virfam Ad1-3 / Hc1-3 / Neck1',
      color: '#8b5cf6',
      highlighted: matrix.connector_count > 0,
    },
    {
      key: 'myo',
      title: '肌尾组件',
      count: matrix.tail_sheath_count + matrix.tail_tube_count + matrix.baseplate_count,
      detail: `TSP x${matrix.tail_sheath_count} · TTP x${matrix.tail_tube_count} · 基板 x${matrix.baseplate_count}`,
      color: '#2563eb',
      highlighted: matrix.tail_sheath_count > 0,
    },
    {
      key: 'sipho',
      title: '长尾/TMP',
      count: matrix.major_tail_count + matrix.tail_assembly_chaperone_count + matrix.tape_measure_count,
      detail: `MTP x${matrix.major_tail_count} · TAP x${matrix.tail_assembly_chaperone_count} · TMP x${matrix.tape_measure_count}`,
      color: '#16a34a',
      highlighted: matrix.major_tail_count > 0 || matrix.tape_measure_count > 0,
    },
    {
      key: 'podo',
      title: '短尾注入',
      count: matrix.tail_tubular_ab_count + matrix.internal_virion_count + matrix.tail_needle_count,
      detail: `TTPA/B x${matrix.tail_tubular_ab_count} · 内核心 x${matrix.internal_virion_count} · 尾针 x${matrix.tail_needle_count}`,
      color: '#ea580c',
      highlighted: matrix.tail_tubular_ab_count + matrix.internal_virion_count + matrix.tail_needle_count > 0,
    },
    {
      key: 'rbp_lysis',
      title: '尾丝/裂解',
      count: matrix.tail_fiber_rbp_count + matrix.lysis_count,
      detail: `RBP/尾丝 x${matrix.tail_fiber_rbp_count} · 裂解/整合酶 x${matrix.lysis_count + matrix.integrase_count}`,
      color: '#0d9488',
      highlighted: matrix.tail_fiber_rbp_count + matrix.lysis_count > 0,
    },
  ]
}

export function summarizeRoleCounts(proteins: StructureProteinItem[]): Record<string, StructureProteinItem[]> {
  const grouped = Object.groupBy(proteins, (p) => p.structural_role)
  return Object.fromEntries(
    Object.entries(grouped).filter((entry): entry is [string, StructureProteinItem[]] => Array.isArray(entry[1]))
  )
}

const SEQ_EXT_RE = /(?:\.(?:fasta|fa|fna|faa|gbk|gb|gbff|genbank|gz))+$/i

export function deriveStructureTaskName(filename: string): string {
  const base = filename.replace(/\\/g, '/').split('/').pop() || filename
  const stem = base.replace(SEQ_EXT_RE, '').trim()
  return stem ? `${stem}_Structure` : 'PhageStructure_Task'
}

export function detectSequenceFormatLabel(filename: string): string {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.faa') || lower.endsWith('.faa.gz')) return 'FAA'
  if (/\.(gbk|gb|gbff|genbank)(\.gz)?$/i.test(lower)) return 'GBK'
  if (/\.(fasta|fa|fna)(\.gz)?$/i.test(lower)) return 'FASTA'
  return 'SEQ'
}

export function compactLocusLabel(locus: string, maxLen: number = 22): string {
  if (!locus || locus.length <= maxLen) return locus
  const cdsMatch = locus.match(/(?:_|-)(CDS_\d+|gp\d+|orf_?\d+)$/i)
  if (cdsMatch && cdsMatch[1]) {
    const tail = cdsMatch[1]
    const headLen = Math.max(4, maxLen - tail.length - 3)
    return `${locus.slice(0, headLen)}...${tail}`
  }
  const half = Math.max(6, Math.floor((maxLen - 3) / 2))
  return `${locus.slice(0, half)}...${locus.slice(locus.length - half)}`
}

export function countFastaRecords(text: string): number {
  if (!text) return 0
  let cnt = 0
  for (const raw of text.split(/\r?\n/)) {
    if (raw.trim().startsWith('>')) cnt += 1
  }
  return cnt
}

export function formatCompletenessStatus(status?: string): string {
  switch (status) {
    case 'complete':
      return '完整闭合'
    case 'high_quality':
      return '高质量完整'
    case 'partial_or_truncated':
      return '部分/截断'
    case 'incomplete':
      return '残缺片段'
    default:
      return '默认评估'
  }
}
