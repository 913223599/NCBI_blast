<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useAppStore } from '../../../../../stores/app'
import { useI18n } from '../../../../../locales'
import type { ContigStructureResult, PhageStructureResult, StructureProteinItem, StructureTaskHistoryItem } from '../types'
import {
  buildModuleMatrixCards,
  formatCompletenessStatus,
  formatGenomeBp,
  formatTailLength,
  getMorphotypeTheme,
} from '../utils'
import StructuralOperonTrack from './StructuralOperonTrack.vue'
import TailMorphotypeDiagram from './TailMorphotypeDiagram.vue'
import TmpRulerChart from './TmpRulerChart.vue'
import type { Protein3DInitialContext } from './Protein3DViewerModal.vue'

const Protein3DViewerModal = defineAsyncComponent(() => import('./Protein3DViewerModal.vue'))

const props = defineProps<{
  task: StructureTaskHistoryItem
  result: PhageStructureResult | null
  isLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'download', fileType: 'json' | 'summary_tsv' | 'features_tsv' | 'tmp_tsv' | 'gbk'): void
  (e: 'open-folder'): void
  (e: 'open-viewer'): void
}>()

const appStore = useAppStore()
const { t } = useI18n()
const activeContigId = ref<string>('')
const roleFilter = ref<'ALL' | 'STRUCTURAL'>('STRUCTURAL')
const searchText = ref<string>('')
const is3DViewerOpen = ref<boolean>(false)
const viewer3DContext = ref<Protein3DInitialContext | null>(null)

function open3DViewerForProtein(item?: StructureProteinItem): void {
  viewer3DContext.value = {
    taskId: props.result?.task_id || props.task?.task_id,
    locusTag: item?.locus_tag,
    product: item?.product || activeContig.value?.prediction?.morphotype_label_cn,
    lengthAa: item?.length_aa,
  }
  is3DViewerOpen.value = true
}

function buildProteinFasta(item: StructureProteinItem): string {
  const header = `>${item.locus_tag} ${item.role_label_cn || item.structural_role} | ${item.product || 'hypothetical protein'} | ${item.length_aa}aa`
  const seq = (item.translation || '').replace(/\s+/g, '')
  const lines: string[] = []
  for (let i = 0; i < seq.length; i += 80) {
    lines.push(seq.slice(i, i + 80))
  }
  return `${header}\n${lines.join('\n')}`
}

async function copyProteinFasta(item: StructureProteinItem): Promise<void> {
  if (!item.translation) {
    appStore.showNotification('该蛋白条目不含氨基酸序列', 'warning')
    return
  }
  try {
    await navigator.clipboard.writeText(buildProteinFasta(item))
    appStore.showNotification(`已复制 ${item.locus_tag} FASTA（可用于 AlphaFold / ESMFold 3D 建模）`, 'success')
  } catch {
    appStore.showNotification('剪贴板写入受限，请尝试导出 FAA 文件', 'warning')
  }
}

function exportStructuralProteinsFaa(): void {
  const items = filteredProteins.value.filter((p) => Boolean(p.translation))
  if (!items.length) {
    appStore.showNotification('当前筛选范围内无可导出的氨基酸序列', 'warning')
    return
  }
  const content = items.map(buildProteinFasta).join('\n') + '\n'
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const safeName = (activeContig.value?.contig_id || props.result?.task_name || 'phage').replace(/[^a-zA-Z0-9._-]/g, '_')
  link.href = url
  link.download = `${safeName}_structural_proteins.faa`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  appStore.showNotification(`已导出 ${items.length} 条结构蛋白 FAA，可用于 AlphaFold / Mol* 3D 结构分析`, 'success')
}

watch(
  () => props.result?.task_id,
  () => {
    const first = props.result?.contigs?.[0]
    activeContigId.value = first?.contig_id || ''
  },
  { immediate: true }
)

const activeContig = computed<ContigStructureResult | null>(() => {
  const list = props.result?.contigs || []
  if (!list.length) return null
  return list.find((c) => c.contig_id === activeContigId.value) || list[0] || null
})

const theme = computed(() => getMorphotypeTheme(activeContig.value?.prediction.morphotype_code))
const moduleCards = computed(() =>
  activeContig.value ? buildModuleMatrixCards(activeContig.value.module_matrix) : []
)

const classScoreEntries = computed(() => {
  const scores = activeContig.value?.prediction.class_scores || {}
  const entries = Object.entries(scores).sort((a, b) => b[1] - a[1])
  const maxVal = Math.max(1, ...entries.map((e) => e[1]))
  return entries.map(([code, val]) => ({
    code,
    val,
    pct: Math.round((val / maxVal) * 100),
    theme: getMorphotypeTheme(code),
  }))
})

const aiProbEntries = computed(() => {
  const probs = activeContig.value?.ai_prediction?.calibrated_probs || {}
  return Object.entries(probs)
    .sort((a, b) => b[1] - a[1])
    .map(([code, prob]) => ({
      code,
      prob,
      pct: Math.round(prob * 1000) / 10,
      theme: getMorphotypeTheme(code),
    }))
})

const filteredProteins = computed(() => {
  const list = activeContig.value?.structural_proteins || []
  const kw = searchText.value.trim().toLowerCase()
  return list.filter((p) => {
    if (roleFilter.value === 'STRUCTURAL' && p.structural_role === 'OTHER' && !p.ptf_is_tail) return false
    if (!kw) return true
    return (
      p.locus_tag.toLowerCase().includes(kw) ||
      p.product.toLowerCase().includes(kw) ||
      (p.phrog_id || '').toLowerCase().includes(kw) ||
      (p.ptf_pfam || '').toLowerCase().includes(kw) ||
      (p.role_label_cn || '').toLowerCase().includes(kw)
    )
  })
})
</script>

<template>
  <div class="results-root">
    <div v-if="isLoading" class="loading-box">加载中...</div>

    <template v-else-if="result && activeContig">
      <!-- 1. 顶部操作工具栏 -->
      <div class="top-bar">
        <div class="tb-left">
          <h3>{{ result.task_name }}</h3>
          <span
            class="morph-badge"
            :style="{
              backgroundColor: theme.badgeBg,
              color: theme.badgeText,
              borderColor: theme.badgeBorder,
            }"
          >
            {{ activeContig.prediction.morphotype_label_cn }}
          </span>
          <span
            v-if="activeContig.phold_3d_triggered"
            class="time-chip phold-chip"
            :title="activeContig.phold_3d_trigger_reason || '已触发 Phold 3D 结构复核'"
          >
            3D 复核 +{{ activeContig.phold_3d_rescued_orfs ?? 0 }} ORF
          </span>
          <span class="time-chip">耗时 {{ result.elapsed_sec }} s</span>
        </div>

        <div class="tb-actions">
          <button
            v-if="result.files?.gbk"
            type="button"
            class="primary-btn"
            @click="emit('open-viewer')"
          >
            图谱查看
          </button>
          <button type="button" class="act-btn" @click="open3DViewerForProtein()">{{ t('structure3d.open_btn') }}</button>
          <button type="button" class="act-btn" @click="exportStructuralProteinsFaa">导出结构蛋白 FAA</button>
          <button type="button" class="act-btn" @click="emit('download', 'summary_tsv')">汇总 TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'features_tsv')">基因 TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'tmp_tsv')">TMP TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'json')">JSON</button>
          <button type="button" class="act-btn" @click="emit('open-folder')">打开目录</button>
        </div>
      </div>

      <!-- 多 Contig 选择条 -->
      <div v-if="result.contigs.length > 1" class="contig-switcher">
        <span class="cs-label">Contig ({{ result.contigs.length }}):</span>
        <button
          v-for="c in result.contigs"
          :key="c.contig_id"
          type="button"
          class="cs-btn"
          :class="{ active: c.contig_id === activeContig.contig_id }"
          @click="activeContigId = c.contig_id"
        >
          {{ c.contig_id }} ({{ getMorphotypeTheme(c.prediction.morphotype_code).shortLabel }})
        </button>
      </div>

      <!-- 2. 核心 4 大 KPI 看板 -->
      <div class="kpi-grid">
        <div class="kpi-card highlight" :style="{ borderColor: theme.badgeBorder }">
          <div class="k-lbl">形态</div>
          <div class="k-val" :style="{ color: theme.accentColor }">
            {{ activeContig.prediction.morphotype_code }}
          </div>
          <div class="k-sub">{{ activeContig.prediction.tail_feature_tag }}</div>
        </div>
        <div class="kpi-card">
          <div class="k-lbl">置信度</div>
          <div class="k-val">{{ (activeContig.prediction.confidence * 100).toFixed(1) }}%</div>
          <div class="k-sub">生活史: {{ activeContig.prediction.lifestyle_hint }}</div>
        </div>
        <div class="kpi-card">
          <div class="k-lbl">尾长</div>
          <div class="k-val">
            {{
              activeContig.prediction.estimated_tail_length_nm != null
                ? `${activeContig.prediction.estimated_tail_length_nm} nm`
                : activeContig.prediction.morphotype_code === 'Podoviridae-like'
                  ? '10–25 nm'
                  : activeContig.prediction.morphotype_code === 'Non-tailed'
                    ? '无尾'
                    : '未定标'
            }}
          </div>
          <div v-if="activeContig.prediction.morphotype_code !== 'Non-tailed'" class="k-sub">
            <template v-if="activeContig.prediction.morphotype_code === 'Podoviridae-like'">
              短尾，无 TMP
            </template>
            <template v-else>
              {{
                formatTailLength(
                  activeContig.prediction.estimated_tail_length_nm,
                  activeContig.prediction.estimated_tail_range_nm
                )
              }}
            </template>
          </div>
        </div>
        <div class="kpi-card">
          <div class="k-lbl">基因组</div>
          <div class="k-val">{{ formatGenomeBp(activeContig.length_bp) }}</div>
          <div class="k-sub">
            GC {{ activeContig.gc_percent }}% · 结构 {{ activeContig.hmm_matched_orfs }}/{{ activeContig.total_orfs }} ORF · Table {{ activeContig.genetic_code_used ?? 11 }}<template v-if="activeContig.completeness"> · {{ formatCompletenessStatus(activeContig.completeness.status) }}</template>
          </div>
        </div>
      </div>

      <!-- 3. 警告提示区 -->
      <div v-if="activeContig.prediction.warnings.length > 0" class="warn-box">
        <div v-for="(w, idx) in activeContig.prediction.warnings" :key="idx" class="warn-line">
          {{ w }}
        </div>
      </div>

      <!-- 4. 形态结构示意图 -->
      <TailMorphotypeDiagram
        :morphotype-code="activeContig.prediction.morphotype_code"
        :connector-profile="activeContig.connector_profile"
        :module-matrix="activeContig.module_matrix"
        :proteins="activeContig.structural_proteins"
        :estimated-length-nm="activeContig.prediction.estimated_tail_length_nm"
      />

      <!-- 5. 6大核心功能模块状态矩阵 + 形态得分竞争柱 -->
      <div class="split-row">
        <div class="panel-box">
          <h4>结构模块</h4>
          <div class="matrix-grid">
            <div
              v-for="m in moduleCards"
              :key="m.key"
              class="mat-item"
              :class="{ active: m.highlighted }"
            >
              <div class="mat-top">
                <span class="mat-dot" :style="{ backgroundColor: m.highlighted ? m.color : '#cbd5e1' }"></span>
                <span class="mat-title">{{ m.title }}</span>
                <span class="mat-cnt">{{ m.count }}</span>
              </div>
              <div class="mat-sub">{{ m.detail }}</div>
            </div>
          </div>
        </div>

        <div class="panel-box">
          <h4>形态得分</h4>
          <div class="score-bars">
            <div v-for="sc in classScoreEntries" :key="sc.code" class="sc-row">
              <div class="sc-meta">
                <span>{{ sc.theme.label }}</span>
                <span class="sc-num">{{ sc.val }}</span>
              </div>
              <div class="sc-track">
                <div
                  class="sc-fill"
                  :style="{ width: `${sc.pct}%`, backgroundColor: sc.theme.accentColor }"
                ></div>
              </div>
            </div>
          </div>
          <div class="basis-box">
            <strong>依据：</strong>{{ activeContig.prediction.decision_basis }}
          </div>
        </div>
      </div>

      <!-- 5.5 AI 双轨校准概率与规则一致性卡片 -->
      <div v-if="activeContig.ai_prediction" class="panel-box ai-panel">
        <div class="ai-head">
          <div class="ai-title-wrap">
            <h4>AI 分类</h4>
            <span class="ai-ver-tag">{{ activeContig.ai_prediction.model_version }}</span>
          </div>
          <div class="ai-badges">
            <span
              class="ai-mode-pill"
              :class="activeContig.ai_prediction.mode === 'ai_deep_only' ? 'deep' : 'fusion'"
            >
              {{
                activeContig.ai_prediction.mode === 'ai_deep_only'
                  ? '纯 AI（无 HMM）'
                  : '融合'
              }}
            </span>
            <span
              class="ai-agree-pill"
              :class="
                activeContig.ai_prediction.abstained
                  ? 'abstained'
                  : activeContig.ai_prediction.agreement_with_rules
                    ? 'agree'
                    : 'conflict'
              "
            >
              {{
                activeContig.ai_prediction.abstained
                  ? '拒识 (Incomplete)'
                  : activeContig.ai_prediction.agreement_with_rules
                    ? '与规则一致'
                    : '与规则不一致'
              }}
            </span>
          </div>
        </div>

        <div class="ai-body">
          <div class="score-bars">
            <div v-for="ap in aiProbEntries" :key="ap.code" class="sc-row">
              <div class="sc-meta">
                <span>{{ ap.theme.label }}</span>
                <span class="sc-num">{{ ap.pct.toFixed(1) }}%</span>
              </div>
              <div class="sc-track">
                <div
                  class="sc-fill"
                  :style="{ width: `${ap.pct}%`, backgroundColor: ap.theme.accentColor }"
                ></div>
              </div>
            </div>
          </div>

          <div class="ai-side-meta">
            <div class="ai-stat-row">
              <span>AI 判定：</span>
              <strong>
                {{ getMorphotypeTheme(activeContig.ai_prediction.predicted_morphotype).shortLabel }}
                ({{ (activeContig.ai_prediction.confidence * 100).toFixed(1) }}%)
              </strong>
            </div>
            <div class="ai-stat-row">
              <span>尾部语义最高概率：</span>
              <span class="mono">{{ (activeContig.ai_prediction.deep_tail_prob_max * 100).toFixed(1) }}%</span>
            </div>
            <div class="ai-stat-row">
              <span>头部语义最高概率：</span>
              <span class="mono">{{ (activeContig.ai_prediction.deep_head_prob_max * 100).toFixed(1) }}%</span>
            </div>
            <div v-if="activeContig.ai_prediction.entropy_norm !== undefined" class="ai-stat-row">
              <span>归一化熵：</span>
              <span class="mono">{{ Number(activeContig.ai_prediction.entropy_norm).toFixed(3) }}</span>
            </div>
            <div v-if="activeContig.ai_prediction.conflict_note" class="ai-conflict-note">
              {{ activeContig.ai_prediction.conflict_note }}
            </div>
          </div>
        </div>
      </div>

      <!-- 6. 证据链明细 -->
      <div class="panel-box">
        <h4>判定证据 ({{ activeContig.prediction.evidence_chain.length }})</h4>
        <div class="ev-list">
          <div v-for="(ev, idx) in activeContig.prediction.evidence_chain" :key="idx" class="ev-row">
            <span
              class="ev-target"
              :style="{
                backgroundColor: getMorphotypeTheme(ev.target_morphotype).badgeBg,
                color: getMorphotypeTheme(ev.target_morphotype).badgeText,
              }"
            >
              +{{ ev.weight }} &rarr; {{ getMorphotypeTheme(ev.target_morphotype).shortLabel }}
            </span>
            <span class="ev-detail">{{ ev.detail }}</span>
            <span v-if="ev.loci.length > 0" class="ev-loci">{{ ev.loci.join(', ') }}</span>
          </div>
        </div>
      </div>

      <!-- 6.5 PhageTailFinder 双状态 HMM 尾部模块集群结果 -->
      <div
        v-if="(activeContig.ptf_tail_protein_count ?? 0) > 0 || (activeContig.ptf_tail_clusters?.length ?? 0) > 0"
        class="panel-box"
      >
        <h4>
          PhageTailFinder 尾部簇
          <span class="ptf-head-tag">{{ activeContig.ptf_tail_protein_count ?? 0 }} 个尾部 ORF</span>
        </h4>
        <div v-if="(activeContig.ptf_tail_clusters?.length ?? 0) === 0" class="ptf-note">
          无连续尾部簇
        </div>
        <div v-else class="ptf-grid">
          <div v-for="cl in activeContig.ptf_tail_clusters || []" :key="cl.cluster_id" class="ptf-card">
            <div class="ptf-top">
              <strong>{{ cl.cluster_id }}</strong>
              <span class="ptf-prob">尾概率 {{ (cl.mean_tail_prob * 100).toFixed(1) }}%</span>
            </div>
            <div class="ptf-coord">{{ cl.start_bp }}..{{ cl.end_bp }} bp · {{ cl.orf_count }} ORF · 新颖 {{ cl.novel_orf_count }}</div>
            <div class="ptf-loci">{{ cl.loci.slice(0, 8).join(', ') }}{{ cl.loci.length > 8 ? ` (+${cl.loci.length - 8})` : '' }}</div>
          </div>
        </div>
      </div>

      <!-- 7. TMP 分子标尺图 -->
      <TmpRulerChart :tmp-list="activeContig.tmp_analyses" />

      <!-- 8. 操纵子物理基因组轨道 -->
      <StructuralOperonTrack
        :proteins="activeContig.structural_proteins"
        :genome-length-bp="activeContig.length_bp"
      />

      <!-- 9. 特征结构蛋白明细表 -->
      <div class="panel-box">
        <div class="tbl-head">
          <h4>结构蛋白 ({{ filteredProteins.length }})</h4>
          <div class="tbl-controls">
            <select v-model="roleFilter" class="filter-sel">
              <option value="STRUCTURAL">仅结构/尾部 ORF</option>
              <option value="ALL">全部 ORF</option>
            </select>
            <input v-model="searchText" type="text" class="search-inp" placeholder="搜索基因 / PHROG / 产物" />
          </div>
        </div>
        <div class="tbl-wrap">
          <table class="feat-table">
            <thead>
              <tr>
                <th>Locus Tag</th>
                <th>区间 (bp)</th>
                <th>长度 (aa)</th>
                <th>结构角色</th>
                <th>PHROG ID</th>
                <th>HMM Score</th>
                <th>PhageTailFinder</th>
                <th>注释</th>
                <th>来源</th>
                <th>3D 建模序列</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in filteredProteins" :key="p.locus_tag">
                <td class="mono bold">{{ p.locus_tag }}</td>
                <td class="mono">{{ p.start }}..{{ p.end }} ({{ p.strand }})</td>
                <td class="mono">{{ p.length_aa }}</td>
                <td><span class="role-badge">{{ p.role_label_cn || p.structural_role }}</span></td>
                <td class="mono">{{ p.phrog_id || '-' }}</td>
                <td class="mono">{{ p.hmm_score > 0 ? p.hmm_score : '-' }}</td>
                <td class="mono">
                  <span v-if="p.ptf_is_tail" class="ptf-pill">
                    TAIL {{ ((p.ptf_tail_prob ?? 0) * 100).toFixed(0) }}%{{ p.ptf_pfam ? ` (${p.ptf_pfam})` : '' }}
                  </span>
                  <span v-else-if="p.ptf_pfam" class="ptf-muted">{{ p.ptf_pfam }}</span>
                  <span v-else>-</span>
                </td>
                <td>{{ p.product }}</td>
                <td class="mono">{{ p.evidence_source }}</td>
                <td>
                  <div class="row-3d-actions">
                    <button
                      type="button"
                      class="act-btn"
                      :disabled="!p.translation"
                      title="复制氨基酸 FASTA 用于 AlphaFold / ESMFold / Mol* 3D 结构分析"
                      @click="copyProteinFasta(p)"
                    >
                      复制 FASTA
                    </button>
                    <button
                      type="button"
                      class="act-btn"
                      title="在交互式 3D 结构检视窗查看蛋白结构或加载 PDB/AlphaFold"
                      @click="open3DViewerForProtein(p)"
                    >
                      {{ t('structure3d.row_btn') }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <Protein3DViewerModal
      v-if="is3DViewerOpen"
      v-model:open="is3DViewerOpen"
      :context="viewer3DContext"
    />
  </div>
</template>

<style scoped src="./structureResults.css"></style>
