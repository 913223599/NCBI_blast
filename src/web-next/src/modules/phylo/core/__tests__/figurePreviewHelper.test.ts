import { describe, expect, it } from 'vitest'
import {
  buildFigureUrlQuery,
  formatFileSize,
  formatLayoutLabel,
  groupPublicationFiguresByLayout,
  isImagePreviewFormat,
  isPdfPreviewFormat,
  pickPreferredPreviewFilename,
} from '../FigurePreviewHelper'
import type { PublicationFigureItem } from '../../types/phylo'

describe('FigurePreviewHelper', () => {
  it('groups publication figures by layout order and sorts formats cleanly', () => {
    const items: PublicationFigureItem[] = [
      {
        filename: 'publication_rectangular.svg',
        format: 'svg',
        layout: 'rectangular',
        size_bytes: 1200,
        download_url: '/api/phylo/jobs/j1/export/figure/publication_rectangular.svg',
      },
      {
        filename: 'publication_circular.pdf',
        format: 'pdf',
        layout: 'circular',
        size_bytes: 5400,
        download_url: '/api/phylo/jobs/j1/export/figure/publication_circular.pdf',
      },
      {
        filename: 'publication_composite.png',
        format: 'png',
        layout: 'composite',
        size_bytes: 82000,
        download_url: '/api/phylo/jobs/j1/export/figure/publication_composite.png',
      },
      {
        filename: 'publication_composite.svg',
        format: 'svg',
        layout: 'composite',
        size_bytes: 42000,
        download_url: '/api/phylo/jobs/j1/export/figure/publication_composite.svg',
      },
      {
        filename: 'publication_composite.pdf',
        format: 'pdf',
        layout: 'composite',
        size_bytes: 95000,
        download_url: '/api/phylo/jobs/j1/export/figure/publication_composite.pdf',
      },
    ]

    const groups = groupPublicationFiguresByLayout(items)
    expect(groups.map((g) => g.layout)).toEqual(['composite', 'circular', 'rectangular'])

    const comp = groups[0]!
    expect(comp.label).toBe('复合双拼图 (a+b)')
    expect(comp.formats.map((f) => f.format)).toEqual(['pdf', 'svg', 'png'])
    expect(comp.preferredPreview?.filename).toBe('publication_composite.png')
    expect(comp.previewPng?.filename).toBe('publication_composite.png')
    expect(comp.previewSvg?.filename).toBe('publication_composite.svg')
    expect(comp.previewPdf?.filename).toBe('publication_composite.pdf')

    const circ = groups[1]!
    expect(circ.preferredPreview?.filename).toBe('publication_circular.pdf')

    const rect = groups[2]!
    expect(rect.preferredPreview?.filename).toBe('publication_rectangular.svg')
  })

  it('picks preferred preview filename across formats and handles empty input', () => {
    const items: PublicationFigureItem[] = [
      {
        filename: 'pub.pdf',
        format: 'pdf',
        layout: 'circular',
        size_bytes: 100,
        download_url: '',
      },
      {
        filename: 'pub.svg',
        format: 'svg',
        layout: 'circular',
        size_bytes: 200,
        download_url: '',
      },
      {
        filename: 'pub.png',
        format: 'png',
        layout: 'circular',
        size_bytes: 300,
        download_url: '',
      },
    ]

    expect(pickPreferredPreviewFilename(items)).toBe('pub.png')
    expect(pickPreferredPreviewFilename(items, 'svg')).toBe('pub.svg')
    expect(pickPreferredPreviewFilename([])).toBeNull()
  })

  it('detects image and pdf preview formats case-insensitively', () => {
    expect(isImagePreviewFormat('png')).toBe(true)
    expect(isImagePreviewFormat('PNG')).toBe(true)
    expect(isImagePreviewFormat('svg')).toBe(true)
    expect(isImagePreviewFormat('pdf')).toBe(false)
    expect(isImagePreviewFormat('eps')).toBe(false)

    expect(isPdfPreviewFormat('pdf')).toBe(true)
    expect(isPdfPreviewFormat('PDF')).toBe(true)
    expect(isPdfPreviewFormat('png')).toBe(false)
  })

  it('builds figure url query parameters cleanly', () => {
    expect(buildFigureUrlQuery()).toBe('')
    expect(buildFigureUrlQuery({})).toBe('')
    expect(buildFigureUrlQuery({ inline: true })).toBe('?inline=1')
    expect(buildFigureUrlQuery({ inline: true, cacheBust: 12345 })).toBe('?inline=1&v=12345')
    expect(buildFigureUrlQuery({ cacheBust: 'v2' })).toBe('?v=v2')
  })

  it('formats byte sizes and layout labels cleanly', () => {
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(12800)).toBe('12.5 KB')
    expect(formatFileSize(1572864)).toBe('1.50 MB')

    expect(formatLayoutLabel('composite')).toBe('复合双拼图 (a+b)')
    expect(formatLayoutLabel('circular')).toBe('环形多环图')
    expect(formatLayoutLabel('rectangular')).toBe('矩形多轨图')
    expect(formatLayoutLabel('custom_view')).toBe('custom_view')
  })
})
