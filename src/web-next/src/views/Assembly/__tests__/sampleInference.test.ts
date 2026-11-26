import { describe, it, expect } from 'vitest'
import { extractCleanSampleName, inferTechAndType } from '../utils/sampleInference'

describe('Assembly sampleInference utils', () => {
  it('extractCleanSampleName 应剥离多层扩展名与测序修饰后缀', () => {
    expect(extractCleanSampleName('Ecoli_K12_R1_clean.fastq.gz')).toBe('Ecoli_K12')
    expect(extractCleanSampleName('Phage_vB_ont_filtered.fq.bz2')).toBe('Phage_vB')
    expect(extractCleanSampleName('SampleA_2.trimmed.fasta')).toBe('SampleA')
    expect(extractCleanSampleName('Demo_val_1.fq.gz')).toBe('Demo')
    expect(extractCleanSampleName('.fastq.gz')).toBe('.fastq.gz')
  })

  it('inferTechAndType 应准确识别测序技术平台与样本生物类型', () => {
    expect(
      inferTechAndType([{ name: 'ecoli_R1.fq.gz' }, { name: 'ecoli_R2.fq.gz' }], 'ecoli_R1.fq.gz', 'ecoli_R2.fq.gz')
    ).toEqual({
      detectedTech: 'ILLUMINA',
      detectedSampleType: 'BACTERIA',
      detectedMode: 'isolate',
    })

    expect(
      inferTechAndType([{ name: 'phage_minion.fastq.gz' }], 'phage_minion.fastq.gz')
    ).toEqual({
      detectedTech: 'NANOPORE',
      detectedSampleType: 'PHAGE',
      detectedMode: 'isolate',
    })

    expect(
      inferTechAndType([{ name: 'soil_metagenome_hifi.fastq' }], 'soil_metagenome_hifi.fastq')
    ).toEqual({
      detectedTech: 'PACBIO_HIFI',
      detectedSampleType: 'METAGENOME',
      detectedMode: 'metagenome',
    })

    expect(
      inferTechAndType(
        [{ name: 'viral_R1.fq.gz' }, { name: 'viral_R2.fq.gz' }, { name: 'viral_ont.fq.gz' }],
        'viral_R1.fq.gz',
        'viral_R2.fq.gz',
        'viral_ont.fq.gz'
      )
    ).toEqual({
      detectedTech: 'HYBRID',
      detectedSampleType: 'VIRUS',
      detectedMode: 'hybrid',
    })
  })
})
