export type SampleBioType = 'BACTERIA' | 'PHAGE' | 'VIRUS' | 'METAGENOME'
export type SequencingTech = 'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI' | 'HYBRID'
export type AssemblyMode = 'isolate' | 'metagenome' | 'metagenome_deep' | 'unconstrained' | 'hybrid'

export interface TechAndTypeInference {
  detectedTech: SequencingTech
  detectedSampleType: SampleBioType
  detectedMode: AssemblyMode
}

/** 深度剥离扩展名与读长修饰词，提取纯净样本名 */
export function extractCleanSampleName(filename: string): string {
  let name = filename
  while (true) {
    const nextName = name.replace(/\.(fastq|fq|fasta|fa|fna|gz|tar|ab1|txt|bz2|zip)$/i, '')
    if (nextName === name) break
    name = nextName
  }
  while (true) {
    const nextName = name.replace(
      /[._-](R1|R2|1|2|read1|read2|forward|reverse|clean|raw|filtered|trimmed|val_1|val_2|subsample|pass|paired|ont|nanopore|hifi|pacbio|mgi|illumina|ngs)$/i,
      ''
    )
    if (nextName === name) break
    name = nextName
  }
  return name.trim() || filename
}

/** 根据文件名特征智能推断测序技术平台与样本生物类型 */
export function inferTechAndType(
  files: Array<{ name: string }>,
  r1Name: string,
  r2Name?: string,
  lrName?: string
): TechAndTypeInference {
  const combinedNames = [r1Name, r2Name || '', lrName || '', ...files.map((f) => f.name)].join(' ').toLowerCase()

  let detectedTech: SequencingTech = 'ILLUMINA'
  const hasLongReads =
    combinedNames.includes('ont') ||
    combinedNames.includes('nanopore') ||
    combinedNames.includes('hifi') ||
    combinedNames.includes('pacbio') ||
    combinedNames.includes('minion') ||
    combinedNames.includes('promethion') ||
    combinedNames.includes('gridion') ||
    combinedNames.includes('dorado') ||
    combinedNames.includes('guppy') ||
    combinedNames.includes('_lr') ||
    combinedNames.includes('.lr.')
  const hasShortReads =
    combinedNames.includes('illumina') ||
    combinedNames.includes('mgi') ||
    combinedNames.includes('_1.') ||
    combinedNames.includes('_2.') ||
    combinedNames.includes('_r1') ||
    combinedNames.includes('_r2') ||
    combinedNames.includes('read1') ||
    combinedNames.includes('read2') ||
    combinedNames.includes('forward') ||
    combinedNames.includes('reverse')

  if (lrName || (hasLongReads && hasShortReads) || (files.length >= 3 && hasLongReads)) {
    detectedTech = 'HYBRID'
  } else if (
    combinedNames.includes('hifi') ||
    combinedNames.includes('pacbio') ||
    combinedNames.includes('ccs') ||
    combinedNames.includes('sequel') ||
    combinedNames.includes('revio')
  ) {
    detectedTech = 'PACBIO_HIFI'
  } else if (hasLongReads) {
    detectedTech = 'NANOPORE'
  } else if (files.length >= 2 || r2Name || hasShortReads) {
    detectedTech = 'ILLUMINA'
  } else if (combinedNames.endsWith('.zip') || combinedNames.includes('.zip')) {
    detectedTech = 'NANOPORE'
  }

  let detectedSampleType: SampleBioType = 'BACTERIA'
  let detectedMode: AssemblyMode = detectedTech === 'HYBRID' ? 'hybrid' : 'isolate'

  if (
    combinedNames.includes('phage') ||
    combinedNames.includes('bacteriophage') ||
    combinedNames.includes('噬菌体') ||
    combinedNames.includes('phi')
  ) {
    detectedSampleType = 'PHAGE'
    detectedMode = detectedTech === 'HYBRID' ? 'hybrid' : 'isolate'
  } else if (combinedNames.includes('virus') || combinedNames.includes('viral') || combinedNames.includes('病毒')) {
    detectedSampleType = 'VIRUS'
    detectedMode = detectedTech === 'HYBRID' ? 'hybrid' : 'isolate'
  } else if (
    combinedNames.includes('meta') ||
    combinedNames.includes('metagenome') ||
    combinedNames.includes('宏基因组') ||
    combinedNames.includes('microbiome') ||
    combinedNames.includes('env')
  ) {
    detectedSampleType = 'METAGENOME'
    detectedMode = detectedTech === 'HYBRID' ? 'hybrid' : 'metagenome'
  }

  return { detectedTech, detectedSampleType, detectedMode }
}
