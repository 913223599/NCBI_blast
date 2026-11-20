import { describe, expect, it } from 'vitest'
import {
  buildModuleMatrixCards,
  compactLocusLabel,
  countFastaRecords,
  deriveStructureTaskName,
  detectSequenceFormatLabel,
  formatGenomeBp,
  formatTailLength,
  getMorphotypeTheme,
  getRoleModuleGroup,
  getRoleTrackColor,
} from '../utils'

describe('phage_structure utils', () => {
  it('maps morphotype codes to distinct themes and falls back safely', () => {
    const myo = getMorphotypeTheme('Myoviridae-like')
    expect(myo.shortLabel).toBe('肌尾 Myo')
    expect(myo.accentColor).toBe('#2563eb')

    const sipho = getMorphotypeTheme('Siphoviridae-like')
    expect(sipho.shortLabel).toBe('长尾 Sipho')

    const podo = getMorphotypeTheme('Podoviridae-like')
    expect(podo.shortLabel).toBe('短尾 Podo')

    const unknown = getMorphotypeTheme('SomethingUnexpected')
    expect(unknown.shortLabel).toBe('不完整')
  })

  it('builds 6-module matrix summary with highlighted states', () => {
    const cards = buildModuleMatrixCards({
      head_packaging_count: 3,
      connector_count: 2,
      tail_sheath_count: 1,
      tail_tube_count: 1,
      major_tail_count: 0,
      tail_assembly_chaperone_count: 0,
      tape_measure_count: 1,
      tail_tubular_ab_count: 0,
      internal_virion_count: 0,
      tail_needle_count: 0,
      baseplate_count: 4,
      tail_fiber_rbp_count: 2,
      lysis_count: 1,
      integrase_count: 0,
      non_tailed_marker_count: 0,
      t6ss_confounder_count: 0,
    })
    expect(cards).toHaveLength(6)
    expect(cards.find((c) => c.key === 'myo')?.highlighted).toBe(true)
    expect(cards.find((c) => c.key === 'podo')?.highlighted).toBe(false)
    expect(cards.find((c) => c.key === 'rbp_lysis')?.count).toBe(3)
  })

  it('formats bp length, estimated tail length and structural role tracks', () => {
    expect(formatGenomeBp(49254)).toBe('49.25 kb')
    expect(formatTailLength(123.7, [119.4, 128.0])).toContain('123.7 nm')
    expect(formatTailLength(null)).toContain('未定标')
    expect(getRoleModuleGroup('TMP')).toBe('tail_core')
    expect(getRoleTrackColor('TSP')).toBe('#1d4ed8')
    expect(getRoleTrackColor('TMP')).toBe('#f59e0b')
  })

  it('derives batch task names, formats, fasta record counts, and compact locus tags', () => {
    expect(deriveStructureTaskName('/data/phages/Enterobacter_p2.gbk.gz')).toBe('Enterobacter_p2_Structure')
    expect(detectSequenceFormatLabel('sample.gbff')).toBe('GBK')
    expect(detectSequenceFormatLabel('proteins.faa')).toBe('FAA')
    expect(detectSequenceFormatLabel('phage.fna.gz')).toBe('FASTA')
    expect(compactLocusLabel('NODE_1_length_72586_cov_126.271825_CDS_0012', 20)).toContain('CDS_0012')
    expect(compactLocusLabel('SHORT_01', 20)).toBe('SHORT_01')
    expect(countFastaRecords('>seq1\nATGC\n>seq2\nGGGG\n')).toBe(2)
  })
})
