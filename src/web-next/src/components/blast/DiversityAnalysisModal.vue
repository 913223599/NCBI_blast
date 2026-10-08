<script setup lang="ts">
/**
 * DiversityAnalysisModal.vue
 * 16S 扩增子混样多样性还原与 rrnDB 拷贝数归一化分析面板
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { apiGet, apiPost, API_BASE } from '../../bridge/electron-bridge'
import { useAppStore } from '../../stores/app'
import { useStrainStore } from '../../stores/strain'
import UniversalUpload from '../common/UniversalUpload.vue'

const props = defineProps<{
  modelValue: boolean
  initialFilePath?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const appStore = useAppStore()
const strainStore = useStrainStore()

// 状态定义
const activeTab = ref<'chart' | 'alpha' | 'pcoa' | 'matrix'>('chart')
const abundanceMode = ref<'norm' | 'raw'>('norm') // 'norm': rrnDB校正, 'raw': 原始Reads
const currentFilePath = ref<string>('')
const isDetecting = ref(false)
const detectedPackage = ref<any>(null)

// 任务执行状态
const isRunning = ref(false)
const taskId = ref<string>('')
const progress = ref<number>(0)
const currentStep = ref<string>('')
const currentSample = ref<string>('')
const results = ref<any>(null)
let pollTimer: any = null

// 颜色板定义 (支持多达 16 种优势物种区分)
const PALETTE = [
  '#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed',
  '#0891b2', '#db2777', '#4b5563', '#4f46e5', '#16a34a',
  '#ea580c', '#e11d48', '#9333ea', '#0284c7', '#65a30d',
  '#94a3b8'
]

// 交互悬停 Tooltip 状态
const tooltip = ref<{
  visible: boolean
  x: number
  y: number
  sample: string
  taxon: string
  rawCount: number
  rawPct: number
  gcn: number
  normPct: number
}>({
  visible: false,
  x: 0,
  y: 0,
  sample: '',
  taxon: '',
  rawCount: 0,
  rawPct: 0,
  gcn: 1,
  normPct: 0
})

interface StackedSegment {
  taxon: string
  pct: number
  rawCount: number
  rawPct: number
  normPct: number
  gcn: number
  color: string
  yBottom: number
  yTop: number
}

interface StackedSample {
  sampleName: string
  totalReads: number
  segments: StackedSegment[]
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.initialFilePath) {
      currentFilePath.value = props.initialFilePath
      detectPackage(props.initialFilePath)
    }
  } else {
    stopPolling()
  }
})

function close() {
  emit('update:modelValue', false)
}

/** 智能检测压缩包 */
async function detectPackage(filePath: string) {
  if (!filePath) return
  isDetecting.value = true
  try {
    const res = await apiPost('/api/diversity/detect_package', { file_path: filePath })
    if (res && res.is_amplicon_package) {
      detectedPackage.value = res
    } else {
      detectedPackage.value = null
    }
  } catch (e) {
    console.error('Detect package failed:', e)
  } finally {
    isDetecting.value = false
  }
}

function handleUploadSuccess(paths: string[]) {
  if (paths && paths.length > 0 && paths[0]) {
    currentFilePath.value = paths[0]
    detectPackage(paths[0])
  }
}

/** 启动分析 */
async function startAnalysis() {
  if (!currentFilePath.value) {
    appStore.showNotification('请先选择或拖入测序结果压缩包', 'warning')
    return
  }

  isRunning.value = true
  progress.value = 2.0
  currentStep.value = '正在初始化分析任务...'
  results.value = null

  try {
    const res = await apiPost('/api/diversity/run', {
      input_path: currentFilePath.value
    })

    if (res && res.task_id) {
      taskId.value = String(res.task_id)
      startPolling()
    } else {
      throw new Error(res?.detail || '任务创建失败')
    }
  } catch (err: any) {
    isRunning.value = false
    appStore.showNotification(`启动失败: ${err.message || err}`, 'error')
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!taskId.value) return
    try {
      const statusRes = await apiGet(`/api/diversity/status/${taskId.value}`)
      if (statusRes) {
        progress.value = statusRes.progress || 0
        currentStep.value = statusRes.current_step || ''
        currentSample.value = statusRes.current_sample || ''

        if (statusRes.status === 'completed') {
          stopPolling()
          fetchResults()
        } else if (statusRes.status === 'error') {
          stopPolling()
          isRunning.value = false
          appStore.showNotification(`分析失败: ${statusRes.error}`, 'error')
        }
      }
    } catch (e) {
      console.error('Polling status error:', e)
    }
  }, 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchResults() {
  try {
    const res = await apiGet(`/api/diversity/results/${taskId.value}`)
    if (res && res.samples) {
      results.value = res
      isRunning.value = false
      appStore.showNotification('16S 群落多样性与 rrnDB 归一化分析完成！', 'success')
    }
  } catch (e: any) {
    isRunning.value = false
    appStore.showNotification(`获取分析报告失败: ${e.message || e}`, 'error')
  }
}

/** 全局 Top 10 物种列表 (其余归入 Other) */
const topTaxaList = computed(() => {
  if (!results.value || !results.value.taxa_overview) return []
  const list = results.value.taxa_overview.slice(0, 10).map((t: any) => t.taxon)
  return list
})

function getTaxonColor(taxon: string): string {
  const idx = topTaxaList.value.indexOf(taxon)
  if (idx >= 0 && idx < PALETTE.length) {
    return PALETTE[idx] || '#94a3b8'
  }
  return '#94a3b8' // Other
}

/** 柱状图数据计算 */
const stackedBarData = computed<StackedSample[]>(() => {
  if (!results.value || !results.value.samples) return []
  const samples = results.value.samples
  const isNorm = abundanceMode.value === 'norm'

  return samples.map((s: any) => {
    const details = s.norm_result?.details || []
    const segments: StackedSegment[] = []
    let cumulative = 0

    // 分离 Top 物种与 Others
    const topItems: any[] = []
    let otherPct = 0
    let otherRaw = 0

    details.forEach((d: any) => {
      const pct = Number(isNorm ? d.norm_pct : d.raw_pct) || 0
      if (topTaxaList.value.includes(d.taxon)) {
        topItems.push({
          taxon: d.taxon,
          pct: pct,
          rawCount: d.raw_count,
          rawPct: d.raw_pct,
          normPct: d.norm_pct,
          gcn: d.gcn_mean
        })
      } else {
        otherPct += pct
        otherRaw += d.raw_count
      }
    })

    if (otherPct > 0) {
      topItems.push({
        taxon: '其他 (Others)',
        pct: Math.round(otherPct * 100) / 100,
        rawCount: otherRaw,
        rawPct: Math.round(otherPct * 100) / 100,
        normPct: Math.round(otherPct * 100) / 100,
        gcn: 1.0
      })
    }

    topItems.forEach((item) => {
      const height = Number(item.pct) || 0
      segments.push({
        taxon: item.taxon,
        pct: height,
        rawCount: item.rawCount,
        rawPct: item.rawPct,
        normPct: item.normPct,
        gcn: item.gcn,
        color: getTaxonColor(item.taxon),
        yBottom: cumulative,
        yTop: cumulative + height
      })
      cumulative += height
    })

    return {
      sampleName: s.sample_name,
      totalReads: s.total_reads,
      segments
    }
  })
})

/** Alpha 多样性统计平均值 */
const alphaSummary = computed(() => {
  if (!results.value || !results.value.samples) return null
  const samples = results.value.samples
  const n = samples.length
  if (n === 0) return null

  const sumRich = samples.reduce((acc: number, s: any) => acc + (s.alpha_diversity?.richness || 0), 0)
  const sumShannon = samples.reduce((acc: number, s: any) => acc + (s.alpha_diversity?.shannon || 0), 0)
  const sumSimpson = samples.reduce((acc: number, s: any) => acc + (s.alpha_diversity?.simpson || 0), 0)
  const sumEven = samples.reduce((acc: number, s: any) => acc + (s.alpha_diversity?.evenness || 0), 0)

  return {
    meanRichness: (sumRich / n).toFixed(1),
    meanShannon: (sumShannon / n).toFixed(2),
    meanSimpson: (sumSimpson / n).toFixed(3),
    meanEvenness: (sumEven / n).toFixed(2)
  }
})

/** PCoA 散点图视口换算 */
const pcoaPlotData = computed(() => {
  if (!results.value || !results.value.beta_diversity?.pcoa_points) return null
  const pts = results.value.beta_diversity.pcoa_points
  if (!pts || pts.length === 0) return null

  const pc1s = pts.map((p: any) => Number(p.pc1) || 0)
  const pc2s = pts.map((p: any) => Number(p.pc2) || 0)

  const minX = Math.min(...pc1s), maxX = Math.max(...pc1s)
  const minY = Math.min(...pc2s), maxY = Math.max(...pc2s)

  const padX = (maxX - minX) * 0.15 || 0.1
  const padY = (maxY - minY) * 0.15 || 0.1

  const dX0 = minX - padX
  const dX1 = maxX + padX
  const dY0 = minY - padY
  const dY1 = maxY + padY
  const spanX = (dX1 - dX0) || 1
  const spanY = (dY1 - dY0) || 1

  const width = 600
  const height = 360

  const mapped = pts.map((p: any) => {
    const valX = Number(p.pc1) || 0
    const valY = Number(p.pc2) || 0
    const cx = 50 + ((valX - dX0) / spanX) * (width - 100)
    const cy = height - 50 - ((valY - dY0) / spanY) * (height - 100)
    return {
      ...p,
      cx,
      cy
    }
  })

  return {
    points: mapped,
    varPc1: results.value.beta_diversity.var_pc1,
    varPc2: results.value.beta_diversity.var_pc2,
    width,
    height
  }
})

function showSegmentTooltip(e: MouseEvent, seg: any, sampleName: string) {
  tooltip.value = {
    visible: true,
    x: e.clientX + 12,
    y: e.clientY - 20,
    sample: sampleName,
    taxon: seg.taxon,
    rawCount: seg.rawCount,
    rawPct: seg.rawPct,
    gcn: seg.gcn,
    normPct: seg.normPct
  }
}

function hideTooltip() {
  tooltip.value.visible = false
}

/** 导出 Excel 报告 */
function exportExcel() {
  if (!taskId.value) return
  const url = `${API_BASE}/api/diversity/export_excel/${taskId.value}`
  window.open(url, '_blank')
}

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div v-if="modelValue" class="modal-overlay" @click.self="close">
    <div class="modal-container-neo">
      <!-- 头部 -->
      <div class="modal-header-neo">
        <div class="header-left">
          <div class="icon-wrap">
            <span class="icon-sym">🧬</span>
          </div>
          <div>
            <h2 class="title">16S 扩增子混样多样性还原与 rrnDB 拷贝数校正</h2>
            <p class="subtitle">针对未纯化样本、环境混样与多采样重复点位的高通量全长群落结构解析</p>
          </div>
        </div>
        <div class="header-right">
          <button v-if="results" class="btn-export-neo" @click="exportExcel">
            <span class="btn-icon">📊</span> 导出 Excel 报告
          </button>
          <button class="btn-close-neo" @click="close">✕</button>
        </div>
      </div>

      <!-- 载入与控制区 -->
      <div v-if="!results && !isRunning" class="import-section-neo">
        <div class="upload-box-wrapper">
          <UniversalUpload 
            type="fasta"
            accept=".zip,.fastq,.fastq.gz"
            label="拖入生工测序交付压缩包 (例如: 吴晨_2140601771_测序结果.zip) 或 FASTQ 集合"
            @success="handleUploadSuccess"
          />
        </div>

        <div v-if="detectedPackage" class="detect-badge-card">
          <div class="badge-status-tag">识别成功</div>
          <div class="detect-info">
            <span class="name">{{ detectedPackage.file_name }}</span>
            <span class="desc">
              检测到 <strong>{{ detectedPackage.fastq_count }} 个</strong> 独立样本的单分子 FASTQ 数据（生工三代测序标准交付件）
            </span>
          </div>
          <button class="btn-start-action" @click="startAnalysis">
            立即启动多样性还原分析
          </button>
        </div>
        <div v-else-if="currentFilePath" class="fallback-launch">
          <button class="btn-start-action" @click="startAnalysis">
            开始分析该文件
          </button>
        </div>
      </div>

      <!-- 运行进度展示 -->
      <div v-if="isRunning" class="progress-section-neo">
        <div class="progress-card-neo">
          <div class="pulse-icon">⚡</div>
          <div class="progress-info">
            <div class="step-text">{{ currentStep }}</div>
            <div class="sample-hint" v-if="currentSample">正在处理点位: <strong>{{ currentSample }}</strong></div>
          </div>
          <div class="progress-bar-wrap">
            <div class="bar-fill" :style="{ width: `${progress}%` }"></div>
          </div>
          <div class="progress-num">{{ progress }}%</div>
          <div class="checkpoint-tip">
            <span>🛡️</span> 分片落盘与断点保护 (Checkpoint) 生效中，防止大规模数据 OOM 崩溃
          </div>
        </div>
      </div>

      <!-- 分析结果面板 -->
      <div v-if="results" class="results-dashboard-neo">
        <!-- 统计核心条目 -->
        <div class="stats-overview-bar">
          <div class="stat-pill">
            <span class="label">样本总数:</span>
            <span class="val">{{ results.total_samples }} 个点位</span>
          </div>
          <div class="stat-pill">
            <span class="label">有效 Reads:</span>
            <span class="val">{{ results.total_classified_reads.toLocaleString() }} 条</span>
          </div>
          <div class="stat-pill">
            <span class="label">检出物种:</span>
            <span class="val">{{ results.taxa_overview.length }} 种</span>
          </div>
          <div class="stat-pill pill-rrndb">
            <span class="label">校正状态:</span>
            <span class="val">rrnDB v5.10 已归一化</span>
          </div>

          <!-- 模式切换开关 -->
          <div class="abundance-mode-toggle">
            <button 
              class="toggle-btn" 
              :class="{ active: abundanceMode === 'norm' }"
              @click="abundanceMode = 'norm'"
              title="消除 16S 基因拷贝数偏好，真实还原微生物细胞丰度"
            >
              rrnDB 拷贝数归一化丰度
            </button>
            <button 
              class="toggle-btn" 
              :class="{ active: abundanceMode === 'raw' }"
              @click="abundanceMode = 'raw'"
              title="原始测序下机 Reads 计数比例"
            >
              原始 Reads 占比
            </button>
          </div>
        </div>

        <!-- 标签页导航 -->
        <div class="sub-tabs-neo">
          <button class="tab-item" :class="{ active: activeTab === 'chart' }" @click="activeTab = 'chart'">
            📊 物种丰度堆叠柱状图
          </button>
          <button class="tab-item" :class="{ active: activeTab === 'alpha' }" @click="activeTab = 'alpha'">
            🌿 Alpha 多样性指数
          </button>
          <button class="tab-item" :class="{ active: activeTab === 'pcoa' }" @click="activeTab = 'pcoa'">
            🌐 Beta 多样性与点位空间分布 (PCoA)
          </button>
          <button class="tab-item" :class="{ active: activeTab === 'matrix' }" @click="activeTab = 'matrix'">
            📑 样本明细与校正大表
          </button>
        </div>

        <!-- TAB 1: 物种丰度堆叠柱状图 -->
        <div v-show="activeTab === 'chart'" class="tab-content-neo scroll-y">
          <div class="chart-container-card">
            <div class="chart-legend-wrap">
              <div 
                v-for="taxon in topTaxaList" 
                :key="taxon" 
                class="legend-badge"
              >
                <span class="dot" :style="{ background: getTaxonColor(taxon) }"></span>
                <span class="text">{{ taxon }}</span>
              </div>
              <div class="legend-badge">
                <span class="dot" style="background: #94a3b8"></span>
                <span class="text">其他 (Others)</span>
              </div>
            </div>

            <!-- SVG 堆叠柱状图 -->
            <div class="svg-scroll-container">
              <svg :width="Math.max(800, stackedBarData.length * 36 + 100)" height="340" class="stacked-bar-svg">
                <!-- 背景网格刻度 -->
                <line x1="50" y1="30" x2="100%" y2="30" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="95" x2="100%" y2="95" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="160" x2="100%" y2="160" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="225" x2="100%" y2="225" stroke="#f1f5f9" stroke-dasharray="4,4" />
                <line x1="50" y1="290" x2="100%" y2="290" stroke="#cbd5e1" />

                <!-- Y 轴标签 -->
                <text x="42" y="34" text-anchor="end" class="axis-txt">100%</text>
                <text x="42" y="99" text-anchor="end" class="axis-txt">75%</text>
                <text x="42" y="164" text-anchor="end" class="axis-txt">50%</text>
                <text x="42" y="229" text-anchor="end" class="axis-txt">25%</text>
                <text x="42" y="294" text-anchor="end" class="axis-txt">0%</text>

                <!-- 样本柱体 -->
                <g v-for="(sample, idx) in stackedBarData" :key="sample.sampleName" :transform="`translate(${65 + idx * 34}, 0)`">
                  <g v-for="seg in sample.segments" :key="seg.taxon">
                    <rect 
                      :y="290 - (seg.yTop / 100 * 260)"
                      :height="(seg.pct / 100 * 260)"
                      width="24"
                      :fill="seg.color"
                      rx="2"
                      class="bar-seg"
                      @mousemove="showSegmentTooltip($event, seg, sample.sampleName)"
                      @mouseleave="hideTooltip"
                    />
                  </g>
                  <!-- X 轴样本名 -->
                  <text 
                    x="12" 
                    y="306" 
                    text-anchor="end" 
                    transform="rotate(-45, 12, 306)" 
                    class="sample-x-label"
                  >
                    {{ sample.sampleName }}
                  </text>
                </g>
              </svg>
            </div>
          </div>
        </div>

        <!-- TAB 2: Alpha 多样性指数 -->
        <div v-show="activeTab === 'alpha'" class="tab-content-neo scroll-y">
          <div v-if="alphaSummary" class="alpha-cards-grid">
            <div class="alpha-card">
              <span class="alpha-label">平均物种丰富度 (Richness)</span>
              <span class="alpha-val text-blue">{{ alphaSummary.meanRichness }}</span>
              <span class="alpha-sub">平均每个采样点检出的菌种数</span>
            </div>
            <div class="alpha-card">
              <span class="alpha-label">平均香农指数 (Shannon-Wiener)</span>
              <span class="alpha-val text-green">{{ alphaSummary.meanShannon }}</span>
              <span class="alpha-sub">群落多样性与复杂性指标</span>
            </div>
            <div class="alpha-card">
              <span class="alpha-label">平均辛普森指数 (Gini-Simpson)</span>
              <span class="alpha-val text-purple">{{ alphaSummary.meanSimpson }}</span>
              <span class="alpha-sub">优势菌种占优程度</span>
            </div>
            <div class="alpha-card">
              <span class="alpha-label">平均 Pielou 均匀度 (Evenness)</span>
              <span class="alpha-val text-orange">{{ alphaSummary.meanEvenness }}</span>
              <span class="alpha-sub">群落分配均匀性 (0~1)</span>
            </div>
          </div>

          <!-- 各点位 Alpha 指数明细表 -->
          <div class="alpha-table-card">
            <table class="neo-data-table">
              <thead>
                <tr>
                  <th>采样点位</th>
                  <th>总测序 Reads</th>
                  <th>分类 Reads</th>
                  <th>丰富度 (Richness)</th>
                  <th>香农指数 (Shannon)</th>
                  <th>辛普森指数 (Simpson)</th>
                  <th>Chao1 估算值</th>
                  <th>均匀度 (Evenness)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in results.samples" :key="s.sample_name">
                  <td class="mono font-bold">{{ s.sample_name }}</td>
                  <td>{{ s.total_reads }}</td>
                  <td>{{ s.classified_reads }}</td>
                  <td><span class="badge-num bg-blue">{{ s.alpha_diversity?.richness }}</span></td>
                  <td>{{ s.alpha_diversity?.shannon }}</td>
                  <td>{{ s.alpha_diversity?.simpson }}</td>
                  <td>{{ s.alpha_diversity?.chao1 }}</td>
                  <td>{{ s.alpha_diversity?.evenness }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- TAB 3: Beta 多样性与点位空间分布 (PCoA) -->
        <div v-show="activeTab === 'pcoa'" class="tab-content-neo scroll-y">
          <div v-if="pcoaPlotData" class="pcoa-card-wrap">
            <div class="pcoa-header">
              <h3 class="card-title">主坐标分析 (PCoA - Bray-Curtis 距离)</h3>
              <p class="card-desc">
                检验随机采样点位之间的空间异质性：点位聚类越紧密，代表微生物群落结构越均一；散布越开，反映微生境空间斑块化程度越高。
              </p>
            </div>
            <div class="pcoa-svg-wrap">
              <svg :width="pcoaPlotData.width" :height="pcoaPlotData.height" class="pcoa-svg">
                <!-- 坐标轴 -->
                <line x1="50" :y1="pcoaPlotData.height - 50" :x2="pcoaPlotData.width - 20" :y2="pcoaPlotData.height - 50" stroke="#cbd5e1" stroke-width="2" />
                <line x1="50" y1="20" x2="50" :y2="pcoaPlotData.height - 50" stroke="#cbd5e1" stroke-width="2" />

                <!-- 轴标签 -->
                <text :x="pcoaPlotData.width / 2" :y="pcoaPlotData.height - 15" text-anchor="middle" class="axis-bold">
                  PC1 (解释度: {{ pcoaPlotData.varPc1 }}%)
                </text>
                <text x="20" :y="pcoaPlotData.height / 2" text-anchor="middle" transform="rotate(-90, 20, 180)" class="axis-bold">
                  PC2 (解释度: {{ pcoaPlotData.varPc2 }}%)
                </text>

                <!-- 散点 -->
                <g v-for="pt in pcoaPlotData.points" :key="pt.sample_name">
                  <circle 
                    :cx="pt.cx" 
                    :cy="pt.cy" 
                    r="7" 
                    fill="#2563eb" 
                    fill-opacity="0.8" 
                    stroke="#ffffff" 
                    stroke-width="2"
                    class="pcoa-point"
                  />
                  <text :x="pt.cx + 9" :y="pt.cy + 4" class="pcoa-label">{{ pt.sample_name }}</text>
                </g>
              </svg>
            </div>
          </div>
        </div>

        <!-- TAB 4: 样本明细与校正大表 -->
        <div v-show="activeTab === 'matrix'" class="tab-content-neo scroll-y">
          <div class="matrix-card">
            <table class="neo-data-table">
              <thead>
                <tr>
                  <th>采样点位</th>
                  <th>物种名称</th>
                  <th>原始 Reads</th>
                  <th>原始占比 (%)</th>
                  <th>16S 拷贝数 (GCN)</th>
                  <th>匹配级别</th>
                  <th>rrnDB 校正后占比 (%)</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="s in results.samples" :key="s.sample_name">
                  <tr v-for="(d, idx) in s.norm_result?.details || []" :key="d.taxon">
                    <td v-if="idx === 0" :rowspan="s.norm_result?.details.length" class="mono font-bold align-top">
                      {{ s.sample_name }}
                    </td>
                    <td class="italic font-medium">{{ d.taxon }}</td>
                    <td>{{ d.raw_count }}</td>
                    <td>{{ d.raw_pct }}%</td>
                    <td><strong>{{ d.gcn_mean }}</strong></td>
                    <td>
                      <span class="badge-match" :class="d.gcn_matched ? 'match-ok' : 'match-fallback'">
                        {{ d.gcn_rank }}
                      </span>
                    </td>
                    <td><span class="norm-val">{{ d.norm_pct }}%</span></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 浮动 Tooltip -->
      <div 
        v-if="tooltip.visible" 
        class="floating-tooltip"
        :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
      >
        <div class="tt-sample">{{ tooltip.sample }}</div>
        <div class="tt-taxon">{{ tooltip.taxon }}</div>
        <div class="tt-divider"></div>
        <div class="tt-row">
          <span>原始 Reads:</span>
          <strong>{{ tooltip.rawCount }} 条 ({{ tooltip.rawPct }}%)</strong>
        </div>
        <div class="tt-row">
          <span>16S 基因拷贝数 (GCN):</span>
          <strong>{{ tooltip.gcn }}</strong>
        </div>
        <div class="tt-row tt-highlight">
          <span>rrnDB 校正相对丰度:</span>
          <strong>{{ tooltip.normPct }}%</strong>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.modal-container-neo {
  width: 95vw;
  max-width: 1280px;
  height: 90vh;
  background: #ffffff;
  border-radius: 18px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.modal-header-neo {
  padding: 16px 24px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #eff6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.4rem;
}
.title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
}
.subtitle {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: #64748b;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn-export-neo {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  background: #10b981;
  color: white;
  border: none;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-export-neo:hover {
  background: #059669;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}
.btn-close-neo {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 8px;
}
.btn-close-neo:hover {
  color: #ef4444;
  background: #fee2e2;
}

.import-section-neo {
  padding: 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  align-items: center;
  justify-content: center;
  flex: 1;
}
.upload-box-wrapper {
  width: 100%;
  max-width: 720px;
}
.detect-badge-card {
  width: 100%;
  max-width: 720px;
  padding: 20px 24px;
  border-radius: 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  display: flex;
  align-items: center;
  gap: 16px;
}
.badge-status-tag {
  background: #16a34a;
  color: white;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
}
.detect-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.detect-info .name {
  font-weight: 700;
  color: #14532d;
  font-size: 0.95rem;
}
.detect-info .desc {
  font-size: 0.82rem;
  color: #166534;
  margin-top: 2px;
}
.btn-start-action {
  padding: 10px 20px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-start-action:hover {
  background: #1d4ed8;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.progress-section-neo {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.progress-card-neo {
  width: 480px;
  padding: 32px;
  background: white;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
  text-align: center;
}
.pulse-icon {
  font-size: 2.2rem;
  margin-bottom: 12px;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.15); opacity: 0.8; }
}
.step-text {
  font-weight: 700;
  color: #1e293b;
  font-size: 1rem;
}
.sample-hint {
  font-size: 0.82rem;
  color: #64748b;
  margin-top: 4px;
}
.progress-bar-wrap {
  width: 100%;
  height: 10px;
  background: #f1f5f9;
  border-radius: 6px;
  overflow: hidden;
  margin: 18px 0 10px;
}
.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #3b82f6);
  border-radius: 6px;
  transition: width 0.3s ease;
}
.progress-num {
  font-weight: 800;
  color: #2563eb;
  font-size: 1.1rem;
}
.checkpoint-tip {
  margin-top: 16px;
  font-size: 0.75rem;
  color: #059669;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: #ecfdf5;
  padding: 6px 12px;
  border-radius: 8px;
}

.results-dashboard-neo {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stats-overview-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 24px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.stat-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  background: white;
  border: 1px solid #e2e8f0;
  font-size: 0.8rem;
}
.stat-pill .label { color: #64748b; }
.stat-pill .val { font-weight: 700; color: #1e293b; }
.pill-rrndb { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.pill-rrndb .val { color: #15803d; }

.abundance-mode-toggle {
  margin-left: auto;
  display: flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: 8px;
}
.toggle-btn {
  padding: 5px 12px;
  border: none;
  background: none;
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.toggle-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.sub-tabs-neo {
  display: flex;
  gap: 8px;
  padding: 10px 24px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}
.tab-item {
  padding: 8px 16px;
  border: none;
  background: none;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-item:hover { color: #1e293b; background: #f1f5f9; }
.tab-item.active { background: #eff6ff; color: #2563eb; font-weight: 700; }

.tab-content-neo {
  flex: 1;
  padding: 20px 24px;
  background: #f8fafc;
}
.scroll-y { overflow-y: auto; }

.chart-container-card {
  background: white;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
}
.chart-legend-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
}
.legend-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.76rem;
  color: #334155;
  font-weight: 500;
}
.legend-badge .dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.svg-scroll-container {
  overflow-x: auto;
  padding-bottom: 16px;
}
.stacked-bar-svg {
  display: block;
}
.axis-txt {
  font-size: 11px;
  fill: #94a3b8;
  font-family: sans-serif;
}
.sample-x-label {
  font-size: 10px;
  fill: #475569;
  font-family: monospace;
}
.bar-seg {
  cursor: pointer;
  transition: opacity 0.2s;
}
.bar-seg:hover {
  opacity: 0.85;
}

.alpha-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.alpha-card {
  background: white;
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
}
.alpha-label { font-size: 0.75rem; color: #64748b; font-weight: 600; }
.alpha-val { font-size: 1.8rem; font-weight: 800; margin: 4px 0; }
.alpha-sub { font-size: 0.7rem; color: #94a3b8; }
.text-blue { color: #2563eb; }
.text-green { color: #059669; }
.text-purple { color: #7c3aed; }
.text-orange { color: #d97706; }

.alpha-table-card, .matrix-card {
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.neo-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  text-align: left;
}
.neo-data-table th {
  background: #f8fafc;
  padding: 12px 16px;
  color: #475569;
  font-weight: 700;
  border-bottom: 1px solid #e2e8f0;
}
.neo-data-table td {
  padding: 10px 16px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}
.mono { font-family: monospace; }
.badge-num {
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 0.75rem;
}
.bg-blue { background: #dbeafe; color: #1e40af; }

.pcoa-card-wrap {
  background: white;
  padding: 24px;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.pcoa-header { width: 100%; margin-bottom: 16px; }
.pcoa-header .card-title { margin: 0; font-size: 1rem; color: #0f172a; }
.pcoa-header .card-desc { margin: 4px 0 0; font-size: 0.8rem; color: #64748b; }
.pcoa-svg-wrap { margin: 10px 0; }
.axis-bold { font-size: 12px; font-weight: 700; fill: #475569; }
.pcoa-point { cursor: pointer; transition: r 0.2s; }
.pcoa-point:hover { r: 10; fill: #1d4ed8; }
.pcoa-label { font-size: 10px; font-family: monospace; fill: #64748b; }

.badge-match {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
}
.match-ok { background: #dcfce7; color: #15803d; }
.match-fallback { background: #fef3c7; color: #b45309; }
.norm-val { font-weight: 700; color: #2563eb; }

.floating-tooltip {
  position: fixed;
  background: rgba(15, 23, 42, 0.95);
  color: white;
  padding: 12px 16px;
  border-radius: 10px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
  pointer-events: none;
  z-index: 10000;
  font-size: 0.78rem;
  max-width: 280px;
}
.tt-sample { font-size: 0.72rem; color: #94a3b8; font-family: monospace; }
.tt-taxon { font-size: 0.88rem; font-weight: 700; color: #38bdf8; margin: 2px 0 6px; }
.tt-divider { height: 1px; background: rgba(255, 255, 255, 0.1); margin: 6px 0; }
.tt-row { display: flex; justify-content: space-between; gap: 12px; margin-top: 3px; }
.tt-row span { color: #cbd5e1; }
.tt-highlight strong { color: #4ade80; }
</style>
