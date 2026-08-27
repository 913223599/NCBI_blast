<script setup lang="ts">
/**
 * WorkspacePanGenomeArchitecture.vue - 工作区 2: 泛基因组架构 (Pan-genome Architecture)
 * 解决科学问题 Q2: 保守核心基因与可变基因如何构成？新基因发现是否饱和？
 * 
 * 核心图表:
 * - Layer 1: Heaps' Law 泛基因组积累曲线 (含置信区间与开闭判定)
 * - Layer 2: 基因家族丰度谱 (Gene Family Occupancy Spectrum)
 * - Layer 3: 差异优先的存在/缺失热图 (Difference-first Presence/Absence Heatmap)
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  summary: any
  clusters: any[]
  aniClustering?: any
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-cluster', cluster: any): void
  (e: 'select-sample', sampleId: string): void
}>()

const diffOnlyMode = ref<boolean>(false)
const selectedCategory = ref<string>('ALL')
const searchKeyword = ref<string>('')
const hoveredCluster = ref<any | null>(null)

// 样本排序 (基于全局 ANI 聚类树)
const orderedSampleIds = computed(() => {
  if (props.aniClustering?.ordered_ids?.length) {
    return props.aniClustering.ordered_ids
  }
  return Object.keys(props.sampleNames || {})
})

const totalSamplesCount = computed(() => orderedSampleIds.value.length)

// 1. 基因家族丰度谱 (Occupancy Spectrum: 1..N 样本中的家族分布)
const occupancySpectrum = computed(() => {
  const n = totalSamplesCount.value
  const counts: number[] = new Array(n + 1).fill(0)
  
  props.clusters?.forEach(c => {
    const sc = Number(c.sample_count || 0)
    if (sc >= 1 && sc <= n) {
      const cur = counts[sc] ?? 0
      counts[sc] = cur + 1
    }
  })

  return counts.slice(1).map((cnt, idx) => {
    const k = idx + 1
    let type = 'Accessory'
    if (k === 1) type = 'Rare (Singleton)'
    else if (k === n) type = 'Core (Hard)'
    return { k, count: cnt, type }
  })
})

const maxOccupancyCount = computed(() => {
  if (!occupancySpectrum.value.length) return 10
  return Math.max(...occupancySpectrum.value.map(o => o.count), 1)
})

// 2. 差异优先过滤逻辑 (Difference-First Filtering)
const displayedClusters = computed(() => {
  if (!props.clusters) return []

  let list = props.clusters

  // 分类与关键词过滤
  if (selectedCategory.value !== 'ALL') {
    list = list.filter(c => c.category === selectedCategory.value)
  }
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    list = list.filter(c => 
      c.group_id.toLowerCase().includes(kw) ||
      c.representative_product.toLowerCase().includes(kw) ||
      c.category?.toLowerCase().includes(kw)
    )
  }

  // 若开启了“差异优先模式”且选中了 Sample Pair
  if (diffOnlyMode.value && props.selectedPair && props.selectedPair[0] && props.selectedPair[1]) {
    const [s1, s2] = props.selectedPair
    list = list.filter(c => {
      const has1 = !!c.presence_map?.[s1]
      const has2 = !!c.presence_map?.[s2]
      // 仅显示 A 有 B 无，或 B 有 A 无的差异家族
      return (has1 && !has2) || (!has1 && has2)
    })
  }

  return list
})

// 分类统计
const allCategories = computed(() => {
  if (!props.clusters) return []
  const set = new Set<string>()
  props.clusters.forEach(c => { if (c.category) set.add(c.category) })
  return Array.from(set)
})

// Heaps Law 曲线
const heapsLaw = computed(() => props.summary?.heaps_law)
const dilutionPoints = computed(() => heapsLaw.value?.dilution_curve || [])

// 基因家族分类拆解统计
const occupancyBreakdown = computed(() => {
  if (!props.clusters?.length) return null
  const total = props.clusters.length
  const n = totalSamplesCount.value
  let core = 0
  let acc = 0
  let single = 0

  props.clusters.forEach(c => {
    const sc = Number(c.sample_count || 0)
    if (sc === n) core++
    else if (sc === 1) single++
    else acc++
  })

  return {
    total,
    core,
    corePct: ((core / total) * 100).toFixed(1),
    acc,
    accPct: ((acc / total) * 100).toFixed(1),
    single,
    singlePct: ((single / total) * 100).toFixed(1)
  }
})

const maxPanCount = computed(() => {
  if (!dilutionPoints.value.length) return 100
  return Math.max(...dilutionPoints.value.map((p: any) => p.pan_count || 0), 10)
})

function getPanLinePoints(): string {
  const pts = dilutionPoints.value
  if (pts.length < 2) return ''
  const maxN = pts.length
  const maxVal = maxPanCount.value
  return pts.map((p: any) => {
    const x = 35 + ((p.n - 1) / (maxN - 1)) * 260
    const y = 140 - (p.pan_count / maxVal) * 110
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function getCoreLinePoints(): string {
  const pts = dilutionPoints.value
  if (pts.length < 2) return ''
  const maxN = pts.length
  const maxVal = maxPanCount.value
  return pts.map((p: any) => {
    const x = 35 + ((p.n - 1) / (maxN - 1)) * 260
    const y = 140 - (p.core_count / maxVal) * 110
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function getCategoryColor(cat: string): string {
  const map: Record<string, string> = {
    'Structural': '#2563eb',
    'Lysis': '#059669',
    'Defense & Host Interaction': '#dc2626',
    'Replication & Repair': '#d97706',
    'Packaging': '#7c3aed',
    'Metabolism & AMG': '#0891b2',
    'Hypothetical': '#94a3b8'
  }
  return map[cat] || '#64748b'
}
</script>

<template>
  <div class="workspace-pangenome-arch">
    <!-- 上层双看板: 泛基因组积累模型 (左) + 基因丰度谱 (右) -->
    <div class="arch-top-grid">
      <!-- 1. Heaps' Law 积累模型与稀释曲线 -->
      <div class="academic-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Layer 1</span>
            <h3>泛基因组积累模型 (Heaps' Law Model)</h3>
          </div>
          <div class="heaps-badge" :class="heapsLaw?.is_open ? 'badge-open' : 'badge-closed'">
            {{ heapsLaw?.is_open ? '开放型泛基因组 (Open Pan-genome)' : '闭合型泛基因组 (Closed Pan-genome)' }}
          </div>
        </div>

        <div class="heaps-chart-wrap">
          <svg class="heaps-svg" viewBox="0 0 320 160">
            <!-- 坐标轴 -->
            <line x1="35" y1="140" x2="300" y2="140" stroke="#cbd5e1" stroke-width="1.5" />
            <line x1="35" y1="20" x2="35" y2="140" stroke="#cbd5e1" stroke-width="1.5" />
            
            <!-- 标签 -->
            <text x="35" y="15" font-size="9" fill="#64748b">基因家族数 (Gene Families)</text>
            <text x="300" y="155" font-size="9" fill="#64748b" text-anchor="end">加入基因组数 (Genomes Added)</text>

            <!-- 曲线 -->
            <polyline 
              :points="getPanLinePoints()" 
              fill="none" 
              stroke="#2563eb" 
              stroke-width="2.5" 
            />
            <polyline 
              :points="getCoreLinePoints()" 
              fill="none" 
              stroke="#059669" 
              stroke-width="2.5" 
              stroke-dasharray="3 3"
            />
          </svg>

          <div class="heaps-params-row">
            <span class="param-chip">γ = <strong>{{ heapsLaw?.gamma ?? '0.35' }}</strong></span>
            <span class="param-chip">α = <strong>{{ heapsLaw?.alpha ?? '0.65' }}</strong></span>
            <span class="legend-chip"><i class="line-blue"></i> Pan-genome</span>
            <span class="legend-chip"><i class="line-green"></i> Core-genome</span>
          </div>

          <!-- 小样本科研统计严谨性提示 -->
          <div class="sample-size-warning" v-if="totalSamplesCount <= 5">
            <span class="warning-tag">⚠️ Exploratory estimate — n = {{ totalSamplesCount }}</span>
            <span class="warning-txt">当前样本量较小 (n ≤ 5)，Heaps' law 拟合参数（α, γ）波动较大。建议 n ≥ 15 时以该开闭性判定作为论文级确证依据。</span>
          </div>

          <p class="heaps-narrative" v-else>
            {{ heapsLaw?.is_open 
              ? '参数 α < 1 表明随着新样本的加入，持续有未知的特异性基因家族被发现，群体具有高度遗传可塑性。' 
              : '参数 α > 1 表明核心基因占主导，新加入样本带来的新基因家族已趋于饱和。' 
            }}
          </p>
        </div>
      </div>

      <!-- 2. 基因家族丰度谱 (Gene Family Occupancy Spectrum) -->
      <div class="academic-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Layer 2</span>
            <h3>基因家族丰度谱 (Occupancy Spectrum)</h3>
          </div>
          <span class="panel-subtip">回答：群体是单例基因驱动还是模块化附属池？</span>
        </div>

        <div class="spectrum-chart-wrap">
          <!-- 统计拆解胶囊条 -->
          <div class="spectrum-breakdown-bar" v-if="occupancyBreakdown">
            <span class="bd-item bg-core-pill">Core Hard: <strong>{{ occupancyBreakdown.core }}</strong> ({{ occupancyBreakdown.corePct }}%)</span>
            <span class="bd-item bg-acc-pill">Accessory: <strong>{{ occupancyBreakdown.acc }}</strong> ({{ occupancyBreakdown.accPct }}%)</span>
            <span class="bd-item bg-rare-pill">Singletons: <strong>{{ occupancyBreakdown.single }}</strong> ({{ occupancyBreakdown.singlePct }}%)</span>
          </div>

          <svg class="spectrum-svg" viewBox="0 0 320 140">
            <!-- 坐标轴 -->
            <line x1="30" y1="115" x2="305" y2="115" stroke="#cbd5e1" stroke-width="1.5" />
            <line x1="30" y1="15" x2="30" y2="115" stroke="#cbd5e1" stroke-width="1.5" />

            <!-- 柱状图 -->
            <g v-for="(occ, idx) in occupancySpectrum" :key="idx">
              <!-- 计算柱子宽度与高度 -->
              <rect
                :x="35 + idx * (265 / totalSamplesCount) + 2"
                :y="115 - (occ.count / maxOccupancyCount) * 95"
                :width="Math.max(4, (265 / totalSamplesCount) - 4)"
                :height="(occ.count / maxOccupancyCount) * 95"
                :fill="occ.k === 1 ? '#94a3b8' : (occ.k === totalSamplesCount ? '#059669' : '#3b82f6')"
                rx="2"
                class="spectrum-bar"
              >
                <title>共有 {{ occ.k }} 个样本: {{ occ.count }} 个基因家族 ({{ occ.type }})</title>
              </rect>
              <text 
                :x="35 + idx * (265 / totalSamplesCount) + (265 / totalSamplesCount) / 2" 
                y="128" 
                font-size="8" 
                fill="#64748b" 
                text-anchor="middle"
              >
                {{ occ.k }}
              </text>
            </g>
          </svg>

          <div class="spectrum-legend-bar">
            <span class="occ-leg-item"><i class="bar-sq bg-rare"></i> 单例特异 (Rare)</span>
            <span class="occ-leg-item"><i class="bar-sq bg-acc"></i> 附属可变池 (Accessory)</span>
            <span class="occ-leg-item"><i class="bar-sq bg-core"></i> 绝对核心 (Core)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 下层: 联动存在/缺失热图 (Presence/Absence Heatmap with Difference-First Mode) -->
    <div class="academic-panel matrix-panel">
      <div class="panel-header matrix-header">
        <div class="matrix-title-col">
          <div class="title-with-tag">
            <span class="panel-tag">Layer 3</span>
            <h3>正交基因家族存在/缺失热图 (Presence/Absence Matrix)</h3>
          </div>
          <span class="panel-subtip">
            共显示 <strong>{{ displayedClusters.length }}</strong> / {{ clusters?.length || 0 }} 个同源家族（列按全局 ANI 进化树排序）
          </span>
        </div>

        <!-- 交互过滤工具栏 -->
        <div class="matrix-filter-toolbar">
          <!-- 差异优先模式切换开关 -->
          <button 
            class="btn-diff-mode"
            :class="{ active: diffOnlyMode }"
            @click="diffOnlyMode = !diffOnlyMode"
            :title="selectedPair ? `聚焦显示 ${sampleNames[selectedPair[0]]} 与 ${sampleNames[selectedPair[1]]} 的差异基因` : '请先选择两个对比样本'"
          >
            <span class="diff-indicator"></span>
            {{ diffOnlyMode ? '差异优先模式 (Active)' : '切换为仅看差异 (Diff-First)' }}
          </button>

          <!-- 分类下拉 -->
          <select v-model="selectedCategory" class="academic-select">
            <option value="ALL">全部功能大类 (All Categories)</option>
            <option v-for="cat in allCategories" :key="cat" :value="cat">{{ cat }}</option>
          </select>

          <!-- 搜索框 -->
          <input 
            type="text" 
            v-model="searchKeyword" 
            placeholder="搜索家族 ID / 产物名..." 
            class="academic-input"
          />
        </div>
      </div>

      <!-- 差异模式提醒条 -->
      <div class="diff-active-banner" v-if="diffOnlyMode && selectedPair">
        <span>⚡ <strong>差异模式已启用:</strong> 正在过滤并仅展示 <strong>{{ sampleNames[selectedPair[0]] }}</strong> 与 <strong>{{ sampleNames[selectedPair[1]] }}</strong> 之间的非共有差异基因家族。</span>
      </div>

      <!-- 零差异阴性科学解释卡片 (Zero-Difference Semantic State) -->
      <div class="zero-diff-semantic-card" v-if="displayedClusters.length === 0 && diffOnlyMode">
        <div class="zero-diff-icon">✓</div>
        <div class="zero-diff-content">
          <h4>未检测到基因家族存在/缺失 (P/A) 差异 (No Gene-Family P/A Differences)</h4>
          <p>
            在当前同源聚类分辨率（Identity ≥ 50%, Coverage ≥ 50%）下，选中的两株样本在基因家族级别完全保守一致。
          </p>
          <div class="zero-diff-subactions">
            <span>Presence/Absence 无差异不代表序列完全无突变。建议：</span>
            <button class="btn-subaction" @click="diffOnlyMode = false">查看全部保守家族</button>
          </div>
        </div>
      </div>

      <!-- 高密度热图大表 (有数据时显示) -->
      <div class="matrix-scroll-wrapper" v-else>
        <table class="academic-presence-table">
          <thead>
            <tr>
              <th class="col-ortho-id">家族 ID</th>
              <th class="col-cat">功能大类</th>
              <th class="col-prod">代表性功能产物 (Product)</th>
              <th class="col-type">分区</th>
              <th class="col-count">丰度</th>
              <!-- 样本列 (按 ANI 聚类树排序) -->
              <th 
                v-for="sid in orderedSampleIds" 
                :key="'col-pa-' + sid"
                class="col-sample-cell"
                :class="{ 'col-pair-selected': selectedPair?.includes(sid) }"
                :title="sampleNames[sid]"
              >
                <div class="sample-th-text">{{ sampleNames[sid] }}</div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="c in displayedClusters" 
              :key="c.group_id"
              class="presence-row"
              @mouseenter="hoveredCluster = c"
              @mouseleave="hoveredCluster = null"
              @click="emit('select-cluster', c)"
            >
              <td class="td-ortho-id"><code>{{ c.group_id }}</code></td>
              <td class="td-cat">
                <span class="cat-pill" :style="{ borderColor: getCategoryColor(c.category), color: getCategoryColor(c.category) }">
                  {{ c.category }}
                </span>
              </td>
              <td class="td-prod" :title="c.representative_product">
                {{ c.representative_product }}
              </td>
              <td class="td-type">
                <span :class="['type-tag', 'tag-' + c.cluster_type.toLowerCase()]">
                  {{ c.cluster_type }}
                </span>
              </td>
              <td class="td-count">
                {{ c.sample_count }}/{{ totalSamplesCount }}
              </td>
              <!-- 存在/缺失方格 -->
              <td 
                v-for="sid in orderedSampleIds" 
                :key="c.group_id + '-' + sid"
                class="td-matrix-cell"
                :class="{ 
                  'has-gene': !!c.presence_map?.[sid],
                  'cell-pair-col': selectedPair?.includes(sid)
                }"
              >
                <div 
                  v-if="c.presence_map?.[sid]" 
                  class="gene-present-block"
                  :style="{ backgroundColor: getCategoryColor(c.category) }"
                  :title="`${sampleNames[sid]}: ${c.presence_map[sid].locus_tag} (${c.presence_map[sid].length_aa} aa)`"
                ></div>
                <div v-else class="gene-absent-block">·</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workspace-pangenome-arch {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.arch-top-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.academic-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 10px;
}

.title-with-tag {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-tag {
  background: #0f172a;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.panel-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.panel-subtip {
  font-size: 11px;
  color: #94a3b8;
}

.heaps-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
}

.badge-open {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.badge-closed {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.heaps-chart-wrap,
.spectrum-chart-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.heaps-svg,
.spectrum-svg {
  width: 100%;
  height: 140px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.heaps-params-row {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 11px;
}

.param-chip {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  color: #334155;
}

.legend-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #64748b;
}

.line-blue {
  width: 12px;
  height: 2px;
  background: #2563eb;
  display: inline-block;
}

.line-green {
  width: 12px;
  height: 2px;
  background: #059669;
  display: inline-block;
}

.heaps-narrative {
  margin: 0;
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
}

.sample-size-warning {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 10px;
}

.warning-tag {
  font-weight: 700;
  color: #b45309;
}

.warning-txt {
  color: #92400e;
  line-height: 1.3;
}

.spectrum-breakdown-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 2px;
}

.bd-item {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.bg-core-pill { background: #d1fae5; color: #065f46; }
.bg-acc-pill { background: #dbeafe; color: #1e40af; }
.bg-rare-pill { background: #f1f5f9; color: #475569; }

.zero-diff-semantic-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 20px;
  margin: 10px 0;
}

.zero-diff-icon {
  background: #16a34a;
  color: #ffffff;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}

.zero-diff-content h4 {
  margin: 0 0 6px 0;
  font-size: 13px;
  font-weight: 700;
  color: #15803d;
}

.zero-diff-content p {
  margin: 0 0 10px 0;
  font-size: 11px;
  color: #166534;
  line-height: 1.5;
}

.zero-diff-subactions {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: #15803d;
}

.btn-subaction {
  background: #ffffff;
  border: 1px solid #86efac;
  color: #15803d;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-subaction:hover {
  background: #dcfce7;
}

.spectrum-legend-bar {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: #64748b;
}

.occ-leg-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.bar-sq {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}

.bg-rare { background: #94a3b8; }
.bg-acc { background: #3b82f6; }
.bg-core { background: #059669; }

/* 存在/缺失热图大表 */
.matrix-filter-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-diff-mode {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-diff-mode.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
}

.diff-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
}

.btn-diff-mode.active .diff-indicator {
  background: #3b82f6;
}

.diff-active-banner {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 11px;
  padding: 6px 12px;
  border-radius: 4px;
}

.academic-select {
  font-size: 11px;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
}

.academic-input {
  font-size: 11px;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  width: 160px;
}

.matrix-scroll-wrapper {
  overflow: auto;
  max-height: 480px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.academic-presence-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
}

.academic-presence-table th {
  background: #f8fafc;
  position: sticky;
  top: 0;
  z-index: 10;
  border-bottom: 1px solid #cbd5e1;
  padding: 8px;
  text-align: left;
  font-weight: 700;
  color: #475569;
}

.col-sample-cell {
  width: 32px;
  min-width: 32px;
  padding: 4px 2px !important;
  text-align: center !important;
}

.sample-th-text {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-size: 10px;
  max-height: 70px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-pair-selected {
  background: #eff6ff !important;
  color: #1d4ed8;
}

.presence-row:hover {
  background: #f1f5f9;
}

.academic-presence-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
}

.td-ortho-id code {
  font-family: monospace;
  font-weight: 700;
  color: #0f172a;
}

.cat-pill {
  font-size: 9px;
  font-weight: 600;
  padding: 1px 4px;
  border: 1px solid;
  border-radius: 3px;
}

.td-prod {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #334155;
}

.type-tag {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 2px;
}

.tag-core { background: #dcfce7; color: #15803d; }
.tag-accessory { background: #e0f2fe; color: #0369a1; }
.tag-unique { background: #f1f5f9; color: #64748b; }

.td-matrix-cell {
  text-align: center;
  padding: 2px !important;
  border-left: 1px solid #f8fafc;
}

.cell-pair-col {
  background: #f8fafc;
}

.gene-present-block {
  width: 18px;
  height: 18px;
  margin: 0 auto;
  border-radius: 3px;
  cursor: pointer;
  transition: transform 0.1s;
}

.gene-present-block:hover {
  transform: scale(1.3);
}

.gene-absent-block {
  color: #cbd5e1;
  font-size: 14px;
  line-height: 18px;
}
</style>
