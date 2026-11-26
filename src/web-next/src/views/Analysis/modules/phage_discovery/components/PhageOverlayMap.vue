<script setup lang="ts">
/**
 * PhageOverlayMap.vue - 目标基因组底图与前噬菌体预测叠图工作台
 * 视口缩放、线性/环形 SVG 投影与交互逻辑已抽离至 overlay/usePhageOverlayMap.ts，样式已抽离至 overlay/phageOverlayMap.css
 */
import {
  usePhageOverlayMap,
  type PhageOverlayMapProps,
} from './overlay/usePhageOverlayMap'

const props = defineProps<PhageOverlayMapProps>()

const emit = defineEmits<{
  (e: 'update:selectedContigId', contigId: string): void
  (e: 'select-region', region: import('../types').PhageRegionItem): void
  (e: 'open-overlay-viewer', contigId: string): void
  (e: 'open-region-viewer', regionIndex: number): void
  (e: 'open-annotation', regionIndex?: number): void
}>()

const {
  viewMode,
  showBaseFeatures,
  showScoreCurve,
  showGcTrack,
  showGcSkew,
  showRejected,
  featureSearch,
  searchCursor,
  inspectedFeature,
  onFeatureSearchKeydown,
  hoverTip,
  viewStartBp,
  viewEndBp,
  circScale,
  circPanX,
  circPanY,
  svgCanvasRef,
  totalLenBp,
  avgGcPct,
  allRegions,
  allRejected,
  allBaseFeatures,
  allScoreBins,
  allBaseBins,
  isGenbankSource,
  hasIntegraseOrTransposase,
  hasRnaFeatures,
  baseLayerLabel,
  searchPlaceholder,
  activeRegion,
  matchedFeatureIndices,
  matchedFeatureList,
  jumpToMatchedFeature,
  focusInterval,
  focusRegion,
  resetView,
  zoomLinear,
  zoomCircular,
  linearZoomFactor,
  getBaseFeatureColor,
  linX,
  linearTicks,
  visibleLinearFeatures,
  visibleLinearRegions,
  visibleLinearRejected,
  linearScoreGeometry,
  linearBaseGeometry,
  circularTicks,
  circularBaseFeatures,
  circularRegions,
  circularRejected,
  circularScoreRingPath,
  circularGcRingPath,
  circularSkewRingPath,
  onCanvasWheel,
  onCanvasMouseDown,
  onCanvasMouseMove,
  onCanvasMouseUp,
  showFeatureTip,
  showRegionTip,
  hideHoverTip,
  selectFeatureItem,
  exportSvgSnapshot,
  minimapIndicator,
  onMinimapClick,
  LIN_W,
  LIN_H,
  LIN_PAD_L,
  LIN_PAD_R,
  LIN_PLOT_W,
  CIRC_W,
  CIRC_H,
  CIRC_CX,
  CIRC_CY,
  formatBpAxis,
} = usePhageOverlayMap(props, emit)
</script>

<template>
  <div class="overlay-card">
    <!-- 顶部标题栏与 Contig 切换 -->
    <div class="overlay-header">
      <div class="title-col">
        <div class="title-line">
          <h4>目标基因组底图与前噬菌体预测叠图工作台</h4>
          <span v-if="overlayData" class="fmt-tag">
            {{ overlayData.source_format === 'genbank' ? 'GenBank 原生注解底图' : 'FASTA + Pyrodigal 底图' }}
          </span>
          <span v-if="overlayData" class="stat-pill">
            {{ allBaseFeatures.length.toLocaleString() }} 底图特征 / {{ allRegions.length }} 预测噬菌体区
          </span>
        </div>
        <span class="sub-desc">
          支持滚轮缩放与拖拽漫游，点击前噬菌体区段或底图基因可精细对齐定位，并支持导出完整叠图至 GenomeViewer
        </span>
      </div>

      <div class="header-controls">
        <select
          :value="selectedContigId"
          class="contig-select"
          @change="emit('update:selectedContigId', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="c in contigs" :key="c.id" :value="c.id">
            {{ c.id }} ({{ formatBpAxis(c.length) }}, 命中 {{ c.hit_count }})
          </option>
        </select>

        <div class="mode-switch">
          <button
            type="button"
            class="mode-btn"
            :class="{ active: viewMode === 'linear' }"
            @click="viewMode = 'linear'"
          >
            线性展开叠图
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: viewMode === 'circular' }"
            @click="viewMode = 'circular'"
          >
            环形全长叠图
          </button>
        </div>
      </div>
    </div>

    <!-- 交互式图层控制、视口缩放与底图特征检索条 -->
    <div class="toolbar-row">
      <div class="layer-toggles">
        <label class="layer-chip" :class="{ on: showBaseFeatures }">
          <input v-model="showBaseFeatures" type="checkbox" />
          <span>{{ baseLayerLabel }}</span>
        </label>
        <label class="layer-chip" :class="{ on: showScoreCurve }">
          <input v-model="showScoreCurve" type="checkbox" />
          <span>模型概率曲线</span>
        </label>
        <label class="layer-chip" :class="{ on: showGcTrack }">
          <input v-model="showGcTrack" type="checkbox" />
          <span>GC% 偏移</span>
        </label>
        <label class="layer-chip" :class="{ on: showGcSkew }">
          <input v-model="showGcSkew" type="checkbox" />
          <span>GC Skew</span>
        </label>
        <label v-if="allRejected.length > 0" class="layer-chip warn" :class="{ on: showRejected }">
          <input v-model="showRejected" type="checkbox" />
          <span>门控过滤 ({{ allRejected.length }})</span>
        </label>
      </div>

      <div class="zoom-search-group">
        <div class="search-box">
          <input
            v-model="featureSearch"
            type="text"
            class="feat-search-input"
            :placeholder="searchPlaceholder"
            @keydown="onFeatureSearchKeydown"
          />
          <template v-if="matchedFeatureList.length > 0">
            <span class="match-count">{{ (searchCursor % matchedFeatureList.length) + 1 }}/{{ matchedFeatureList.length }}</span>
            <button type="button" class="mini-step-btn" title="上一个匹配基因" @click="jumpToMatchedFeature(-1)">&lt;</button>
            <button type="button" class="mini-step-btn" title="下一个匹配基因" @click="jumpToMatchedFeature(1)">&gt;</button>
          </template>
        </div>

        <div class="zoom-btns">
          <button
            type="button"
            class="tool-btn"
            title="放大"
            @click="viewMode === 'linear' ? zoomLinear(1.6) : zoomCircular(1.3)"
          >
            +
          </button>
          <button
            type="button"
            class="tool-btn"
            title="缩小"
            @click="viewMode === 'linear' ? zoomLinear(1 / 1.6) : zoomCircular(1 / 1.3)"
          >
            -
          </button>
          <button type="button" class="tool-btn wide" @click="resetView">
            重置 {{ viewMode === 'linear' ? `${linearZoomFactor.toFixed(1)}x` : `${circScale.toFixed(1)}x` }}
          </button>
          <button type="button" class="tool-btn wide" @click="exportSvgSnapshot">导出 SVG</button>
          <button
            type="button"
            class="viewer-launch-btn"
            :disabled="!overlayData"
            @click="overlayData && emit('open-overlay-viewer', overlayData.contig_id)"
          >
            在 GenomeViewer 打开全长叠图
          </button>
        </div>
      </div>
    </div>

    <!-- 主 SVG 交互绘布 -->
    <div v-if="isLoading" class="overlay-loading">正在组装全序列底图与预测叠图轨道...</div>

    <div
      v-else-if="overlayData"
      class="canvas-frame"
      @mouseleave="hideHoverTip"
      @mouseup="onCanvasMouseUp"
    >
      <!-- 图例说明栏 -->
      <div class="legend-strip">
        <span class="lg-item"><i class="sw prophage"></i>预测噬菌体区段</span>
        <span class="lg-item"><i class="sw cds-in"></i>{{ isGenbankSource ? '区段内基因' : '区段内 ORF' }}</span>
        <span class="lg-item"><i class="sw cds-host"></i>{{ isGenbankSource ? '宿主基因' : '宿主 ORF' }}</span>
        <span v-if="hasIntegraseOrTransposase" class="lg-item"><i class="sw integrase"></i>整合酶 / 转座酶</span>
        <span v-if="hasRnaFeatures" class="lg-item"><i class="sw trna"></i>tRNA / rRNA</span>
        <span v-if="featureSearch.trim()" class="lg-item"><i class="sw match"></i>检索命中高亮</span>
        <span class="viewport-range">
          当前视口: {{ (viewStartBp + 1).toLocaleString() }} - {{ viewEndBp.toLocaleString() }} bp
          (跨度 {{ formatBpAxis(viewEndBp - viewStartBp) }})
        </span>
      </div>

      <!-- 模式 A：线性多轨道对齐叠图 -->
      <svg
        v-if="viewMode === 'linear'"
        ref="svgCanvasRef"
        :viewBox="`0 0 ${LIN_W} ${LIN_H}`"
        class="overlay-svg linear-svg"
        @wheel.prevent="onCanvasWheel"
        @mousedown="onCanvasMouseDown"
        @mousemove="onCanvasMouseMove"
      >
        <!-- 轨道标题标签 (左侧固定列) -->
        <text x="6" y="34" class="track-label">坐标轴</text>
        <text x="6" y="90" class="track-label">+ 链特征</text>
        <text x="6" y="122" class="track-label">- 链特征</text>
        <text x="6" y="194" class="track-label">预测分数</text>
        <text x="6" y="274" class="track-label">GC% 偏移</text>
        <text x="6" y="328" class="track-label">GC Skew</text>

        <!-- 背景分隔网格 -->
        <line :x1="LIN_PAD_L" y1="42" :x2="LIN_W - LIN_PAD_R" y2="42" stroke="#cbd5e1" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="102" :x2="LIN_W - LIN_PAD_R" y2="102" stroke="#e2e8f0" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="142" :x2="LIN_W - LIN_PAD_R" y2="142" stroke="#e2e8f0" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="228" :x2="LIN_W - LIN_PAD_R" y2="228" stroke="#cbd5e1" stroke-width="1" />
        <line :x1="LIN_PAD_L" y1="272" :x2="LIN_W - LIN_PAD_R" y2="272" stroke="#e2e8f0" stroke-dasharray="3 3" />
        <line :x1="LIN_PAD_L" y1="326" :x2="LIN_W - LIN_PAD_R" y2="326" stroke="#e2e8f0" stroke-dasharray="3 3" />

        <!-- 垂直刻度线与坐标标尺 -->
        <g v-for="tk in linearTicks" :key="tk.bp">
          <line :x1="tk.x" y1="42" :x2="tk.x" y2="352" stroke="#f1f5f9" stroke-width="1" />
          <line :x1="tk.x" y1="36" :x2="tk.x" y2="42" stroke="#64748b" stroke-width="1.2" />
          <text :x="tk.x" y="29" text-anchor="middle" class="tick-label">{{ tk.label }}</text>
        </g>

        <!-- 1. 门控拒绝候选叠图 (虚线对照带) -->
        <g v-for="item in visibleLinearRejected" :key="`rej_${item.idx}`">
          <rect
            :x="item.x1"
            y="50"
            :width="item.w"
            height="178"
            fill="#f59e0b"
            fill-opacity="0.08"
            stroke="#d97706"
            stroke-width="1.2"
            stroke-dasharray="4 3"
            rx="3"
          />
        </g>

        <!-- 2. 预测噬菌体/前噬菌体贯穿包络叠图帯 (置于底层半透明以免遮挡基因箭头交互) -->
        <g
          v-for="item in visibleLinearRegions"
          :key="`lreg_${item.reg.index}`"
          class="clickable-group"
          @click.stop="focusRegion(item.reg)"
          @mouseenter="showRegionTip($event, item.reg)"
          @mouseleave="hideHoverTip"
        >
          <rect
            :x="item.x1"
            y="46"
            :width="item.w"
            height="182"
            :fill="item.active ? '#2563eb' : '#0ea5e9'"
            :fill-opacity="item.active ? 0.14 : 0.09"
            :stroke="item.active ? '#1d4ed8' : '#0284c7'"
            :stroke-width="item.active ? 1.8 : 1"
            rx="4"
          />
          <rect
            :data-region-badge="item.reg.region_id"
            :x="item.x1"
            y="46"
            :width="Math.max(item.w, item.reg.region_id.length * 6.8 + 12)"
            height="16"
            rx="3"
            :fill="item.active ? '#1d4ed8' : '#0284c7'"
          />
          <text
            :x="item.x1 + 5"
            y="57.5"
            class="region-badge-text"
          >
            {{ item.reg.region_id }}
          </text>
        </g>

        <!-- 3. 输入序列底图特征 (+/- 链基因箭头) -->
        <g v-if="showBaseFeatures">
          <path
            v-for="item in visibleLinearFeatures"
            :key="`lf_${item.feat.index}`"
            :d="item.pathD"
            :fill="item.color"
            :fill-opacity="item.opacity"
            :stroke="inspectedFeature?.index === item.feat.index ? '#0f172a' : (item.isMatched ? '#a16207' : 'none')"
            :stroke-width="inspectedFeature?.index === item.feat.index || item.isMatched ? 1.4 : 0"
            class="clickable-group"
            @click.stop="selectFeatureItem(item.feat)"
            @mouseenter="showFeatureTip($event, item.feat)"
            @mouseleave="hideHoverTip"
          />
        </g>

        <!-- 4. V4.2 连续概率景观轨迹 -->
        <g v-if="linearScoreGeometry">
          <line
            :x1="LIN_PAD_L"
            :y1="linearScoreGeometry.yHalf"
            :x2="LIN_W - LIN_PAD_R"
            :y2="linearScoreGeometry.yHalf"
            stroke="#f59e0b"
            stroke-width="1"
            stroke-dasharray="4 4"
          />
          <path :d="linearScoreGeometry.areaD" fill="#2563eb" fill-opacity="0.16" />
          <polyline
            :points="linearScoreGeometry.polylineMax"
            fill="none"
            stroke="#2563eb"
            stroke-width="1.8"
            stroke-linejoin="round"
          />
          <polyline
            :points="linearScoreGeometry.polylineMean"
            fill="none"
            stroke="#0d9488"
            stroke-width="1.2"
            stroke-dasharray="3 2"
          />
        </g>

        <!-- 5. GC% 偏移与 GC Skew 底图波形 -->
        <g v-if="linearBaseGeometry">
          <template v-if="showGcTrack">
            <path :d="linearBaseGeometry.gcAreaD" fill="#10b981" fill-opacity="0.16" />
            <polyline
              :points="linearBaseGeometry.gcPolyline"
              fill="none"
              stroke="#059669"
              stroke-width="1.4"
            />
          </template>
          <template v-if="showGcSkew">
            <path :d="linearBaseGeometry.skewAreaD" fill="#8b5cf6" fill-opacity="0.16" />
            <polyline
              :points="linearBaseGeometry.skewPolyline"
              fill="none"
              stroke="#7c3aed"
              stroke-width="1.3"
            />
          </template>
        </g>
      </svg>

      <!-- 模式 B：环形全长叠图 -->
      <svg
        v-else
        ref="svgCanvasRef"
        :viewBox="`0 0 ${CIRC_W} ${CIRC_H}`"
        class="overlay-svg circular-svg"
        @wheel.prevent="onCanvasWheel"
        @mousedown="onCanvasMouseDown"
        @mousemove="onCanvasMouseMove"
      >
        <g :transform="`translate(${CIRC_CX + circPanX}, ${CIRC_CY + circPanY}) scale(${circScale})`">
          <!-- 参考底圆 -->
          <circle cx="0" cy="0" r="208" fill="none" stroke="#cbd5e1" stroke-width="1.2" />
          <circle cx="0" cy="0" r="184" fill="none" stroke="#e2e8f0" stroke-width="0.8" />
          <circle cx="0" cy="0" r="164" fill="none" stroke="#e2e8f0" stroke-width="0.8" />
          <circle cx="0" cy="0" r="142" fill="none" stroke="#fde68a" stroke-width="0.8" stroke-dasharray="3 3" />
          <circle cx="0" cy="0" r="128" fill="none" stroke="#cbd5e1" stroke-width="0.8" />
          <circle cx="0" cy="0" r="104" fill="none" stroke="#d1fae5" stroke-width="0.8" stroke-dasharray="2 3" />
          <circle cx="0" cy="0" r="78" fill="none" stroke="#ede9fe" stroke-width="0.8" stroke-dasharray="2 3" />

          <!-- 外围刻度 -->
          <g v-for="tk in circularTicks" :key="tk.label">
            <line :x1="tk.x1" :y1="tk.y1" :x2="tk.x2" :y2="tk.y2" stroke="#64748b" stroke-width="1.2" />
            <text :x="tk.tx" :y="tk.ty" :text-anchor="tk.anchor" dominant-baseline="middle" class="tick-label">
              {{ tk.label }}
            </text>
          </g>

          <!-- 内环 GC Skew & GC% & V4.2 景观环 -->
          <path v-if="circularSkewRingPath" :d="circularSkewRingPath" fill="#8b5cf6" fill-opacity="0.14" stroke="#7c3aed" stroke-width="1.2" />
          <path v-if="circularGcRingPath" :d="circularGcRingPath" fill="#10b981" fill-opacity="0.14" stroke="#059669" stroke-width="1.3" />
          <path v-if="circularScoreRingPath" :d="circularScoreRingPath" fill="#3b82f6" fill-opacity="0.18" stroke="#2563eb" stroke-width="1.5" />

          <!-- 预测前噬菌体环形包络高亮带 -->
          <g
            v-for="item in circularRegions"
            :key="`creg_${item.reg.index}`"
            class="clickable-group"
            @click.stop="focusRegion(item.reg)"
            @mouseenter="showRegionTip($event, item.reg)"
            @mouseleave="hideHoverTip"
          >
            <path
              :d="item.d"
              :fill="item.active ? '#2563eb' : '#0ea5e9'"
              :fill-opacity="item.active ? 0.22 : 0.14"
              :stroke="item.active ? '#1e3a8a' : '#0284c7'"
              :stroke-width="item.active ? 1.8 : 1.1"
            />
            <path :d="item.lineD" stroke="#0284c7" stroke-width="1" />
            <text
              :x="item.tx"
              :y="item.ty"
              :text-anchor="item.anchor"
              dominant-baseline="middle"
              class="circ-region-label"
            >
              {{ item.reg.region_id }}
            </text>
          </g>

          <!-- 门控拦截对照弧 -->
          <path
            v-for="rej in circularRejected"
            :key="`crej_${rej.idx}`"
            :d="rej.d"
            fill="#f59e0b"
            fill-opacity="0.1"
            stroke="#d97706"
            stroke-width="1"
            stroke-dasharray="3 2"
          />

          <!-- 底图正/负链特征弧 -->
          <path
            v-for="item in circularBaseFeatures"
            :key="`cbf_${item.feat.index}`"
            :d="item.d"
            :fill="item.color"
            :fill-opacity="item.isMatched || item.feat.in_prophage ? 0.95 : 0.72"
            :stroke="inspectedFeature?.index === item.feat.index ? '#0f172a' : 'none'"
            stroke-width="1.2"
            class="clickable-group"
            @click.stop="selectFeatureItem(item.feat)"
            @mouseenter="showFeatureTip($event, item.feat)"
            @mouseleave="hideHoverTip"
          />

          <!-- 中央信息摘要 -->
          <text x="0" y="-12" text-anchor="middle" class="circ-center-title">{{ overlayData.contig_id }}</text>
          <text x="0" y="6" text-anchor="middle" class="circ-center-sub">{{ overlayData.length_bp.toLocaleString() }} bp</text>
          <text x="0" y="22" text-anchor="middle" class="circ-center-sub">GC {{ overlayData.gc_percent }}% | {{ allRegions.length }} Prophage</text>
        </g>
      </svg>

      <!-- 线性全基因组俯瞰缩略条 (Minimap 快速跳转) -->
      <div v-if="viewMode === 'linear'" class="minimap-bar" title="点击任意位置快速跳转视口" @click="onMinimapClick">
        <div class="minimap-base-line"></div>
        <div
          v-for="r in allRegions"
          :key="`mm_${r.index}`"
          class="minimap-hit"
          :class="{ active: r.index === selectedRegionIndex }"
          :style="{
            left: `${(r.start_bp / totalLenBp) * 100}%`,
            width: `${Math.max(0.8, ((r.end_bp - r.start_bp) / totalLenBp) * 100)}%`,
          }"
        ></div>
        <div class="minimap-viewport" :style="minimapIndicator"></div>
      </div>

      <!-- 悬浮详情框 -->
      <div
        v-if="hoverTip.visible"
        class="hover-tooltip"
        :style="{ left: `${hoverTip.x}px`, top: `${hoverTip.y}px`, borderLeftColor: hoverTip.accent }"
      >
        <div class="ht-title">{{ hoverTip.title }}</div>
        <div class="ht-sub">{{ hoverTip.subtitle }}</div>
        <div class="ht-meta">{{ hoverTip.meta }}</div>
      </div>
    </div>

    <!-- 底部交互检查栏 (选中特征 + 一键区域聚焦条) -->
    <div v-if="overlayData" class="inspector-footer">
      <div v-if="inspectedFeature" class="feature-inspector">
        <span class="fi-badge">{{ inspectedFeature.type }}</span>
        <strong class="fi-name">
          {{ inspectedFeature.gene ? `${inspectedFeature.gene} / ` : '' }}{{ inspectedFeature.locus_tag || `Feature_${inspectedFeature.index}` }}
        </strong>
        <span class="fi-pos">
          {{ (inspectedFeature.start_bp + 1).toLocaleString() }}..{{ inspectedFeature.end_bp.toLocaleString() }} bp
          ({{ inspectedFeature.strand >= 0 ? '+链' : '-链' }})
        </span>
        <span class="fi-prod">{{ inspectedFeature.product }}</span>
        <span v-if="inspectedFeature.overlay_region_id" class="fi-in-phage">
          位于预测区段 {{ inspectedFeature.overlay_region_id }}
        </span>
        <button
          type="button"
          class="fi-focus-btn"
          @click="focusInterval(inspectedFeature.start_bp, inspectedFeature.end_bp, 4000)"
        >
          聚焦该基因 (+/-4kb)
        </button>
      </div>

      <div v-else class="region-pills-bar">
        <span class="pills-title">快速聚焦前噬菌体区段:</span>
        <span v-if="allRegions.length === 0" class="no-hits-note">当前 Contig 未检出高置信度前噬菌体整合区域</span>
        <button
          v-for="reg in allRegions"
          :key="`pill_${reg.index}`"
          type="button"
          class="region-pill"
          :class="{ active: reg.index === selectedRegionIndex }"
          @click="focusRegion(reg)"
        >
          {{ reg.region_id }} ({{ formatBpAxis(reg.start_bp) }} - {{ formatBpAxis(reg.end_bp) }})
        </button>
        <div v-if="activeRegion" class="pills-actions">
          <button
            type="button"
            class="pill-action-btn viewer"
            data-testid="active-region-viewer-btn"
            @click="emit('open-region-viewer', activeRegion.index)"
          >
            查看 {{ activeRegion.region_id }} 图谱
          </button>
          <button
            type="button"
            class="pill-action-btn anno"
            data-testid="active-region-anno-btn"
            @click="emit('open-annotation', activeRegion.index)"
          >
            注释 {{ activeRegion.region_id }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import './overlay/phageOverlayMap.css';
</style>
