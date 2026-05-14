<script setup lang="ts">
/**
 * AssemblyReportDialog - 基因组拼接分析报告弹窗
 * 展示质控、宿主剔除、组装、注释四大模块的结构化报告
 */
import { ref, computed, watch } from 'vue'
import { getBridge } from '../../../bridge'

const props = defineProps<{
  show: boolean
  taskId: string
  taskName: string
}>()

const emit = defineEmits(['close'])

const report = ref<any>(null)
const loading = ref(false)
const error = ref('')
const activeTab = ref('overview')
const exporting = ref(false)


const tabs = [
  { key: 'overview', label: '总览' },
  { key: 'qc', label: '质控' },
  { key: 'assembly', label: '组装' },
  { key: 'annotation', label: '注释' },
]

watch(() => props.show, async (val) => {
  if (val && props.taskId) {
    await fetchReport()
  }
})

async function fetchReport() {
  loading.value = true
  error.value = ''
  try {
    const bridge = getBridge()
    const res = await bridge.get_assembly_report(props.taskId)
    report.value = res?.data || res
  } catch (e: any) {
    error.value = e.message || '报告加载失败'
  } finally {
    loading.value = false
  }
}

async function handleExport() {
  exporting.value = true
  try {
    const bridge = getBridge()
    const res = await bridge.export_assembly_report(props.taskId)
    const data = res?.data || res
    if (data?.path) {
      // 尝试通过 Electron 打开文件
      if ((window as any).electronAPI?.openPath) {
        await (window as any).electronAPI.openPath(data.path)
      } else {
        alert(`报告已导出至: ${data.path}`)
      }
    }
  } catch (e: any) {
    alert('导出失败: ' + (e.message || e))
  } finally {
    exporting.value = false
  }
}



// ─── 计算属性 ─────────────────────────────────────

const genomeInfo = computed(() => report.value?.annotation?.pharokka?.genome || {})
const funcList = computed(() => report.value?.annotation?.pharokka?.functions || [])
const asmInfo = computed(() => report.value?.assembly || {})
const qcInfo = computed(() => report.value?.qc || {})
const pholdInfo = computed(() => report.value?.annotation?.phold || null)
const backfillInfo = computed(() => report.value?.annotation?.phagescope_backfill || null)
const checkvInfo = computed(() => report.value?.checkv || null)
const hostCleanerInfo = computed(() => report.value?.host_cleaning?.host_contamination_percent || null)

// V5 新增字段解析
const lifecycleInfo = computed(() => report.value?.lifecycle_prediction || null)
const prophageInfo = computed(() => report.value?.prophage_separation || null)
const correctionInfo = computed(() => report.value?.correction_metadata || null)
const hostPredictionInfo = computed(() => report.value?.host_prediction || null)
const auditInfo = computed(() => report.value?.phagescope_audit || null)

const visualMapUrl = computed(() => {
  const mapSuffix = report.value?.annotation?.visual_map
  if (!mapSuffix) return null
  return `http://127.0.0.1:8765/api/assembly/report/${props.taskId}/plot?t=${new Date().getTime()}`
})

const funcChartData = computed(() => {
  const items = funcList.value.filter((f: any) => f.name !== 'CDS' && f.count > 0)
  const total = items.reduce((s: number, i: any) => s + i.count, 0)
  return items.map((i: any) => ({ ...i, pct: total > 0 ? Math.round(i.count / total * 100) : 0 }))
})

const confidenceSummary = computed(() => {
  if (!pholdInfo.value?.confidence) return null
  const c = pholdInfo.value.confidence
  const total = c.high + c.medium + c.low + c.none
  return { ...c, total }
})

function formatBp(bp: number): string {
  if (!bp) return '--'
  if (bp >= 1e6) return (bp / 1e6).toFixed(2) + ' Mbp'
  if (bp >= 1e3) return (bp / 1e3).toFixed(1) + ' Kbp'
  return bp + ' bp'
}

function formatReads(n: number): string {
  if (!n) return '--'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

function pct(v: number): string {
  if (!v && v !== 0) return '--'
  return (v * 100).toFixed(2) + '%'
}

const funcColors: Record<string, string> = {
  'head and packaging': '#3b82f6',
  'tail': '#8b5cf6',
  'DNA, RNA and nucleotide metabolism': '#10b981',
  'lysis': '#ef4444',
  'connector': '#f59e0b',
  'transcription regulation': '#06b6d4',
  'moron, auxiliary metabolic gene and host takeover': '#ec4899',
  'integration and excision': '#f97316',
  'other': '#6b7280',
  'unknown function': '#cbd5e1',
}

function getFuncColor(name: string): string {
  return funcColors[name] || '#94a3b8'
}
</script>

<template>
  <Teleport to="body">
    <div class="report-overlay" v-if="show" @click="emit('close')">
      <div class="report-dialog" @click.stop>
        <!-- 头部 -->
        <header class="report-header">
          <div class="header-left">
            <h2>拼接分析报告</h2>
            <span class="task-label">{{ taskName || taskId }}</span>
          </div>
          <div class="header-actions">
            <button class="header-btn export-btn" @click="handleExport" :disabled="exporting || !report">
              {{ exporting ? '导出中...' : '导出报告' }}
            </button>
            <button class="close-btn" @click="emit('close')">✕</button>
          </div>
        </header>

        <!-- 标签导航 -->
        <nav class="tab-nav">
          <button v-for="tab in tabs" :key="tab.key" class="tab-btn" :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key">
            {{ tab.label }}
          </button>
        </nav>

        <!-- 内容区 -->
        <div class="report-body" v-if="loading">
          <div class="loading-state">
            <div class="spinner"></div>
            <p>正在解析报告数据...</p>
          </div>
        </div>

        <div class="report-body" v-else-if="error">
          <div class="error-state">
            <p>{{ error }}</p>
            <button @click="fetchReport">重试</button>
          </div>
        </div>

        <div class="report-body" v-else-if="report">
          <!-- ═══ 总览 Tab ═══ -->
          <div v-if="activeTab === 'overview'" class="tab-content">
            <div class="overview-grid">
              <!-- ===== 1. 基础检控与宿主鉴定区 ===== -->
              <div class="stat-card qc-card">
                <div class="card-body">
                  <h4>质控</h4>
                  <div class="stat-value" v-if="qcInfo.after">{{ formatReads(qcInfo.after.total_reads) }}</div>
                  <div class="stat-value" v-else>--</div>
                  <div class="stat-sub" v-if="qcInfo.after">Q30: {{ pct(qcInfo.after.q30_rate) }}</div>
                </div>
              </div>

              <!-- 宿主剔除卡片 -->
              <div class="stat-card host-card" v-if="hostCleanerInfo !== null">
                <div class="card-body">
                  <h4>宿主成分</h4>
                  <div class="stat-value">{{ hostCleanerInfo.toFixed(1) }}%</div>
                  <div class="stat-sub">Kraken2 已剔除背景</div>
                </div>
              </div>

              <!-- V5 追加：MASH 宿主溯源预测 -->
              <div class="stat-card" style="background: linear-gradient(135deg, #fff7ed, #ffedd5)" v-if="hostPredictionInfo && hostPredictionInfo.top_hit_species">
                <div class="card-body">
                  <h4>MASH 宿主溯源</h4>
                  <div class="stat-value" style="font-size: 13px; margin-top:2px;" :title="hostPredictionInfo.top_hit_species">{{ hostPredictionInfo.top_hit_species }}</div>
                  <div class="stat-sub">P-value: {{ hostPredictionInfo.p_value }} | 距离: {{ hostPredictionInfo.distance }}</div>
                </div>
              </div>

              <!-- ===== 2. 组装与形态提取区 ===== -->
              <!-- 基因组概览卡片 -->
              <div class="stat-card genome-card">
                <div class="card-body">
                  <h4>基因组</h4>
                  <div class="stat-value">{{ formatBp(parseInt(genomeInfo.length) || asmInfo.total_length || 0) }}</div>
                  <div class="stat-sub" v-if="genomeInfo.gc_perc">GC: {{ (parseFloat(genomeInfo.gc_perc) * 100).toFixed(1) }}%</div>
                </div>
              </div>

              <div class="stat-card contig-card">
                <div class="card-body">
                  <h4>Contigs</h4>
                  <div class="stat-value">{{ asmInfo.num_contigs || '--' }}</div>
                  <div class="stat-sub" v-if="asmInfo.n50">N50: {{ formatBp(asmInfo.n50) }}</div>
                </div>
              </div>

              <!-- V5 追加：一致性校正遥测 -->
              <div class="stat-card" style="background: linear-gradient(135deg, #f8fafc, #e2e8f0)" v-if="correctionInfo && correctionInfo.engine">
                <div class="card-body">
                  <h4>一致性校正</h4>
                  <div class="stat-value">{{ correctionInfo.engine === 'medaka' ? 'Medaka (RNN)' : 'Polypolish' }}</div>
                  <div class="stat-sub" v-if="correctionInfo.engine === 'polypolish'">修复错误: {{ correctionInfo.fixed_errors || 0 }} 处</div>
                  <div class="stat-sub" v-if="correctionInfo.engine === 'medaka'">单碱基自动推断极化修复</div>
                </div>
              </div>

              <!-- V5 追加：前噬菌体/杂质萃取记录 -->
              <div class="stat-card" style="background: linear-gradient(135deg, #fdf4ff, #fae8ff)" v-if="prophageInfo && prophageInfo.vibrant_contigs > 0">
                <div class="card-body">
                  <h4>VIBRANT 脱敏纯化</h4>
                  <div class="stat-value">{{ prophageInfo.vibrant_contigs }} 条</div>
                  <div class="stat-sub">已从中切割/提纯出有效游离病毒 Contigs</div>
                </div>
              </div>

              <!-- ===== 3. 注释与质量评估区 ===== -->
              <!-- CheckV 质量评估卡片 -->
              <div class="stat-card checkv-card" v-if="checkvInfo" :class="checkvInfo.quality?.toLowerCase().replace(' ', '-')">
                <div class="card-body">
                  <h4>CheckV 完整度</h4>
                  <div class="stat-value">{{ checkvInfo.quality || '--' }}</div>
                  <div class="stat-sub">完整度: {{ checkvInfo.completeness }}% | 污染度: {{ checkvInfo.contamination }}%</div>
                </div>
              </div>

              <div class="stat-card cds-card">
                <div class="card-body">
                  <h4>预测 CDS</h4>
                  <div class="stat-value">{{funcList.find((f: any) => f.name === 'CDS')?.count || pholdInfo?.total_cds || '--' }}</div>
                  <div class="stat-sub" v-if="genomeInfo.cds_coding_density">编码密度: {{ genomeInfo.cds_coding_density }}%</div>
                </div>
              </div>

              <!-- PhageScope 回填卡片 -->
              <div class="stat-card backfill-card" v-if="backfillInfo">
                <div class="card-body">
                  <h4>PhageScope 回填</h4>
                  <div class="stat-value">+{{ backfillInfo.hits }}</div>
                  <div class="stat-sub">扫描 {{ backfillInfo.unknown_before }} 个未知蛋白</div>
                </div>
              </div>

              <!-- ===== 4. 临床转化与致病性审计红线 ===== -->
              <!-- V5 追加：BacpHLiP 生活史预测/药用安全 -->
              <div class="stat-card" style="background: linear-gradient(135deg, #f0fdfa, #ccfbf1)" v-if="lifecycleInfo && lifecycleInfo.lifestyle">
                <div class="card-body">
                  <h4>生活史 (药源安全)</h4>
                  <div class="stat-value" :style="{ color: lifecycleInfo.lifestyle === 'Virulent' ? '#10b981' : '#ef4444' }">
                    {{ lifecycleInfo.lifestyle === 'Virulent' ? '裂解 (安全)' : '温和 (风险)' }}
                  </div>
                  <div class="stat-sub">Virulent: {{ (lifecycleInfo.virulent_prob * 100).toFixed(1) }}%</div>
                </div>
              </div>

              <!-- V5 追加：毒力因子与抗性基因 (AMR) 监控 -->
              <div class="stat-card" :style="{ background: (auditInfo?.amr_genes?.length || auditInfo?.virulence_factors?.length) ? 'linear-gradient(135deg, #fef2f2, #fee2e2)' : 'linear-gradient(135deg, #f0fdf4, #dcfce7)' }" v-if="auditInfo">
                <div class="card-body">
                  <h4>毒力与耐药库审计</h4>
                  <div class="stat-value" :style="{ color: (auditInfo?.amr_genes?.length || auditInfo?.virulence_factors?.length) ? '#ef4444' : '#10b981' }">
                    {{ (auditInfo?.amr_genes?.length || auditInfo?.virulence_factors?.length) ? '检出风险物质' : '清白 (未检出)' }}
                  </div>
                  <div class="stat-sub">AMR: {{ auditInfo.amr_genes?.length || 0 }} 项 | 毒力因子: {{ auditInfo.virulence_factors?.length || 0 }} 项</div>
                </div>
              </div>
            </div>

            <!-- 全景基因组图谱 (集成化展示) -->
            <div class="section-block" v-if="visualMapUrl" style="margin-top: 24px;">
              <h3 class="section-title">全景集成基因组图谱 (AI & Reference)</h3>
              <div class="visual-map-container"
                style="text-align: center; background: #fff; padding: 20px; border-radius: 8px; border: 1px solid var(--border-color);">
                <img :src="visualMapUrl" alt="Integrated Phage Map"
                  style="max-width: 100%; height: auto; border-radius: 4px;" />
              </div>
            </div>

            <!-- 功能分类可视化 -->
            <div class="section-block" v-if="funcChartData.length > 0">
              <h3 class="section-title">功能分类分布</h3>
              <div class="func-bar-chart">
                <div v-for="item in funcChartData" :key="item.name" class="func-bar-row">
                  <span class="func-label" :title="item.name">{{ item.name }}</span>
                  <div class="func-bar-track">
                    <div class="func-bar-fill"
                      :style="{ width: Math.max(item.pct, 3) + '%', background: getFuncColor(item.name) }"></div>
                  </div>
                  <span class="func-count">{{ item.count }}</span>
                </div>
              </div>
            </div>

            <!-- Phold 预测置信度 -->
            <div class="section-block" v-if="confidenceSummary">
              <h3 class="section-title">AI 结构预测置信度 (Phold)</h3>
              <div class="confidence-bars">
                <div class="conf-item">
                  <span class="conf-label high">High</span>
                  <div class="conf-track">
                    <div class="conf-fill high"
                      :style="{ width: (confidenceSummary.high / confidenceSummary.total * 100) + '%' }"></div>
                  </div>
                  <span class="conf-num">{{ confidenceSummary.high }}</span>
                </div>
                <div class="conf-item">
                  <span class="conf-label medium">Medium</span>
                  <div class="conf-track">
                    <div class="conf-fill medium"
                      :style="{ width: (confidenceSummary.medium / confidenceSummary.total * 100) + '%' }"></div>
                  </div>
                  <span class="conf-num">{{ confidenceSummary.medium }}</span>
                </div>
                <div class="conf-item">
                  <span class="conf-label low">Low</span>
                  <div class="conf-track">
                    <div class="conf-fill low"
                      :style="{ width: (confidenceSummary.low / confidenceSummary.total * 100) + '%' }"></div>
                  </div>
                  <span class="conf-num">{{ confidenceSummary.low }}</span>
                </div>
                <div class="conf-item">
                  <span class="conf-label none">None</span>
                  <div class="conf-track">
                    <div class="conf-fill none"
                      :style="{ width: (confidenceSummary.none / confidenceSummary.total * 100) + '%' }"></div>
                  </div>
                  <span class="conf-num">{{ confidenceSummary.none }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- ═══ 质控 Tab ═══ -->
          <div v-if="activeTab === 'qc'" class="tab-content">
            <div v-if="qcInfo.status === 'ok'" class="qc-detail">
              <h3 class="section-title">过滤前后对比</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    <th>过滤前</th>
                    <th>过滤后</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>总 Reads</td>
                    <td>{{ formatReads(qcInfo.before.total_reads) }}</td>
                    <td>{{ formatReads(qcInfo.after.total_reads) }}</td>
                  </tr>
                  <tr>
                    <td>总碱基</td>
                    <td>{{ formatBp(qcInfo.before.total_bases) }}</td>
                    <td>{{ formatBp(qcInfo.after.total_bases) }}</td>
                  </tr>
                  <tr>
                    <td>Q20</td>
                    <td>{{ pct(qcInfo.before.q20_rate) }}</td>
                    <td>{{ pct(qcInfo.after.q20_rate) }}</td>
                  </tr>
                  <tr>
                    <td>Q30</td>
                    <td>{{ pct(qcInfo.before.q30_rate) }}</td>
                    <td>{{ pct(qcInfo.after.q30_rate) }}</td>
                  </tr>
                  <tr>
                    <td>GC 含量</td>
                    <td>{{ pct(qcInfo.before.gc_content) }}</td>
                    <td>{{ pct(qcInfo.after.gc_content) }}</td>
                  </tr>
                </tbody>
              </table>

              <h3 class="section-title" style="margin-top: 24px">过滤统计</h3>
              <div class="filter-stats">
                <div class="filter-item pass"><span>通过</span><strong>{{ formatReads(qcInfo.filtering.passed) }}</strong>
                </div>
                <div class="filter-item fail"><span>低质量</span><strong>{{ formatReads(qcInfo.filtering.low_quality)
                    }}</strong></div>
                <div class="filter-item fail"><span>过多 N</span><strong>{{ formatReads(qcInfo.filtering.too_many_N)
                    }}</strong></div>
                <div class="filter-item fail"><span>过短</span><strong>{{ formatReads(qcInfo.filtering.too_short)
                    }}</strong></div>
              </div>

              <div class="host-filtration-details" v-if="hostCleanerInfo !== null" style="margin-top: 24px">
                <h3 class="section-title">宿主污染详细评估 (Genus-level Kraken2)</h3>
                <div class="host-warn-box" :class="{ 'warning': hostCleanerInfo > 50 }">
                  <div class="warn-icon">{{ hostCleanerInfo > 50 ? '⚠️' : '✅' }}</div>
                  <div class="warn-content">
                    <p class="warn-txt">检测到样本中含有 <strong>{{ hostCleanerInfo.toFixed(2) }}%</strong> 的宿主背景序列。</p>
                    <p class="warn-desc" v-if="hostCleanerInfo > 50">高污染背景。已通过分类排除策略强行剥离宿主信号，当前组装仅针对 <strong>{{ (100 -
                        hostCleanerInfo).toFixed(2) }}%</strong> 的非宿主序列。已开启支架连接强化，以对抗由于背景过高导致的潜在覆盖度不均。</p>
                    <p class="warn-desc" v-else>宿主背景较低，样本纯净度良好。已完成物种专项分类清洗。</p>
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="qcInfo.status === 'partial'" class="partial-info">
              <p>质控已完成（清洁数据已生成），但未找到 fastp 详细报告。</p>
              <div v-for="f in qcInfo.clean_files" :key="f.name" class="file-tag">
                {{ f.name }} ({{ f.size_mb }} MB)
              </div>
            </div>
            <div v-else class="empty-section">
              <p>暂无质控数据</p>
            </div>
          </div>

          <!-- ═══ 组装 Tab ═══ -->
          <div v-if="activeTab === 'assembly'" class="tab-content">
            <div v-if="asmInfo.status === 'ok'">
              <div class="asm-stats-grid">
                <div class="asm-stat"><label>Contig 数</label><span>{{ asmInfo.num_contigs }}</span></div>
                <div class="asm-stat"><label>总长度</label><span>{{ formatBp(asmInfo.total_length) }}</span></div>
                <div class="asm-stat"><label>N50</label><span>{{ formatBp(asmInfo.n50) }}</span></div>
                <div class="asm-stat"><label>最长</label><span>{{ formatBp(asmInfo.longest) }}</span></div>
                <div class="asm-stat"><label>最短</label><span>{{ formatBp(asmInfo.shortest) }}</span></div>
              </div>

              <h3 class="section-title" style="margin-top: 24px">Contig 列表</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>ID</th>
                    <th>长度</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(c, i) in asmInfo.contigs" :key="c.id">
                    <td>{{ Number(i) + 1 }}</td>
                    <td class="mono">{{ c.id }}</td>
                    <td>{{ formatBp(c.length) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-section">
              <p>暂无组装数据</p>
            </div>
          </div>

          <!-- ═══ 注释 Tab ═══ -->
          <div v-if="activeTab === 'annotation'" class="tab-content">
            <!-- PhageScope 自动回填报告 -->
            <div class="backfill-status-bar" :class="{ 'has-data': backfillInfo }">
              <div class="txt">
                <p class="main">PhageScope 本地蛋白库自动回填</p>
                <p class="sub" v-if="backfillInfo">
                  扫描 {{ backfillInfo.unknown_before }} 个未知蛋白，命中 {{ backfillInfo.hits }} 个 ({{ backfillInfo.hit_rate }}%)
                </p>
                <p class="sub" v-else>流水线在注释完成后自动将未知蛋白与 PhageScope 104万条蛋白序列进行本地比对</p>
              </div>
              <span class="auto-badge" v-if="backfillInfo">+{{ backfillInfo.hits }} 已回填</span>
              <span class="auto-badge pending" v-else>待执行</span>
            </div>

            <!-- PhageScope 回填统计卡片 -->
            <div v-if="backfillInfo" class="backfill-stats-grid">
              <div class="bf-stat">
                <label>总 CDS</label>
                <span>{{ backfillInfo.total_cds }}</span>
              </div>
              <div class="bf-stat">
                <label>未知蛋白</label>
                <span>{{ backfillInfo.unknown_before }}</span>
              </div>
              <div class="bf-stat highlight">
                <label>PhageScope 命中</label>
                <span>{{ backfillInfo.hits }}</span>
              </div>
              <div class="bf-stat">
                <label>命中率</label>
                <span>{{ backfillInfo.hit_rate }}%</span>
              </div>
            </div>

            <!-- PhageScope 命中详情表 -->
            <div v-if="backfillInfo?.details?.length" style="margin-bottom: 24px">
              <h3 class="section-title">PhageScope 回填详情</h3>
              <div class="table-scroll" style="max-height: 240px">
                <table class="data-table compact">
                  <thead>
                    <tr>
                      <th>CDS ID</th>
                      <th>比对产物</th>
                      <th>E-value</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="d in backfillInfo.details" :key="d.cds_id">
                      <td class="mono">{{ d.cds_id }}</td>
                      <td class="product-cell" :title="d.product">{{ d.product }}</td>
                      <td class="mono">{{ d.evalue }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Phold 预测详情表 -->
            <div v-if="pholdInfo?.predictions?.length">
              <h3 class="section-title">CDS 功能预测 (Phold AI + Pharokka)</h3>
              <div class="table-scroll">
                <table class="data-table compact">
                  <thead>
                    <tr>
                      <th>CDS ID</th>
                      <th>位置</th>
                      <th>链</th>
                      <th>功能</th>
                      <th>产物</th>
                      <th>方法</th>
                      <th>置信度</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="p in pholdInfo.predictions" :key="p.cds_id">
                      <td class="mono">{{ p.cds_id }}</td>
                      <td class="mono">{{ p.start }}-{{ p.end }}</td>
                      <td>{{ p.strand }}</td>
                      <td><span class="func-tag"
                          :style="{ background: getFuncColor(p.function) + '20', color: getFuncColor(p.function) }">{{
                          p.function }}</span></td>
                      <td class="product-cell" :title="p.product">{{ p.product }}</td>
                      <td><span class="method-tag">{{ p.method || 'none' }}</span></td>
                      <td><span class="conf-tag" :class="p.confidence">{{ p.confidence || 'none' }}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Pharokka 功能统计表 -->
            <div v-else-if="funcList.length" style="margin-top: 20px">
              <h3 class="section-title">功能分类统计 (Pharokka)</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>类别</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="f in funcList" :key="f.name">
                    <td>{{ f.name }}</td>
                    <td>{{ f.count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-section">
              <p>暂无注释数据</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.report-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(6px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}

.report-dialog {
  width: 90vw;
  max-width: 960px;
  max-height: 88vh;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: scaleIn 0.25s ease;
}

/* ─── 头部 ─── */
.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 28px;
  background: linear-gradient(135deg, #1e3a5f, #2563eb);
  color: #fff;
}

.header-left h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-btn {
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.export-btn {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.export-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.35);
}

.export-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.task-label {
  font-size: 12px;
  opacity: 0.8;
  margin-top: 2px;
  display: block;
}

.close-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: #fff;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  font-size: 18px;
  cursor: pointer;
  transition: background 0.2s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

/* ─── 标签导航 ─── */
.tab-nav {
  display: flex;
  gap: 4px;
  padding: 12px 28px 0;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.tab-btn {
  padding: 10px 18px;
  border: none;
  background: none;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-btn:hover {
  color: #334155;
}

.tab-btn.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
}

.tab-icon {
  font-size: 16px;
}

/* ─── 内容区 ─── */
.report-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}

.tab-content {
  animation: fadeIn 0.2s ease;
}

/* ─── 总览网格 ─── */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  padding: 12px;
  border-radius: 8px;
  display: flex;
  gap: 10px;
  align-items: flex-start;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.genome-card {
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
}

.contig-card {
  background: linear-gradient(135deg, #f5f3ff, #ede9fe);
}

.cds-card {
  background: linear-gradient(135deg, #ecfdf5, #d1fae5);
}

.qc-card {
  background: linear-gradient(135deg, #fef3c7, #fde68a40);
}

.host-card {
  background: linear-gradient(135deg, #fff1f2, #ffe4e6);
}

.backfill-card {
  background: linear-gradient(135deg, #f0fdf4, #bbf7d0);
}

.checkv-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

/* CheckV 质量等级 */
.checkv-card.complete,
.checkv-card.high-quality {
  border-left: 4px solid #10b981;
  background: #ecfdf5;
}

.checkv-card.medium-quality {
  border-left: 4px solid #f59e0b;
  background: #fffbeb;
}

.checkv-card.low-quality {
  border-left: 4px solid #ef4444;
  background: #fef2f2;
}


.card-icon {
  font-size: 20px;
}

.card-body h4 {
  margin: 0 0 2px;
  font-size: 11px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 16px;
  font-weight: 800;
  color: #1e293b;
}

.stat-sub {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

/* ─── 功能条形图 ─── */
.section-block {
  margin-bottom: 28px;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 14px;
}

.func-bar-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.func-bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.func-label {
  width: 200px;
  font-size: 12px;
  color: #475569;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 0;
}

.func-bar-track {
  flex: 1;
  height: 20px;
  background: #f1f5f9;
  border-radius: 6px;
  overflow: hidden;
}

.func-bar-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.5s ease;
  min-width: 4px;
}

.func-count {
  width: 32px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
  text-align: right;
}

/* ─── 置信度条 ─── */
.confidence-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.conf-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.conf-label {
  width: 70px;
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}

.conf-label.high {
  color: #059669;
}

.conf-label.medium {
  color: #d97706;
}

.conf-label.low {
  color: #dc2626;
}

.conf-label.none {
  color: #94a3b8;
}

.conf-track {
  flex: 1;
  height: 14px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
}

.conf-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.conf-fill.high {
  background: #10b981;
}

.conf-fill.medium {
  background: #f59e0b;
}

.conf-fill.low {
  background: #ef4444;
}

.conf-fill.none {
  background: #cbd5e1;
}

.conf-num {
  width: 36px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

/* ─── 数据表格 ─── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th {
  background: #f8fafc;
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: #475569;
  border-bottom: 2px solid #e2e8f0;
  position: sticky;
  top: 0;
}

.data-table td {
  padding: 8px 14px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}

.data-table tbody tr:hover {
  background: #f8fafc;
}

.data-table.compact td {
  padding: 6px 10px;
  font-size: 12px;
}

.data-table.compact th {
  padding: 8px 10px;
  font-size: 12px;
}

.table-scroll {
  max-height: 480px;
  overflow-y: auto;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.mono {
  font-family: 'Cascadia Code', 'JetBrains Mono', monospace;
  font-size: 11px;
}

.product-cell {
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.func-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.method-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  background: #f1f5f9;
  color: #64748b;
}

.conf-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.conf-tag.high {
  background: #ecfdf5;
  color: #059669;
}

.conf-tag.medium {
  background: #fffbeb;
  color: #d97706;
}

.conf-tag.low {
  background: #fef2f2;
  color: #dc2626;
}

.conf-tag.none {
  background: #f1f5f9;
  color: #94a3b8;
}

/* ─── QC 过滤统计 ─── */
.filter-stats {
  display: flex;
  gap: 12px;
}

.filter-item {
  flex: 1;
  padding: 14px;
  border-radius: 10px;
  text-align: center;
}

.filter-item span {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.filter-item strong {
  font-size: 18px;
  color: #1e293b;
}

.filter-item.pass {
  background: #ecfdf5;
}

.filter-item.fail {
  background: #fef2f2;
}

/* ─── 组装统计 ─── */
.asm-stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.asm-stat {
  text-align: center;
  padding: 16px;
  background: #f8fafc;
  border-radius: 10px;
}

.asm-stat label {
  display: block;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 6px;
  text-transform: uppercase;
}

.asm-stat span {
  font-size: 18px;
  font-weight: 800;
  color: #1e293b;
}

/* ─── 状态 ─── */
.loading-state,
.error-state,
.empty-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: #94a3b8;
}

.spinner {
  width: 36px;
  height: 36px;
  border: 4px solid #f1f5f9;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 12px;
}

/* ─── 宿主详细提示框 ─── */
.host-warn-box {
  display: flex;
  gap: 16px;
  padding: 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 12px;
}

.host-warn-box.warning {
  background: #fff1f2;
  border-color: #fecdd3;
}

.warn-icon {
  font-size: 24px;
}

.warn-txt {
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px;
}

.warn-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  margin: 0;
}

.file-tag {
  display: inline-block;
  padding: 6px 12px;
  background: #f1f5f9;
  border-radius: 6px;
  margin: 4px;
  font-size: 12px;
}

.meta-tag {
  display: inline-block;
  padding: 2px 8px;
  background: #f1f5f9;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
}

/* ─── PhageScope 自动回填状态条 ─── */
.backfill-status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 22px;
  background: linear-gradient(135deg, #ecfdf5, #d1fae5);
  border: 1px solid #a7f3d0;
  border-radius: 14px;
  margin-bottom: 24px;
}

.backfill-status-bar .icon {
  font-size: 28px;
  flex-shrink: 0;
}

.backfill-status-bar .txt {
  flex: 1;
}

.backfill-status-bar .txt .main {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #065f46;
}

.backfill-status-bar .txt .sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: #047857;
  line-height: 1.4;
}

.auto-badge {
  padding: 6px 14px;
  background: #059669;
  color: white;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: 0.3px;
}

.auto-badge.pending {
  background: #94a3b8;
}

/* ─── PhageScope 回填统计卡片 ─── */
.backfill-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 20px;
}

.bf-stat {
  text-align: center;
  padding: 12px;
  background: #f0fdf4;
  border-radius: 10px;
  border: 1px solid #d1fae5;
}

.bf-stat.highlight {
  background: #ecfdf5;
  border-color: #6ee7b7;
}

.bf-stat label {
  display: block;
  font-size: 11px;
  color: #047857;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.bf-stat span {
  font-size: 20px;
  font-weight: 800;
  color: #065f46;
}

/* ─── 动画 ─── */
@keyframes fadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .overview-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .asm-stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .filter-stats {
    flex-wrap: wrap;
  }

  .func-label {
    width: 120px;
  }

  .report-dialog {
    width: 96vw;
    max-height: 94vh;
  }
}
</style>
