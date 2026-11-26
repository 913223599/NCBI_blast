/**
 * 16S 多样性分析纯计算、色板与格式化辅助模块
 */
import type { DiversitySampleItem, DiversityTaxonDetail } from './useDiversityModal'

export interface SampleGroupDef {
  id: string
  name: string
  pattern: string
}

export interface StackedSegment {
  taxon: string
  pct: number
  rawCount: number
  rawPct: number
  normPct: number
  gcn: number
  color: string
  yBottom: number
  yTop: number
}

export interface StackedSample {
  sampleName: string
  totalReads: number
  isGroup?: boolean
  memberSamples?: string[]
  segments: StackedSegment[]
}

export const DIVERSITY_PALETTE = [
  '#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed',
  '#0891b2', '#db2777', '#4b5563', '#4f46e5', '#16a34a',
  '#ea580c', '#e11d48', '#9333ea', '#0284c7', '#65a30d',
  '#0d9488', '#b45309', '#be185d', '#6366f1', '#15803d',
  '#c2410c', '#9d174d', '#7e22ce', '#0369a1',
]

export function formatTime(timestamp: number | string | undefined): string {
  if (!timestamp) return ''
  const d =
    typeof timestamp === 'number' && timestamp < 10000000000
      ? new Date(timestamp * 1000)
      : new Date(timestamp)
  if (isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function formatReadsCount(num: number | undefined): string {
  if (!num) return '0'
  return num.toLocaleString()
}

export function getStatusLabel(s: string): string {
  const m: Record<string, string> = {
    completed: '已完成',
    running: '分析中',
    interrupted: '已中断',
    queued: '排队中',
    error: '失败',
  }
  return m[s] || s
}

export function formatPct(val: number | string | null | undefined): string {
  if (val === null || val === undefined || isNaN(Number(val))) return '0.00'
  const num = Number(val)
  if (num === 0) return '0.00'
  if (num > 0 && num < 0.01) return '<0.01'
  return num.toFixed(2)
}

export function isNoiseTaxon(taxon: string): boolean {
  if (!taxon) return false
  const lower = taxon.toLowerCase()
  return lower.startsWith('other') || lower.includes('噪声') || lower.includes('低频')
}

export function parseSamplePattern(pattern: string, samples: string[]): string[] {
  if (!pattern || !pattern.trim()) return []
  const matched = new Set<string>()
  const tokens = pattern
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)

  for (const token of tokens) {
    const rangeMatch = token.match(/^(-?\d+)\s*[-~至到]\s*(-?\d+)$/)
    if (rangeMatch) {
      const num1 = Math.abs(parseInt(rangeMatch[1] || '0', 10))
      const num2 = Math.abs(parseInt(rangeMatch[2] || '0', 10))
      const minNum = Math.min(num1, num2)
      const maxNum = Math.max(num1, num2)
      samples.forEach((sName) => {
        const m = sName.match(/\d+/)
        if (m) {
          const val = parseInt(m[0], 10)
          if (val >= minNum && val <= maxNum) matched.add(sName)
        }
      })
      continue
    }

    samples.forEach((sName) => {
      const pureToken = token.replace(/^-/, '')
      const pureSample = sName.replace(/^-/, '')
      if (
        sName === token ||
        pureSample === pureToken ||
        sName.toLowerCase().includes(token.toLowerCase())
      ) {
        matched.add(sName)
      }
    })
  }

  return Array.from(matched).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
  )
}

interface DraftTaxonDetail {
  taxon: string
  raw_count: number
  raw_pct: number
  gcn_mean: number
  norm_count: number
}

export function buildMergedGroupSamples(
  rawSamples: DiversitySampleItem[],
  validGroups: Array<SampleGroupDef & { matchedSamples: string[] }>
): DiversitySampleItem[] {
  const assignedNames = new Set<string>()
  const mergedResult: DiversitySampleItem[] = []

  for (const group of validGroups) {
    const subSamples = rawSamples.filter((s) => group.matchedSamples.includes(s.sample_name))
    if (subSamples.length === 0) continue

    subSamples.forEach((s) => assignedNames.add(s.sample_name))

    let groupTotalReads = 0
    let groupClassifiedReads = 0
    const taxaCounts: Record<string, number> = {}
    const gcnMap: Record<string, number> = {}

    for (const sub of subSamples) {
      groupTotalReads += sub.total_reads || 0
      groupClassifiedReads += Number(sub.classified_reads || 0)
      for (const d of sub.norm_result?.details || []) {
        taxaCounts[d.taxon] = (taxaCounts[d.taxon] || 0) + (d.raw_count || 0)
        gcnMap[d.taxon] = d.gcn_mean || 1.0
      }
    }

    let totalNorm = 0
    const tempDetails: DraftTaxonDetail[] = []
    for (const [taxon, count] of Object.entries(taxaCounts)) {
      const gcn = gcnMap[taxon] || 1.0
      const normVal = count / gcn
      totalNorm += normVal
      tempDetails.push({
        taxon,
        raw_count: count,
        raw_pct: groupClassifiedReads > 0 ? (count / groupClassifiedReads) * 100 : 0,
        gcn_mean: gcn,
        norm_count: normVal,
      })
    }

    const details: DiversityTaxonDetail[] = tempDetails
      .map((d) => ({
        ...d,
        norm_pct: totalNorm > 0 ? (d.norm_count / totalNorm) * 100 : 0,
        raw_pct: Math.round(d.raw_pct * 100) / 100,
        gcn_rank: 'species',
        gcn_matched: true,
      }))
      .sort((a, b) => b.raw_count - a.raw_count)

    mergedResult.push({
      sample_name: group.name,
      is_group: true,
      member_samples: group.matchedSamples,
      total_reads: groupTotalReads,
      classified_reads: groupClassifiedReads,
      taxa_counts: taxaCounts,
      norm_result: {
        total_raw: groupClassifiedReads,
        total_norm: totalNorm,
        details,
      },
    })
  }

  const unassigned = rawSamples.filter((s) => !assignedNames.has(s.sample_name))
  return [...mergedResult, ...unassigned]
}
