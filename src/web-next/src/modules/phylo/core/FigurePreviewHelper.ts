import type { PublicationFigureItem } from '../types/phylo'

export interface FigureUrlOptions {
  inline?: boolean
  cacheBust?: number | string
}

export interface PublicationLayoutGroup {
  layout: string
  label: string
  formats: PublicationFigureItem[]
  previewPng: PublicationFigureItem | null
  previewSvg: PublicationFigureItem | null
  previewPdf: PublicationFigureItem | null
  preferredPreview: PublicationFigureItem | null
}

const LAYOUT_ORDER: readonly string[] = ['composite', 'circular', 'half_circular', 'rectangular']
const FORMAT_ORDER: readonly string[] = ['pdf', 'svg', 'png', 'eps']

const LAYOUT_LABELS: Record<string, string> = {
  composite: '复合双拼图 (a+b)',
  circular: '环形多环图',
  half_circular: '180° 半圆全景树',
  rectangular: '矩形多轨图',
}

export function formatLayoutLabel(layout: string): string {
  return LAYOUT_LABELS[layout] ?? layout
}

export function isImagePreviewFormat(format: string): boolean {
  const norm = format.trim().toLowerCase()
  return norm === 'png' || norm === 'svg'
}

export function isPdfPreviewFormat(format: string): boolean {
  return format.trim().toLowerCase() === 'pdf'
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '0 B'
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export function buildFigureUrlQuery(options?: FigureUrlOptions): string {
  if (!options) return ''
  const params: string[] = []
  if (options.inline) {
    params.push('inline=1')
  }
  if (options.cacheBust !== undefined && options.cacheBust !== null && options.cacheBust !== '') {
    params.push(`v=${encodeURIComponent(String(options.cacheBust))}`)
  }
  return params.length ? `?${params.join('&')}` : ''
}

export function pickPreferredPreviewFilename(
  figures: PublicationFigureItem[],
  preferredFormat: 'png' | 'svg' = 'png'
): string | null {
  if (!figures.length) return null
  const primary = figures.find((f) => f.format.toLowerCase() === preferredFormat)
  if (primary) return primary.filename
  const secondaryFmt = preferredFormat === 'png' ? 'svg' : 'png'
  const secondary = figures.find((f) => f.format.toLowerCase() === secondaryFmt)
  if (secondary) return secondary.filename
  const pdf = figures.find((f) => f.format.toLowerCase() === 'pdf')
  return pdf ? pdf.filename : figures[0]!.filename
}

export function groupPublicationFiguresByLayout(
  figures: PublicationFigureItem[]
): PublicationLayoutGroup[] {
  const buckets = new Map<string, PublicationFigureItem[]>()
  for (const item of figures) {
    if (!item || !item.filename) continue
    const key = item.layout || 'other'
    const list = buckets.get(key)
    if (list) {
      list.push(item)
    } else {
      buckets.set(key, [item])
    }
  }

  const orderedLayouts = Array.from(buckets.keys()).sort((a, b) => {
    const ia = LAYOUT_ORDER.indexOf(a)
    const ib = LAYOUT_ORDER.indexOf(b)
    if (ia >= 0 && ib >= 0) return ia - ib
    if (ia >= 0) return -1
    if (ib >= 0) return 1
    return a.localeCompare(b)
  })

  return orderedLayouts.map((layout) => {
    const rawList = buckets.get(layout) ?? []
    const formats = [...rawList].sort((a, b) => {
      const fa = FORMAT_ORDER.indexOf(a.format.toLowerCase())
      const fb = FORMAT_ORDER.indexOf(b.format.toLowerCase())
      if (fa >= 0 && fb >= 0) return fa - fb
      if (fa >= 0) return -1
      if (fb >= 0) return 1
      return a.format.localeCompare(b.format)
    })
    const previewPng = formats.find((f) => f.format.toLowerCase() === 'png') ?? null
    const previewSvg = formats.find((f) => f.format.toLowerCase() === 'svg') ?? null
    const previewPdf = formats.find((f) => f.format.toLowerCase() === 'pdf') ?? null
    const preferredPreview = previewPng ?? previewSvg ?? previewPdf ?? formats[0] ?? null
    return {
      layout,
      label: formatLayoutLabel(layout),
      formats,
      previewPng,
      previewSvg,
      previewPdf,
      preferredPreview,
    }
  })
}
