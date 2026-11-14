<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  PhageContigOverlayData,
  PhageRegionItem,
  PhageScanResultPayload,
  PhageTaskRecord,
} from '../types'
import PhageOverlayMap from './PhageOverlayMap.vue'

const props = defineProps<{
  task: PhageTaskRecord
  result: PhageScanResultPayload | null
  isLoading: boolean
  overlayData: PhageContigOverlayData | null
  isOverlayLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'download', fileType: 'fasta' | 'tsv' | 'gff3' | 'gbk'): void
  (e: 'open-folder'): void
  (e: 'open-viewer', regionIndex: number): void
  (e: 'open-overlay-viewer', contigId: string): void
  (e: 'open-annotation', regionIndex?: number): void
  (e: 'contig-change', contigId: string): void
}>()

const selectedContigId = ref<string>('')
const selectedRegionIndex = ref<number>(0)
const showRejected = ref<boolean>(false)
const searchKeyword = ref<string>('')

const regions = computed(() => props.result?.regions || [])
const contigs = computed(() => props.result?.contigs || [])
const rejected = computed(() => props.result?.rejected_candidates || [])
const summary = computed(() => props.result?.summary || props.task.summary || {})

const filteredRegions = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return regions.value
  return regions.value.filter(
    (r) =>
      r.region_id.toLowerCase().includes(kw) ||
      r.contig_id.toLowerCase().includes(kw) ||
      r.completeness_label.toLowerCase().includes(kw)
  )
})

watch(
  () => props.result,
  (val) => {
    if (!val) return
    const firstWithHit = val.contigs.find((c) => c.hit_count > 0) || val.contigs[0]
    selectedContigId.value = firstWithHit ? firstWithHit.id : ''
    const firstRegion = val.regions[0]
    selectedRegionIndex.value = firstRegion ? firstRegion.index : 0
  },
  { immediate: true }
)

const activeRegion = computed<PhageRegionItem | null>(() => {
  if (regions.value.length === 0) return null
  const found = regions.value.find((r) => r.index === selectedRegionIndex.value) ?? regions.value[0]
  return found ?? null
})

function selectRegion(region: PhageRegionItem): void {
  selectedRegionIndex.value = region.index
  if (selectedContigId.value !== region.contig_id) {
    selectedContigId.value = region.contig_id
  }
}

watch(selectedContigId, (cid) => {
  if (cid) {
    emit('contig-change', cid)
  }
})

function formatBp(bp?: number): string {
  const v = Number(bp || 0)
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)} Mb`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)} kb`
  return `${v} bp`
}
</script>

<template>
  <div class="results-container">
    <div v-if="isLoading" class="loading-box">正在载入扫描结果与 200bp 边界剖面数据...</div>

    <template v-else-if="result">
      <!-- 1. 顶部交付操作栏 -->
      <div class="results-topbar">
        <div class="top-title">
          <h3>{{ task.task_name }}</h3>
          <span class="ver-badge">Student V4.2</span>
          <span class="dev-badge">{{ String(summary.device_used || task.device || 'cpu').toUpperCase() }}</span>
          <span v-if="summary.apply_protein_gate" class="gate-badge">BLASTp 门控验证</span>
        </div>

        <div class="top-actions">
          <button
            v-if="regions.length > 0"
            type="button"
            class="primary-handoff-btn"
            @click="emit('open-annotation')"
          >
            全部前噬菌体送入功能注释
          </button>
          <button type="button" class="action-btn" @click="emit('download', 'fasta')">FASTA</button>
          <button type="button" class="action-btn" @click="emit('download', 'tsv')">TSV</button>
          <button type="button" class="action-btn" @click="emit('download', 'gff3')">GFF3</button>
          <button type="button" class="action-btn" @click="emit('download', 'gbk')">GBK</button>
          <button type="button" class="action-btn" @click="emit('open-folder')">打开目录</button>
        </div>
      </div>

      <!-- 2. KPI 指标网格 -->
      <div class="kpi-grid">
        <div class="kpi-card highlight">
          <div class="kpi-label">识别前噬菌体区段</div>
          <div class="kpi-value">{{ summary.region_count ?? regions.length }}</div>
          <div class="kpi-sub">占总碱基 {{ summary.prophage_fraction_pct ?? 0 }}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">前噬菌体总长度</div>
          <div class="kpi-value">{{ formatBp(summary.total_prophage_bp) }}</div>
          <div class="kpi-sub">原始候选 {{ summary.raw_region_count ?? regions.length }} / 拦截 {{ summary.rejected_count ?? 0 }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">输入基因组总规模</div>
          <div class="kpi-value">{{ formatBp(summary.total_bp) }}</div>
          <div class="kpi-sub">{{ summary.contig_count ?? contigs.length }} 条 Contig ({{ summary.total_windows ?? 0 }} 窗口)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">V4.2 总推理耗时</div>
          <div class="kpi-value">{{ (summary.timings_sec?.total_sec ?? 0).toFixed(2) }} s</div>
          <div class="kpi-sub">200bp SubBin 精细分割已启用</div>
        </div>
      </div>

      <!-- 3. 目标基因基底图与预测前噬菌体交互式叠图显示工作台 -->
      <PhageOverlayMap
        v-if="contigs.length > 0"
        :contigs="contigs"
        :selected-contig-id="selectedContigId"
        :overlay-data="overlayData"
        :is-loading="isOverlayLoading"
        :selected-region-index="selectedRegionIndex"
        @update:selected-contig-id="(cid) => (selectedContigId = cid)"
        @select-region="selectRegion"
        @open-overlay-viewer="(cid) => emit('open-overlay-viewer', cid)"
        @open-region-viewer="(idx) => emit('open-viewer', idx)"
        @open-annotation="(idx) => emit('open-annotation', idx)"
      />

      <!-- 4. 识别区段明细表 -->
      <div class="panel-card">
        <div class="panel-header">
          <div>
            <h4>识别前噬菌体清单 ({{ filteredRegions.length }})</h4>
          </div>
          <input
            v-model="searchKeyword"
            type="text"
            class="search-input"
            placeholder="过滤 Contig / ID / 可信度..."
          />
        </div>

        <div v-if="filteredRegions.length === 0" class="empty-table">
          当前全基因组扫描未检出符合阈值的前噬菌体整合区域。
        </div>
        <div v-else class="table-wrap">
          <table class="regions-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Contig</th>
                <th>起止坐标 (bp)</th>
                <th>长度</th>
                <th>Peak / Mean</th>
                <th>GC%</th>
                <th>ORF 数</th>
                <th>完整度 / 门控证据</th>
                <th>联动操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in filteredRegions"
                :key="r.index"
                :class="{ active: r.index === activeRegion?.index }"
                @click="selectRegion(r)"
              >
                <td class="mono bold">{{ r.region_id }}</td>
                <td class="mono">{{ r.contig_id }}</td>
                <td class="mono">{{ r.start_1based.toLocaleString() }} - {{ r.end_1based.toLocaleString() }}</td>
                <td class="mono">{{ r.length_bp.toLocaleString() }} bp</td>
                <td class="mono">
                  <span class="score-high">{{ r.peak_score.toFixed(3) }}</span> / {{ r.mean_score.toFixed(3) }}
                </td>
                <td class="mono">{{ r.gc_percent }}%</td>
                <td class="mono">{{ r.orf_count }}</td>
                <td>
                  <div class="comp-cell">
                    <span class="comp-tag" :class="r.completeness_key">{{ r.completeness_label }}</span>
                    <span v-if="r.gate_decision !== 'bypass'" class="gate-mini">
                      Hallmark {{ r.hallmark_hits }} | 转座酶 {{ r.transposase_hits }}
                    </span>
                  </div>
                </td>
                <td>
                  <div class="row-actions" @click.stop>
                    <button type="button" class="mini-btn blue" @click="emit('open-viewer', r.index)">
                      图谱
                    </button>
                    <button type="button" class="mini-btn teal" @click="emit('open-annotation', r.index)">
                      注释
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 6. 可折叠被蛋白门控拦截复核记录 -->
      <div v-if="rejected.length > 0" class="panel-card">
        <button type="button" class="collapse-btn" @click="showRejected = !showRejected">
          被 BLASTp 蛋白门控过滤的低可信候选 ({{ rejected.length }}) - 点击展开复核
        </button>
        <div v-if="showRejected" class="table-wrap" style="margin-top: 10px">
          <table class="regions-table">
            <thead>
              <tr>
                <th>Contig</th>
                <th>区间 (bp)</th>
                <th>长度</th>
                <th>Peak 分</th>
                <th>Hallmark / 转座酶</th>
                <th>参考命中示例</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in rejected" :key="idx">
                <td class="mono">{{ item.contig_id }}</td>
                <td class="mono">{{ item.start_bp + 1 }} - {{ item.end_bp }}</td>
                <td class="mono">{{ item.length_bp.toLocaleString() }} bp</td>
                <td class="mono">{{ item.peak_score.toFixed(3) }}</td>
                <td class="mono">{{ item.hallmark_hits }} / {{ item.transposase_hits }}</td>
                <td class="small-text">{{ item.matched_titles.slice(0, 3).join('; ') || '--' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.results-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.loading-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 36px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.results-topbar {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.top-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.top-title h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}

.ver-badge {
  background: #4338ca;
  color: white;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
}

.dev-badge {
  background: #f1f5f9;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
}

.gate-badge {
  background: #ecfeff;
  color: #0e7490;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
}

.top-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.primary-handoff-btn {
  background: #0f766e;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.primary-handoff-btn:hover {
  background: #115e59;
}

.action-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.action-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.kpi-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
}

.kpi-card.highlight {
  border-color: #bfdbfe;
  background: #f0f9ff;
}

.kpi-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.kpi-value {
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
  margin: 4px 0;
}

.kpi-sub {
  font-size: 11px;
  color: #64748b;
}

.panel-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.panel-header h4 {
  margin: 0 0 2px;
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}

.panel-sub {
  font-size: 11px;
  color: #64748b;
}

.contig-select,
.search-input {
  height: 32px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 0 10px;
  font-size: 12px;
  color: #1e293b;
}

.empty-table {
  text-align: center;
  padding: 28px;
  color: #64748b;
  font-size: 13px;
}

.table-wrap {
  overflow-x: auto;
}

.regions-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.regions-table th {
  text-align: left;
  padding: 9px 10px;
  border-bottom: 1px solid #e2e8f0;
  color: #475569;
  font-weight: 700;
  background: #f8fafc;
}

.regions-table td {
  padding: 9px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.regions-table tbody tr {
  cursor: pointer;
}

.regions-table tbody tr:hover {
  background: #f8fafc;
}

.regions-table tbody tr.active {
  background: #eff6ff;
}

.mono {
  font-family: 'Consolas', monospace;
}

.bold {
  font-weight: 700;
}

.score-high {
  color: #1d4ed8;
  font-weight: 700;
}

.comp-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.comp-tag {
  display: inline-block;
  width: fit-content;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #334155;
  font-weight: 600;
}

.comp-tag.high,
.comp-tag.intact_like {
  background: #dcfce7;
  color: #15803d;
}

.comp-tag.medium {
  background: #fef3c7;
  color: #b45309;
}

.gate-mini {
  font-size: 10px;
  color: #0e7490;
}

.row-actions {
  display: flex;
  gap: 6px;
}

.mini-btn {
  border: none;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  color: white;
}

.mini-btn.blue {
  background: #2563eb;
}

.mini-btn.teal {
  background: #0f766e;
}

.collapse-btn {
  border: none;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.small-text {
  font-size: 11px;
  color: #64748b;
  max-width: 260px;
}
</style>
