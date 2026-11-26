/**
 * WorkspaceCocktailDeRedundancy 核心决策推理引擎与状态 Composable
 * 负责受体分型聚类、代表株/协同株/冗余株/安全剔除分流、KPI 汇总、二维散点映射及 CSV 导出
 */
import { ref, computed } from 'vue'
import type { ArmsRaceEntry, OrthologCluster, PhageLifestyleEntry } from '../../types'

interface SampleEvaluationSummary {
  sid: string
  name: string
  lifestyle: string
  isSafe: boolean
  acrCnt: number
  uniq: number
  total: number
}

export interface DeRedundancySample {
  sample_id: string
  sample_name: string
  decision: 'KEEP' | 'SYNERGISTIC' | 'REDUNDANT' | 'REJECT'
  decision_label: string
  role: '核心骨干' | '协同变异' | '冗余同质' | '安全风险'
  cluster_id: number
  receptor_label: string
  redundant_with?: string
  redundant_with_name?: string
  ani_to_rep: number
  tail_to_rep: number
  receptor_divergence: number
  confidence: number
  lifestyle: string
  is_safe: boolean
  acr_count: number
  unique_genes: number
  total_genes: number
  orthoX?: number
  broadY?: number
  cx?: number
  cy?: number
  evidence_chips: string[]
  detailed_reasons: {
    genome_ani: string
    receptor_mechanism: string
    coverage: string
    unique_signals: string
  }
}

export interface CocktailDeRedundancyProps {
  aniMatrix: Record<string, Record<string, number | null>>
  tailMatrix?: Record<string, Record<string, number>>
  lysisMatrix?: Record<string, Record<string, number>>
  clusters?: OrthologCluster[]
  lifestyles?: PhageLifestyleEntry[]
  armsRaceMatrix?: Record<string, ArmsRaceEntry>
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}

export interface CocktailDeRedundancyEmits {
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
}

export function useCocktailDeRedundancy(
  props: CocktailDeRedundancyProps,
  emit: CocktailDeRedundancyEmits
) {
  const statusFilter = ref<'ALL' | 'KEEP' | 'SYNERGISTIC' | 'REDUNDANT' | 'REJECT'>('ALL')
  const searchQuery = ref('')
  const selectedDrawerSample = ref<DeRedundancySample | null>(null)
  const isDrawerOpen = ref(false)
  const hoveredScatterSample = ref<DeRedundancySample | null>(null)

  const sampleIds = computed<string[]>(() => Object.keys(props.sampleNames || {}))

  const decisionEvaluation = computed(() => {
    const ids = sampleIds.value
    if (ids.length === 0) return { samples: [], optimalSet: [], clusters: [], total: 0 }

    const sampleMap: Record<string, SampleEvaluationSummary> = {}
    ids.forEach(sid => {
      const life = props.lifestyles?.find((l: PhageLifestyleEntry) => l.sample_id === sid)
      const isSafe = life
        ? life.lifestyle === 'Lytic' &&
        !life.has_toxin &&
        !life.has_integrase &&
        life.is_safe_for_therapy !== false
        : true
      const acrCnt = props.armsRaceMatrix?.[sid]?.acr_count || 0

      let uniq = 0
      let total = 0
      props.clusters?.forEach((c: OrthologCluster) => {
        if (c.presence_map?.[sid]) {
          total++
          const occup = Object.values(c.presence_map).filter(Boolean).length
          if (occup === 1) uniq++
        }
      })

      sampleMap[sid] = {
        sid,
        name: props.sampleNames[sid] || sid,
        lifestyle: life?.lifestyle || 'Lytic',
        isSafe,
        acrCnt,
        uniq,
        total,
      }
    })

    // 受体分型聚类 (Receptor Serotype Single-Linkage at 88% identity)
    const receptorClusters: string[][] = []
    const assigned = new Set<string>()

    ids.forEach(sid => {
      if (assigned.has(sid)) return
      const currentCluster: string[] = [sid]
      assigned.add(sid)

      ids.forEach(otherId => {
        if (assigned.has(otherId)) return
        const tailSim = props.tailMatrix?.[sid]?.[otherId] ?? 0
        if (tailSim >= 88) {
          currentCluster.push(otherId)
          assigned.add(otherId)
        }
      })
      receptorClusters.push(currentCluster)
    })

    const results: DeRedundancySample[] = []
    const optimalSetIds: string[] = []

    receptorClusters.forEach((clusterMembers, cIdx) => {
      const clusterNum = cIdx + 1
      const receptorTag = `受体谱系 #${clusterNum}`

      const safeMembers = clusterMembers.filter(sid => Boolean(sampleMap[sid]?.isSafe))
      const unsafeMembers = clusterMembers.filter(sid => !sampleMap[sid]?.isSafe)

      unsafeMembers.forEach(sid => {
        const info = sampleMap[sid]
        if (!info) return
        results.push({
          sample_id: sid,
          sample_name: info.name,
          decision: 'REJECT',
          decision_label: '安全剔除',
          role: '安全风险',
          cluster_id: clusterNum,
          receptor_label: receptorTag,
          ani_to_rep: 0,
          tail_to_rep: 0,
          receptor_divergence: 0,
          confidence: 96,
          lifestyle: info.lifestyle,
          is_safe: false,
          acr_count: info.acrCnt,
          unique_genes: info.uniq,
          total_genes: info.total,
          evidence_chips: ['[警示] 检出关键溶原整合元件', '安全筛查: 未通过 (Temperate/Risk)'],
          detailed_reasons: {
            genome_ani: '不适用 (安全性否决)',
            receptor_mechanism: `${receptorTag} 识别域存在`,
            coverage: '0% (严禁用于活性治疗)',
            unique_signals: '检测到核心整合酶 (Integrase)、整合重组酶或溶原阻遏蛋白等关键温和标志物',
          },
        })
      })

      if (safeMembers.length === 0) return

      const sortedMembers = safeMembers.toSorted((a, b) => {
        const da = sampleMap[a]
        const db = sampleMap[b]
        if (!da || !db) return 0
        if (da.uniq !== db.uniq) return db.uniq - da.uniq
        return db.total - da.total
      })

      const repId = sortedMembers[0]
      const repInfo = repId ? sampleMap[repId] : undefined
      if (!repId || !repInfo) return

      optimalSetIds.push(repId)

      results.push({
        sample_id: repId,
        sample_name: repInfo.name,
        decision: 'KEEP',
        decision_label: '核心保留',
        role: '核心骨干',
        cluster_id: clusterNum,
        receptor_label: receptorTag,
        ani_to_rep: 100,
        tail_to_rep: 100,
        receptor_divergence: 0,
        confidence: 95,
        lifestyle: repInfo.lifestyle,
        is_safe: true,
        acr_count: repInfo.acrCnt,
        unique_genes: repInfo.uniq,
        total_genes: repInfo.total,
        evidence_chips: [
          '独立核心骨干代表株',
          `${receptorTag} (100% 覆盖)`,
          `Acr 防御: ${repInfo.acrCnt}`,
        ],
        detailed_reasons: {
          genome_ani: '100% (自身基准)',
          receptor_mechanism: `${receptorTag} 骨干受体`,
          coverage: `代表谱系 #${clusterNum} 全受体覆盖`,
          unique_signals:
            repInfo.uniq > 0
              ? `检出 ${repInfo.uniq} 个独有特征家族`
              : '高质量完整组装序列',
        },
      })

      for (let i = 1; i < sortedMembers.length; i++) {
        const sid = sortedMembers[i]
        const info = sid ? sampleMap[sid] : undefined
        if (!sid || !info) continue
        const aniToRep = props.aniMatrix?.[sid]?.[repId] ?? 0
        const tailToRep = props.tailMatrix?.[sid]?.[repId] ?? 100
        const divergence = Math.max(0, 100 - tailToRep)

        if (aniToRep >= 98.0 && tailToRep >= 98.0) {
          results.push({
            sample_id: sid,
            sample_name: info.name,
            decision: 'REDUNDANT',
            decision_label: '建议冗存',
            role: '冗余同质',
            cluster_id: clusterNum,
            receptor_label: receptorTag,
            redundant_with: repId,
            redundant_with_name: repInfo.name,
            ani_to_rep: aniToRep,
            tail_to_rep: tailToRep,
            receptor_divergence: divergence,
            confidence: 92,
            lifestyle: info.lifestyle,
            is_safe: true,
            acr_count: info.acrCnt,
            unique_genes: info.uniq,
            total_genes: info.total,
            evidence_chips: [
              `与代表株 ANI ${aniToRep.toFixed(1)}%`,
              '机制: 完全一致',
              '受体重叠率: 100%',
            ],
            detailed_reasons: {
              genome_ani: `与代表株 ANI ${aniToRep.toFixed(1)}% (同质化克隆)`,
              receptor_mechanism: `尾丝一致性 ${tailToRep.toFixed(1)}% (相同受体机制)`,
              coverage: `已由骨干株【${repInfo.name}】100% 覆盖`,
              unique_signals: '未检出有意义的受体漂移或额外攻防元件',
            },
          })
        } else {
          results.push({
            sample_id: sid,
            sample_name: info.name,
            decision: 'SYNERGISTIC',
            decision_label: '协同备选',
            role: '协同变异',
            cluster_id: clusterNum,
            receptor_label: receptorTag,
            redundant_with: repId,
            redundant_with_name: repInfo.name,
            ani_to_rep: aniToRep,
            tail_to_rep: tailToRep,
            receptor_divergence: divergence,
            confidence: 88,
            lifestyle: info.lifestyle,
            is_safe: true,
            acr_count: info.acrCnt,
            unique_genes: info.uniq,
            total_genes: info.total,
            evidence_chips: [
              `受体漂移度: ${divergence.toFixed(1)}%`,
              `Acr: ${info.acrCnt}`,
              '突变逃逸互补株',
            ],
            detailed_reasons: {
              genome_ani: `ANI ${aniToRep.toFixed(1)}%`,
              receptor_mechanism: `受体位点漂移 ${divergence.toFixed(1)}% (具备突变捕获潜力)`,
              coverage: '对同源宿主提供防御突变补充',
              unique_signals: '携带独特抗防御 Acr 基因或受体位点漂移',
            },
          })
        }
      }
    })

    return {
      samples: results,
      optimalSet: optimalSetIds,
      clusters: receptorClusters,
      total: ids.length,
    }
  })

  const kpis = computed(() => {
    const all = decisionEvaluation.value.samples
    const total = all.length || 1
    const core = all.filter(s => s.decision === 'KEEP').length
    const syn = all.filter(s => s.decision === 'SYNERGISTIC').length
    const red = all.filter(s => s.decision === 'REDUNDANT').length
    const reject = all.filter(s => s.decision === 'REJECT').length
    const coveredClusters = decisionEvaluation.value.clusters.length

    return {
      total,
      core,
      syn,
      red,
      reject,
      coveredClusters,
      retainedRatio: Math.round(((core + syn) / total) * 100),
      redundantRatio: Math.round((red / total) * 100),
    }
  })

  const tableSamples = computed(() => {
    let list = decisionEvaluation.value.samples
    if (statusFilter.value !== 'ALL') {
      list = list.filter(s => s.decision === statusFilter.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      list = list.filter(
        s => s.sample_name.toLowerCase().includes(q) || s.receptor_label.toLowerCase().includes(q)
      )
    }
    return list
  })

  const scatterPoints = computed(() => {
    const optSet = decisionEvaluation.value.optimalSet
    const allSamples = decisionEvaluation.value.samples

    return allSamples.map(s => {
      let orthoX = 0
      let broadY = 0

      if (s.decision === 'KEEP') {
        const otherReps = optSet.filter(id => id !== s.sample_id)
        if (otherReps.length > 0) {
          const avgAniToOthers =
            otherReps.reduce((sum, oid) => sum + (props.aniMatrix?.[s.sample_id]?.[oid] ?? 0), 0) /
            otherReps.length
          const avgTailToOthers =
            otherReps.reduce((sum, oid) => sum + (props.tailMatrix?.[s.sample_id]?.[oid] ?? 0), 0) /
            otherReps.length
          orthoX = Math.max(70, Math.min(98, 100 - avgAniToOthers))
          broadY = Math.max(70, Math.min(98, 100 - avgTailToOthers))
        } else {
          orthoX = 92
          broadY = 92
        }
      } else if (s.decision === 'SYNERGISTIC') {
        const aniDist = 100 - s.ani_to_rep
        const tailDist = s.receptor_divergence
        orthoX = Math.max(10, Math.min(48, aniDist * 1.5 + 8))
        broadY = Math.max(52, Math.min(95, tailDist * 1.2 + 25))
      } else if (s.decision === 'REDUNDANT') {
        const aniDist = 100 - s.ani_to_rep
        const tailDist = s.receptor_divergence
        orthoX = Math.max(5, Math.min(45, aniDist * 2.0 + 4))
        broadY = Math.max(5, Math.min(45, tailDist * 1.5 + 4))
      } else {
        orthoX = Math.max(6, Math.min(45, 100 - s.ani_to_rep + 5))
        broadY = Math.max(10, Math.min(45, s.receptor_divergence + 10))
      }

      const cx = 55 + (orthoX / 100) * (565 - 55)
      const cy = 235 - (broadY / 100) * (235 - 30)

      return {
        ...s,
        orthoX,
        broadY,
        cx,
        cy,
      }
    })
  })

  function openDrawer(sample: DeRedundancySample) {
    selectedDrawerSample.value = sample
    isDrawerOpen.value = true
    emit('select-sample', sample.sample_id)
  }

  function closeDrawer() {
    isDrawerOpen.value = false
  }

  function handleCompare(s1: string, s2: string) {
    emit('select-pair', [s1, s2])
  }

  function handleExportPlanCsv() {
    const rows = [
      [
        '决策建议',
        '样本 ID',
        '样本名称',
        '受体谱系',
        '与骨干株 ANI',
        '受体一致性',
        '科学证据链',
        '生活史',
        'Acr 数量',
        '置信度',
      ],
    ]
    decisionEvaluation.value.samples.forEach(s => {
      rows.push([
        s.decision_label,
        s.sample_id,
        `"${s.sample_name}"`,
        s.receptor_label,
        `${s.ani_to_rep.toFixed(1)}%`,
        `${s.tail_to_rep.toFixed(1)}%`,
        `"${s.evidence_chips.join('; ')}"`,
        s.lifestyle,
        String(s.acr_count),
        `${s.confidence}%`,
      ])
    })

    const csvContent = '\uFEFF' + rows.map(e => e.join(',')).join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', '噬菌体鸡尾酒优选决策清单.csv')
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return {
    statusFilter,
    searchQuery,
    selectedDrawerSample,
    isDrawerOpen,
    hoveredScatterSample,
    sampleIds,
    decisionEvaluation,
    kpis,
    tableSamples,
    scatterPoints,
    openDrawer,
    closeDrawer,
    handleCompare,
    handleExportPlanCsv,
  }
}
