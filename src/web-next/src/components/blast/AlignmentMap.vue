<script setup lang="ts">
/**
 * AlignmentMap.vue - 专业生物序列 BLAST 比对可视化与变异指纹图谱
 * 支持：
 * 1. SNP / 错配与突变位点指纹图 (Mismatch Fingerprint Track)
 * 2. 交互式碱基比对详情展开 (Interactive Base-by-Base Alignment)
 * 3. 物种相似度与分辨力梯队图 (Identity Spectrum)
 */
import { ref, computed } from 'vue'

interface Mismatch {
  q_pos: number
  s_pos: number
  q_base: string
  s_base: string
  type: 'snp' | 'insertion' | 'deletion'
}

interface HSP {
  query_start: number
  query_end: number
  sbjct_start?: number
  sbjct_end?: number
  score: number
  evalue: number
  identity: number
  identity_pct?: number
  identities?: number
  align_length?: number
  gaps?: number
  mismatch_count?: number
  mismatches?: Mismatch[]
  query_seq?: string
  sbjct_seq?: string
  midline?: string
}

interface Hit {
  title: string
  length: number
  hsps: HSP[]
}

const props = defineProps<{
  queryName: string
  queryLength: number
  hits: Hit[]
}>()

// 当前激活的视图模式: 'fingerprint' | 'coverage' | 'spectrum'
const activeView = ref<'fingerprint' | 'coverage' | 'spectrum'>('fingerprint')

// 当前选中的 Hit 索引（用于展开比对详情）
const expandedHitIndex = ref<number | null>(0)

const currentExpandedHit = computed<Hit | null>(() => {
  if (expandedHitIndex.value === null || !props.hits) return null
  return props.hits[expandedHitIndex.value] ?? null
})

const currentExpandedHsp = computed<HSP | null>(() => {
  return currentExpandedHit.value?.hsps?.[0] ?? null
})

// 浮动 Tooltip 状态
const tooltip = ref<{
  show: boolean
  x: number
  y: number
  title: string
  detail: string
}>({
  show: false,
  x: 0,
  y: 0,
  title: '',
  detail: ''
})

// 绘图尺寸常量
const WIDTH = 820
const ROW_HEIGHT = 38
const LEFT_MARGIN = 260
const RIGHT_MARGIN = 160
const TOP_MARGIN = 55
const BOTTOM_MARGIN = 35

const totalWidth = WIDTH + LEFT_MARGIN + RIGHT_MARGIN
const totalHeight = computed(() => (props.hits?.length ?? 0) * ROW_HEIGHT + TOP_MARGIN + BOTTOM_MARGIN)

// 比例尺
const scaleX = (pos: number) => {
  if (!props.queryLength || props.queryLength <= 0) return 0
  return (pos / props.queryLength) * WIDTH
}

// 碱基颜色规范
function getBaseColor(base: string) {
  const b = (base || '').toUpperCase()
  if (b === 'A') return '#10b981' // 绿色
  if (b === 'T') return '#ef4444' // 红色
  if (b === 'C') return '#3b82f6' // 蓝色
  if (b === 'G') return '#f59e0b' // 琥珀橙
  if (b === '-') return '#8b5cf6' // 紫色 (InDel)
  return '#94a3b8'
}

// 精细相似度颜色
function getIdentityColor(pct: number) {
  if (pct >= 99.0) return '#059669' // 翠绿 (高同源)
  if (pct >= 97.0) return '#2563eb' // 经典蓝 (同种/近缘)
  if (pct >= 95.0) return '#7c3aed' // 紫色 (同属近缘)
  if (pct >= 90.0) return '#ea580c' // 橙色 (同科/远缘)
  return '#dc2626' // 红色 (<90%)
}

// 提取精简物种标题
function simplifyTitle(title?: string): string {
  if (!title) return '未知序列'
  const match = title.match(/\[(.*?)\]/)
  if (match && match[1]) return match[1]
  
  const clean = title.replace(/^gi\|\d+\|gb\|[^|]+\|\s*/, '').replace(/^gi\|\d+\|ref\|[^|]+\|\s*/, '')
  const words = clean.split(/\s+/)
  return words.slice(0, 5).join(' ') || title
}

// 统计信息
const stats = computed(() => {
  if (!props.hits || props.hits.length === 0) return null
  const allHsps = props.hits.flatMap(h => h.hsps || [])
  if (allHsps.length === 0) return null
  const maxIdentity = Math.max(...allHsps.map(h => h.identity_pct || (h.identity * 100)))
  const minIdentity = Math.min(...allHsps.map(h => h.identity_pct || (h.identity * 100)))
  const totalMismatches = allHsps.reduce((acc, h) => acc + (h.mismatch_count || 0), 0)
  return {
    hitCount: props.hits.length,
    maxIdentity: maxIdentity.toFixed(2),
    minIdentity: minIdentity.toFixed(2),
    avgMismatches: (totalMismatches / allHsps.length).toFixed(1)
  }
})

// Tooltip 交互
function showMismatchTooltip(event: MouseEvent, m: Mismatch, hitTitle?: string) {
  tooltip.value = {
    show: true,
    x: event.clientX + 10,
    y: event.clientY - 20,
    title: simplifyTitle(hitTitle),
    detail: `位置: ${m.q_pos} bp | 查询序列: [${m.q_base}] -> 目标序列: [${m.s_base}] (${m.type === 'snp' ? '单碱基突变' : m.type === 'insertion' ? '插入' : '缺失'})`
  }
}

function hideTooltip() {
  tooltip.value.show = false
}

// 格式化对齐序列（分块显示）
function getAlignmentBlocks(hsp: HSP | null | undefined, blockSize = 60) {
  if (!hsp || !hsp.query_seq || !hsp.sbjct_seq) return []
  const blocks = []
  const len = hsp.query_seq.length
  let qCurr = hsp.query_start
  let sCurr = hsp.sbjct_start || 1

  for (let i = 0; i < len; i += blockSize) {
    const qChunk = hsp.query_seq.slice(i, i + blockSize)
    const sChunk = hsp.sbjct_seq.slice(i, i + blockSize)
    const mChunk = (hsp.midline || '').slice(i, i + blockSize)

    const qGaps = (qChunk.match(/-/g) || []).length
    const sGaps = (sChunk.match(/-/g) || []).length

    const qEnd = qCurr + qChunk.length - qGaps - 1
    const sEnd = sCurr + sChunk.length - sGaps - 1

    blocks.push({
      qStart: qCurr,
      qEnd: qEnd,
      sStart: sCurr,
      sEnd: sEnd,
      qSeq: qChunk,
      sSeq: sChunk,
      midline: mChunk
    })

    qCurr = qEnd + 1
    sCurr = sEnd + 1
  }
  return blocks
}
</script>

<template>
  <div class="advanced-alignment-visualizer">
    <!-- 顶部概览仪表板 -->
    <div class="visual-header-banner">
      <div class="query-info-box">
        <span class="badge">Query</span>
        <div class="query-title" :title="queryName">{{ queryName }}</div>
        <div class="query-len">{{ queryLength }} bp</div>
      </div>

      <!-- 核心指标统计 -->
      <div v-if="stats" class="stats-ribbon">
        <div class="stat-pill">
          <span class="label">Top Hit 相似度</span>
          <span class="val high">{{ stats.maxIdentity }}%</span>
        </div>
        <div class="stat-pill">
          <span class="label">相似度区间</span>
          <span class="val">{{ stats.minIdentity }}% ~ {{ stats.maxIdentity }}%</span>
        </div>
        <div class="stat-pill">
          <span class="label">平均错配位点</span>
          <span class="val">{{ stats.avgMismatches }} bp</span>
        </div>
        <div class="stat-pill">
          <span class="label">比对命中数</span>
          <span class="val count">{{ stats.hitCount }} 条</span>
        </div>
      </div>

      <!-- 视图模式切换器 -->
      <div class="view-switch-tabs">
        <button 
          class="tab-btn" 
          :class="{ active: activeView === 'fingerprint' }"
          @click="activeView = 'fingerprint'"
        >
          突变指纹图谱
        </button>
        <button 
          class="tab-btn" 
          :class="{ active: activeView === 'coverage' }"
          @click="activeView = 'coverage'"
        >
          全长覆盖度
        </button>
        <button 
          class="tab-btn" 
          :class="{ active: activeView === 'spectrum' }"
          @click="activeView = 'spectrum'"
        >
          相似度梯队
        </button>
      </div>
    </div>

    <!-- 图例与操作说明栏 -->
    <div class="legend-bar">
      <div v-if="activeView === 'fingerprint'" class="legend-items">
        <span class="legend-title">突变标记图例:</span>
        <span class="legend-dot" style="background:#10b981;"></span> 腺嘌呤 (A)
        <span class="legend-dot" style="background:#ef4444;"></span> 胸腺嘧啶 (T)
        <span class="legend-dot" style="background:#3b82f6;"></span> 胞嘧啶 (C)
        <span class="legend-dot" style="background:#f59e0b;"></span> 鸟嘌呤 (G)
        <span class="legend-dot" style="background:#8b5cf6;"></span> 插入/缺失 (InDel)
        <span class="hint-text">（点击任意条目可展开碱基逐位对齐详情）</span>
      </div>
      <div v-else-if="activeView === 'coverage'" class="legend-items">
        <span class="legend-title">相似度梯度:</span>
        <span class="legend-block" style="background:#059669;"></span> &ge; 99%
        <span class="legend-block" style="background:#2563eb;"></span> 97% ~ 99%
        <span class="legend-block" style="background:#7c3aed;"></span> 95% ~ 97%
        <span class="legend-block" style="background:#ea580c;"></span> 90% ~ 95%
        <span class="legend-block" style="background:#dc2626;"></span> &lt; 90%
      </div>
      <div v-else class="legend-items">
        <span class="legend-title">梯队说明:</span>
        <span>反映候选物种间的微小区分度与得分断层</span>
      </div>
    </div>

    <!-- 主展示区 1: 突变指纹与覆盖图 (SVG 渲染) -->
    <div v-if="activeView === 'fingerprint' || activeView === 'coverage'" class="canvas-scroll-container scroll-v">
      <svg :width="totalWidth" :height="totalHeight" :viewBox="`0 0 ${totalWidth} ${totalHeight}`" class="main-visual-svg">
        <!-- 坐标轴与刻度 -->
        <g :transform="`translate(${LEFT_MARGIN}, ${TOP_MARGIN})`">
          <line x1="0" y1="0" :x2="WIDTH" y2="0" stroke="#cbd5e1" stroke-width="2" />
          <g v-for="i in 6" :key="i">
            <line 
              :x1="scaleX((queryLength * (i-1)) / 5)" 
              y1="0" 
              :x2="scaleX((queryLength * (i-1)) / 5)" 
              y2="5" 
              stroke="#64748b" 
              stroke-width="1.5" 
            />
            <text 
              :x="scaleX((queryLength * (i-1)) / 5)" 
              y="-8" 
              font-size="11" 
              font-family="'JetBrains Mono', monospace" 
              fill="#64748b" 
              text-anchor="middle"
            >
              {{ Math.round((queryLength * (i-1)) / 5) }} bp
            </text>
          </g>
        </g>

        <!-- Hits 列表渲染 -->
        <g 
          v-for="(hit, idx) in hits" 
          :key="idx" 
          :transform="`translate(0, ${TOP_MARGIN + idx * ROW_HEIGHT})`"
          class="hit-row-group"
          :class="{ selected: expandedHitIndex === idx }"
          @click="expandedHitIndex = expandedHitIndex === idx ? null : idx"
        >
          <!-- 背景高亮条（悬停/选中） -->
          <rect 
            x="10" 
            y="2" 
            :width="totalWidth - 20" 
            :height="ROW_HEIGHT - 4" 
            rx="6" 
            fill="transparent"
            class="row-hover-bg" 
          />

          <!-- 左侧物种标题与序号 -->
          <text 
            :x="LEFT_MARGIN - 15" 
            :y="ROW_HEIGHT / 2 + 4" 
            font-size="12" 
            font-weight="600"
            text-anchor="end" 
            fill="#334155" 
            class="hit-title-text"
          >
            {{ idx + 1 }}. {{ simplifyTitle(hit.title) }}
          </text>

          <!-- 轨道基底线 -->
          <line 
            :x1="LEFT_MARGIN" 
            :y1="ROW_HEIGHT / 2" 
            :x2="LEFT_MARGIN + WIDTH" 
            :y2="ROW_HEIGHT / 2" 
            stroke="#f1f5f9" 
            stroke-width="2" 
          />

          <!-- HSP 渲染 -->
          <g 
            v-for="(hsp, hIdx) in hit.hsps" 
            :key="hIdx"
            :transform="`translate(${LEFT_MARGIN}, 0)`"
          >
            <!-- 模式 1: 突变指纹图模式 (浅色主干 + 高亮突变竖线) -->
            <template v-if="activeView === 'fingerprint'">
              <!-- 主干覆盖区域 (轻柔底色) -->
              <rect 
                :x="scaleX(hsp.query_start)"
                :y="ROW_HEIGHT / 2 - 6"
                :width="Math.max(2, scaleX(hsp.query_end - hsp.query_start))"
                :height="12"
                fill="#e2e8f0"
                rx="3"
                stroke="#cbd5e1"
                stroke-width="0.5"
              />

              <!-- 错配与突变点 (单碱基竖纹指纹) -->
              <g v-if="hsp.mismatches && hsp.mismatches.length > 0">
                <line 
                  v-for="(m, mIdx) in hsp.mismatches" 
                  :key="mIdx"
                  :x1="scaleX(m.q_pos)"
                  :y1="ROW_HEIGHT / 2 - 8"
                  :x2="scaleX(m.q_pos)"
                  :y2="ROW_HEIGHT / 2 + 8"
                  :stroke="getBaseColor(m.s_base)"
                  stroke-width="2"
                  class="mismatch-pin"
                  @mouseenter="showMismatchTooltip($event, m, hit.title)"
                  @mouseleave="hideTooltip"
                />
              </g>
            </template>

            <!-- 模式 2: 全长覆盖度模式 (渐变高精度色阶) -->
            <template v-else>
              <rect 
                :x="scaleX(hsp.query_start)"
                :y="ROW_HEIGHT / 2 - 7"
                :width="Math.max(2, scaleX(hsp.query_end - hsp.query_start))"
                :height="14"
                :fill="getIdentityColor(hsp.identity_pct || (hsp.identity * 100))"
                rx="4"
                stroke="rgba(0,0,0,0.1)"
                stroke-width="0.5"
              />
            </template>
          </g>

          <!-- 右侧统计数据标签 (相似度 & 错配数 & Score) -->
          <g :transform="`translate(${LEFT_MARGIN + WIDTH + 20}, ${ROW_HEIGHT / 2 + 4})`">
            <text font-size="12" font-weight="700" font-family="'JetBrains Mono', monospace" :fill="getIdentityColor(hit.hsps[0]?.identity_pct ?? 90)">
              {{ (hit.hsps[0]?.identity_pct || (hit.hsps[0]?.identity ? hit.hsps[0].identity * 100 : 0)).toFixed(1) }}%
            </text>
            <text x="60" font-size="11" font-family="'JetBrains Mono', monospace" fill="#64748b">
              {{ hit.hsps[0]?.mismatch_count ?? 0 }} 突变
            </text>
          </g>
        </g>
      </svg>
    </div>

    <!-- 主展示区 2: 相似度梯队分布 (Spectrum View) -->
    <div v-else-if="activeView === 'spectrum'" class="spectrum-container scroll-v">
      <div class="spectrum-card-grid">
        <div 
          v-for="(hit, idx) in hits" 
          :key="idx" 
          class="spectrum-card"
          :class="{ top: idx === 0 }"
        >
          <div class="card-header">
            <span class="rank-badge">#{{ idx + 1 }}</span>
            <span class="card-title" :title="hit.title">{{ simplifyTitle(hit.title) }}</span>
          </div>
          <div class="card-body">
            <div class="metric-row">
              <span class="m-label">一致性相似度:</span>
              <span class="m-val" :style="{ color: getIdentityColor(hit.hsps[0]?.identity_pct || 90) }">
                {{ (hit.hsps[0]?.identity_pct || (hit.hsps[0]?.identity ? hit.hsps[0].identity * 100 : 0)).toFixed(2) }}%
              </span>
            </div>
            <!-- 相似度进度条 -->
            <div class="progress-bar-track">
              <div 
                class="progress-bar-fill" 
                :style="{ 
                  width: `${hit.hsps[0]?.identity_pct || 90}%`, 
                  background: getIdentityColor(hit.hsps[0]?.identity_pct || 90) 
                }"
              ></div>
            </div>
            <div class="details-grid">
              <div>错配变异: <strong>{{ hit.hsps[0]?.mismatch_count || 0 }} bp</strong></div>
              <div>比对长度: <strong>{{ hit.hsps[0]?.align_length || hit.length }} bp</strong></div>
              <div>Score: <strong>{{ hit.hsps[0]?.score ?? 0 }}</strong></div>
              <div>E-value: <strong>{{ hit.hsps[0]?.evalue ?? 0 }}</strong></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部展开: 交互式碱基比对详情 (Base-by-Base Alignment) -->
    <div v-if="currentExpandedHit && currentExpandedHsp" class="expanded-alignment-detail">
      <div class="detail-header">
        <div class="detail-title">
          <span class="dot"></span>
          <span>比对碱基逐位对齐详情: #{{ (expandedHitIndex ?? 0) + 1 }} - {{ simplifyTitle(currentExpandedHit.title) }}</span>
        </div>
        <button class="close-detail-btn" @click="expandedHitIndex = null">收起</button>
      </div>

      <div class="alignment-blocks-container scroll-v">
        <div 
          v-for="(block, bIdx) in getAlignmentBlocks(currentExpandedHsp)" 
          :key="bIdx" 
          class="alignment-block"
        >
          <!-- Query 行 -->
          <div class="aln-line">
            <span class="aln-label">Query</span>
            <span class="aln-pos">{{ block.qStart }}</span>
            <span class="aln-seq mono">
              <span 
                v-for="(ch, cIdx) in block.qSeq.split('')" 
                :key="cIdx"
                :class="{ 'mismatch-base': block.midline[cIdx] === ' ' || ch === '-' }"
              >{{ ch }}</span>
            </span>
            <span class="aln-pos end">{{ block.qEnd }}</span>
          </div>

          <!-- Match 中间匹配线 -->
          <div class="aln-line midline">
            <span class="aln-label"></span>
            <span class="aln-pos"></span>
            <span class="aln-seq mono midline-text">{{ block.midline }}</span>
            <span class="aln-pos end"></span>
          </div>

          <!-- Sbjct 目标行 -->
          <div class="aln-line">
            <span class="aln-label">Sbjct</span>
            <span class="aln-pos">{{ block.sStart }}</span>
            <span class="aln-seq mono">
              <span 
                v-for="(ch, cIdx) in block.sSeq.split('')" 
                :key="cIdx"
                :class="{ 'mismatch-base': block.midline[cIdx] === ' ' || ch === '-' }"
              >{{ ch }}</span>
            </span>
            <span class="aln-pos end">{{ block.sEnd }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 浮动 Tooltip 提示框 -->
    <div 
      v-if="tooltip.show" 
      class="floating-tooltip"
      :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
    >
      <div class="tt-title">{{ tooltip.title }}</div>
      <div class="tt-detail">{{ tooltip.detail }}</div>
    </div>
  </div>
</template>

<style scoped>
.advanced-alignment-visualizer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-radius: 12px;
  overflow: hidden;
  user-select: none;
}

/* 顶部 Banner */
.visual-header-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  gap: 20px;
}

.query-info-box {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 320px;
}
.query-info-box .badge {
  background: #2563eb;
  color: white;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 700;
}
.query-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.query-len {
  font-size: 0.78rem;
  color: #64748b;
  font-family: 'JetBrains Mono', monospace;
}

/* 统计卡片条 */
.stats-ribbon {
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-pill {
  display: flex;
  flex-direction: column;
  background: white;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.stat-pill .label {
  font-size: 0.68rem;
  color: #64748b;
  font-weight: 500;
}
.stat-pill .val {
  font-size: 0.85rem;
  font-weight: 700;
  color: #1e293b;
  font-family: 'JetBrains Mono', monospace;
}
.stat-pill .val.high { color: #059669; }

/* 视图切换按钮 */
.view-switch-tabs {
  display: flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: 8px;
  gap: 2px;
}
.tab-btn {
  background: transparent;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tab-btn.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

/* 图例栏 */
.legend-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 24px;
  background: white;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.75rem;
  color: #64748b;
}
.legend-items {
  display: flex;
  align-items: center;
  gap: 10px;
}
.legend-title {
  font-weight: 700;
  color: #334155;
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.legend-block {
  width: 14px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.hint-text {
  color: #94a3b8;
  margin-left: 10px;
  font-style: italic;
}

/* 主 SVG 画布滚动区 */
.canvas-scroll-container {
  flex: 1;
  overflow: auto;
  padding: 10px 20px;
  background: white;
  min-height: 380px;
}
.main-visual-svg {
  display: block;
  margin: 0 auto;
}

.hit-row-group {
  cursor: pointer;
  transition: all 0.15s ease;
}
.hit-row-group:hover .row-hover-bg {
  fill: #f8fafc;
}
.hit-row-group.selected .row-hover-bg {
  fill: #eff6ff;
  stroke: #bfdbfe;
  stroke-width: 1;
}
.hit-row-group:hover .hit-title-text {
  fill: #2563eb;
}
.mismatch-pin {
  cursor: help;
  transition: stroke-width 0.1s;
}
.mismatch-pin:hover {
  stroke-width: 3.5;
}

/* 相似度梯队网格视图 */
.spectrum-container {
  flex: 1;
  padding: 20px;
  background: #f8fafc;
  overflow: auto;
}
.spectrum-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.spectrum-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.spectrum-card.top {
  border-color: #3b82f6;
  box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.1);
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.rank-badge {
  background: #f1f5f9;
  color: #475569;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 700;
}
.card-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.metric-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
  margin-bottom: 6px;
}
.m-label { color: #64748b; }
.m-val { font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.progress-bar-track {
  height: 6px;
  background: #f1f5f9;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 12px;
}
.progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.details-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  font-size: 0.72rem;
  color: #64748b;
  border-top: 1px solid #f1f5f9;
  padding-top: 8px;
}

/* 展开的碱基对齐详情 */
.expanded-alignment-detail {
  background: #0f172a;
  color: #e2e8f0;
  border-top: 1px solid #334155;
  padding: 16px 24px;
  max-height: 260px;
  display: flex;
  flex-direction: column;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  font-weight: 700;
  color: #38bdf8;
}
.detail-title .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #38bdf8;
}
.close-detail-btn {
  background: #1e293b;
  border: 1px solid #475569;
  color: #94a3b8;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 0.72rem;
  cursor: pointer;
}
.close-detail-btn:hover {
  background: #334155;
  color: white;
}
.alignment-blocks-container {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.alignment-block {
  background: #1e293b;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.78rem;
}
.aln-line {
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.4;
}
.aln-label {
  width: 40px;
  color: #94a3b8;
  font-size: 0.72rem;
}
.aln-pos {
  width: 45px;
  text-align: right;
  color: #64748b;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
}
.aln-pos.end {
  text-align: left;
}
.aln-seq {
  flex: 1;
  letter-spacing: 1px;
}
.mono {
  font-family: 'JetBrains Mono', 'Courier New', monospace;
}
.midline-text {
  color: #059669;
  white-space: pre;
}
.mismatch-base {
  color: #f43f5e;
  font-weight: 700;
  background: rgba(244, 63, 94, 0.2);
  border-radius: 2px;
}

/* 浮动 Tooltip */
.floating-tooltip {
  position: fixed;
  z-index: 3000;
  background: rgba(15, 23, 42, 0.95);
  color: white;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.75rem;
  pointer-events: none;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
  backdrop-filter: blur(4px);
  border: 1px solid #334155;
  max-width: 320px;
}
.tt-title {
  font-weight: 700;
  color: #38bdf8;
  margin-bottom: 4px;
}
.tt-detail {
  color: #cbd5e1;
  line-height: 1.4;
}
</style>
