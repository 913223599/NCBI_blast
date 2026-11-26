<script setup lang="ts">
import {
  CHORD_OUTER_RADIUS,
  FUNCTION_DEFS,
  FUNCTION_KEYS,
  getSampleColor,
  usePanGenomicsChord,
} from '../../composables/usePanGenomicsChord'
import type { ChordClusterItem } from '../../composables/usePanGenomicsChord'

const props = defineProps<{
  clusters: ChordClusterItem[]
  sampleNames: Record<string, string>
  visibleSampleIds: string[]
  aniMatrix?: Record<string, Record<string, number | null>>
  tailMatrix?: Record<string, Record<string, number>>
  lifestyles?: Record<string, unknown>[]
  selectedPair?: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
  (e: 'open-cluster-drawer', cluster: ChordClusterItem): void
}>()

const outerRadius = CHORD_OUTER_RADIUS

const {
  chordMode,
  minSharedThreshold,
  legendSearch,
  hoveredEntity,
  sampleStatsMap,
  maxSharedValue,
  sampleChordLayout,
  bipartiteChordLayout,
  filteredLegendSampleIds,
  getSampleShortName,
  getRibbonPath,
  getArcPath,
  getCatColor,
  handleGroupMouseEnter,
  handleRibbonMouseEnter,
  handleMouseLeave,
  handleGroupClick,
  handleRibbonClick,
  handleLegendMouseEnter,
  handleLegendFunctionMouseEnter,
} = usePanGenomicsChord(props, emit)
</script>

<template>
  <div class="chord-diagram-container">
    <div class="chord-toolbar">
      <div class="left-controls">
        <div class="mode-switch-group">
          <span class="toolbar-label">拓扑视角:</span>
          <div class="segmented-pill">
            <button type="button" class="seg-item" :class="{ active: chordMode === 'sample-sample' }" @click="chordMode = 'sample-sample'">
              样本间基因共享流 (两两互联)
            </button>
            <button type="button" class="seg-item" :class="{ active: chordMode === 'sample-function' }" @click="chordMode = 'sample-function'">
              样本 ↔ 10 大功能系统关联
            </button>
          </div>
        </div>

        <div v-if="chordMode === 'sample-sample'" class="filter-slider-group">
          <span class="toolbar-label">关联阈值:</span>
          <div class="step-buttons">
            <button
              v-for="st in [0, 5, 15, 30]"
              :key="st"
              type="button"
              class="step-btn"
              :class="{ active: minSharedThreshold === st }"
              @click="minSharedThreshold = st"
            >
              {{ st === 0 ? '全部' : `&ge;${st}` }}
            </button>
          </div>
          <input
            v-model.number="minSharedThreshold"
            type="range"
            min="0"
            :max="maxSharedValue"
            step="1"
            class="mini-range"
            title="拖动微调共享基因数过滤阈值"
          />
          <span class="threshold-tag">&ge; {{ minSharedThreshold }} 基因</span>
        </div>
      </div>

      <div class="status-summary-pill">
        <span v-if="chordMode === 'sample-sample'">
          当前显示 <strong>{{ sampleChordLayout?.validChords.length || 0 }}</strong> 条跨样本共享流
        </span>
        <span v-else>
          当前显示 <strong>{{ bipartiteChordLayout?.validChords.length || 0 }}</strong> 条功能操纵子映射
        </span>
      </div>
    </div>

    <div class="chord-main-layout">
      <div class="chord-svg-viewport">
        <svg viewBox="-350 -350 700 700" class="chord-main-svg">
          <template v-if="chordMode === 'sample-sample' && sampleChordLayout">
            <g class="ribbons-layer">
              <path
                v-for="(d, i) in sampleChordLayout.validChords"
                :key="i"
                :d="getRibbonPath(d)"
                :fill="getSampleColor(d.source.index)"
                :class="[
                  'chord-ribbon',
                  {
                    faded: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && hoveredEntity.id !== sampleChordLayout.ids[d.source.index] && hoveredEntity.id !== sampleChordLayout.ids[d.target.index]) ||
                      (hoveredEntity.type === 'ribbon' && (hoveredEntity.id !== sampleChordLayout.ids[d.source.index] || hoveredEntity.targetId !== sampleChordLayout.ids[d.target.index]))
                    ),
                    active: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && (hoveredEntity.id === sampleChordLayout.ids[d.source.index] || hoveredEntity.id === sampleChordLayout.ids[d.target.index])) ||
                      (hoveredEntity.type === 'ribbon' && hoveredEntity.id === sampleChordLayout.ids[d.source.index] && hoveredEntity.targetId === sampleChordLayout.ids[d.target.index])
                    ),
                  },
                ]"
                @mouseenter="handleRibbonMouseEnter(d)"
                @mouseleave="handleMouseLeave"
                @click="handleRibbonClick(d)"
              />
            </g>

            <g class="groups-layer">
              <g
                v-for="(group, i) in sampleChordLayout.chords.groups"
                :key="i"
                class="chord-arc-group"
                @mouseenter="handleGroupMouseEnter(i)"
                @mouseleave="handleMouseLeave"
                @click="handleGroupClick(i)"
              >
                <path :d="getArcPath(group)" :fill="getSampleColor(i)" class="arc-path" />
                <g :transform="`rotate(${((group.startAngle + group.endAngle) / 2) * (180 / Math.PI) - 90}) translate(${outerRadius + 8}, 0)`">
                  <text
                    :text-anchor="(group.startAngle + group.endAngle) / 2 > Math.PI ? 'end' : 'start'"
                    :transform="(group.startAngle + group.endAngle) / 2 > Math.PI ? 'rotate(180)' : ''"
                    class="arc-label"
                  >
                    {{ getSampleShortName(sampleChordLayout.ids[i]!) }}
                  </text>
                </g>
              </g>
            </g>
          </template>

          <template v-else-if="chordMode === 'sample-function' && bipartiteChordLayout">
            <g class="ribbons-layer">
              <path
                v-for="(d, i) in bipartiteChordLayout.validChords"
                :key="i"
                :d="getRibbonPath(d)"
                :fill="d.source.index < bipartiteChordLayout.sIds.length ? getSampleColor(d.source.index) : getCatColor(bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length]!)"
                :class="[
                  'chord-ribbon',
                  {
                    faded: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && hoveredEntity.id !== bipartiteChordLayout.sIds[d.source.index] && hoveredEntity.id !== bipartiteChordLayout.sIds[d.target.index]) ||
                      (hoveredEntity.type === 'function' && hoveredEntity.id !== bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length] && hoveredEntity.id !== bipartiteChordLayout.fKeys[d.target.index - bipartiteChordLayout.sIds.length])
                    ),
                    active: hoveredEntity && (
                      (hoveredEntity.type === 'sample' && (hoveredEntity.id === bipartiteChordLayout.sIds[d.source.index] || hoveredEntity.id === bipartiteChordLayout.sIds[d.target.index])) ||
                      (hoveredEntity.type === 'function' && (hoveredEntity.id === bipartiteChordLayout.fKeys[d.source.index - bipartiteChordLayout.sIds.length] || hoveredEntity.id === bipartiteChordLayout.fKeys[d.target.index - bipartiteChordLayout.sIds.length]))
                    ),
                  },
                ]"
                @mouseenter="handleRibbonMouseEnter(d)"
                @mouseleave="handleMouseLeave"
              />
            </g>

            <g class="groups-layer">
              <g
                v-for="(group, i) in bipartiteChordLayout.chords.groups"
                :key="i"
                class="chord-arc-group"
                @mouseenter="handleGroupMouseEnter(i)"
                @mouseleave="handleMouseLeave"
              >
                <path
                  :d="getArcPath(group)"
                  :fill="i < bipartiteChordLayout.sIds.length ? getSampleColor(i) : getCatColor(bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]!)"
                  class="arc-path"
                />
                <g :transform="`rotate(${((group.startAngle + group.endAngle) / 2) * (180 / Math.PI) - 90}) translate(${outerRadius + 8}, 0)`">
                  <text
                    :text-anchor="(group.startAngle + group.endAngle) / 2 > Math.PI ? 'end' : 'start'"
                    :transform="(group.startAngle + group.endAngle) / 2 > Math.PI ? 'rotate(180)' : ''"
                    class="arc-label"
                    :class="{ 'func-label': i >= bipartiteChordLayout.sIds.length }"
                  >
                    {{
                      i < bipartiteChordLayout.sIds.length
                        ? getSampleShortName(bipartiteChordLayout.sIds[i]!)
                        : FUNCTION_DEFS[bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]!]?.short ||
                          bipartiteChordLayout.fKeys[i - bipartiteChordLayout.sIds.length]
                    }}
                  </text>
                </g>
              </g>
            </g>
          </template>
        </svg>
      </div>

      <div class="chord-legend-sidebar">
        <div class="inspector-hud-panel">
          <template v-if="hoveredEntity?.type === 'sample'">
            <div class="hud-header">
              <span class="hud-badge sample">噬菌体分离株</span>
              <span class="hud-code">{{ getSampleShortName(hoveredEntity.id) }}</span>
            </div>
            <div class="hud-name" :title="hoveredEntity.name">{{ hoveredEntity.name }}</div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">拥有家族</span>
                <strong class="hud-stat-val">{{ hoveredEntity.totalGenes }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">独有特异</span>
                <strong class="hud-stat-val c-amber">{{ hoveredEntity.uniqueGenes }}</strong>
              </div>
            </div>
          </template>

          <template v-else-if="hoveredEntity?.type === 'function'">
            <div class="hud-header"><span class="hud-badge func">生物学功能系统</span></div>
            <div class="hud-name">{{ hoveredEntity.name }}</div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">泛基因家族数</span>
                <strong class="hud-stat-val">{{ hoveredEntity.totalClustersInCat }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">覆盖株系</span>
                <strong class="hud-stat-val highlight">{{ hoveredEntity.coveredSamples }}/{{ props.visibleSampleIds.length }}</strong>
              </div>
            </div>
          </template>

          <template v-else-if="hoveredEntity?.type === 'ribbon'">
            <div class="hud-header">
              <span class="hud-badge ribbon">{{ chordMode === 'sample-sample' ? '跨株同源共享流' : '样本 ↔ 功能映射' }}</span>
            </div>
            <div class="hud-pair-row">
              <span class="pair-tag">{{ getSampleShortName(hoveredEntity.id) }}</span>
              <span class="pair-arrow">↔</span>
              <span class="pair-tag">{{ chordMode === 'sample-sample' ? getSampleShortName(hoveredEntity.targetId || '') : hoveredEntity.targetName }}</span>
            </div>
            <div class="hud-stats-grid">
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">{{ chordMode === 'sample-sample' ? '共享家族数' : '所含基因' }}</span>
                <strong class="hud-stat-val highlight">{{ hoveredEntity.value }}</strong>
              </div>
              <div class="hud-stat-cell">
                <span class="hud-stat-lbl">{{ hoveredEntity.ani ? '全蛋白 ANI' : '拓扑状态' }}</span>
                <strong class="hud-stat-val">{{ hoveredEntity.ani ? `${hoveredEntity.ani.toFixed(1)}%` : '已连接' }}</strong>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="hud-header">
              <span class="hud-badge overview">群体拓扑概览</span>
              <span class="hud-code">{{ props.visibleSampleIds.length }} 株</span>
            </div>
            <div class="hud-default-txt">悬停或点击任意弧段/连线，即时检视同源共享与功能构成。</div>
          </template>
        </div>

        <div class="legend-sidebar-head">
          <span class="sidebar-title">{{ chordMode === 'sample-sample' ? '样本色系图注' : '噬菌体与功能图注' }}</span>
          <span class="sidebar-count">{{ props.visibleSampleIds.length }} 样本</span>
        </div>

        <div class="legend-search-box">
          <input v-model="legendSearch" placeholder="搜索样本全称或短标..." class="wb-input legend-search-input" />
        </div>

        <div class="legend-scroll-wrap">
          <div v-if="chordMode === 'sample-function'" class="legend-section-title">10 大生物学功能操纵子</div>
          <div v-if="chordMode === 'sample-function'" class="func-legend-grid">
            <div
              v-for="fKey in FUNCTION_KEYS"
              :key="fKey"
              class="func-legend-chip"
              :class="{ active: hoveredEntity && hoveredEntity.id === fKey }"
              @mouseenter="handleLegendFunctionMouseEnter(fKey)"
              @mouseleave="handleMouseLeave"
            >
              <i class="func-dot" :style="{ backgroundColor: getCatColor(fKey) }"></i>
              <span class="func-lbl">{{ FUNCTION_DEFS[fKey]?.label }}</span>
            </div>
          </div>

          <div v-if="chordMode === 'sample-function'" class="legend-section-title mt-section">噬菌体分离株列表</div>

          <div
            v-for="sid in filteredLegendSampleIds"
            :key="sid"
            class="legend-sample-card"
            :class="{
              active: hoveredEntity && (hoveredEntity.id === sid || hoveredEntity.targetId === sid),
              selected: selectedPair && (selectedPair[0] === sid || selectedPair[1] === sid),
            }"
            @mouseenter="handleLegendMouseEnter(sid)"
            @mouseleave="handleMouseLeave"
            @click="emit('select-sample', sid)"
          >
            <div class="card-left-bar" :style="{ backgroundColor: getSampleColor(props.visibleSampleIds.indexOf(sid)) }"></div>
            <div class="card-content">
              <div class="card-top-row">
                <span class="card-short-tag" :style="{ color: getSampleColor(props.visibleSampleIds.indexOf(sid)) }">
                  {{ getSampleShortName(sid) }}
                </span>
                <span class="card-genes-badge">{{ sampleStatsMap[sid]?.total || 0 }} CDS</span>
              </div>
              <div class="card-fullname" :title="props.sampleNames[sid] || sid">{{ props.sampleNames[sid] || sid }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chord-diagram-container { display: flex; flex-direction: column; height: 680px; max-height: 680px; background: #ffffff; border-radius: 10px; overflow: hidden; position: relative; }
.chord-toolbar, .legend-sidebar-head, .hud-header, .card-top-row { display: flex; align-items: center; justify-content: space-between; }
.chord-toolbar { padding: 8px 16px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; gap: 12px; flex-shrink: 0; }
.left-controls, .mode-switch-group, .filter-slider-group, .step-buttons, .hud-pair-row { display: flex; align-items: center; gap: 8px; }
.left-controls { gap: 16px; }
.step-buttons { gap: 3px; }
.toolbar-label { font-size: 0.75rem; font-weight: 700; color: #475569; }
.segmented-pill { display: flex; background: #e2e8f0; padding: 2px; border-radius: 6px; }
.seg-item { background: transparent; border: none; padding: 3px 10px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; color: #475569; cursor: pointer; }
.seg-item.active { background: #ffffff; color: #2563eb; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08); }
.step-btn { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; padding: 1px 6px; font-size: 0.68rem; font-weight: 600; color: #475569; cursor: pointer; }
.step-btn:hover { background: #f1f5f9; }
.step-btn.active { background: #2563eb; color: #ffffff; border-color: #2563eb; }
.mini-range { width: 80px; cursor: pointer; }
.threshold-tag, .hud-code, .pair-tag, .hud-stat-val, .card-short-tag { font-family: 'JetBrains Mono', ui-monospace, monospace; }
.threshold-tag { font-size: 0.7rem; font-weight: 700; color: #2563eb; }
.status-summary-pill { font-size: 0.7rem; color: #64748b; background: #f1f5f9; padding: 3px 10px; border-radius: 6px; }
.status-summary-pill strong { color: #0f172a; }
.chord-main-layout { display: flex; flex: 1; min-height: 0; overflow: hidden; }
.chord-svg-viewport { flex: 1; min-width: 0; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 10px; background: #ffffff; }
.chord-main-svg { width: 100%; height: 100%; max-width: 580px; max-height: 580px; display: block; }
.chord-ribbon { fill-opacity: 0.55; transition: fill-opacity 0.2s, stroke 0.2s; cursor: pointer; }
.chord-ribbon:hover, .chord-ribbon.active { fill-opacity: 0.9; stroke: #0f172a; stroke-width: 1px; }
.chord-ribbon.faded { fill-opacity: 0.04; }
.chord-arc-group { cursor: pointer; }
.chord-arc-group:hover .arc-path { filter: brightness(1.15); }
.arc-label { font-size: 8.5px; font-family: 'JetBrains Mono', ui-monospace, monospace; fill: #334155; font-weight: 700; pointer-events: none; }
.arc-label.func-label { font-weight: 800; fill: #0f172a; font-size: 9px; }
.chord-legend-sidebar { width: 280px; background: #f8fafc; border-left: 1px solid #e2e8f0; display: flex; flex-direction: column; flex-shrink: 0; height: 100%; overflow: hidden; }
.inspector-hud-panel { background: #ffffff; border-bottom: 1px solid #e2e8f0; padding: 10px 12px; display: flex; flex-direction: column; gap: 5px; height: 116px; box-sizing: border-box; justify-content: center; flex-shrink: 0; }
.hud-badge { font-size: 0.62rem; font-weight: 700; padding: 1px 6px; border-radius: 4px; }
.hud-badge.sample { background: #eff6ff; color: #2563eb; }
.hud-badge.func { background: #f0fdf4; color: #16a34a; }
.hud-badge.ribbon { background: #faf5ff; color: #9333ea; }
.hud-badge.overview { background: #f1f5f9; color: #475569; }
.hud-code { font-size: 0.75rem; font-weight: 700; color: #2563eb; }
.hud-name { font-size: 0.74rem; font-weight: 700; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hud-pair-row { gap: 4px; font-size: 0.72rem; font-weight: 700; color: #0f172a; }
.pair-tag { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; }
.pair-arrow { color: #94a3b8; }
.hud-stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; background: #f8fafc; border-radius: 4px; padding: 4px 8px; }
.hud-stat-cell { display: flex; flex-direction: column; }
.hud-stat-lbl { font-size: 0.58rem; color: #64748b; }
.hud-stat-val { font-size: 0.8rem; color: #0f172a; }
.hud-stat-val.highlight { color: #2563eb; }
.hud-stat-val.c-amber { color: #d97706; }
.hud-default-txt { font-size: 0.68rem; color: #64748b; line-height: 1.4; }
.legend-sidebar-head { padding: 6px 12px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; flex-shrink: 0; }
.sidebar-title { font-size: 0.72rem; font-weight: 700; color: #1e293b; }
.sidebar-count { font-size: 0.65rem; font-weight: 600; background: #eff6ff; color: #2563eb; padding: 1px 5px; border-radius: 4px; }
.legend-search-box { padding: 5px 10px; background: #ffffff; border-bottom: 1px solid #f1f5f9; flex-shrink: 0; }
.legend-search-input { width: 100%; padding: 3px 6px; font-size: 0.7rem; border-radius: 4px; }
.legend-scroll-wrap { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; scrollbar-color: var(--scrollbar-thumb) transparent; scrollbar-width: thin; }
@supports not (scrollbar-color: auto) {
  .legend-scroll-wrap { scrollbar-width: auto; }
  .legend-scroll-wrap::-webkit-scrollbar { width: 6px; }
  .legend-scroll-wrap::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 4px; }
}
.legend-section-title { font-size: 0.65rem; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 2px; flex-shrink: 0; }
.mt-section { margin-top: 10px; }
.func-legend-grid { display: flex; flex-direction: column; gap: 3px; flex-shrink: 0; }
.func-legend-chip { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; font-size: 0.68rem; color: #334155; cursor: pointer; flex-shrink: 0; min-height: 24px; }
.func-legend-chip:hover, .func-legend-chip.active { background: #f1f5f9; border-color: #94a3b8; font-weight: 600; }
.func-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.func-lbl, .card-fullname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.legend-sample-card { display: flex; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; cursor: pointer; flex-shrink: 0; min-height: 46px; }
.legend-sample-card:hover, .legend-sample-card.active { border-color: #2563eb; background: #eff6ff; transform: translateX(-1px); }
.card-left-bar { width: 4px; flex-shrink: 0; }
.card-content { flex: 1; padding: 4px 8px; display: flex; flex-direction: column; justify-content: center; gap: 2px; min-width: 0; }
.card-short-tag { font-size: 0.72rem; font-weight: 700; }
.card-genes-badge { font-size: 0.62rem; color: #64748b; font-weight: 600; }
.card-fullname { font-size: 0.66rem; color: #475569; line-height: 1.2; }
</style>
