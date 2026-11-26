<script setup lang="ts">
import type { StackedSample, StackedSegment } from './diversityHelpers'

defineProps<{
  isGroupView: boolean
  activeSampleCount: number
  topTaxaCount: number
  topTaxaList: string[]
  stackedBarData: StackedSample[]
  getTaxonColor: (taxon: string) => string
}>()

const emit = defineEmits<{
  (e: 'update:topTaxaCount', value: number): void
  (e: 'showTooltip', event: MouseEvent, seg: StackedSegment, sampleName: string): void
  (e: 'hideTooltip'): void
}>()
</script>

<template>
  <div class="tab-content-neo scroll-y">
    <div class="chart-container-card">
      <div class="chart-status-banner" v-if="isGroupView">
        <span class="banner-tag">合并模式已生效</span>
        <span class="banner-desc">
          已将随机采样点位合并汇总为 {{ activeSampleCount }} 个样本/组，各组内序列 Reads 已重新按 rrnDB GCN 拷贝数精准归一化
        </span>
      </div>

      <div class="chart-top-bar">
        <div class="top-taxa-selector">
          <span class="selector-lbl">物种展示模式:</span>
          <div class="selector-btn-group">
            <button
              type="button"
              class="selector-btn"
              :class="{ active: topTaxaCount === 10 }"
              @click="emit('update:topTaxaCount', 10)"
            >
              Top 10
            </button>
            <button
              type="button"
              class="selector-btn"
              :class="{ active: topTaxaCount === 15 }"
              @click="emit('update:topTaxaCount', 15)"
            >
              Top 15
            </button>
            <button
              type="button"
              class="selector-btn"
              :class="{ active: topTaxaCount === 20 }"
              @click="emit('update:topTaxaCount', 20)"
            >
              Top 20
            </button>
            <button
              type="button"
              class="selector-btn"
              :class="{ active: topTaxaCount >= 900 }"
              @click="emit('update:topTaxaCount', 999)"
            >
              全部物种 (All)
            </button>
          </div>
        </div>
      </div>

      <div class="chart-legend-wrap">
        <div v-for="taxon in topTaxaList" :key="taxon" class="legend-badge">
          <span class="dot" :style="{ background: getTaxonColor(taxon) }"></span>
          <span class="text">{{ taxon }}</span>
        </div>
        <div
          v-if="topTaxaCount < 900"
          class="legend-badge badge-minor"
          title="非前列的真实低丰度长尾微生物合集，可切换‘全部物种’展开"
        >
          <span class="dot" style="background: #94a3b8"></span>
          <span class="text">长尾微量物种 (Minor Taxa)</span>
        </div>
        <div
          class="legend-badge badge-noise"
          title="单/双 Reads 孤儿伪物种与随机测序噪声，经质控过滤器隔离"
        >
          <span class="dot" style="background: #475569"></span>
          <span class="text">低频测序噪声 (已质控过滤)</span>
        </div>
      </div>

      <div class="chart-guide-tip">
        <span class="guide-tag">图表说明</span>
        <span class="guide-txt">
          每个柱状条代表独立测序点位或合并组的 100% 相对丰度构成。图例圆点颜色与明细表物种颜色严格联动。
        </span>
      </div>

      <div class="svg-scroll-container">
        <svg :width="Math.max(800, stackedBarData.length * 48 + 120)" height="360" class="stacked-bar-svg">
          <line x1="50" y1="30" x2="100%" y2="30" stroke="#f1f5f9" stroke-dasharray="4,4" />
          <line x1="50" y1="95" x2="100%" y2="95" stroke="#f1f5f9" stroke-dasharray="4,4" />
          <line x1="50" y1="160" x2="100%" y2="160" stroke="#f1f5f9" stroke-dasharray="4,4" />
          <line x1="50" y1="225" x2="100%" y2="225" stroke="#f1f5f9" stroke-dasharray="4,4" />
          <line x1="50" y1="290" x2="100%" y2="290" stroke="#cbd5e1" />

          <text x="42" y="34" text-anchor="end" class="axis-txt">100%</text>
          <text x="42" y="99" text-anchor="end" class="axis-txt">75%</text>
          <text x="42" y="164" text-anchor="end" class="axis-txt">50%</text>
          <text x="42" y="229" text-anchor="end" class="axis-txt">25%</text>
          <text x="42" y="294" text-anchor="end" class="axis-txt">0%</text>

          <g
            v-for="(sample, idx) in stackedBarData"
            :key="sample.sampleName"
            :transform="`translate(${65 + idx * 46}, 0)`"
          >
            <g v-for="seg in sample.segments" :key="seg.taxon">
              <rect
                :y="290 - (seg.yTop / 100) * 260"
                :height="(seg.pct / 100) * 260"
                width="32"
                :fill="seg.color"
                rx="3"
                class="bar-seg"
                @mousemove="emit('showTooltip', $event, seg, sample.sampleName)"
                @mouseleave="emit('hideTooltip')"
              />
            </g>
            <rect v-if="sample.isGroup" x="2" y="294" width="28" height="4" rx="2" fill="#3b82f6" />
            <text
              x="16"
              y="312"
              text-anchor="end"
              transform="rotate(-40, 16, 312)"
              class="sample-x-label"
              :class="{ 'label-group': sample.isGroup }"
            >
              {{ sample.sampleName }}
            </text>
          </g>
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped src="./styles/chart.css"></style>
