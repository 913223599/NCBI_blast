export interface PhageBadgeMeta {
  modelId?: string
  modelVersion?: string
  modelLabel?: string
  featureProfile?: string
  hasUnifiedJudge?: boolean
}

export function formatPhageModelBadge(meta: PhageBadgeMeta): string {
  const ver = String(meta.modelVersion || '')
  const lbl = String(meta.modelLabel || '')
  if (
    meta.hasUnifiedJudge ||
    meta.modelId === 'unified' ||
    ver.includes('Unified') ||
    lbl.includes('Unified')
  ) {
    return ver || 'Unified V4'
  }
  if (meta.featureProfile === 'stage1' || lbl.includes('Stage 1.2') || meta.modelId === 'stage1_2') {
    return 'Stage 1.2'
  }
  return ver || 'Student V4.2'
}

