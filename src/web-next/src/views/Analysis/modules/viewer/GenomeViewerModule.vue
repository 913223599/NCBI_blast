<template>
  <div class="genome-viewer-module">
    <!-- 全局高阶运算加载遮罩 -->
    <div v-if="isComputing" class="loading-overlay">
      <div class="spinner-xl"></div>
      <div class="loading-text">正在解析序列与构建多维特征轨迹...</div>
    </div>

    <!-- 顶部轻量 Toast 提示 -->
    <div v-if="toastMessage" class="floating-toast">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5">
        <polyline points="20 6 9 17 4 12"></polyline>
      </svg>
      <span>{{ toastMessage }}</span>
    </div>

    <!-- 1. 顶部操作栏 -->
    <header class="viewer-toolbar">
      <div class="toolbar-left">
        <div class="file-upload-mini">
          <input type="file" id="seq-upload" hidden @change="handleFileUpload" accept=".fasta,.fa,.gbk,.gb,.gff" />
          <label for="seq-upload" class="upload-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            打开序列文件
          </label>
        </div>
        <div v-if="fileName" class="current-file-badge">
          <span class="file-icon-dot"></span>
          <span class="file-name" :title="fileName">{{ fileName }}</span>
          <span class="seq-len">{{ formatLength(sequenceLength) }}</span>
          <span class="gc-badge" v-if="overallGC > 0">GC: {{ overallGC }}%</span>
        </div>
      </div>

      <div class="toolbar-center" v-if="sequenceLength > 0">
        <div class="view-mode-tabs">
          <button type="button" :class="{ active: viewMode === 'circular' }" @click="viewMode = 'circular'">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10" /><path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
            环形图谱 (Circular)
          </button>
          <button type="button" :class="{ active: viewMode === 'linear' }" @click="viewMode = 'linear'">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="18" x2="21" y2="18" />
            </svg>
            线性图谱 (Linear)
          </button>
        </div>
      </div>

      <div class="toolbar-right">
        <!-- 轨道开关菜单组 -->
        <div class="track-toggle-group" v-if="sequenceLength > 0">
          <button type="button" class="track-btn" :class="{ active: showGC }" @click="showGC = !showGC" title="GC 含量与 GC 偏斜双环轨迹">
            <span class="toggle-dot gc-dot"></span>
            GC 曲线 (Content & Skew)
          </button>
          <button type="button" class="track-btn" :class="{ active: showEnzymes }" @click="showEnzymes = !showEnzymes" title="常用内切酶识别位点">
            内切酶位点
          </button>
          <button type="button" class="track-btn" :class="{ active: showPositions }" @click="showPositions = !showPositions" title="刻度坐标数值">
            坐标标尺
          </button>
        </div>

        <button type="button" v-if="sequenceLength > 0" class="export-btn primary" @click="exportImage('png')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1M16 10l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          导出图片
        </button>
        <button type="button" v-if="sequenceLength > 0" class="export-btn secondary" @click="exportImage('svg')" title="导出 Adobe Illustrator 可编辑矢量图">
          SVG 矢量图
        </button>
      </div>
    </header>

    <div class="viewer-main">
      <!-- 2. 左侧特征浏览器 (Feature Explorer) -->
      <aside class="features-sidebar">
        <div class="sidebar-header">
          <div class="sidebar-title-wrap">
            <span class="sidebar-title">基因特征定位</span>
            <span class="feat-total-tag">{{ filteredFeatures.length }} / {{ baseTrackFeatures.length }} 个</span>
          </div>
        </div>

        <!-- 多维检索与分类筛选过滤 -->
        <div class="filter-box">
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input type="text" v-model="searchQuery" placeholder="搜索基因名 / 产物 / Locus..." />
            <button type="button" v-if="searchQuery" class="clear-btn" @click="searchQuery = ''">×</button>
          </div>

          <div class="filter-selectors">
            <select v-model="selectedCategoryFilter" class="filter-select">
              <option value="ALL">全部生物学大类 (All Categories)</option>
              <option v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" :value="key">
                {{ cat.label }}
              </option>
            </select>

            <div class="strand-toggle">
              <button type="button" :class="{ active: strandFilter === 'ALL' }" @click="strandFilter = 'ALL'">全</button>
              <button type="button" :class="{ active: strandFilter === '+' }" @click="strandFilter = '+'">+ 正链</button>
              <button type="button" :class="{ active: strandFilter === '-' }" @click="strandFilter = '-'">- 负链</button>
            </div>
          </div>
        </div>

        <!-- 特征卡片滚动列表 -->
        <div class="features-list" ref="featuresListRef">
          <div 
            v-for="(feat, idx) in filteredFeatures" 
            :key="idx" 
            class="feature-card"
            :class="{ active: selectedFeature === feat, dimmed: highlightedCategory && feat.category !== highlightedCategory }" 
            :style="{ '--accent-color': getFeatureColor(feat.type, feat.category, feat.product) }"
            @click="selectFeature(feat)"
          >
            <div class="card-top">
              <span class="locus-badge">{{ feat.locus_tag || feat.name || `CDS_${idx+1}` }}</span>
              <span class="strand-pill" :class="feat.strand === '+' ? 'plus' : 'minus'">
                {{ feat.strand === '+' ? '▶ 正向 (+)' : '◀ 反向 (-)' }}
              </span>
              <span class="pos-range">{{ feat.start.toLocaleString() }} - {{ feat.end.toLocaleString() }}</span>
            </div>

            <div class="card-product" :title="feat.product || feat.name">
              {{ feat.product || feat.name || 'hypothetical protein' }}
            </div>

            <div class="card-bottom">
              <span class="category-chip" :style="{ backgroundColor: getFeatureColor(feat.type, feat.category, feat.product) + '20', color: getFeatureColor(feat.type, feat.category, feat.product) }">
                {{ feat.category }}
              </span>
              <span class="length-chip">{{ (feat.end - feat.start + 1) }} bp ({{ Math.round((feat.end - feat.start + 1)/3) }} aa)</span>
            </div>
          </div>

          <div v-if="filteredFeatures.length === 0" class="no-features-tip">
            未找到符合筛选条件的基因特征
          </div>
        </div>
      </aside>

      <!-- 3. 画布核心区域 -->
      <section class="canvas-area" ref="canvasArea">
        <div v-if="!sequenceLength" class="empty-state">
          <div class="empty-icon-pulse">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="1.8">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
              <path d="M2 12h20" />
            </svg>
          </div>
          <h3>科研级序列与基因组可视化工作台</h3>
          <p>请点击左上角“打开序列文件”加载数据，或从注释任务直接跳转</p>
          <div class="supported-formats">
            <span>支持格式:</span>
            <span class="fmt-tag">GenBank (.gbk/.gb)</span>
            <span class="fmt-tag">GFF3 (.gff)</span>
            <span class="fmt-tag">FASTA (.fasta/.fa)</span>
          </div>
        </div>

        <div v-else class="svg-container" 
          @wheel.prevent="handleZoom" 
          @mousedown="startPan" 
          @mousemove="doPan" 
          @mouseup="endPan"
          @mouseleave="endPan" 
          @click="handleCanvasClick"
        >

          <!-- 环形视图 (Circular Genome Map) -->
          <svg v-if="viewMode === 'circular'" ref="svgRef" width="100%" height="100%" class="genome-svg">
            <svg x="50%" y="50%" overflow="visible">
              
              <!-- 缩放与平移图元容器 -->
              <g :transform="`translate(${panX}, ${panY}) scale(${zoomScale})`">
                
                <!-- 1. 背景同心主轴轨道 -->
                <circle cx="0" cy="0" :r="outerRadius" class="track-backbone outer" vector-effect="non-scaling-stroke" />
                <circle cx="0" cy="0" :r="innerRadius" class="track-backbone inner" vector-effect="non-scaling-stroke" />
                <circle cx="0" cy="0" :r="midSplitRadius" class="track-split" vector-effect="non-scaling-stroke" />

                <!-- 2. 刻度线与网格 -->
                <g class="rulers" v-if="showPositions">
                  <line 
                    v-for="(tick, i) in circularTicks" :key="'tick'+i"
                    :x1="tick.x1" :y1="tick.y1" :x2="tick.x2" :y2="tick.y2"
                    :stroke="tick.major ? '#475569' : '#cbd5e1'" 
                    :stroke-width="tick.major ? 1.5 : 1"
                    vector-effect="non-scaling-stroke"
                  />
                  <!-- 刻度数值文本 -->
                  <text 
                    v-for="(tick, i) in majorCircularTicks" :key="'tick_txt'+i"
                    :x="tick.tx" :y="tick.ty" 
                    :text-anchor="tick.anchor" 
                    dominant-baseline="middle"
                    class="tick-text-circular"
                  >{{ tick.label }}</text>
                </g>

                <!-- 3. GC 含量与 GC Skew 波动轨迹 (半径 95 ~ 170) -->
                <g class="gc-layer" v-if="showGC">
                  <!-- GC Content 波动轨道 -->
                  <g class="gc-content-sublayer">
                    <circle cx="0" cy="0" :r="gcBaselineR" fill="none" stroke="#cbd5e1" stroke-dasharray="3 3" stroke-width="1" vector-effect="non-scaling-stroke" />
                    <!-- 高于平均 GC：翠绿色填充 -->
                    <path :d="gcPaths.gcHighPathData" fill="#10b981" opacity="0.65" vector-effect="non-scaling-stroke" />
                    <!-- 低于平均 GC：深灰色填充 -->
                    <path :d="gcPaths.gcLowPathData" fill="#64748b" opacity="0.65" vector-effect="non-scaling-stroke" />
                    <path :d="gcPaths.gcPathData" fill="none" stroke="#059669" stroke-width="1" vector-effect="non-scaling-stroke" />
                  </g>

                  <!-- GC Skew 偏斜波动轨道 -->
                  <g class="gc-skew-sublayer">
                    <circle cx="0" cy="0" :r="skewBaselineR" fill="none" stroke="#e2e8f0" stroke-dasharray="3 3" stroke-width="1" vector-effect="non-scaling-stroke" />
                    <!-- G > C (Leading strand): 紫色填充 -->
                    <path :d="gcPaths.gcSkewPosPathData" fill="#8b5cf6" opacity="0.65" vector-effect="non-scaling-stroke" />
                    <!-- G < C (Lagging strand): 琥珀橙填充 -->
                    <path :d="gcPaths.gcSkewNegPathData" fill="#f59e0b" opacity="0.65" vector-effect="non-scaling-stroke" />
                  </g>
                </g>

                <!-- 4. 限制性内切酶位点指示线 -->
                <g class="enzyme-layer" v-if="showEnzymes">
                  <template v-for="(f, i) in renderCircularEnzymes" :key="'enz_path'+i">
                    <path v-if="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)"
                      :d="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)?.line" 
                      fill="none" :stroke="f.color" stroke-width="1.2"
                      vector-effect="non-scaling-stroke"
                    />
                    <text v-if="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)"
                      :x="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)?.textX"
                      :y="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)?.textY"
                      :text-anchor="getEnzymeCircularLabel(f, sequenceLength, outerRadius + 28)?.anchor"
                      dominant-baseline="middle"
                      class="enzyme-label"
                      :fill="f.color"
                    >{{ f.name }}</text>
                  </template>
                </g>

                <!-- 4.5 预测前噬菌体跨链半透明叠图包络层 (Circular Overlay Track) -->
                <g class="prophage-overlay-layer" v-if="prophageOverlayFeatures.length > 0">
                  <path
                    v-for="(pf, pi) in prophageOverlayFeatures"
                    :key="'poverlay_' + pi"
                    :d="getCircularPath({ ...pf, strand: '+' }, sequenceLength, { innerR: 175, outerR: 254 })"
                    fill="#0ea5e9"
                    :fill-opacity="selectedFeature === pf ? 0.28 : 0.16"
                    stroke="#0284c7"
                    :stroke-width="selectedFeature === pf ? 2.2 : 1.2"
                    class="feature-glyph"
                    @mouseenter="hoverFeature = pf"
                    @mouseleave="hoverFeature = null"
                    @click.stop="selectFeature(pf)"
                  >
                    <title>{{ pf.locus_tag || pf.name }}: {{ pf.product || 'Predicted Prophage' }} [{{ pf.start }}..{{ pf.end }} bp]</title>
                  </path>
                </g>

                <!-- 5. 核心基因特征图谱 (正链在外轨 R=215~245，负链在内轨 R=180~210) -->
                <g class="features-layer">
                  <path 
                    v-for="(f, i) in baseTrackFeatures" 
                    :key="'feat_'+i"
                    :d="getCircularPath(f, sequenceLength, f.strand === '+' ? { innerR: 215, outerR: 245 } : { innerR: 180, outerR: 210 })"
                    :fill="getFeatureColor(f.type, f.category, f.product)"
                    :class="['feature-glyph', { 
                      'is-selected': selectedFeature === f, 
                      'is-dimmed': isFeatureDimmed(f)
                    }]"
                    @mouseenter="hoverFeature = f"
                    @mouseleave="hoverFeature = null"
                    @click.stop="selectFeature(f)"
                  >
                    <title>{{ f.locus_tag || f.name }}: {{ f.product || 'hypothetical protein' }} [{{ f.start }}..{{ f.end }} bp]</title>
                  </path>
                </g>

                <!-- 6. 选中基因高亮发光描边 -->
                <path 
                  v-if="selectedFeature && selectedFeature.type !== 'prophage_region'"
                  :d="getCircularPath(selectedFeature, sequenceLength, selectedFeature.strand === '+' ? { innerR: 215, outerR: 245 } : { innerR: 180, outerR: 210 })"
                  fill="none" 
                  stroke="#ffffff" 
                  stroke-width="2.5"
                  class="selected-highlight-stroke"
                  vector-effect="non-scaling-stroke"
                  style="pointer-events: none;"
                />

                <!-- 7. 紧凑型环形中心数据看板 (半径 75，留出足量空间展示内部 GC 曲线) -->
                <g class="center-infobox" style="pointer-events: none;">
                  <circle cx="0" cy="0" :r="centerCardRadius" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" class="center-bg" />
                  <text x="0" y="-24" text-anchor="middle" class="center-title">{{ fileName || 'Phage Genome' }}</text>
                  <text x="0" y="-2" text-anchor="middle" class="center-length">{{ formatLength(sequenceLength) }}</text>
                  <text x="0" y="18" text-anchor="middle" class="center-sub">GC 含量: {{ overallGC }}%</text>
                  <text x="0" y="34" text-anchor="middle" class="center-cds-count">CDS: {{ baseTrackFeatures.length }} 个特征</text>
                </g>

              </g>
            </svg>
          </svg>

          <!-- 线性视图 (Linear Genome View) -->
          <svg v-else ref="svgRef" width="100%" height="100%" class="genome-svg linear-svg">
            <svg x="0" y="50%" overflow="visible">
              <g :transform="`translate(${panX}, 0) scale(${zoomScale}, 1)`">
                <!-- 线性骨架主轴 -->
                <line x1="0" y1="0" :x2="computedLinearWidth" y2="0" class="linear-backbone" />
                
                <!-- 线性刻度标尺 -->
                <g class="linear-rulers" v-if="showPositions">
                  <line 
                    v-for="(tick, i) in linearTicks" :key="'ltick_' + i" 
                    :x1="tick.x" y1="-8" :x2="tick.x" :y2="tick.major ? 8 : 4" 
                    :stroke="tick.major ? '#475569' : '#94a3b8'" 
                    :stroke-width="tick.major ? 1.5 : 1" 
                  />
                  <text 
                    v-for="(tick, i) in majorLinearTicks" :key="'ltxt_' + i" 
                    :x="tick.x" y="-18" 
                    text-anchor="middle" 
                    class="linear-tick-label"
                  >{{ tick.label }}</text>
                </g>

                <!-- 预测前噬菌体跨链半透明叠图高亮层 (Linear Overlay Track) -->
                <g class="linear-prophage-overlay" v-if="prophageOverlayFeatures.length > 0 && sequenceLength > 0">
                  <g
                    v-for="(pf, pi) in prophageOverlayFeatures"
                    :key="'lpoverlay_' + pi"
                    class="feature-glyph"
                    @mouseenter="hoverFeature = pf"
                    @mouseleave="hoverFeature = null"
                    @click.stop="selectFeature(pf)"
                  >
                    <rect
                      :x="(pf.start / sequenceLength) * computedLinearWidth"
                      y="-38"
                      :width="Math.max(4, ((pf.end - pf.start) / sequenceLength) * computedLinearWidth)"
                      height="76"
                      rx="3"
                      fill="#0ea5e9"
                      :fill-opacity="selectedFeature === pf ? 0.24 : 0.14"
                      stroke="#0284c7"
                      :stroke-width="selectedFeature === pf ? 2 : 1"
                    />
                    <text
                      :x="(pf.start / sequenceLength) * computedLinearWidth + 3"
                      y="-41"
                      fill="#0369a1"
                      font-size="9.5"
                      font-weight="700"
                    >{{ pf.locus_tag || pf.name }}</text>
                  </g>
                </g>

                <!-- 特征图形渲染 (正链上方，负链下方) -->
                <g class="linear-features">
                  <path 
                    v-for="(f, i) in baseTrackFeatures" 
                    :key="'lfeat_' + i"
                    :d="getLinearPath(f, sequenceLength, computedLinearWidth, { linearY: f.strand === '+' ? -28 : 8, rowHeight: 20 })" 
                    :fill="getFeatureColor(f.type, f.category, f.product)"
                    :class="['feature-glyph', { 
                      'is-selected': selectedFeature === f, 
                      'is-dimmed': isFeatureDimmed(f)
                    }]"
                    @mouseenter="hoverFeature = f"
                    @mouseleave="hoverFeature = null"
                    @click.stop="selectFeature(f)"
                  >
                    <title>{{ f.locus_tag || f.name }}: {{ f.product || 'hypothetical protein' }} [{{ f.start }}..{{ f.end }} bp]</title>
                  </path>
                </g>

                <!-- 线性选中高亮 -->
                <path 
                  v-if="selectedFeature && selectedFeature.type !== 'prophage_region'"
                  :d="getLinearPath(selectedFeature, sequenceLength, computedLinearWidth, { linearY: selectedFeature.strand === '+' ? -28 : 8, rowHeight: 20 })" 
                  fill="none" 
                  stroke="#0f172a" 
                  stroke-width="2.5" 
                  style="pointer-events: none;" 
                />
              </g>
            </svg>
          </svg>

          <!-- 4. 浮动功能大类图例徽章栏 (Interactive Legend) -->
          <div class="floating-legend" v-if="sequenceLength > 0">
            <div class="legend-header">
              <span>功能大类图例 (点击高亮聚焦)</span>
              <button type="button" v-if="highlightedCategory" class="reset-legend-btn" @click="highlightedCategory = ''">清除高亮</button>
            </div>
            <div class="legend-items">
              <div 
                v-for="(cat, key) in FUNCTIONAL_CATEGORIES" 
                :key="key"
                class="legend-item"
                :class="{ active: highlightedCategory === key }"
                @click="toggleHighlightCategory(key)"
              >
                <span class="color-dot" :style="{ backgroundColor: cat.color }"></span>
                <span class="legend-label">{{ cat.label.split(' ')[0] }}</span>
                <span class="legend-count">{{ categoryCounts[key] || 0 }}</span>
              </div>
            </div>

            <!-- GC 轨迹说明 -->
            <div class="gc-legend-sub" v-if="showGC">
              <div class="gc-legend-title">GC 轨迹说明:</div>
              <div class="gc-legend-row"><span class="gc-box green"></span> GC 含量高于均值</div>
              <div class="gc-legend-row"><span class="gc-box gray"></span> GC 含量低于均值</div>
              <div class="gc-legend-row"><span class="gc-box purple"></span> GC Skew (+) 前导链</div>
              <div class="gc-legend-row"><span class="gc-box orange"></span> GC Skew (-) 滞后链</div>
            </div>
          </div>

          <!-- 5. 悬浮微型卡片 Tooltip -->
          <div 
            class="floating-tooltip" 
            v-if="hoverFeature && !selectedFeature"
            :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
          >
            <div class="tt-header">
              <span class="tt-locus">{{ hoverFeature.locus_tag || hoverFeature.name }}</span>
              <span class="tt-cat-badge" :style="{ backgroundColor: (hoverFeature.type === 'prophage_region' ? '#0284c7' : getFeatureColor(hoverFeature.type, hoverFeature.category, hoverFeature.product)) + '20', color: hoverFeature.type === 'prophage_region' ? '#0284c7' : getFeatureColor(hoverFeature.type, hoverFeature.category, hoverFeature.product) }">
                {{ hoverFeature.type === 'prophage_region' ? '预测前噬菌体区段' : hoverFeature.category }}
              </span>
            </div>
            <div class="tt-product">{{ hoverFeature.product || 'hypothetical protein' }}</div>
            <div class="tt-meta">
              <template v-if="hoverFeature.type === 'prophage_region'">
                <span>区段区间: {{ hoverFeature.start.toLocaleString() }} - {{ hoverFeature.end.toLocaleString() }} bp</span>
                <span>区段跨度: {{ (hoverFeature.end - hoverFeature.start + 1).toLocaleString() }} bp</span>
              </template>
              <template v-else>
                <span>坐标: {{ hoverFeature.start.toLocaleString() }} - {{ hoverFeature.end.toLocaleString() }} bp ({{ hoverFeature.strand === '+' ? '正链 +' : '负链 -' }})</span>
                <span>长度: {{ hoverFeature.end - hoverFeature.start + 1 }} bp ({{ Math.round((hoverFeature.end - hoverFeature.start + 1)/3) }} aa)</span>
              </template>
            </div>
          </div>

          <!-- 6. 视口操控悬浮工具组 (Zoom & Reset) -->
          <div class="viewport-controls">
            <button type="button" @click="zoomIn" title="放大 (+)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
            </button>
            <button type="button" @click="zoomOut" title="缩小 (-)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
            </button>
            <button type="button" @click="resetView" title="重置视图与居中">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            </button>
          </div>

          <!-- 7. 选中基因深度详情抽屉 (Gene Inspector) -->
          <div class="feature-inspector-drawer" v-if="selectedFeature">
            <div class="drawer-header">
              <div class="drawer-title-group">
                <span class="drawer-icon-tag" :style="{ backgroundColor: selectedFeature.type === 'prophage_region' ? '#0284c7' : getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product) }"></span>
                <span class="drawer-locus">{{ selectedFeature.locus_tag || selectedFeature.name || 'CDS Feature' }}</span>
                <span class="drawer-cat-chip" :style="{ color: selectedFeature.type === 'prophage_region' ? '#0284c7' : getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product), backgroundColor: (selectedFeature.type === 'prophage_region' ? '#0284c7' : getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product)) + '15' }">
                  {{ selectedFeature.type === 'prophage_region' ? '预测前噬菌体区段' : selectedFeature.category }}
                </span>
              </div>
              <button type="button" class="drawer-close" @click="selectedFeature = null">×</button>
            </div>

            <div class="drawer-body">
              <div class="info-row">
                <span class="info-k">{{ selectedFeature.type === 'prophage_region' ? '区段描述:' : '产物功能:' }}</span>
                <span class="info-v highlight">{{ selectedFeature.product || 'hypothetical protein' }}</span>
              </div>
              <div class="info-row">
                <span class="info-k">物理区间:</span>
                <span class="info-v">
                  <template v-if="selectedFeature.type === 'prophage_region'">
                    {{ selectedFeature.start.toLocaleString() }} .. {{ selectedFeature.end.toLocaleString() }} bp (全长 {{ (selectedFeature.end - selectedFeature.start + 1).toLocaleString() }} bp 跨链区段)
                  </template>
                  <template v-else>
                    {{ selectedFeature.start.toLocaleString() }} .. {{ selectedFeature.end.toLocaleString() }} bp ({{ selectedFeature.strand === '+' ? '正链 Forward +' : '反链 Reverse -' }})
                  </template>
                </span>
              </div>
              <div class="info-row" v-if="selectedFeature.type !== 'prophage_region'">
                <span class="info-k">蛋白规模:</span>
                <span class="info-v">{{ Math.round((selectedFeature.end - selectedFeature.start + 1) / 3) }} aa (分子量约 {{ ((selectedFeature.end - selectedFeature.start + 1) / 3 * 0.11).toFixed(2) }} kDa)</span>
              </div>
              <div class="info-row" v-if="selectedFeature.gene">
                <span class="info-k">基因代号:</span>
                <span class="info-v">{{ selectedFeature.gene }}</span>
              </div>
              <div class="info-row" v-if="selectedFeature.note">
                <span class="info-k">注释证据:</span>
                <span class="info-v note-text">{{ selectedFeature.note }}</span>
              </div>
            </div>

            <div class="drawer-actions">
              <button type="button" @click="copySequence" class="act-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                {{ selectedFeature.type === 'prophage_region' ? '复制区段核酸序列' : '复制核酸 CDS' }}
              </button>
              <button type="button" @click="copyTranslation" class="act-btn" v-if="selectedFeature.type !== 'prophage_region' && (selectedFeature.translation || rawSequence)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>
                复制蛋白翻译序列
              </button>
            </div>
          </div>

        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  getCircularPath,
  getLinearPath,
  getEnzymeCircularLabel,
  getFeatureColor,
  formatLength,
  FUNCTIONAL_CATEGORIES,
} from './utils/render'
import { useGenomeViewer } from './useGenomeViewer'

const props = defineProps<{
  initialGbk?: string
  initialName?: string
}>()

const {
  fileName, sequenceLength, rawSequence, viewMode, isComputing, toastMessage,
  searchQuery, selectedCategoryFilter, strandFilter, highlightedCategory, selectedFeature, hoverFeature,
  showGC, showEnzymes, showPositions, outerRadius, innerRadius, midSplitRadius, gcBaselineR,
  skewBaselineR, centerCardRadius, zoomScale, panX, panY, tooltipX, tooltipY, svgRef,
  computedLinearWidth, overallGC, prophageOverlayFeatures, baseTrackFeatures, categoryCounts,
  filteredFeatures, gcPaths, renderCircularEnzymes, circularTicks, majorCircularTicks,
  linearTicks, majorLinearTicks, isFeatureDimmed, selectFeature, toggleHighlightCategory,
  handleCanvasClick, handleZoom, zoomIn, zoomOut, resetView, startPan, doPan, endPan,
  handleFileUpload, copySequence, copyTranslation, exportImage,
} = useGenomeViewer(props)

void svgRef
</script>

<style scoped src="./genomeViewer.css"></style>
