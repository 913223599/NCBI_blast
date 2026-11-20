<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PolyXRegion, TandemRepeatUnit, TmpAnalysisItem } from '../types'

const props = defineProps<{
  tmpList: TmpAnalysisItem[]
}>()

const activeIdx = ref<number>(0)
const currentTmp = computed<TmpAnalysisItem | null>(() => {
  if (!props.tmpList.length) return null
  return props.tmpList[Math.min(activeIdx.value, props.tmpList.length - 1)] || null
})

const hoverInfo = ref<{ title: string; detail: string } | null>(null)

const chartW = 760
const padL = 50
const padR = 24
const plotW = chartW - padL - padR

function xPos(aaPos: number, lenAa: number): number {
  return padL + (Math.max(0, Math.min(aaPos, lenAa)) / Math.max(1, lenAa)) * plotW
}

const aaTicks = computed(() => {
  const t = currentTmp.value
  if (!t) return []
  const step = Math.max(100, Math.ceil(t.length_aa / 6 / 50) * 50)
  const ticks: number[] = [0]
  for (let x = step; x < t.length_aa - 40; x += step) ticks.push(x)
  ticks.push(t.length_aa)
  return ticks
})

const hydroPath = computed(() => {
  const t = currentTmp.value
  if (!t || !t.hydropathy_profile.length) return ''
  const n = t.hydropathy_profile.length
  const baseY = 198
  const scaleY = 12
  return t.hydropathy_profile
    .map((val, i) => {
      const x = padL + ((i + 0.5) / n) * plotW
      const y = baseY - Math.max(-2.5, Math.min(2.5, val)) * scaleY
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
})

function onHoverPolyX(p: PolyXRegion): void {
  hoverInfo.value = {
    title: `polyX ${p.kind === 'homorun' ? '连续同聚区' : '低复杂度富集窗'} (${p.start_aa}..${p.end_aa} aa)`,
    detail: `优势氨基酸: ${p.dominant_aa} | 长度 ${p.length_aa} aa | 片段: ${p.snippet}`,
  }
}

function onHoverTR(tr: TandemRepeatUnit): void {
  hoverInfo.value = {
    title: `串联重复序列 TR (${tr.start_aa}..${tr.end_aa} aa)`,
    detail: `周期 ${tr.period_aa} aa × ${tr.copy_number} 拷贝 | 相似度 ${(tr.similarity * 100).toFixed(0)}% | 示例单元: ${tr.unit_sample}`,
  }
}
</script>

<template>
  <div class="tmp-card">
    <div class="tmp-head">
      <div>
        <h4>卷尺蛋白 (TMP) 分子标尺与序列重复区剖析</h4>
        <p class="tmp-sub">
          基于 α-螺旋轴向每残基约 0.145 nm (0.140~0.150 nm/aa) 构型折算理论尾管物理量纲，并同步解析 polyX 与串联重复阵列 (TRs)
        </p>
      </div>

      <div v-if="tmpList.length > 1" class="tmp-switcher">
        <button
          v-for="(item, idx) in tmpList"
          :key="item.locus_tag"
          type="button"
          class="switch-btn"
          :class="{ active: idx === activeIdx }"
          @click="activeIdx = idx"
        >
          {{ item.locus_tag }} ({{ item.length_aa }} aa)
        </button>
      </div>
    </div>

    <div v-if="!currentTmp" class="tmp-empty">
      未检测到符合标尺标准 (&ge;250 aa) 的卷尺蛋白 (TMP)。对极短尾 (Podoviridae-like) 或非有尾噬菌体属正常形态表现。
    </div>

    <div v-else class="tmp-body">
      <!-- 定量摘要栏 -->
      <div class="tmp-metrics">
        <div class="metric-pill highlight">
          <span class="m-lbl">理论估算尾长</span>
          <span class="m-val">
            约 {{ currentTmp.est_tail_length_nm }} nm
            <small v-if="currentTmp.est_tail_range_nm.length >= 2">
              ({{ currentTmp.est_tail_range_nm[0] }}~{{ currentTmp.est_tail_range_nm[1] }} nm)
            </small>
          </span>
        </div>
        <div class="metric-pill">
          <span class="m-lbl">标尺基因长度</span>
          <span class="m-val">{{ currentTmp.length_aa }} aa <small>({{ currentTmp.locus_tag }})</small></span>
        </div>
        <div class="metric-pill">
          <span class="m-lbl">polyX 富集</span>
          <span class="m-val">{{ currentTmp.polyx_count }} 区 / {{ currentTmp.polyx_total_aa }} aa ({{ currentTmp.polyx_fraction_pct }}%)</span>
        </div>
        <div class="metric-pill">
          <span class="m-lbl">串联重复 TRs</span>
          <span class="m-val">
            {{ currentTmp.tr_count }} 阵 / {{ currentTmp.tr_total_aa }} aa ({{ currentTmp.tr_fraction_pct }}%)
          </span>
        </div>
      </div>

      <!-- 交互矢量标尺图 -->
      <div class="ruler-svg-wrap" @mouseleave="hoverInfo = null">
        <svg :viewBox="`0 0 ${chartW} 248`" class="ruler-svg">
          <!-- 标尺底座与坐标轴 -->
          <line :x1="padL" y1="32" :x2="chartW - padR" y2="32" stroke="#94a3b8" stroke-width="1.5" />
          <g v-for="tk in aaTicks" :key="tk">
            <line :x1="xPos(tk, currentTmp.length_aa)" y1="27" :x2="xPos(tk, currentTmp.length_aa)" y2="36" stroke="#64748b" />
            <text :x="xPos(tk, currentTmp.length_aa)" y="21" text-anchor="middle" class="axis-txt">{{ tk }} aa</text>
          </g>

          <!-- 1. 串联重复弧拱轨道 -->
          <text x="8" y="65" class="track-lbl">TRs</text>
          <line :x1="padL" y1="68" :x2="chartW - padR" y2="68" stroke="#e2e8f0" stroke-width="3" stroke-linecap="round" />
          <g v-for="(tr, i) in currentTmp.tandem_repeats" :key="`tr-${i}`" class="hover-target" @mouseenter="onHoverTR(tr)">
            <rect
              :x="xPos(tr.start_aa - 1, currentTmp.length_aa)"
              y="55"
              :width="Math.max(5, xPos(tr.end_aa, currentTmp.length_aa) - xPos(tr.start_aa - 1, currentTmp.length_aa))"
              height="18"
              rx="4"
              fill="#0ea5e9"
              opacity="0.88"
            />
            <path
              :d="`M ${xPos(tr.start_aa - 1, currentTmp.length_aa)} 55 Q ${(xPos(tr.start_aa - 1, currentTmp.length_aa) + xPos(tr.end_aa, currentTmp.length_aa)) / 2} 38 ${xPos(tr.end_aa, currentTmp.length_aa)} 55`"
              fill="none"
              stroke="#0284c7"
              stroke-width="1.5"
            />
          </g>

          <!-- 2. polyX 序列热斑轨道 -->
          <text x="8" y="109" class="track-lbl">polyX</text>
          <rect :x="padL" y="96" :width="plotW" height="18" rx="5" fill="#fef3c7" stroke="#fde68a" />
          <g v-for="(px, i) in currentTmp.polyx_regions" :key="`px-${i}`" class="hover-target" @mouseenter="onHoverPolyX(px)">
            <rect
              :x="xPos(px.start_aa - 1, currentTmp.length_aa)"
              y="96"
              :width="Math.max(4, xPos(px.end_aa, currentTmp.length_aa) - xPos(px.start_aa - 1, currentTmp.length_aa))"
              height="18"
              rx="3"
              :fill="px.kind === 'homorun' ? '#dc2626' : '#f59e0b'"
            />
          </g>

          <!-- 3. Kyte-Doolittle 疏水性折线图 -->
          <text x="8" y="198" class="track-lbl">疏水</text>
          <line :x1="padL" y1="198" :x2="chartW - padR" y2="198" stroke="#cbd5e1" stroke-dasharray="4 4" />
          <rect
            v-for="(hs, i) in currentTmp.hydrophobic_segments"
            :key="`hs-${i}`"
            :x="xPos(hs.start_aa - 1, currentTmp.length_aa)"
            y="160"
            :width="Math.max(4, xPos(hs.end_aa, currentTmp.length_aa) - xPos(hs.start_aa - 1, currentTmp.length_aa))"
            height="68"
            fill="#f43f5e"
            opacity="0.12"
          />
          <path :d="hydroPath" fill="none" stroke="#4f46e5" stroke-width="2" />
          <text :x="padL + 6" y="152" class="legend-txt">
            蓝色弧: Tandem Repeats · 红/橙块: polyX 寡聚与富集区 · 紫线: Kyte-Doolittle 疏水区段 (虚线=0)
          </text>
        </svg>

        <div v-if="hoverInfo" class="hover-bar">
          <strong>{{ hoverInfo.title }}</strong>
          <span>{{ hoverInfo.detail }}</span>
        </div>
      </div>

      <!-- 机理与统计定性解说 -->
      <div class="interp-box">
        {{ currentTmp.interpretation }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.tmp-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 18px 20px;
}

.tmp-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

h4 {
  margin: 0;
  font-size: 0.98rem;
  color: #0f172a;
}

.tmp-sub {
  margin: 3px 0 0 0;
  font-size: 0.8rem;
  color: #64748b;
}

.tmp-switcher {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.switch-btn {
  padding: 4px 10px;
  font-size: 0.78rem;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
}

.switch-btn.active {
  background: #f59e0b;
  color: #ffffff;
  border-color: #d97706;
}

.tmp-empty {
  padding: 18px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  color: #64748b;
  font-size: 0.86rem;
}

.tmp-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.metric-pill {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.metric-pill.highlight {
  background: #fffbeb;
  border-color: #fcd34d;
}

.m-lbl {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
}

.m-val {
  font-size: 0.92rem;
  font-weight: 700;
  color: #0f172a;
}

.m-val small {
  font-weight: 500;
  color: #64748b;
}

.ruler-svg-wrap {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 10px 6px 10px;
}

.ruler-svg {
  width: 100%;
  height: auto;
  display: block;
}

.axis-txt {
  fill: #64748b;
  font-size: 10px;
  font-family: ui-monospace, monospace;
}

.track-lbl {
  fill: #334155;
  font-size: 11px;
  font-weight: 700;
}

.legend-txt {
  fill: #475569;
  font-size: 10px;
}

.hover-target {
  cursor: pointer;
}

.hover-bar {
  margin-top: 6px;
  padding: 7px 10px;
  border-radius: 7px;
  background: #ffffff;
  border: 1px solid #bae6fd;
  font-size: 0.8rem;
  color: #0f172a;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.interp-box {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 9px;
  background: #f1f5f9;
  color: #334155;
  font-size: 0.84rem;
  line-height: 1.55;
}
</style>
