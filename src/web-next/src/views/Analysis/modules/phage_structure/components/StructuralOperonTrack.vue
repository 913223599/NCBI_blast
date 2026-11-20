<script setup lang="ts">
import { computed, ref } from 'vue'
import type { StructureProteinItem } from '../types'
import { formatGenomeBp, getRoleTrackColor } from '../utils'

const props = defineProps<{
  proteins: StructureProteinItem[]
  genomeLengthBp: number
}>()

const onlyStructural = ref<boolean>(true)
const selectedProtein = ref<StructureProteinItem | null>(null)

const visibleProteins = computed(() => {
  if (!onlyStructural.value) return props.proteins
  return props.proteins.filter((p) => p.structural_role !== 'OTHER' || p.ptf_is_tail)
})

const safeTotalBp = computed(() => Math.max(1000, props.genomeLengthBp || 1))
const svgW = 820
const padL = 24
const padR = 24
const spanW = svgW - padL - padR

function mapX(bp: number): number {
  return padL + (Math.max(0, Math.min(bp, safeTotalBp.value)) / safeTotalBp.value) * spanW
}

function buildArrowPoints(p: StructureProteinItem): string {
  const x1 = mapX(p.start)
  const x2 = mapX(p.end)
  const w = Math.max(4, x2 - x1)
  const tip = Math.min(8, w * 0.4)
  const yMid = p.strand === '+' ? 42 : 76
  const h = 11

  if (p.strand === '+') {
    const endX = x1 + w
    return `${x1},${yMid - h} ${endX - tip},${yMid - h} ${endX},${yMid} ${endX - tip},${yMid + h} ${x1},${yMid + h}`
  }
  const endX = x1 + w
  return `${x1 + tip},${yMid - h} ${endX},${yMid - h} ${endX},${yMid + h} ${x1 + tip},${yMid + h} ${x1},${yMid}`
}
</script>

<template>
  <div class="operon-card">
    <div class="operon-head">
      <div>
        <h4>结构操纵子物理基因组轨道</h4>
        <p class="operon-sub">
          展示 {{ formatGenomeBp(safeTotalBp) }} 范围内的头部-连接器-尾部-TMP-裂解基因物理排布（正链上排，负链下排，点击基因块查看明细）
        </p>
      </div>
      <label class="toggle-lbl">
        <input v-model="onlyStructural" type="checkbox" />
        <span>
          仅高亮结构与尾模块 ORF ({{ proteins.filter((p) => p.structural_role !== 'OTHER' || p.ptf_is_tail).length }}/{{ proteins.length }})
        </span>
      </label>
    </div>

    <div class="legend-row">
      <span class="lg-item"><i style="background:#0ea5e9"></i>头部/包装</span>
      <span class="lg-item"><i style="background:#8b5cf6"></i>连接器</span>
      <span class="lg-item"><i style="background:#1d4ed8"></i>尾鞘 TSP</span>
      <span class="lg-item"><i style="background:#16a34a"></i>MTP/TTP/TAP</span>
      <span class="lg-item"><i style="background:#f59e0b"></i>TMP 卷尺</span>
      <span class="lg-item"><i style="background:#ea580c"></i>短尾注入模块</span>
      <span class="lg-item"><i style="background:#0d9488"></i>尾丝 RBP</span>
      <span class="lg-item"><i style="background:#e11d48"></i>裂解/整合</span>
    </div>

    <div class="track-wrap">
      <svg :viewBox="`0 0 ${svgW} 112`" class="track-svg">
        <line :x1="padL" y1="59" :x2="svgW - padR" y2="59" stroke="#cbd5e1" stroke-width="1.5" />
        <polygon
          v-for="p in visibleProteins"
          :key="p.locus_tag"
          :points="buildArrowPoints(p)"
          :fill="getRoleTrackColor(p.structural_role)"
          :stroke="selectedProtein?.locus_tag === p.locus_tag ? '#0f172a' : '#ffffff'"
          :stroke-width="selectedProtein?.locus_tag === p.locus_tag ? 1.8 : 0.6"
          class="gene-poly"
          @click="selectedProtein = p"
          @mouseenter="selectedProtein = p"
        />
      </svg>
    </div>

    <div v-if="selectedProtein" class="selected-banner">
      <span class="sb-locus">{{ selectedProtein.locus_tag }}</span>
      <span class="sb-role">{{ selectedProtein.role_label_cn || selectedProtein.structural_role }}</span>
      <span class="sb-coord">{{ selectedProtein.start }}..{{ selectedProtein.end }} bp ({{ selectedProtein.strand }}) · {{ selectedProtein.length_aa }} aa</span>
      <span v-if="selectedProtein.phrog_id" class="sb-phrog">{{ selectedProtein.phrog_id }} (score {{ selectedProtein.hmm_score }})</span>
      <span v-if="selectedProtein.ptf_is_tail" class="sb-phrog">
        PhageTailFinder 尾概率 {{ (selectedProtein.ptf_tail_prob * 100).toFixed(0) }}%
        {{ selectedProtein.ptf_pfam ? `(${selectedProtein.ptf_pfam})` : '' }}
      </span>
      <span class="sb-prod">{{ selectedProtein.product }}</span>
    </div>
  </div>
</template>

<style scoped>
.operon-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 18px 20px;
}

.operon-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

h4 {
  margin: 0;
  font-size: 0.98rem;
  color: #0f172a;
}

.operon-sub {
  margin: 3px 0 0 0;
  font-size: 0.8rem;
  color: #64748b;
}

.toggle-lbl {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  color: #334155;
  cursor: pointer;
}

.legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 0.76rem;
  color: #475569;
}

.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.lg-item i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
}

.track-wrap {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px;
}

.track-svg {
  width: 100%;
  height: auto;
  display: block;
}

.gene-poly {
  cursor: pointer;
  transition: opacity 0.12s;
}

.gene-poly:hover {
  opacity: 0.82;
}

.selected-banner {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 0.8rem;
}

.sb-locus {
  font-weight: 700;
  font-family: ui-monospace, monospace;
  color: #1d4ed8;
}

.sb-role {
  background: #ffffff;
  border: 1px solid #93c5fd;
  color: #1e40af;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
}

.sb-coord,
.sb-phrog {
  color: #475569;
  font-family: ui-monospace, monospace;
}

.sb-prod {
  color: #0f172a;
  font-weight: 500;
}
</style>
