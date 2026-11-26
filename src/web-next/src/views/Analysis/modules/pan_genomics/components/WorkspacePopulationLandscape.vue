<script setup lang="ts">
/**
 * WorkspacePopulationLandscape.vue - 旗舰组合图 1: Phylogenomic Evidence Matrix
 * 核心状态、聚类与导出逻辑已抽离至 landscape/usePopulationLandscape.ts，样式已抽离至 landscape/populationLandscape.css
 */
import { FUNCTIONAL_CATEGORIES } from '../../viewer/utils/render'
import { getCatColor, getCategoryChinese } from '../utils/pangenomeVariants'
import PhylogenyTreeSvg from './subcomponents/PhylogenyTreeSvg.vue'
import SampleFilterPopover from './subcomponents/SampleFilterPopover.vue'
import GeneClusterDetailDrawer from './subcomponents/GeneClusterDetailDrawer.vue'
import PanGenomicsChordDiagram from './subcomponents/PanGenomicsChordDiagram.vue'
import {
  usePopulationLandscape,
  type PopulationLandscapeProps,
} from './landscape/usePopulationLandscape'

const props = defineProps<PopulationLandscapeProps>()

const emit = defineEmits<{
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
}>()

const {
  viewMode,
  handleSelectSample,
  handleSelectPair,
  hoveredGeneCluster,
  selectedGeneCluster,
  geneCategoryFilter,
  genePartitionFilter,
  crosshairVisible,
  crosshairLeft,
  crosshairWidth,
  handleClusterMouseEnter,
  handleClusterMouseLeave,
  isLegendCollapsed,
  isPhylogenyTrackVisible,
  isMetadataTrackVisible,
  isAniTrackVisible,
  isGeneMatrixTrackVisible,
  displayDensity,
  allSampleIdList,
  currentMatrixMode,
  cdsMatrixData,
  cdsClustering,
  activeClustering,
  activeSimilarityMatrix,
  sampleSortOrder,
  rawClusteredIds,
  orderedSampleIds,
  hiddenSampleIds,
  isSampleFilterOpen,
  visibleSampleIds,
  toggleSampleVisibility,
  showAllSamples,
  clearAllSamples,
  focusOnlyPair,
  focusOnlySingle,
  invertSampleSelection,
  openClusterDrawer,
  rowHeight,
  sampleAnnotations,
  sortedGeneClusters,
  pangenomePartition,
  getActiveCellValue,
  getAniCellColor,
  getAniTextColor,
  formatAniDisplay,
  getAniCellTitle,
  handleCellClick,
  isCurrentPair,
  isExporting,
  handleExportFigure,
} = usePopulationLandscape(props, emit)
</script>

<template>
  <div class="workspace-population-landscape" :class="['density-' + displayDensity]">
    <!-- 顶刊旗舰组合图: Phylogenomic Evidence Matrix -->
    <div class="academic-panel flagship-matrix-panel">
      <!-- 1. 顶层主标题与全局视图控制带 -->
      <div class="panel-header-deck">
        <div class="deck-title-area">
          <div class="title-main-row">
            <span class="panel-tag-pill">Figure 1</span>
            <h3 class="panel-heading-text">系统发育与泛基因组同源矩阵</h3>
            <span class="matrix-scope-badge">
              {{ visibleSampleIds.length }} 株系 (共 {{ orderedSampleIds.length }}) · {{ sortedGeneClusters.length }} 基因家族
            </span>
          </div>

          <!-- 样本可见性工具条 -->
          <div class="sample-visibility-toolbar">
            <div class="sample-count-pill" :class="{ 'has-hidden': hiddenSampleIds.size > 0 }">
              <span>显示 <strong>{{ visibleSampleIds.length }}</strong>/{{ orderedSampleIds.length }}</span>
              <span v-if="hiddenSampleIds.size > 0" class="hidden-badge">已隐藏 {{ hiddenSampleIds.size }}</span>
            </div>

            <div class="sample-filter-btn-group">
              <button
                v-if="hiddenSampleIds.size > 0"
                class="btn-sample-action btn-show-all"
                @click="showAllSamples"
                title="恢复显示全部样本"
              >
                全部显示
              </button>

              <button
                v-if="selectedPair && visibleSampleIds.length > 2"
                class="btn-sample-action btn-focus-pair"
                @click="focusOnlyPair"
                title="仅保留当前选中的 2 株对比样本"
              >
                仅看当前对
              </button>

              <!-- 独立样本筛选浮层 -->
              <SampleFilterPopover
                v-model:isOpen="isSampleFilterOpen"
                :ordered-sample-ids="orderedSampleIds"
                :hidden-sample-ids="hiddenSampleIds"
                :sample-names="sampleNames"
                :selected-pair="selectedPair"
                @toggle-sample="toggleSampleVisibility"
                @show-all="showAllSamples"
                @clear-all="clearAllSamples"
                @invert-selection="invertSampleSelection"
                @focus-pair="focusOnlyPair"
                @focus-single="focusOnlySingle"
              />
            </div>
          </div>
        </div>

        <div class="deck-actions-area">
          <!-- 视图模式控制器 (同源矩阵 vs 拓扑弦图) -->
          <div class="segmented-density-control">
            <span class="control-label">视图:</span>
            <div class="seg-pills">
              <button
                class="seg-btn"
                :class="{ active: viewMode === 'matrix' }"
                @click="viewMode = 'matrix'"
                title="同源矩阵视图 (全基因组同源基因家族分布与序列变异)"
              >
                同源矩阵
              </button>
              <button
                class="seg-btn"
                :class="{ active: viewMode === 'chord' }"
                @click="viewMode = 'chord'"
                title="拓扑弦图 (展示样本间同源基因共享关联与分布)"
              >
                拓扑弦图
              </button>
            </div>
          </div>

          <!-- 排序分段控制器 -->
          <div class="segmented-density-control">
            <span class="control-label">排序:</span>
            <div class="seg-pills">
              <button
                class="seg-btn"
                :class="{ active: sampleSortOrder === 'natural' }"
                @click="sampleSortOrder = 'natural'"
                title="按样本名称与编号自然递增排列 (BC01, BC02...)"
              >
                自然顺序
              </button>
              <button
                class="seg-btn"
                :class="{ active: sampleSortOrder === 'cluster' }"
                @click="sampleSortOrder = 'cluster'"
                :title="currentMatrixMode === 'cds_jaccard' ? '按 CDS 直系同源基因分布谱聚类排列 (依据基因家族存在/缺失聚类)' : '按全基因组 ANI 核酸亲缘进化树聚类排列'"
              >
                进化聚类{{ currentMatrixMode === 'cds_jaccard' ? ' (CDS)' : ' (ANI)' }}
              </button>
            </div>
          </div>

          <!-- 密度分段控制器 -->
          <div class="segmented-density-control">
            <span class="control-label">密度:</span>
            <div class="seg-pills">
              <button
                class="seg-btn btn-spacious"
                :class="{ active: displayDensity === 'spacious' }"
                @click="displayDensity = 'spacious'"
                title="宽松模式 (行高 36px，适合 2~12 株小样本精细观察)"
              >
                宽松
              </button>
              <button
                class="seg-btn"
                :class="{ active: displayDensity === 'comfortable' }"
                @click="displayDensity = 'comfortable'"
                title="舒适模式 (行高 24px，适合 12~25 株)"
              >
                舒适
              </button>
              <button
                class="seg-btn"
                :class="{ active: displayDensity === 'compact' }"
                @click="displayDensity = 'compact'"
                title="紧凑模式 (行高 17px，适合 25~45 株)"
              >
                紧凑
              </button>
              <button
                class="seg-btn btn-ultra"
                :class="{ active: displayDensity === 'ultra' }"
                @click="displayDensity = 'ultra'"
                title="微缩模式 (行高 11px，适合 45~100+ 株)"
              >
                微缩 (50+)
              </button>
            </div>
          </div>

          <!-- 图注收折按钮 -->
          <button
            class="btn-legend-toggle"
            :class="{ active: !isLegendCollapsed }"
            @click="isLegendCollapsed = !isLegendCollapsed"
            :title="isLegendCollapsed ? '展开图注' : '收起图注'"
          >
            <svg class="legend-icon" viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </svg>
            {{ isLegendCollapsed ? '展开图注' : '收起图注' }}
          </button>

          <!-- 整体完整导出图表按钮组 -->
          <div class="export-figure-group">
            <button
              class="btn-export-fig"
              :disabled="isExporting"
              @click="handleExportFigure('png')"
              title="将当前图表（含系统发育树、全部样本与全量同源基因家族）完整导出为超清科研图 (PNG)"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              {{ isExporting ? '导出中...' : '导出图表 (PNG)' }}
            </button>
            <button
              class="btn-export-fig btn-export-svg"
              :disabled="isExporting"
              @click="handleExportFigure('svg')"
              title="完整导出为无限缩放矢量图 (SVG)"
            >
              SVG
            </button>
          </div>
        </div>
      </div>

      <!-- 2. 统一操作带 (Unified Tool Ribbon) -->
      <div class="matrix-ribbon-bar">
        <!-- 左侧：CDS 分区与功能分类过滤 -->
        <div class="ribbon-left-filters">
          <div class="filter-group">
            <span class="ribbon-group-label">CDS 分区:</span>
            <div class="ribbon-pills">
              <button
                class="r-pill"
                :class="{ active: genePartitionFilter === 'ALL' }"
                @click="genePartitionFilter = 'ALL'"
              >
                全部 ({{ clusters?.length || 0 }})
              </button>
              <button
                class="r-pill r-pill-amber"
                :class="{ active: genePartitionFilter === 'VARIABLE' }"
                @click="genePartitionFilter = 'VARIABLE'"
                title="仅显示存在样本分布差异的可变基因家族"
              >
                差异 ({{ (clusters?.length || 0) - Number(pangenomePartition.core) }})
              </button>
              <button
                class="r-pill r-pill-blue"
                :class="{ active: genePartitionFilter === 'CORE' }"
                @click="genePartitionFilter = 'CORE'"
                title="仅显示全样本共有 (100%) 的核心基因家族"
              >
                核心基因 ({{ pangenomePartition.core }})
              </button>
              <button
                class="r-pill"
                :class="{ active: genePartitionFilter === 'UNIQUE' }"
                @click="genePartitionFilter = 'UNIQUE'"
                title="仅显示仅存在于单一株系的特有基因家族"
              >
                单株特有
              </button>
            </div>
          </div>

          <div class="filter-divider"></div>

          <div class="filter-group">
            <span class="ribbon-group-label">功能:</span>
            <select v-model="geneCategoryFilter" class="modern-select select-cat">
              <option value="ALL">全部功能模块</option>
              <option v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" :value="key">
                {{ cat.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- 右侧：多维轨道显隐开关 -->
        <div class="ribbon-right-tracks">
          <span class="ribbon-group-label">显示轨道:</span>
          <div class="track-check-pills">
            <button
              class="trk-pill"
              :class="{ active: isPhylogenyTrackVisible }"
              @click="isPhylogenyTrackVisible = !isPhylogenyTrackVisible"
              title="显示/隐藏系统发育树轨道"
            >
              <span class="trk-dot"></span> 进化树
            </button>
            <button
              class="trk-pill"
              :class="{ active: isMetadataTrackVisible }"
              @click="isMetadataTrackVisible = !isMetadataTrackVisible"
              title="显示/隐藏样本特征轨道"
            >
              <span class="trk-dot"></span> 样本特征
            </button>
            <button
              class="trk-pill"
              :class="{ active: isAniTrackVisible }"
              @click="isAniTrackVisible = !isAniTrackVisible"
              title="显示/隐藏全基因组 ANI 相似度矩阵"
            >
              <span class="trk-dot"></span> ANI 矩阵
            </button>
            <button
              class="trk-pill"
              :class="{ active: isGeneMatrixTrackVisible }"
              @click="isGeneMatrixTrackVisible = !isGeneMatrixTrackVisible"
              title="显示/隐藏泛基因组同源基因家族矩阵"
            >
              <span class="trk-dot"></span> 基因矩阵
            </button>
          </div>
        </div>
      </div>

      <!-- 3. 精炼学术图注条 (可一键收起/展开) -->
      <div class="academic-legend-deck" v-show="!isLegendCollapsed && viewMode === 'matrix'">
        <div class="leg-col leg-col-function">
          <span class="leg-col-title">CDS 功能分类:</span>
          <div class="leg-items-wrap">
            <span v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" class="leg-chip">
              <i :style="{ background: cat.color }"></i>{{ cat.label.split(' ')[0] }}
            </span>
          </div>
        </div>

        <div class="leg-col leg-col-variation">
          <span class="leg-col-title">变异形态:</span>
          <div class="leg-items-wrap">
            <span class="leg-chip"><span class="swatch-sq sq-legend-conserved"></span>等长保守 (纯色)</span>
            <span class="leg-chip"><span class="swatch-sq sq-legend-truncated"></span>序列截短 (斜纹)</span>
            <span class="leg-chip"><span class="swatch-sq sq-legend-extended"></span>序列延伸 (端标)</span>
            <span class="leg-chip"><span class="swatch-dot" style="background-color: #cbd5e1;"></span>基因缺失</span>
          </div>
        </div>

        <div class="leg-col leg-col-ani" v-if="isAniTrackVisible">
          <!-- 矩阵度量维度切换控制器 (核酸 ANI vs CDS 基因功能谱) -->
          <div class="matrix-metric-switcher">
            <button
              class="btn-metric-toggle"
              :class="{ active: currentMatrixMode === 'ani' }"
              @click="currentMatrixMode = 'ani'"
              title="全基因组平均核苷酸一致性 (DNA 核酸水平 1020bp RBH) - 衡量碱基点突变保守性；在进化聚类模式下将联动核酸系统发育树"
            >
              全基因组 ANI (核酸)
            </button>
            <button
              class="btn-metric-toggle"
              :class="{ active: currentMatrixMode === 'cds_jaccard' }"
              @click="currentMatrixMode = 'cds_jaccard'"
              title="CDS 直系同源基因分布谱一致性 (Jaccard: 共享CDS / 并集CDS) - 衡量同源家族得失；在进化聚类模式下将自动重新聚类"
            >
              CDS 同源基因一致性
            </button>
          </div>

          <div class="ani-heat-swatch-list">
            <span class="heat-chip" style="background-color: #f8fafc; color: #94a3b8; border: 1px solid #e2e8f0;" title="0% 或远缘无显著同源区段">-</span>
            <span class="heat-chip" style="background-color: #eff6ff; color: #1e3a8a;" title="低相似度 (<70%)">&lt;70</span>
            <span class="heat-chip" style="background-color: #bfdbfe; color: #1e3a8a;" title="同属/中度界限 (70% ~ 80%)">70</span>
            <span class="heat-chip" style="background-color: #93c5fd; color: #1e3a8a;" title="中度同源 (80% ~ 90%)">80</span>
            <span class="heat-chip" style="background-color: #60a5fa; color: #ffffff;" title="高度同源 (90% ~ 95%)">90</span>
            <span class="heat-chip" style="background-color: #2563eb; color: #ffffff;" title="同种同源界限 (≥95%)">95</span>
            <span class="heat-chip" style="background-color: #1e3a8a; color: #ffffff;" title="完全一致 (100%)">100</span>
          </div>
        </div>
      </div>

      <!-- 视图 A: 共享样本排序的一体化矩阵画板 -->
      <div v-if="viewMode === 'matrix'" class="phylogenomic-composite-canvas" @mouseleave="handleClusterMouseLeave">
        <!-- 零响应式开销的 GPU 硬件加速十字准星垂直导轨 (平滑悬浮于对应列，0 次 VNode Diff) -->
        <div 
          v-show="crosshairVisible" 
          class="crosshair-vertical-guide"
          :style="{
            left: `${crosshairLeft}px`,
            width: `${crosshairWidth}px`
          }"
        ></div>

        <table class="composite-evidence-table">
          <thead>
            <tr>
              <!-- 1. 进化树列头 (可收起) -->
              <th v-if="isPhylogenyTrackVisible" class="th-tree th-sticky-left-1" title="系统发育拓扑树 (UPGMA 聚类构建)">系统发育</th>
              <!-- 2. 样本名称列头 -->
              <th
                class="th-sample-name"
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                title="样本标识名称"
              >
                样本编号
              </th>
              <!-- 3. 元数据轨道列头 -->
              <template v-if="isMetadataTrackVisible">
                <th class="th-meta" title="生活周期类型 (Lytic 烈性 / Lysogenic 温和溶原)">生活周期</th>
                <th class="th-meta" title="生物安全性评估 (毒力因子与耐药基因筛查)">生物安全</th>
                <th class="th-meta" title="抗 CRISPR 系统 (Anti-CRISPR 蛋白基因数)">抗 CRISPR</th>
              </template>
              <!-- 4. ANI 矩阵列头 -->
              <template v-if="isAniTrackVisible">
                <th
                  v-for="colId in visibleSampleIds"
                  :key="'ani-h-' + colId"
                  class="th-ani-col"
                  :class="{ 'th-active-pair': selectedPair?.includes(colId) }"
                >
                  <div class="th-rot-label" :title="sampleNames[colId]">
                    {{ sampleNames[colId] || colId }}
                  </div>
                </th>
              </template>
              <!-- 5. 基因家族存在/缺失矩阵列头 -->
              <th
                v-if="isGeneMatrixTrackVisible"
                class="th-genefamily-title"
                :colspan="Math.max(1, sortedGeneClusters.length)"
              >
                <div class="gene-matrix-header-bar">
                  <span class="gene-matrix-title-txt">泛基因组直系同源基因矩阵 (共 {{ sortedGeneClusters.length }} 基因家族，按功能着色)</span>
                </div>
              </th>
              <!-- 6. 弹性吸纳列 -->
              <th class="th-elastic-spacer"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(rowId, rIdx) in visibleSampleIds"
              :key="'row-sample-' + rowId"
              class="composite-row"
              :class="{ 'row-pair-selected': selectedPair?.includes(rowId) }"
            >
              <!-- 1. 左侧系统发育拓扑树 (独立子组件渲染) -->
              <td
                v-if="isPhylogenyTrackVisible && rIdx === 0"
                class="td-tree-col th-sticky-left-1"
                :rowspan="visibleSampleIds.length"
              >
                <PhylogenyTreeSvg
                  :visible-sample-ids="visibleSampleIds"
                  :ani-matrix="activeSimilarityMatrix"
                  :row-height="rowHeight"
                  :display-density="displayDensity"
                  :tree-root="activeClustering?.root"
                  :sort-order="sampleSortOrder"
                />
              </td>

              <!-- 2. 样本名称 -->
              <td
                class="td-sample-name-col"
                :class="isPhylogenyTrackVisible ? 'th-sticky-left-2' : 'th-sticky-left-1'"
                :title="sampleNames[rowId]"
              >
                <div class="sample-name-cell-inner">
                  <button
                    class="btn-sample-eye"
                    @click.stop="toggleSampleVisibility(rowId)"
                    title="暂时隐藏该样本"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </button>
                  <span class="sample-title-txt" @click="emit('select-sample', rowId)">
                    {{ sampleNames[rowId] || rowId }}
                  </span>
                </div>
              </td>

              <!-- 3. 样本多维元数据轨道 -->
              <template v-if="isMetadataTrackVisible">
                <td class="td-meta-col">
                  <span
                    :class="['meta-badge', (sampleAnnotations[rowId]?.lifestyle === 'Lytic') ? 'bg-lytic' : 'bg-temperate']"
                    :title="sampleAnnotations[rowId]?.lifestyle === 'Lytic' ? '专性烈性噬菌体' : '检出温和溶源整合元件'"
                  >
                    {{ sampleAnnotations[rowId]?.lifestyle === 'Lytic' ? '烈性' : '温和' }}
                  </span>
                </td>
                <td class="td-meta-col">
                  <span
                    :class="['meta-badge', sampleAnnotations[rowId]?.safe ? 'bg-safe' : 'bg-risk']"
                    :title="sampleAnnotations[rowId]?.safe ? '治疗应用安全' : '含有潜在毒力或整合风险元件'"
                  >
                    {{ sampleAnnotations[rowId]?.safe ? '安全' : '警示' }}
                  </span>
                </td>
                <td class="td-meta-col">
                  <strong class="text-blue">{{ sampleAnnotations[rowId]?.acrCount || 0 }}</strong>
                </td>
              </template>

              <!-- 4. 全基因组一致性矩阵单元格 (支持核酸 ANI 与 CDS 基因功能谱双模切换) -->
              <template v-if="isAniTrackVisible">
                <td
                  v-for="colId in visibleSampleIds"
                  :key="'ani-cell-' + rowId + '-' + colId"
                  class="td-ani-val-cell"
                  :style="{
                    backgroundColor: getAniCellColor(getActiveCellValue(rowId, colId)),
                    color: getAniTextColor(getActiveCellValue(rowId, colId))
                  }"
                  :class="{ 
                    'cell-pair-highlight': isCurrentPair(rowId, colId),
                    'cell-ani-na': getActiveCellValue(rowId, colId) === null || getActiveCellValue(rowId, colId) === undefined || getActiveCellValue(rowId, colId) === 0
                  }"
                  @click="handleCellClick(rowId, colId)"
                  :title="getAniCellTitle(rowId, colId)"
                >
                  <span v-if="displayDensity !== 'ultra'">
                    {{ formatAniDisplay(getActiveCellValue(rowId, colId), rowId, colId) }}
                  </span>
                </td>
              </template>

              <!-- 5. 同源基因家族存在/缺失方块矩阵 (纯静态零 Diff 渲染 + 绝对定位导轨极速联动) -->
              <template v-if="isGeneMatrixTrackVisible">
                <td
                  v-for="c in sortedGeneClusters"
                  :key="'cluster-' + rowId + '-' + c.group_id"
                  class="td-cluster-block"
                  @mouseenter="handleClusterMouseEnter($event, c, rowId)"
                  @click="openClusterDrawer(c)"
                >
                  <div
                    v-if="c.presence_map?.[rowId]"
                    class="gene-present-square"
                    :class="c._variantMap[rowId].className"
                    :style="c._variantMap[rowId].style"
                    :title="c._variantMap[rowId].title"
                  ></div>
                  <div v-else class="gene-absent-dot" title="该样本缺失此 CDS"></div>
                </td>
              </template>

              <!-- 6. 弹性吸纳单元格 -->
              <td class="td-elastic-spacer"></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 视图 B: 群体拓扑弦图画板 -->
      <div v-else class="phylogenomic-chord-canvas">
        <PanGenomicsChordDiagram
          :clusters="clusters || []"
          :sample-names="sampleNames"
          :visible-sample-ids="visibleSampleIds"
          :ani-matrix="aniMatrix"
          :tail-matrix="tailMatrix"
          :lifestyles="lifestyles"
          :selected-pair="selectedPair"
          @select-sample="handleSelectSample"
          @select-pair="handleSelectPair"
          @open-cluster-drawer="openClusterDrawer"
        />
      </div>

      <!-- 悬停基因家族信息提示条 (固定高度状态栏) -->
      <div v-if="viewMode === 'matrix'" class="cluster-hover-info-strip" :class="{ active: !!hoveredGeneCluster }">
        <template v-if="hoveredGeneCluster">
          <span class="chip-cat" :style="{ backgroundColor: getCatColor(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }">
            {{ getCategoryChinese(hoveredGeneCluster.cluster?._inferredCategory || hoveredGeneCluster.cluster?.category) }}
          </span>
          <strong>{{ hoveredGeneCluster.cluster?.group_id }}</strong>:
          <span class="strip-prod-txt">{{ hoveredGeneCluster.cluster?.representative_product }}</span>
          <span class="hover-sample-tag">【{{ sampleNames[hoveredGeneCluster.rowId] || hoveredGeneCluster.rowId }}】: <strong>{{ hoveredGeneCluster.variant?.variantLabel }}</strong></span>
          <span class="text-slate"> (共享率: {{ hoveredGeneCluster.cluster?.sample_count }}/{{ orderedSampleIds.length }} 样本 · 点击展开多样本比对)</span>
        </template>
        <template v-else>
          <span class="strip-placeholder-txt">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px; vertical-align: middle;">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            将鼠标悬停在同源基因方块上，可在此实时预览详细功能注释与序列变异情况；点击方块可展开多样本同源基因比对详情。
          </span>
        </template>
      </div>

      <!-- CDS 详细属性卡片模态 (独立抽屉子组件) -->
      <GeneClusterDetailDrawer
        :cluster="selectedGeneCluster"
        :visible-sample-ids="visibleSampleIds"
        :sample-names="sampleNames"
        :selected-pair="selectedPair"
        :total-sample-count="orderedSampleIds.length"
        @close="selectedGeneCluster = null"
      />
    </div>
  </div>
</template>

<style scoped>
@import './landscape/populationLandscape.css';
</style>
