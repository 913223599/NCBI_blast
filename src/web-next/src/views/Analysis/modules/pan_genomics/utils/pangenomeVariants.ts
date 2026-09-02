/**
 * pangenomeVariants.ts - 泛基因组学变异形态探测与功能分类计算引擎
 * 提供全基因组同源基因家族众数长度计算、微观变异类型判别、氨基酸差异分析及分类归一化。
 */
import { FUNCTIONAL_CATEGORIES, inferCategoryFromText } from '../../viewer/utils/render'

export interface ClusterVariantInfo {
  type: 'conserved' | 'truncated' | 'extended' | 'absent'
  className: string
  title: string
  style: Record<string, string>
  variantLabel: string
}

export interface AminoAcidVariationResult {
  type: 'baseline' | 'identical' | 'deletion' | 'insertion' | 'absent'
  badgeText: string
  badgeClass: string
  diffDetail: string
  lengthDelta: number
}

// 统一标准生物学分类别名映射字典
export const CATEGORY_ALIAS_MAP: Record<string, string> = {
  packaging: 'Head & Packaging',
  structural: 'Head & Packaging',
  capsid: 'Head & Packaging',
  head: 'Head & Packaging',
  'head & packaging': 'Head & Packaging',
  tail: 'Tail & Host Interaction',
  'tail & host interaction': 'Tail & Host Interaction',
  fiber: 'Tail & Host Interaction',
  lysis: 'Lysis',
  'lysis system': 'Lysis',
  integration: 'Integration & Excision',
  'integration & excision': 'Integration & Excision',
  excision: 'Integration & Excision',
  defense: 'Defense & Host Interaction',
  'defense & host interaction': 'Defense & Host Interaction',
  acr: 'Defense & Host Interaction',
  replication: 'Replication & Repair',
  'replication & repair': 'Replication & Repair',
  repair: 'Replication & Repair',
  regulation: 'Transcription & Regulation',
  transcription: 'Transcription & Regulation',
  'transcription & regulation': 'Transcription & Regulation',
  metabolism: 'Metabolism & AMG',
  'metabolism & amg': 'Metabolism & AMG',
  amg: 'Metabolism & AMG',
  other: 'Other Functional',
  'other functional': 'Other Functional',
  hypothetical: 'Hypothetical'
}

export const CATEGORY_ORDER: Record<string, number> = {
  'Tail & Host Interaction': 1,
  Lysis: 2,
  'Defense & Host Interaction': 3,
  'Head & Packaging': 4,
  'Integration & Excision': 5,
  'Replication & Repair': 6,
  'Transcription & Regulation': 7,
  'Metabolism & AMG': 8,
  'Other Functional': 9,
  Hypothetical: 10
}

export const CATEGORY_CHINESE_MAP: Record<string, string> = {
  'Head & Packaging': '头部与衣壳包装',
  'Tail & Host Interaction': '尾部与宿主吸附',
  Lysis: '宿主裂解系统',
  'Defense & Host Interaction': '宿主防御与互作',
  'Integration & Excision': '溶源整合与切除',
  'Replication & Repair': 'DNA复制与重组修复',
  'Transcription & Regulation': '转录调控与开关',
  'Metabolism & AMG': '辅助代谢基因 (AMG)',
  'Other Functional': '其他功能蛋白',
  Hypothetical: '假定蛋白与未表征'
}

export function getCategoryChinese(cat?: string): string {
  if (!cat) return '假定蛋白与未表征'
  const norm = normalizeCategoryName(cat)
  return CATEGORY_CHINESE_MAP[norm] || CATEGORY_CHINESE_MAP[cat] || cat
}

export function normalizeCategoryName(raw?: string): string {
  if (!raw) return 'Hypothetical'
  const key = raw.trim().toLowerCase()
  return CATEGORY_ALIAS_MAP[key] || raw
}

export function inferClusterCategory(c: any): string {
  if (!c) return 'Hypothetical'

  // 1. 优先依据代表性产物名称与注释细节重新推断标准分类
  const prod = c.representative_product || c.representative_annotation?.product || c.cluster_name || ''
  const notes = c.notes || c.representative_annotation?.notes || ''
  const inferred = inferCategoryFromText(prod, notes)
  if (inferred && inferred !== 'Hypothetical') {
    return inferred
  }

  // 2. 依据后端原始分类进行标准化别名转换
  if (c.category) {
    const norm = normalizeCategoryName(c.category)
    if (norm && norm !== 'Hypothetical') {
      return norm
    }
  }

  return inferred || 'Hypothetical'
}

export function getCatColor(cat: string): string {
  const norm = normalizeCategoryName(cat)
  if (FUNCTIONAL_CATEGORIES[norm]) {
    return FUNCTIONAL_CATEGORIES[norm].color
  }
  return '#94a3b8'
}

export function getClusterConsensusLen(c: any): number {
  if (!c?.presence_map) return 0
  const lens: number[] = Object.values(c.presence_map)
    .map((m: any) => Number(m?.length_aa || 0))
    .filter((l: number) => l > 0)
  if (lens.length === 0) return 0

  const counts: Record<number, number> = {}
  let maxCount = 0
  let modeLen = lens[0] || 0
  for (const l of lens) {
    counts[l] = (counts[l] || 0) + 1
    if (counts[l] > maxCount) {
      maxCount = counts[l]
      modeLen = l
    }
  }
  return modeLen
}

export function getClusterVariantInfo(
  c: any,
  rowId: string,
  precalculatedConsensusLen?: number,
  precalculatedCategory?: string
): ClusterVariantInfo {
  const item = c.presence_map?.[rowId]
  if (!item) {
    return {
      type: 'absent',
      className: '',
      title: '该样本缺失此 CDS',
      style: {},
      variantLabel: '缺失'
    }
  }

  const consensusLen = precalculatedConsensusLen ?? (c._consensusLen ?? getClusterConsensusLen(c))
  const len = Number(item.length_aa || 0)
  const effectiveCat = precalculatedCategory || c._inferredCategory || inferClusterCategory(c)
  const catColor = getCatColor(effectiveCat)

  // 1. 完全等长保守
  if (!consensusLen || len === consensusLen) {
    return {
      type: 'conserved',
      className: 'sq-conserved',
      title: `${c.group_id} (${effectiveCat}): ${c.representative_product || item.product || ''} · [等长保守] ${len} aa (与群体众数一致)`,
      style: {
        backgroundColor: catColor
      },
      variantLabel: '等长保守'
    }
  }

  const delta = len - consensusLen
  // 2. 缺失截短变异 (Truncated / Deletion)
  if (delta < 0) {
    const absDelta = Math.abs(delta)
    const pct = ((absDelta / consensusLen) * 100).toFixed(0)
    return {
      type: 'truncated',
      className: 'sq-truncated',
      title: `${c.group_id} (${effectiveCat}): ${c.representative_product || item.product || ''} · [缺失截短] -${absDelta} aa (${pct}% 截短，当前 ${len} aa vs 众数 ${consensusLen} aa)`,
      style: {
        backgroundColor: catColor
      },
      variantLabel: `缺失截短 (-${absDelta} aa)`
    }
  }

  // 3. 插入延长变异 (Extended / Insertion)
  const pct = ((delta / consensusLen) * 100).toFixed(0)
  return {
    type: 'extended',
    className: 'sq-extended',
    title: `${c.group_id} (${effectiveCat}): ${c.representative_product || item.product || ''} · [插入延长] +${delta} aa (+${pct}% 延长，当前 ${len} aa vs 众数 ${consensusLen} aa)`,
    style: {
      backgroundColor: catColor
    },
    variantLabel: `插入延长 (+${delta} aa)`
  }
}

export function getAminoAcidVariation(cluster: any, sid: string, baselineSid: string): AminoAcidVariationResult {
  if (!cluster) {
    return { type: 'absent', badgeText: '缺失', badgeClass: 'var-absent', diffDetail: '—', lengthDelta: 0 }
  }

  const item = cluster.presence_map?.[sid]
  const baseItem = cluster.presence_map?.[baselineSid]

  // 1. 基准样本自身
  if (sid === baselineSid) {
    const len = item?.length_aa || 0
    return {
      type: 'baseline',
      badgeText: '[基准] 对照基准',
      badgeClass: 'var-baseline',
      diffDetail: `基准序列 (${len} aa)`,
      lengthDelta: 0
    }
  }

  // 2. 当前样本缺失此基因
  if (!item) {
    const baseLen = Number(baseItem?.length_aa || 0)
    return {
      type: 'absent',
      badgeText: '基因完全缺失',
      badgeClass: 'var-absent',
      diffDetail: baseLen ? `较基准全长缺失 -${baseLen} aa (-100%)` : '该样本未编码此 CDS',
      lengthDelta: -baseLen
    }
  }

  const targetLen = Number(item.length_aa || 0)
  const baseLen = Number(baseItem?.length_aa || 0)

  // 3. 基准株缺失但当前株存在
  if (!baseItem || baseLen === 0) {
    return {
      type: 'identical',
      badgeText: '单方存在',
      badgeClass: 'var-present',
      diffDetail: `${targetLen} aa (对照基准株缺失此基因)`,
      lengthDelta: targetLen
    }
  }

  const delta = targetLen - baseLen

  // 4. 缺失 / 截短 (Deletion / Truncation)
  if (delta < 0) {
    const absDelta = Math.abs(delta)
    const pct = ((absDelta / baseLen) * 100).toFixed(1)
    return {
      type: 'deletion',
      badgeText: `缺失截短 (-${absDelta} aa)`,
      badgeClass: 'var-deletion',
      diffDetail: `较基准缺失 ${absDelta} 个氨基酸 (${pct}% 长度截短)`,
      lengthDelta: delta
    }
  }

  // 5. 插入 / 延长 (Insertion / Extension)
  if (delta > 0) {
    const pct = ((delta / baseLen) * 100).toFixed(1)
    return {
      type: 'insertion',
      badgeText: `插入延长 (+${delta} aa)`,
      badgeClass: 'var-insertion',
      diffDetail: `较基准插入 +${delta} 个氨基酸 (+${pct}% 长度延长)`,
      lengthDelta: delta
    }
  }

  // 6. 等长同源 (Identical / Point Mutation candidate)
  return {
    type: 'identical',
    badgeText: '等长保守',
    badgeClass: 'var-identical',
    diffDetail: `长度完全一致 (${targetLen} aa) · 同源结构域保守`,
    lengthDelta: 0
  }
}
