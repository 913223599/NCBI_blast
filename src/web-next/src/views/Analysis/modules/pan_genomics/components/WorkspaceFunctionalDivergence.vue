<script setup lang="ts">
/**
 * WorkspaceFunctionalDivergence.vue - 旗舰组合图 3: Phage Tree × Receptor Orthology & Evidence Strip
 * (系统发育 × 受体结合蛋白正交矩阵与重组证据体系)
 * 
 * 遵循 Nature / Science / Cell (N/S/C) 组学组合图语法 (Figure Grammar):
 * 1. 上层: 功能策略矩阵与关键差异驱动排序榜 (Functional Strategy & Divergence Ranking)
 * 2. 下层左: 宏观基因组 ↔ 尾部受体双树对齐图 (Dual-Tree Tanglegram + Discordance Evidence Strip)
 * 3. 下层右: 宿主识别靶点正交互补网络与鸡尾酒配对矩阵 (Receptor Orthology & Complementarity Dual-View)
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  categoryDistributions: Record<string, Record<string, number>>
  tailMatrix?: Record<string, Record<string, number>>
  tailClustering?: any
  aniMatrix?: Record<string, Record<string, number>>
  aniClustering?: any
  hostRangePrediction?: any
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-pair', pair: [string, string]): void
  (e: 'select-sample', sampleId: string): void
}>()

const matrixMetricMode = ref<'count' | 'proportion' | 'divergence'>('count')
const activeNetworkFilter = ref<'ALL' | 'Orthogonal' | 'Divergent' | 'Overlapping'>('ALL')

// 排序样本
const orderedSampleIds = computed(() => {
  if (props.aniClustering?.ordered_ids?.length) {
    return props.aniClustering.ordered_ids
  }
  return Object.keys(props.sampleNames || {})
})

// Tail 聚类顺序
const orderedTailIds = computed(() => {
  if (props.tailClustering?.ordered_ids?.length) {
    return props.tailClustering.ordered_ids
  }
  return orderedSampleIds.value
})

// 标准生物学分类别名映射字典
const CATEGORY_ALIAS_MAP: Record<string, string> = {
  'packaging': 'Head & Packaging',
  'structural': 'Head & Packaging',
  'capsid': 'Head & Packaging',
  'head': 'Head & Packaging',
  'head & packaging': 'Head & Packaging',
  'tail': 'Tail & Host Interaction',
  'tail & host interaction': 'Tail & Host Interaction',
  'fiber': 'Tail & Host Interaction',
  'lysis': 'Lysis',
  'lysis system': 'Lysis',
  'integration': 'Integration & Excision',
  'integration & excision': 'Integration & Excision',
  'excision': 'Integration & Excision',
  'defense': 'Defense & Host Interaction',
  'defense & host interaction': 'Defense & Host Interaction',
  'acr': 'Defense & Host Interaction',
  'replication': 'Replication & Repair',
  'replication & repair': 'Replication & Repair',
  'repair': 'Replication & Repair',
  'regulation': 'Transcription & Regulation',
  'transcription': 'Transcription & Regulation',
  'transcription & regulation': 'Transcription & Regulation',
  'metabolism': 'Metabolism & AMG',
  'metabolism & amg': 'Metabolism & AMG',
  'amg': 'Metabolism & AMG',
  'other': 'Other Functional',
  'other functional': 'Other Functional',
  'hypothetical': 'Hypothetical'
}

function normalizeCategoryName(raw?: string): string {
  if (!raw) return 'Hypothetical'
  const key = raw.trim().toLowerCase()
  return CATEGORY_ALIAS_MAP[key] || raw
}

// 统一功能大类模块与色彩定义
const functionalModules = [
  { id: 'Tail & Host Interaction', name: '尾丝与受体吸附 (Tail & Fiber)', color: '#06b6d4' },
  { id: 'Head & Packaging', name: '头部与衣壳包装 (Head & Packaging)', color: '#0284c7' },
  { id: 'Lysis', name: '宿主裂解系统 (Lysis Cassette)', color: '#f43f5e' },
  { id: 'Replication & Repair', name: '复制与核酸修复 (Replication)', color: '#f59e0b' },
  { id: 'Transcription & Regulation', name: '转录调控与开关 (Regulation)', color: '#10b981' },
  { id: 'Defense & Host Interaction', name: '免疫防御与攻防 (Defense & Acr)', color: '#8b5cf6' },
  { id: 'Integration & Excision', name: '溶源整合与切除 (Integration)', color: '#6366f1' },
  { id: 'Metabolism & AMG', name: '辅助代谢重塑 (Metabolism & AMG)', color: '#eab308' }
]

// 计算矩阵单元格数值
function getMatrixValue(sid: string, modId: string): number {
  const dist = props.categoryDistributions?.[sid] || {}
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1

  let rawCount = 0
  for (const [k, v] of Object.entries(dist)) {
    if (normalizeCategoryName(k) === modId || k === modId) {
      rawCount += v
    }
  }

  if (matrixMetricMode.value === 'count') {
    return rawCount
  }
  if (matrixMetricMode.value === 'proportion') {
    return Math.round((rawCount / total) * 100)
  }
  // Divergence score
  const allCounts = orderedSampleIds.value.map((s: string) => {
    const d = props.categoryDistributions?.[s] || {}
    let c = 0
    for (const [k, v] of Object.entries(d)) {
      if (normalizeCategoryName(k) === modId || k === modId) c += v
    }
    return c
  })
  const mean = allCounts.reduce((a: number, b: number) => a + b, 0) / (allCounts.length || 1)
  return Math.abs(rawCount - mean)
}

function getMatrixCellBg(val: number, modColor: string): string {
  if (val === 0) return '#f8fafc'
  return `${modColor}22`
}

// 差异功能模块排序
const divergenceRanking = computed(() => {
  if (!props.selectedPair) return []
  const [s1, s2] = props.selectedPair

  return functionalModules.map(mod => {
    const val1 = getMatrixValue(s1, mod.id)
    const val2 = getMatrixValue(s2, mod.id)
    const diff = Math.abs(val1 - val2)

    let desc = '差异较小，高度保守'
    let level = 'Low'
    if (mod.id === 'Tail/RBP') {
      const tailSim = props.tailMatrix?.[s1]?.[s2] ?? 100
      const tailDiff = 100 - tailSim
      if (tailDiff >= 50) {
        level = 'Critical'
        desc = `受体结合序列差异高达 ${tailDiff.toFixed(1)}%，决定了宿主裂解谱的根本分化`
      } else if (tailDiff >= 20) {
        level = 'Moderate'
        desc = `受体结构域发生部分突变 (${tailDiff.toFixed(1)}%)`
      }
    } else if (diff >= 3) {
      level = 'High'
      desc = `基因数量显著差异 (Δ = ${diff})`
    }

    return {
      name: mod.name,
      diffScore: diff,
      level,
      desc,
      color: mod.color
    }
  }).sort((a, b) => {
    const scoreA = a.level === 'Critical' ? 3 : (a.level === 'High' ? 2 : (a.level === 'Moderate' ? 1 : 0))
    const scoreB = b.level === 'Critical' ? 3 : (b.level === 'High' ? 2 : (b.level === 'Moderate' ? 1 : 0))
    return scoreB - scoreA || b.diffScore - a.diffScore
  })
})

const hasSignificantDivergence = computed(() => {
  return divergenceRanking.value.some(item => item.level === 'Critical' || item.level === 'High' || item.diffScore >= 3)
})

const subtleDifferences = computed(() => {
  return divergenceRanking.value.filter(item => item.diffScore > 0)
})

// 正交网络与配对数据
const networkPairs = computed(() => {
  const all: any[] = []
  const ids = orderedSampleIds.value

  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const s1 = ids[i]
      const s2 = ids[j]
      if (s1 && s2) {
        const tailSim = props.tailMatrix?.[s1]?.[s2] ?? 100
        const ani = props.aniMatrix?.[s1]?.[s2] ?? 100
        const name1 = props.sampleNames[s1] || s1
        const name2 = props.sampleNames[s2] || s2

        let type = '正交互补 (Orthogonal)'
        let category = 'Orthogonal'
        let color = '#10b981'
        let desc = '受体结合结构域高度分化，预测识别完全不同的宿主表面抗原，适宜联合用药。'

        if (tailSim >= 90) {
          type = '靶点冗余 (Redundant)'
          category = 'Overlapping'
          color = '#64748b'
          desc = '尾丝受体结构一致性 ≥ 90%，宿主识别重叠，属于同源克隆变体。'
        } else if (tailSim >= 50) {
          type = '部分分化 (Divergent)'
          category = 'Divergent'
          color = '#f59e0b'
          desc = '受体结构域存在局部点突变，可能识别同一宿主表面受体的不同表位。'
        }

        all.push({
          sample1: s1,
          sample2: s2,
          pair: `${name1} ↔ ${name2}`,
          tail_identity: tailSim.toFixed(1),
          ani: ani.toFixed(1),
          type,
          category,
          color,
          desc
        })
      }
    }
  }

  if (activeNetworkFilter.value !== 'ALL') {
    return all.filter(p => p.category === activeNetworkFilter.value)
  }
  return all
})

// Tanglegram 动态高度与坐标计算
const tanglegramHeight = computed(() => Math.max(260, orderedSampleIds.value.length * 28 + 60))
</script>

<template>
  <div class="workspace-functional-divergence">
    <!-- 上层主看板: 功能策略矩阵 (左) + 差异功能排序榜 (右) -->
    <div class="func-top-grid">
      <!-- Panel A: 功能策略分化矩阵 -->
      <div class="academic-panel strategy-matrix-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Panel A</span>
            <h3>多维度功能策略分化矩阵 (Functional Strategy Matrix)</h3>
          </div>
          <div class="metric-tabs">
            <button 
              :class="['m-tab-btn', { active: matrixMetricMode === 'count' }]"
              @click="matrixMetricMode = 'count'"
            >
              基因数量
            </button>
            <button 
              :class="['m-tab-btn', { active: matrixMetricMode === 'proportion' }]"
              @click="matrixMetricMode = 'proportion'"
            >
              百分比占比 (%)
            </button>
            <button 
              :class="['m-tab-btn', { active: matrixMetricMode === 'divergence' }]"
              @click="matrixMetricMode = 'divergence'"
            >
              群体离散度 (Δ)
            </button>
          </div>
        </div>

        <div class="matrix-table-wrap">
          <table class="academic-strategy-table">
            <thead>
              <tr>
                <th class="th-module">功能模块 (Functional Module)</th>
                <th 
                  v-for="sid in orderedSampleIds" 
                  :key="'f-col-' + sid"
                  class="th-sample-col"
                  :class="{ 'col-selected': selectedPair?.includes(sid) }"
                >
                  <div class="sample-name-v" :title="sampleNames[sid]">{{ sampleNames[sid] }}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mod in functionalModules" :key="mod.id">
                <td class="td-mod-name">
                  <span class="mod-dot" :style="{ backgroundColor: mod.color }"></span>
                  {{ mod.name }}
                </td>
                <td 
                  v-for="sid in orderedSampleIds" 
                  :key="mod.id + '-' + sid"
                  class="td-val-cell"
                  :style="{ backgroundColor: getMatrixCellBg(getMatrixValue(sid, mod.id), mod.color) }"
                >
                  <strong :style="{ color: mod.color }">
                    {{ getMatrixValue(sid, mod.id) }}{{ matrixMetricMode === 'proportion' ? '%' : '' }}
                  </strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Panel B: 关键差异功能排序榜 -->
      <div class="academic-panel ranking-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Panel B</span>
            <h3>功能分化驱动因子排序 (Divergence Ranking)</h3>
          </div>
          <span class="pair-focus-tag" v-if="selectedPair">
            {{ sampleNames[selectedPair[0]] }} ↔ {{ sampleNames[selectedPair[1]] }}
          </span>
          <span class="pair-focus-tag empty-tag" v-else>
            请在上方选择样本对
          </span>
        </div>

        <!-- 有显著分化时显示完整排行榜 -->
        <div class="ranking-list" v-if="selectedPair && hasSignificantDivergence">
          <div 
            v-for="(item, idx) in divergenceRanking" 
            :key="idx"
            class="ranking-card"
            :class="'level-' + item.level.toLowerCase()"
          >
            <div class="rank-badge" :style="{ backgroundColor: item.color }">#{{ idx + 1 }}</div>
            <div class="rank-content">
              <div class="rank-title-row">
                <span class="rank-name">{{ item.name }}</span>
                <span :class="['level-chip', 'chip-' + item.level.toLowerCase()]">
                  {{ item.level }} Divergence
                </span>
              </div>
              <p class="rank-desc">{{ item.desc }}</p>
            </div>
          </div>
        </div>

        <!-- 无显著分化时自动压缩显示 (Low-Information Suppression) -->
        <div class="conserved-summary-card" v-else-if="selectedPair && !hasSignificantDivergence">
          <div class="conserved-head">
            <span class="cons-icon">✓</span>
            <div>
              <strong>未发现显著的功能模块分化 (Functional Conservation Dominates)</strong>
              <p>在所有 7 个核心功能大类中，选中的两株样本均表现出高度保守的基因配额与策略一致性。</p>
            </div>
          </div>
          
          <div class="subtle-diff-area" v-if="subtleDifferences.length > 0">
            <span class="subtle-label">仅检测到以下微弱数量差异:</span>
            <div class="subtle-tags">
              <span v-for="sd in subtleDifferences" :key="sd.name" class="subtle-chip">
                {{ sd.name }}: Δ = {{ sd.diffScore }}
              </span>
            </div>
          </div>
          <div class="subtle-diff-area" v-else>
            <span class="subtle-label">两株样本在所有功能分类下的基因数量与比例完全 100% 一致。</span>
          </div>
        </div>

        <div class="empty-ranking-placeholder" v-else>
          <p>在任意热图或图表中点击选择两个样本，系统将自动计算并排名导致两株噬菌体表型差异的核心功能模块。</p>
        </div>
      </div>
    </div>

    <!-- 🌟 下层双看板: 进化对齐双树图 (左) + 宿主互补网络 (右) -->
    <div class="func-bottom-grid">
      <!-- Panel C: 进化对齐双树图 (Tanglegram) -->
      <div class="academic-panel tanglegram-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Figure 3 Flagship</span>
            <h3>全基因组 ↔ 尾部受体 双树进化对齐 (Dual-Tree Tanglegram)</h3>
          </div>
          <span class="panel-subtip">平行连线 = 协同演化；交叉连线 = 候选重组信号</span>
        </div>

        <!-- 证据等级标牌与断点说明 -->
        <div class="tanglegram-confidence-bar">
          <span class="conf-badge">Evidence: Exploratory (n={{ orderedSampleIds.length }})</span>
          <span class="conf-desc">拓扑交叉提示潜在水平转移或受体加速演化；确证需结合断点检验与宿主实验。</span>
        </div>

        <!-- 极简通俗图解导读框 -->
        <div class="tanglegram-guide-card">
          <div class="guide-item">
            <span class="guide-dot bg-blue"></span>
            <strong>左侧 (全基因组 ANI)</strong>: 全身所有基因的宏观亲缘排序
          </div>
          <div class="guide-item">
            <span class="guide-dot bg-amber"></span>
            <strong>右侧 (尾部受体 Tail)</strong>: 仅看抓捕宿主的受体蛋白亲缘排序
          </div>
          <div class="guide-item">
            <strong class="text-slate">平行线</strong>: 协同演化 (受体亲缘与全基因组吻合)
          </div>
          <div class="guide-item">
            <strong class="text-amber">交叉线</strong>: 潜在重组/受体置换 (远亲拥有相似受体，或近亲受体特化)
          </div>
        </div>

        <div class="tanglegram-svg-wrap">
          <svg class="tanglegram-svg" :viewBox="`0 0 920 ${tanglegramHeight}`">
            <!-- 左侧: ANI Phylogeny 标注 -->
            <text x="30" y="24" font-size="12" font-weight="700" fill="#2563eb">全基因组 ANI 谱系 (Genome)</text>
            <!-- 右侧: Tail Phylogeny 标注 -->
            <text x="890" y="24" font-size="12" font-weight="700" fill="#f59e0b" text-anchor="end">受体结合区谱系 (Receptor)</text>

            <!-- 绘制样本节点与连线 -->
            <g v-for="(sid, idx) in orderedSampleIds" :key="'tang-' + sid">
              <!-- 左侧连线起点: x=360, y=50 + idx*28 -->
              <circle :cx="360" :cy="50 + Number(idx) * 28" r="4.5" fill="#2563eb" />
              <text 
                :x="350" 
                :y="54 + Number(idx) * 28" 
                font-size="11" 
                text-anchor="end" 
                fill="#334155" 
                font-weight="600"
                class="tangle-node-text"
              >
                {{ sampleNames[sid] }}
              </text>

              <!-- 右侧连线终点: x=560, y=50 + tailIdx*28 -->
              <line
                :x1="360"
                :y1="50 + Number(idx) * 28"
                :x2="560"
                :y2="50 + (orderedTailIds.indexOf(sid) !== -1 ? orderedTailIds.indexOf(sid) : Number(idx)) * 28"
                :stroke="selectedPair?.includes(sid) ? '#ef4444' : (orderedTailIds.indexOf(sid) !== Number(idx) ? '#f59e0b' : '#cbd5e1')"
                :stroke-width="selectedPair?.includes(sid) ? 2.5 : (orderedTailIds.indexOf(sid) !== Number(idx) ? 1.8 : 1.2)"
                :stroke-dasharray="orderedTailIds.indexOf(sid) !== Number(idx) ? '4 2' : 'none'"
                class="tanglegram-line"
              />
            </g>

            <!-- 右侧节点 -->
            <g v-for="(sid, idx) in orderedTailIds" :key="'tail-n-' + sid">
              <circle :cx="560" :cy="50 + Number(idx) * 28" r="4.5" fill="#f59e0b" />
              <text 
                :x="570" 
                :y="54 + Number(idx) * 28" 
                font-size="11" 
                fill="#334155"
                font-weight="600"
                class="tangle-node-text"
              >
                {{ sampleNames[sid] }}
              </text>
            </g>
          </svg>
        </div>
      </div>

      <!-- Panel D: 宿主识别互补网络与鸡尾酒配对矩阵 -->
      <div class="academic-panel network-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Panel D</span>
            <h3>宿主识别受体正交与鸡尾酒配对矩阵 (Receptor Orthology)</h3>
          </div>
          <div class="filter-chips">
            <button 
              :class="['chip-btn', { active: activeNetworkFilter === 'ALL' }]"
              @click="activeNetworkFilter = 'ALL'"
            >
              全部 ({{ networkPairs.length }})
            </button>
            <button 
              :class="['chip-btn chip-orth', { active: activeNetworkFilter === 'Orthogonal' }]"
              @click="activeNetworkFilter = 'Orthogonal'"
            >
              正交互补
            </button>
            <button 
              :class="['chip-btn chip-div', { active: activeNetworkFilter === 'Divergent' }]"
              @click="activeNetworkFilter = 'Divergent'"
            >
              分化变异
            </button>
          </div>
        </div>

        <div class="network-cards-scroll">
          <div 
            v-for="(pair, idx) in networkPairs" 
            :key="idx"
            class="pair-orth-card"
            @click="pair.sample1 && pair.sample2 && emit('select-pair', [pair.sample1, pair.sample2])"
          >
            <div class="pair-card-header">
              <strong>{{ pair.pair }}</strong>
              <span class="pair-type-tag" :style="{ backgroundColor: pair.color + '22', color: pair.color }">
                {{ pair.type }}
              </span>
            </div>
            <p class="pair-desc">{{ pair.desc }}</p>
            <div class="pair-metrics">
              <span>受体同源性 (Tail Identity): <strong>{{ pair.tail_identity }}%</strong></span>
              <span>全基因组 ANI: <strong>{{ pair.ani }}%</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workspace-functional-divergence {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.func-top-grid,
.func-bottom-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
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
  font-weight: 800;
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

.metric-tabs {
  display: flex;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 6px;
  gap: 2px;
}

.m-tab-btn {
  background: transparent;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.m-tab-btn.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.matrix-table-wrap {
  overflow-x: auto;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
}

.academic-strategy-table {
  width: 100%;
  border-collapse: collapse;
}

.th-module {
  text-align: left;
  font-size: 10px;
  color: #64748b;
  padding: 8px;
  border-bottom: 1px solid #e2e8f0;
}

.th-sample-col {
  width: 38px;
  vertical-align: bottom;
  padding: 6px 2px;
  height: 70px;
  border-bottom: 1px solid #e2e8f0;
}

.sample-name-v {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-size: 10px;
  max-height: 65px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-selected {
  background: #eff6ff;
}

.td-mod-name {
  padding: 8px;
  font-weight: 600;
  color: #334155;
  border-bottom: 1px solid #f1f5f9;
  white-space: nowrap;
  font-size: 11px;
}

.mod-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
}

.td-val-cell {
  text-align: center;
  padding: 6px;
  border-bottom: 1px solid #f1f5f9;
  border-left: 1px solid #f8fafc;
  font-size: 11px;
}

/* 排序榜 */
.pair-focus-tag {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 3px 8px;
  border-radius: 4px;
}

.empty-tag {
  color: #94a3b8;
  background: #f1f5f9;
}

.ranking-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.ranking-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.ranking-card.level-critical {
  background: #fffbeb;
  border-color: #fde68a;
}

.rank-badge {
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.rank-content {
  flex: 1;
}

.rank-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.rank-name {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}

.level-chip {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.chip-critical { background: #fee2e2; color: #b91c1c; }
.chip-high { background: #ffedd5; color: #c2410c; }
.chip-moderate { background: #fef9c3; color: #a16207; }
.chip-low { background: #f1f5f9; color: #475569; }

.rank-desc {
  margin: 4px 0 0;
  font-size: 11px;
  color: #64748b;
  line-height: 1.3;
}

.empty-ranking-placeholder {
  padding: 30px 16px;
  text-align: center;
  color: #94a3b8;
  font-size: 11px;
}

/* 保守型概览卡片 */
.conserved-summary-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.conserved-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.cons-icon {
  background: #16a34a;
  color: #ffffff;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  flex-shrink: 0;
}

.conserved-head strong {
  display: block;
  font-size: 12px;
  color: #15803d;
  margin-bottom: 2px;
}

.conserved-head p {
  margin: 0;
  font-size: 11px;
  color: #166534;
  line-height: 1.4;
}

.subtle-diff-area {
  border-top: 1px solid #dcfce7;
  padding-top: 8px;
  font-size: 10px;
}

.subtle-label {
  color: #15803d;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
}

.subtle-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.subtle-chip {
  background: #ffffff;
  border: 1px solid #86efac;
  color: #15803d;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

/* Tanglegram 导读框 */
.tanglegram-guide-card {
  display: flex;
  gap: 12px;
  background: #f1f5f9;
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 10px;
  color: #475569;
  flex-wrap: wrap;
}

.guide-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.guide-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.bg-blue { background: #2563eb; }
.bg-amber { background: #f59e0b; }

/* Tanglegram 证据标牌 */
.tanglegram-confidence-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 10px;
}

.conf-badge {
  background: #f59e0b;
  color: #ffffff;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
  flex-shrink: 0;
}

.conf-desc {
  color: #92400e;
}

/* 双树对齐图 */
.tanglegram-svg-wrap {
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  padding: 12px;
  max-height: 380px;
  overflow-y: auto;
}

.tanglegram-svg {
  width: 100%;
  height: auto;
  display: block;
}

.tangle-node-text {
  dominant-baseline: middle;
}

.tanglegram-line {
  transition: all 0.2s;
}

.tanglegram-line:hover {
  stroke: #2563eb;
  stroke-width: 2.5;
}

/* 互补网络卡片 */
.filter-chips {
  display: flex;
  gap: 4px;
}

.chip-btn {
  background: #f1f5f9;
  border: none;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.chip-btn.active {
  background: #0f172a;
  color: #ffffff;
}

.network-cards-scroll {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 380px;
  overflow-y: auto;
  padding-right: 4px;
}

.pair-orth-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.pair-orth-card:hover {
  background: #ffffff;
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.pair-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.pair-type-tag {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.pair-desc {
  margin: 0 0 6px;
  font-size: 11px;
  color: #64748b;
  line-height: 1.3;
}

.pair-metrics {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: #475569;
}
</style>
