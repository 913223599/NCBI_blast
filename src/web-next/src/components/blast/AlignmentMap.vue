<script setup lang="ts">
/**
 * AlignmentMap.vue - BLAST 比对结果覆盖度图 (SVG 版)
 * 复刻 legacy Matplotlib 逻辑，展示 Query 覆盖范围和一致性颜色
 */
import { computed } from 'vue'

interface HSP {
  query_start: number
  query_end: number
  score: number
  evalue: number
  identity: number
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

// 绘图常量
const WIDTH = 800
const ROW_HEIGHT = 30
const LEFT_MARGIN = 200
const RIGHT_MARGIN = 50
const TOP_MARGIN = 60
const BOTTOM_MARGIN = 40

const totalWidth = WIDTH + LEFT_MARGIN + RIGHT_MARGIN
const totalHeight = computed(() => props.hits.length * ROW_HEIGHT + TOP_MARGIN + BOTTOM_MARGIN)

// 比例尺
const scaleX = (pos: number) => (pos / props.queryLength) * WIDTH

// 颜色逻辑 (同 legacy)
function getColor(identity: number) {
  if (identity >= 0.9) return '#d62728' // Red
  if (identity >= 0.7) return '#ff7f0e' // Orange
  if (identity >= 0.5) return '#2ca02c' // Green
  return '#1f77b4' // Blue
}

// 简化标题 (同 legacy)
function simplifyTitle(title: string) {
  if (!title) return 'Unknown'
  const match = title.match(/\[(.*?)\]/)
  if (match) return match[1]
  const words = title.split('|').pop()?.trim().split(/\s+/) || []
  return words.slice(0, 4).join(' ') || title
}
</script>

<template>
  <div class="alignment-map-container scroll-v">
    <svg :width="totalWidth" :height="totalHeight" :viewBox="`0 0 ${totalWidth} ${totalHeight}`" class="alignment-svg">
      <!-- 坐标轴与背景网格 -->
      <g :transform="`translate(${LEFT_MARGIN}, ${TOP_MARGIN})`">
        <line x1="0" y1="0" :x2="WIDTH" y2="0" stroke="#e2e8f0" stroke-width="1" />
        <text v-for="i in 5" :key="i" :x="scaleX((props.queryLength * (i-1)) / 4)" y="-10" font-size="12" fill="#64748b" text-anchor="middle">
          {{ Math.round((props.queryLength * (i-1)) / 4) }}
        </text>
        <text :x="WIDTH / 2" y="-35" font-size="14" font-weight="700" text-anchor="middle" fill="#1e293b">
          Query: {{ queryName }} ({{ queryLength }} bp)
        </text>
      </g>

      <!-- Hits 列表 -->
      <g v-for="(hit, idx) in hits" :key="idx" :transform="`translate(0, ${TOP_MARGIN + idx * ROW_HEIGHT})`">
        <!-- 标题标签 -->
        <text :x="LEFT_MARGIN - 10" :y="ROW_HEIGHT / 2 + 5" font-size="11" text-anchor="end" fill="#334155" class="hit-label" :title="hit.title">
          {{ idx + 1 }}. {{ simplifyTitle(hit.title) }}
        </text>
        
        <!-- 背景线 -->
        <line :x1="LEFT_MARGIN" :y1="ROW_HEIGHT / 2" :x2="LEFT_MARGIN + WIDTH" :y2="ROW_HEIGHT / 2" stroke="#f1f5f9" stroke-width="1" />

        <!-- HSPs (比对片段) -->
        <g :transform="`translate(${LEFT_MARGIN}, 0)`">
          <rect 
            v-for="(hsp, hIdx) in hit.hsps" 
            :key="hIdx"
            :x="scaleX(hsp.query_start)"
            :y="5"
            :width="scaleX(hsp.query_end - hsp.query_start)"
            :height="ROW_HEIGHT - 10"
            :fill="getColor(hsp.identity)"
            rx="2"
            stroke="#000"
            stroke-width="0.5"
          >
            <title>Identity: {{ (hsp.identity * 100).toFixed(1) }}%, E-value: {{ hsp.evalue }}, Range: {{ hsp.query_start }}-{{ hsp.query_end }}</title>
          </rect>
        </g>
      </g>

      <!-- 图例 -->
      <g :transform="`translate(${totalWidth - 180}, 10)`">
        <rect x="0" y="0" width="10" height="10" fill="#d62728" /> <text x="15" y="10" font-size="10">>= 90%</text>
        <rect x="0" y="15" width="10" height="10" fill="#ff7f0e" /> <text x="15" y="25" font-size="10">70% - 90%</text>
        <rect x="0" y="30" width="10" height="10" fill="#2ca02c" /> <text x="15" y="40" font-size="10">50% - 70%</text>
        <rect x="0" y="45" width="10" height="10" fill="#1f77b4" /> <text x="15" y="55" font-size="10">< 50%</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.alignment-map-container {
  width: 100%;
  overflow-x: auto;
  background: white;
  border-radius: 12px;
  padding: 20px;
}
.alignment-svg {
  display: block;
  margin: 0 auto;
}
.hit-label {
  cursor: help;
}
.hit-label:hover {
  fill: #2563eb;
  font-weight: 700;
}
</style>
