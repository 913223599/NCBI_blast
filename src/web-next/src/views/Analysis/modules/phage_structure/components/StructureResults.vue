<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ContigStructureResult, PhageStructureResult, StructureTaskHistoryItem } from '../types'
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

const activeContigId = ref<string>('')
const roleFilter = ref<'ALL' | 'STRUCTURAL'>('STRUCTURAL')
const searchText = ref<string>('')

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
    <div v-if="isLoading" class="loading-box">正在载入结构与尾部形态解析报告...</div>

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
          <span class="time-chip">耗时 {{ result.elapsed_sec }} s</span>
        </div>

        <div class="tb-actions">
          <button
            v-if="result.files?.gbk"
            type="button"
            class="primary-btn"
            @click="emit('open-viewer')"
          >
            在基因组图谱中查看
          </button>
          <button type="button" class="act-btn" @click="emit('download', 'summary_tsv')">形态汇总 TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'features_tsv')">结构基因 TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'tmp_tsv')">TMP 标尺 TSV</button>
          <button type="button" class="act-btn" @click="emit('download', 'json')">JSON</button>
          <button type="button" class="act-btn" @click="emit('open-folder')">打开目录</button>
        </div>
      </div>

      <!-- 多 Contig 选择条 -->
      <div v-if="result.contigs.length > 1" class="contig-switcher">
        <span class="cs-label">切换预测 Contig ({{ result.contigs.length }}):</span>
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
          <div class="k-lbl">主导尾部形态判别</div>
          <div class="k-val" :style="{ color: theme.accentColor }">
            {{ activeContig.prediction.morphotype_code }}
          </div>
          <div class="k-sub">{{ activeContig.prediction.tail_feature_tag }}</div>
        </div>
        <div class="kpi-card">
          <div class="k-lbl">融合置信度 / 生活史倾向</div>
          <div class="k-val">{{ (activeContig.prediction.confidence * 100).toFixed(1) }}%</div>
          <div class="k-sub">生活史推论: {{ activeContig.prediction.lifestyle_hint }}</div>
        </div>
        <div class="kpi-card">
          <div class="k-lbl">TMP 推算理论尾长</div>
          <div class="k-val">
            {{
              activeContig.prediction.estimated_tail_length_nm != null
                ? `${activeContig.prediction.estimated_tail_length_nm} nm`
                : activeContig.prediction.morphotype_code === 'Podoviridae-like'
                  ? '短尾无 TMP 标尺'
                  : activeContig.prediction.morphotype_code === 'Non-tailed'
                    ? '无复合尾器'
                    : '未定标'
            }}
          </div>
          <div class="k-sub">
            <template v-if="activeContig.prediction.morphotype_code === 'Podoviridae-like'">
              典型短尾物理长度约 10–25 nm（非卷尺蛋白定长）
            </template>
            <template v-else-if="activeContig.prediction.morphotype_code === 'Non-tailed'">
              非有尾噬菌体构型，无尾部尺度结构 (0 nm)
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
          <div class="k-lbl">基因组与 PHROG 识别率</div>
          <div class="k-val">{{ formatGenomeBp(activeContig.length_bp) }}</div>
          <div class="k-sub">
            GC {{ activeContig.gc_percent }}% · 结构注释 {{ activeContig.hmm_matched_orfs }} / {{ activeContig.total_orfs }} ORF · 密码表 Table {{ activeContig.genetic_code_used ?? 11 }}<template v-if="activeContig.completeness"> · 完整度: {{ formatCompletenessStatus(activeContig.completeness.status) }}</template>
          </div>
        </div>
      </div>

      <!-- 3. 警告提示区 -->
      <div v-if="activeContig.prediction.warnings.length > 0" class="warn-box">
        <div v-for="(w, idx) in activeContig.prediction.warnings" :key="idx" class="warn-line">
          [复核提示] {{ w }}
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
          <h4>六大结构组件检出矩阵</h4>
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
          <h4>多证据分型竞争打分</h4>
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
            <strong>主要判定依据：</strong>{{ activeContig.prediction.decision_basis }}
          </div>
        </div>
      </div>

      <!-- 6. 证据链明细 -->
      <div class="panel-box">
        <h4>可解释推理证据链 ({{ activeContig.prediction.evidence_chain.length }} 项命中规则)</h4>
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
          PhageTailFinder 双状态 HMM 尾部基因簇预测
          <span class="ptf-head-tag">共识别 {{ activeContig.ptf_tail_protein_count ?? 0 }} 个尾部关联 ORF</span>
        </h4>
        <div v-if="(activeContig.ptf_tail_clusters?.length ?? 0) === 0" class="ptf-note">
          未形成连续尾部蛋白簇（仅零星散在候选蛋白）。
        </div>
        <div v-else class="ptf-grid">
          <div v-for="cl in activeContig.ptf_tail_clusters || []" :key="cl.cluster_id" class="ptf-card">
            <div class="ptf-top">
              <strong>{{ cl.cluster_id }}</strong>
              <span class="ptf-prob">平均尾概率 {{ (cl.mean_tail_prob * 100).toFixed(1) }}%</span>
            </div>
            <div class="ptf-coord">{{ cl.start_bp }}..{{ cl.end_bp }} bp ({{ cl.orf_count }} ORF · 新颖未知 x{{ cl.novel_orf_count }})</div>
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
          <h4>结构与辅助功能蛋白明细 ({{ filteredProteins.length }})</h4>
          <div class="tbl-controls">
            <select v-model="roleFilter" class="filter-sel">
              <option value="STRUCTURAL">仅展示结构 / 连接 / 尾部特征 ORF</option>
              <option value="ALL">展示全部预测 ORF</option>
            </select>
            <input v-model="searchText" type="text" class="search-inp" placeholder="搜索基因、PHROG 或产物名称..." />
          </div>
        </div>
        <div class="tbl-wrap">
          <table class="feat-table">
            <thead>
              <tr>
                <th>Locus Tag</th>
                <th>区间 (bp)</th>
                <th>长度 (aa)</th>
                <th>结构角色分类</th>
                <th>PHROG ID</th>
                <th>HMM Score</th>
                <th>PhageTailFinder</th>
                <th>蛋白产物注释</th>
                <th>来源</th>
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
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.results-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.loading-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 40px;
  text-align: center;
  color: #64748b;
}

.top-bar {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.tb-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tb-left h3 {
  margin: 0;
  font-size: 1.06rem;
  color: #0f172a;
}

.morph-badge {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid;
}

.time-chip {
  font-size: 0.76rem;
  background: #f1f5f9;
  color: #475569;
  padding: 3px 8px;
  border-radius: 6px;
}

.tb-actions {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}

.primary-btn {
  padding: 6px 13px;
  border-radius: 8px;
  border: none;
  background: #2563eb;
  color: #ffffff;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.act-btn {
  padding: 6px 11px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 0.79rem;
  font-weight: 600;
  cursor: pointer;
}

.act-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}

.contig-switcher {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cs-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
}

.cs-btn {
  padding: 4px 10px;
  border-radius: 7px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  font-size: 0.8rem;
  cursor: pointer;
}

.cs-btn.active {
  background: #2563eb;
  color: #ffffff;
  border-color: #2563eb;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.kpi-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 16px;
}

.kpi-card.highlight {
  border-width: 1.5px;
}

.k-lbl {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 600;
}

.k-val {
  margin-top: 5px;
  font-size: 1.24rem;
  font-weight: 800;
  color: #0f172a;
}

.k-sub {
  margin-top: 4px;
  font-size: 0.77rem;
  line-height: 1.4;
  color: #64748b;
}

.warn-box {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 0.83rem;
  color: #92400e;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.split-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.panel-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px 18px;
}

.panel-box h4 {
  margin: 0 0 12px 0;
  font-size: 0.96rem;
  color: #0f172a;
}

.matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 10px;
}

.mat-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  opacity: 0.72;
}

.mat-item.active {
  background: #ffffff;
  border-color: #cbd5e1;
  opacity: 1;
}

.mat-top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mat-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.mat-title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #1e293b;
  flex: 1;
}

.mat-cnt {
  font-size: 0.9rem;
  font-weight: 800;
  color: #0f172a;
}

.mat-sub {
  margin-top: 5px;
  font-size: 0.74rem;
  color: #64748b;
}

.score-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sc-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sc-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: #334155;
  font-weight: 600;
}

.sc-track {
  height: 8px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}

.sc-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

.basis-box {
  margin-top: 12px;
  padding: 9px 12px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 0.82rem;
  color: #334155;
  line-height: 1.5;
}

.ev-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ev-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 0.82rem;
  padding: 7px 10px;
  border-radius: 8px;
  background: #f8fafc;
}

.ev-target {
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.76rem;
}

.ev-detail {
  color: #0f172a;
  flex: 1;
}

.ev-loci {
  font-family: ui-monospace, monospace;
  font-size: 0.76rem;
  color: #475569;
}

.tbl-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.tbl-head h4 {
  margin: 0;
}

.tbl-controls {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-sel,
.search-inp {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.82rem;
}

.tbl-wrap {
  max-height: 380px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.feat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.feat-table th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
  text-align: left;
  padding: 9px 10px;
  border-bottom: 1px solid #e2e8f0;
}

.feat-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.mono {
  font-family: ui-monospace, monospace;
}

.bold {
  font-weight: 700;
}

.role-badge {
  background: #f1f5f9;
  color: #334155;
  padding: 2px 7px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 0.75rem;
}

.ptf-head-tag {
  margin-left: 8px;
  font-size: 0.76rem;
  font-weight: 600;
  background: #eff6ff;
  color: #1d4ed8;
  padding: 2px 9px;
  border-radius: 999px;
}

.ptf-note {
  font-size: 0.82rem;
  color: #64748b;
}

.ptf-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.ptf-card {
  background: #f8fafc;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  padding: 10px 12px;
}

.ptf-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.84rem;
  color: #1e293b;
}

.ptf-prob {
  color: #2563eb;
  font-weight: 700;
  font-size: 0.78rem;
}

.ptf-coord {
  margin-top: 4px;
  font-size: 0.77rem;
  color: #475569;
  font-family: ui-monospace, monospace;
}

.ptf-loci {
  margin-top: 5px;
  font-size: 0.74rem;
  color: #64748b;
  font-family: ui-monospace, monospace;
  word-break: break-word;
}

.ptf-pill {
  display: inline-block;
  background: #dbeafe;
  color: #1d4ed8;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}

.ptf-muted {
  color: #94a3b8;
  font-size: 0.74rem;
}
</style>
