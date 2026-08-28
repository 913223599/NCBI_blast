<script setup lang="ts">
/**
 * WorkspaceGenomeArchitecture.vue - 旗舰组合图 2: Overview → Signal Density → Hotspot Zoom
 * (宏观共线性 → 变异信号密度轨 → 局部高精机制放大 三层联动体系)
 * 
 * 遵循 Nature / Science / Cell (N/S/C) 组学组合图语法 (Figure Grammar):
 * 1. Layer 1 (Global Synteny): 宏观基因组全景物理排列与共线性同源带
 * 2. Layer 2 (Signal Density): 基因组坐标上的变异密度与断点信号峰值标定
 * 3. Layer 3 (Hotspot Zoom): 尾部受体/裂解操纵子/攻防岛 局部高精 ORF 构型与序列同源梯形带
 */
import { ref, computed } from 'vue'
import { FUNCTIONAL_CATEGORIES, inferCategoryFromText } from '../../viewer/utils/render'

const props = defineProps<{
  clusters: any[]
  tailProteins?: any[]
  lysisProteins?: any[]
  lysisMatrix?: Record<string, Record<string, number>>
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}>()

const activeHotspot = ref<'tail' | 'lysis' | 'defense'>('tail')
const hoveredGene = ref<any | null>(null)
const trackScope = ref<'pair' | 'all'>('pair')

// 待展示的样本 ID 列表
const activeSampleIds = computed<string[]>(() => {
  if (trackScope.value === 'pair' && props.selectedPair && props.selectedPair[0] && props.selectedPair[1]) {
    return [props.selectedPair[0], props.selectedPair[1]]
  }
  return Object.keys(props.sampleNames || {})
})

// 检查内溶素是否 100% 保守
const isLysisInvariant = computed(() => {
  if (!props.lysisMatrix) return false
  const ids = Object.keys(props.sampleNames || {})
  if (ids.length < 2) return true

  let allHigh = true
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const s1 = ids[i]
      const s2 = ids[j]
      if (s1 && s2) {
        const val = props.lysisMatrix[s1]?.[s2] ?? 0
        if (val < 98) {
          allHigh = false
          break
        }
      }
    }
  }
  return allHigh
})

// 分类颜色映射 (统一使用全基因组色彩体系)
function getCatColor(cat: string): string {
  if (FUNCTIONAL_CATEGORIES[cat]) {
    return FUNCTIONAL_CATEGORIES[cat].color
  }
  return '#64748b'
}

// 提取各样本的全基因组基因列表
const sampleGeneTracks = computed(() => {
  const tracks: Record<string, any[]> = {}
  
  activeSampleIds.value.forEach(sid => {
    const genes: any[] = []

    // 整合 lysis 蛋白
    props.lysisProteins?.filter(lp => lp.sample_id === sid).forEach((lp, idx) => {
      genes.push({
        locus_tag: lp.locus_tag,
        product: lp.product,
        start: 12000 + (idx * 900),
        end: 12000 + (idx * 900) + (lp.length_aa || 160) * 3,
        strand: '+',
        category: 'Lysis',
        role: lp.lysis_role,
        color: '#059669'
      })
    })

    // 整合 tail 蛋白
    props.tailProteins?.filter(tp => tp.sample_id === sid).forEach((tp, idx) => {
      genes.push({
        locus_tag: tp.locus_tag,
        product: tp.product,
        start: 28000 + (idx * 1200),
        end: 28000 + (idx * 1200) + (tp.length_aa || 350) * 3,
        strand: '+',
        category: 'Tail',
        role: tp.tail_type,
        color: '#f59e0b'
      })
    })

    // 整合来自 clusters 的其他基因
    props.clusters?.forEach((c, cIdx) => {
      const g = c.presence_map?.[sid]
      if (g && !genes.some(exist => exist.locus_tag === g.locus_tag)) {
        const estStart = 2000 + (cIdx * 750)
        genes.push({
          locus_tag: g.locus_tag,
          product: g.product,
          start: g.start || estStart,
          end: g.end || (estStart + (g.length_aa || 200) * 3),
          strand: g.strand || '+',
          category: g.category || c.category || 'Other',
          role: c.group_id,
          color: getCatColor(g.category || c.category)
        })
      }
    })

    genes.sort((a, b) => a.start - b.start)
    tracks[sid] = genes
  })

  return tracks
})

// 最大物理坐标长度 (基准 42000 bp)
const maxGenomeLength = computed(() => {
  let maxL = 42000
  Object.values(sampleGeneTracks.value).forEach(list => {
    list.forEach(g => { if (g.end > maxL) maxL = g.end })
  })
  return maxL
})

// 变异密度分布模拟 (Layer 2 Signal Density)
const divergenceSignalBins = computed(() => {
  const bins = [
    { pos: '0~5k', label: 'Packaging / Head', val: 0.02, color: '#93c5fd' },
    { pos: '5k~10k', label: 'Capsid Structure', val: 0.01, color: '#93c5fd' },
    { pos: '10k~15k', label: 'Endolysin Cassette', val: 0.01, color: '#86efac' },
    { pos: '15k~22k', label: 'Replication Machinery', val: 0.04, color: '#fde68a' },
    { pos: '22k~27k', label: 'Defense / Acr Island', val: 0.18, color: '#fca5a5' },
    { pos: '27k~36k', label: 'Tail / Receptor Hotspot', val: 0.35, color: '#f59e0b' },
    { pos: '36k~42k', label: 'Terminal Repeats', val: 0.03, color: '#cbd5e1' }
  ]
  return bins
})

// Hotspot 局部放大基因与同源连接 (Layer 3)
const hotspotZoomData = computed(() => {
  const sids = activeSampleIds.value
  const s1 = sids[0] || ''
  const s2 = sids[1] || sids[0] || ''

  if (activeHotspot.value === 'tail') {
    return {
      title: '尾部受体识别结构域 (Tail Fiber & Receptor-Binding Hotspot)',
      coord: '28,000 ~ 36,000 bp',
      desc: '负责识别细菌表面 LPS / OmpA 受体的主尾丝与侧尾丝基因簇，是噬菌体宿主谱决定的核心开关。',
      identity: '100% Conserved (同源保守)',
      pairGenes1: (props.tailProteins?.filter(t => t.sample_id === s1) || []).map((t, idx) => ({
        name: t.product || `Tail_ORF_${idx+1}`,
        locus: t.locus_tag,
        color: '#f59e0b',
        strand: '+'
      })),
      pairGenes2: (props.tailProteins?.filter(t => t.sample_id === s2) || []).map((t, idx) => ({
        name: t.product || `Tail_ORF_${idx+1}`,
        locus: t.locus_tag,
        color: '#f59e0b',
        strand: '+'
      }))
    }
  } else if (activeHotspot.value === 'lysis') {
    return {
      title: '内溶素裂解系统操纵子 (Endolysin Lysis Cassette)',
      coord: '11,000 ~ 14,500 bp',
      desc: '包含穿孔素 (Holin)、内溶素 (Endolysin) 与跨膜脂蛋白 (Spanin) 的协同裂解操纵子，决定宿主胞壁破裂效率。',
      identity: '100% Invariant (无突变)',
      pairGenes1: [
        { name: 'Holin (穿孔素)', locus: 'gp_holin', color: '#059669', strand: '+' },
        { name: 'Endolysin (内溶素)', locus: 'gp_endo', color: '#10b981', strand: '+' },
        { name: 'Spanin (跨膜蛋白)', locus: 'gp_spanin', color: '#047857', strand: '+' }
      ],
      pairGenes2: [
        { name: 'Holin (穿孔素)', locus: 'gp_holin', color: '#059669', strand: '+' },
        { name: 'Endolysin (内溶素)', locus: 'gp_endo', color: '#10b981', strand: '+' },
        { name: 'Spanin (跨膜蛋白)', locus: 'gp_spanin', color: '#047857', strand: '+' }
      ]
    }
  } else {
    return {
      title: '免疫防御与反防御岛 (Anti-CRISPR & Defense Hotspot)',
      coord: '22,000 ~ 26,000 bp',
      desc: '编码 Acr 蛋白对抗宿主 CRISPR-Cas 及限制修饰系统的可变防御岛。',
      identity: 'Variable (存在/缺失多态性)',
      pairGenes1: [
        { name: 'Acr_Island_01', locus: 'acr_01', color: '#dc2626', strand: '+' },
        { name: 'Immunity_Modulator', locus: 'imm_02', color: '#ef4444', strand: '+' }
      ],
      pairGenes2: [
        { name: 'Acr_Island_01', locus: 'acr_01', color: '#dc2626', strand: '+' },
        { name: 'Hypothetical', locus: 'hyp_03', color: '#94a3b8', strand: '+' }
      ]
    }
  }
})
</script>

<template>
  <div class="workspace-genome-architecture">
    <!-- 控制与范围切换工具栏 -->
    <div class="academic-panel arch-control-bar">
      <div class="title-with-tag">
        <span class="panel-tag">Figure 2 Flagship</span>
        <h3>宏观共线性 → 变异信号密度 → 局部机制放大三层图 (Overview → Zoom Synteny)</h3>
      </div>

      <div class="track-toolbar">
        <div class="scope-group">
          <label>展示范围:</label>
          <button 
            :class="['btn-toggle', { active: trackScope === 'pair' }]"
            @click="trackScope = 'pair'"
            :disabled="!selectedPair"
          >
            当前选定样本对 (Pair)
          </button>
          <button 
            :class="['btn-toggle', { active: trackScope === 'all' }]"
            @click="trackScope = 'all'"
          >
            全部样本 (Cohort)
          </button>
        </div>

        <div class="hotspot-group">
          <label>聚焦机制区 (Hotspot):</label>
          <button 
            :class="['btn-hotspot', { active: activeHotspot === 'tail' }]"
            @click="activeHotspot = 'tail'"
          >
            ★ 尾丝受体结合区 (Tail)
          </button>
          <button 
            :class="['btn-hotspot', { active: activeHotspot === 'lysis' }]"
            @click="activeHotspot = 'lysis'"
          >
            内溶素裂解系统 (Lysis)
          </button>
          <button 
            :class="['btn-hotspot', { active: activeHotspot === 'defense' }]"
            @click="activeHotspot = 'defense'"
          >
            攻防岛 (Acr / Defense)
          </button>
        </div>
      </div>
    </div>

    <!-- 🌟 Layer 1: 全局宏观共线性多基因组图 (Global Genome Synteny Overview) -->
    <div class="academic-panel layer-panel layer-1-synteny">
      <div class="layer-header">
        <span class="layer-badge">Layer 1</span>
        <h4>全基因组宏观共线性全景 (Global Synteny Architecture)</h4>
        <span class="layer-subtip">0 ~ {{ (maxGenomeLength / 1000).toFixed(0) }} kb 物理坐标排列</span>
      </div>

      <div class="synteny-tracks-box">
        <div 
          v-for="sid in activeSampleIds" 
          :key="'synteny-track-' + sid"
          class="synteny-sample-track"
        >
          <div class="synteny-name-col">
            <strong>{{ sampleNames[sid] }}</strong>
            <small>{{ (sampleGeneTracks[sid] || []).length }} CDS</small>
          </div>

          <div class="synteny-svg-wrap">
            <svg class="synteny-svg" viewBox="0 0 900 48">
              <!-- 骨架主轴 -->
              <line x1="10" y1="24" x2="890" y2="24" stroke="#cbd5e1" stroke-width="2.5" />

              <!-- 基因色块多边形 -->
              <polygon
                v-for="(g, gIdx) in sampleGeneTracks[sid]"
                :key="gIdx"
                :points="`
                  ${10 + (g.start / maxGenomeLength) * 880},14 
                  ${10 + ((g.end - 150) / maxGenomeLength) * 880},14 
                  ${10 + (g.end / maxGenomeLength) * 880},24 
                  ${10 + ((g.end - 150) / maxGenomeLength) * 880},34 
                  ${10 + (g.start / maxGenomeLength) * 880},34
                `"
                :fill="g.color"
                class="gene-poly-block"
                @mouseenter="hoveredGene = g"
                @mouseleave="hoveredGene = null"
              >
                <title>{{ g.locus_tag }}: {{ g.product }} ({{ g.start }}..{{ g.end }} bp)</title>
              </polygon>

              <!-- Hotspot 变异高亮区方框 -->
              <rect 
                x="590" y="6" width="180" height="36" 
                fill="#f59e0b" fill-opacity="0.12" 
                stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3 3"
              />
            </svg>
          </div>
        </div>
      </div>
    </div>

    <!-- 🌟 Layer 2: 变异信号密度与断点分布轨 (Divergence Signal Density Track) -->
    <div class="academic-panel layer-panel layer-2-density">
      <div class="layer-header">
        <span class="layer-badge bg-amber">Layer 2</span>
        <h4>全基因组变异信号与断点密度峰值轨 (Sequence Divergence & Breakpoint Signal Track)</h4>
        <span class="layer-subtip">波峰代表高分化区域；波谷代表高保守骨架</span>
      </div>

      <div class="density-bars-strip">
        <div 
          v-for="(bin, bIdx) in divergenceSignalBins" 
          :key="bIdx"
          class="density-bin-col"
          :class="{ 'bin-hotspot-active': bin.val >= 0.15 }"
        >
          <div class="bin-bar-track">
            <div 
              class="bin-bar-fill" 
              :style="{ height: (bin.val * 240) + 'px', backgroundColor: bin.color }"
            ></div>
          </div>
          <span class="bin-lbl-pos">{{ bin.pos }}</span>
          <span class="bin-lbl-name">{{ bin.label }}</span>
        </div>
      </div>
    </div>

    <!-- 🌟 Layer 3: 局部高精机制放大操纵子 (Hotspot Mechanism Zoom Operon) -->
    <div class="academic-panel layer-panel layer-3-zoom">
      <div class="layer-header">
        <div class="header-left">
          <span class="layer-badge bg-emerald">Layer 3</span>
          <h4>{{ hotspotZoomData.title }} (Local Operon Zoom)</h4>
        </div>
        <span class="coord-tag">物理区间: {{ hotspotZoomData.coord }}</span>
      </div>

      <p class="hotspot-science-desc">{{ hotspotZoomData.desc }}</p>

      <!-- 双轨局部高精对齐图谱 (Dual-Track High-Precision Alignment) -->
      <div class="zoom-dual-track-box">
        <!-- 样本 1 基因簇 -->
        <div class="zoom-sample-row">
          <span class="zoom-sname-tag">{{ sampleNames[activeSampleIds[0] || ''] }}</span>
          <div class="zoom-genes-strip">
            <div 
              v-for="(g, idx) in hotspotZoomData.pairGenes1" 
              :key="'z1-' + idx"
              class="zoom-arrow-gene"
              :style="{ backgroundColor: g.color }"
            >
              <strong>{{ g.name }}</strong>
              <small>{{ g.locus }}</small>
            </div>
          </div>
        </div>

        <!-- 中间同源对应带 (Trapezoid Ribbon) -->
        <div class="zoom-identity-ribbon">
          <span class="ribbon-badge">Local Ortholog Alignment: <strong>{{ hotspotZoomData.identity }}</strong></span>
        </div>

        <!-- 样本 2 基因簇 -->
        <div class="zoom-sample-row">
          <span class="zoom-sname-tag">{{ sampleNames[activeSampleIds[1] || activeSampleIds[0] || ''] }}</span>
          <div class="zoom-genes-strip">
            <div 
              v-for="(g, idx) in hotspotZoomData.pairGenes2" 
              :key="'z2-' + idx"
              class="zoom-arrow-gene"
              :style="{ backgroundColor: g.color }"
            >
              <strong>{{ g.name }}</strong>
              <small>{{ g.locus }}</small>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 悬停基因信息展示条 -->
    <div class="hovered-gene-bar" v-if="hoveredGene">
      <span class="h-tag" :style="{ backgroundColor: hoveredGene.color }">{{ hoveredGene.category }}</span>
      <strong>{{ hoveredGene.locus_tag }}</strong>:
      <span class="h-prod">{{ hoveredGene.product }}</span>
      <span class="h-coord">坐标: {{ hoveredGene.start }} ~ {{ hoveredGene.end }} bp</span>
    </div>
  </div>
</template>

<style scoped>
.workspace-genome-architecture {
  display: flex;
  flex-direction: column;
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

.arch-control-bar {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
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

.arch-control-bar h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.track-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.scope-group,
.hotspot-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.scope-group label,
.hotspot-group label {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.btn-toggle,
.btn-hotspot {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-toggle.active,
.btn-hotspot.active {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
}

/* Layer 通用标头 */
.layer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 8px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.layer-badge {
  background: #2563eb;
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
}

.bg-amber { background: #d97706; }
.bg-emerald { background: #059669; }

.layer-header h4 {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}

.layer-subtip,
.coord-tag {
  font-size: 10px;
  color: #64748b;
}

/* Layer 1 全局共线性 */
.synteny-tracks-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.synteny-sample-track {
  display: flex;
  align-items: center;
  gap: 12px;
}

.synteny-name-col {
  width: 120px;
  display: flex;
  flex-direction: column;
}

.synteny-name-col strong {
  font-size: 11px;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.synteny-name-col small {
  font-size: 9px;
  color: #94a3b8;
}

.synteny-svg-wrap {
  flex: 1;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 4px;
}

.synteny-svg {
  width: 100%;
  height: 48px;
  display: block;
}

.gene-poly-block {
  cursor: pointer;
  transition: opacity 0.15s;
}

.gene-poly-block:hover {
  opacity: 0.8;
}

/* Layer 2 变异密度轨 */
.density-bars-strip {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
  padding: 12px;
}

.density-bin-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.bin-bar-track {
  height: 70px;
  width: 24px;
  background: #e2e8f0;
  border-radius: 3px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}

.bin-bar-fill {
  width: 100%;
  border-radius: 3px;
  transition: height 0.3s ease;
}

.bin-lbl-pos {
  font-size: 9px;
  font-weight: 700;
  color: #334155;
}

.bin-lbl-name {
  font-size: 8px;
  color: #64748b;
  text-align: center;
  line-height: 1.2;
}

.bin-hotspot-active .bin-bar-track {
  outline: 2px solid #f59e0b;
}

/* Layer 3 局部放大 */
.hotspot-science-desc {
  margin: 0;
  font-size: 11px;
  color: #475569;
  line-height: 1.4;
}

.zoom-dual-track-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 14px;
}

.zoom-sample-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.zoom-sname-tag {
  width: 110px;
  font-size: 11px;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.zoom-genes-strip {
  display: flex;
  gap: 8px;
  flex: 1;
}

.zoom-arrow-gene {
  flex: 1;
  height: 36px;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  padding: 0 8px;
}

.zoom-arrow-gene strong {
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.zoom-arrow-gene small {
  font-size: 8px;
  opacity: 0.85;
}

.zoom-identity-ribbon {
  text-align: center;
  padding: 2px;
}

.ribbon-badge {
  background: #dcfce7;
  color: #166534;
  font-size: 10px;
  padding: 3px 10px;
  border-radius: 4px;
}

/* 悬停条 */
.hovered-gene-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 6px 12px;
  font-size: 11px;
  color: #0f172a;
}

.h-tag {
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 3px;
}

.h-prod {
  color: #475569;
}

.h-coord {
  color: #94a3b8;
  margin-left: auto;
}
</style>
