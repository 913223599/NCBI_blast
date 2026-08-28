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
          <button :class="{ active: viewMode === 'circular' }" @click="viewMode = 'circular'">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10" /><path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
            环形图谱 (Circular)
          </button>
          <button :class="{ active: viewMode === 'linear' }" @click="viewMode = 'linear'">
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
          <button class="track-btn" :class="{ active: showGC }" @click="showGC = !showGC" title="GC 含量与 GC 偏斜双环轨迹">
            <span class="toggle-dot gc-dot"></span>
            GC 曲线 (Content & Skew)
          </button>
          <button class="track-btn" :class="{ active: showEnzymes }" @click="showEnzymes = !showEnzymes" title="常用内切酶识别位点">
            内切酶位点
          </button>
          <button class="track-btn" :class="{ active: showPositions }" @click="showPositions = !showPositions" title="刻度坐标数值">
            坐标标尺
          </button>
        </div>

        <button v-if="sequenceLength > 0" class="export-btn primary" @click="exportImage('png')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1M16 10l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          导出图片
        </button>
        <button v-if="sequenceLength > 0" class="export-btn secondary" @click="exportImage('svg')" title="导出 Adobe Illustrator 可编辑矢量图">
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
            <span class="feat-total-tag">{{ filteredFeatures.length }} / {{ features.length }} 个</span>
          </div>
        </div>

        <!-- 多维检索与分类筛选过滤 -->
        <div class="filter-box">
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input type="text" v-model="searchQuery" placeholder="搜索基因名 / 产物 / Locus..." />
            <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''">×</button>
          </div>

          <div class="filter-selectors">
            <select v-model="selectedCategoryFilter" class="filter-select">
              <option value="ALL">全部生物学大类 (All Categories)</option>
              <option v-for="(cat, key) in FUNCTIONAL_CATEGORIES" :key="key" :value="key">
                {{ cat.label }}
              </option>
            </select>

            <div class="strand-toggle">
              <button :class="{ active: strandFilter === 'ALL' }" @click="strandFilter = 'ALL'">全</button>
              <button :class="{ active: strandFilter === '+' }" @click="strandFilter = '+'">+ 正链</button>
              <button :class="{ active: strandFilter === '-' }" @click="strandFilter = '-'">- 负链</button>
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

                <!-- 5. 核心基因特征图谱 (正链在外轨 R=215~245，负链在内轨 R=180~210) -->
                <g class="features-layer">
                  <path 
                    v-for="(f, i) in features" 
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
                  v-if="selectedFeature"
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
                  <text x="0" y="34" text-anchor="middle" class="center-cds-count">CDS: {{ features.length }} 个特征</text>
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

                <!-- 特征图形渲染 (正链上方，负链下方) -->
                <g class="linear-features">
                  <path 
                    v-for="(f, i) in features" 
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
                  v-if="selectedFeature"
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
              <button v-if="highlightedCategory" class="reset-legend-btn" @click="highlightedCategory = ''">清除高亮</button>
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
              <span class="tt-cat-badge" :style="{ backgroundColor: getFeatureColor(hoverFeature.type, hoverFeature.category, hoverFeature.product) + '20', color: getFeatureColor(hoverFeature.type, hoverFeature.category, hoverFeature.product) }">
                {{ hoverFeature.category }}
              </span>
            </div>
            <div class="tt-product">{{ hoverFeature.product || 'hypothetical protein' }}</div>
            <div class="tt-meta">
              <span>坐标: {{ hoverFeature.start.toLocaleString() }} - {{ hoverFeature.end.toLocaleString() }} bp ({{ hoverFeature.strand === '+' ? '正链 +' : '负链 -' }})</span>
              <span>长度: {{ hoverFeature.end - hoverFeature.start + 1 }} bp ({{ Math.round((hoverFeature.end - hoverFeature.start + 1)/3) }} aa)</span>
            </div>
          </div>

          <!-- 6. 视口操控悬浮工具组 (Zoom & Reset) -->
          <div class="viewport-controls">
            <button @click="zoomIn" title="放大 (+)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
            </button>
            <button @click="zoomOut" title="缩小 (-)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
            </button>
            <button @click="resetView" title="重置视图与居中">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            </button>
          </div>

          <!-- 7. 选中基因深度详情抽屉 (Gene Inspector) -->
          <div class="feature-inspector-drawer" v-if="selectedFeature">
            <div class="drawer-header">
              <div class="drawer-title-group">
                <span class="drawer-icon-tag" :style="{ backgroundColor: getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product) }"></span>
                <span class="drawer-locus">{{ selectedFeature.locus_tag || selectedFeature.name || 'CDS Feature' }}</span>
                <span class="drawer-cat-chip" :style="{ color: getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product), backgroundColor: getFeatureColor(selectedFeature.type, selectedFeature.category, selectedFeature.product) + '15' }">
                  {{ selectedFeature.category }}
                </span>
              </div>
              <button class="drawer-close" @click="selectedFeature = null">×</button>
            </div>

            <div class="drawer-body">
              <div class="info-row">
                <span class="info-k">产物功能:</span>
                <span class="info-v highlight">{{ selectedFeature.product || 'hypothetical protein' }}</span>
              </div>
              <div class="info-row">
                <span class="info-k">物理区间:</span>
                <span class="info-v">{{ selectedFeature.start.toLocaleString() }} .. {{ selectedFeature.end.toLocaleString() }} bp ({{ selectedFeature.strand === '+' ? '正链 Forward +' : '反链 Reverse -' }})</span>
              </div>
              <div class="info-row">
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
              <button @click="copySequence" class="act-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                复制核酸 CDS
              </button>
              <button @click="copyTranslation" class="act-btn" v-if="selectedFeature.translation || rawSequence">
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
import { ref, computed, watch } from "vue";
import { parseGenBank, parseFasta } from "./utils/parser";
import { calculateGC, calculateEnzymes } from "./utils/calculations";
import { 
  getCircularPath, 
  getLinearPath, 
  getEnzymeCircularLabel, 
  getFeatureColor, 
  formatLength, 
  formatTickLabel,
  polarToCartesian,
  FUNCTIONAL_CATEGORIES 
} from "./utils/render";
import { extractFeatureSequence, translateDNA } from "./utils/sequence";

const props = defineProps<{
  initialGbk?: string;
  initialName?: string;
}>();

// --- 核心状态 ---
const fileName = ref("");
const sequenceLength = ref(0);
const rawSequence = ref("");
const features = ref<any[]>([]);
const viewMode = ref<"circular" | "linear">("circular");
const isComputing = ref(false);
const toastMessage = ref("");

// 过滤与交互
const searchQuery = ref("");
const selectedCategoryFilter = ref("ALL");
const strandFilter = ref("ALL");
const highlightedCategory = ref("");
const selectedFeature = ref<any>(null);
const hoverFeature = ref<any>(null);

// 轨迹开关 (默认开启 GC 曲线与坐标标尺)
const showGC = ref(true);
const showEnzymes = ref(false);
const showPositions = ref(true);

// 几何半径系统
const outerRadius = 245;
const innerRadius = 180;
const midSplitRadius = 212.5;

const gcBaselineR = 150;
const skewBaselineR = 110;
const centerCardRadius = 75;

const zoomScale = ref(1);
const panX = ref(0);
const panY = ref(0);
let isPanning = false;
let startMouseX = 0;
let startMouseY = 0;
let initialPanX = 0;
let initialPanY = 0;

const tooltipX = ref(0);
const tooltipY = ref(0);
const svgRef = ref<SVGElement | null>(null);

const computedLinearWidth = computed(() => Math.max(1200, sequenceLength.value * 0.08));

// --- 统计与计算 ---
const overallGC = computed(() => {
  if (!rawSequence.value || rawSequence.value.length === 0) return 0;
  const seq = rawSequence.value.toUpperCase();
  let gcCount = 0;
  for (let i = 0; i < seq.length; i++) {
    if (seq[i] === "G" || seq[i] === "C") gcCount++;
  }
  return Number(((gcCount / seq.length) * 100).toFixed(2));
});

const categoryCounts = computed(() => {
  const counts: Record<string, number> = {};
  for (const f of features.value) {
    const cat = f.category || "Hypothetical";
    counts[cat] = (counts[cat] || 0) + 1;
  }
  return counts;
});

function matchesSearchAndFilter(f: any): boolean {
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase();
    const matchName = (f.name || "").toLowerCase().includes(q);
    const matchLocus = (f.locus_tag || "").toLowerCase().includes(q);
    const matchProduct = (f.product || "").toLowerCase().includes(q);
    const matchGene = (f.gene || "").toLowerCase().includes(q);
    if (!matchName && !matchLocus && !matchProduct && !matchGene) return false;
  }
  if (selectedCategoryFilter.value !== "ALL" && f.category !== selectedCategoryFilter.value) {
    return false;
  }
  if (strandFilter.value !== "ALL" && f.strand !== strandFilter.value) {
    return false;
  }
  return true;
}

// 判断图谱上的特征是否需要半透明变暗 (多重联动)
function isFeatureDimmed(f: any): boolean {
  if (selectedFeature.value) {
    return selectedFeature.value !== f;
  }
  if (highlightedCategory.value) {
    return f.category !== highlightedCategory.value;
  }
  if (searchQuery.value || selectedCategoryFilter.value !== "ALL" || strandFilter.value !== "ALL") {
    return !matchesSearchAndFilter(f);
  }
  return false;
}

// 过滤后的基因特征列表
const filteredFeatures = computed(() => {
  return features.value.filter(matchesSearchAndFilter);
});

// GC 轨迹路径
const gcPaths = computed(() => {
  if (!rawSequence.value || !showGC.value) {
    return {
      gcPathData: "",
      gcHighPathData: "",
      gcLowPathData: "",
      gcSkewPosPathData: "",
      gcSkewNegPathData: "",
      gcBaselineRadius: gcBaselineR,
      skewBaselineRadius: skewBaselineR
    };
  }
  return calculateGC(
    rawSequence.value,
    { innerR: 132, outerR: 168 },
    { innerR: 95, outerR: 125 }
  );
});

// 限制性内切酶
const enzymes = computed(() => {
  if (!rawSequence.value || !showEnzymes.value) return [];
  return calculateEnzymes(rawSequence.value);
});

const renderCircularEnzymes = computed(() => enzymes.value.slice(0, 36));

// --- 刻度计算 ---
const circularTicks = computed(() => {
  if (!sequenceLength.value) return [];
  const len = sequenceLength.value;
  const step = calculateTickStep(len);
  const ticks = [];
  
  for (let pos = 0; pos < len; pos += step) {
    const angle = (pos / len) * 360;
    const isMajor = pos % (step * 5) === 0 || pos === 0;
    const r1 = outerRadius + 8;
    const r2 = outerRadius + (isMajor ? 18 : 13);
    
    const p1 = polarToCartesian(0, 0, r1, angle);
    const p2 = polarToCartesian(0, 0, r2, angle);
    
    ticks.push({
      x1: p1.x, y1: p1.y,
      x2: p2.x, y2: p2.y,
      major: isMajor,
      pos
    });
  }
  return ticks;
});

const majorCircularTicks = computed(() => {
  if (!sequenceLength.value) return [];
  const len = sequenceLength.value;
  const step = calculateTickStep(len) * 5;
  const ticks = [];
  
  for (let pos = 0; pos < len; pos += step) {
    const angle = (pos / len) * 360;
    const r = outerRadius + 32;
    const p = polarToCartesian(0, 0, r, angle);
    
    ticks.push({
      tx: p.x,
      ty: p.y,
      label: formatTickLabel(pos),
      anchor: angle > 10 && angle < 170 ? "start" : angle > 190 && angle < 350 ? "end" : "middle"
    });
  }
  return ticks;
});

const linearTicks = computed(() => {
  if (!sequenceLength.value) return [];
  const len = sequenceLength.value;
  const step = calculateTickStep(len);
  const width = computedLinearWidth.value;
  const ticks = [];
  
  for (let pos = 0; pos <= len; pos += step) {
    ticks.push({
      x: (pos / len) * width,
      major: pos % (step * 5) === 0 || pos === 0,
      pos
    });
  }
  return ticks;
});

const majorLinearTicks = computed(() => {
  if (!sequenceLength.value) return [];
  const len = sequenceLength.value;
  const step = calculateTickStep(len) * 5;
  const width = computedLinearWidth.value;
  const ticks = [];
  
  for (let pos = 0; pos <= len; pos += step) {
    ticks.push({
      x: (pos / len) * width,
      label: formatTickLabel(pos)
    });
  }
  return ticks;
});

function calculateTickStep(len: number): number {
  if (len < 5000) return 200;
  if (len < 20000) return 1000;
  if (len < 100000) return 5000;
  if (len < 500000) return 20000;
  return 50000;
}

// --- 交互处理 ---
function selectFeature(feat: any) {
  selectedFeature.value = feat;
}

function toggleHighlightCategory(catKey: string) {
  if (highlightedCategory.value === catKey) {
    highlightedCategory.value = "";
  } else {
    highlightedCategory.value = catKey;
  }
}

function handleCanvasClick(e: MouseEvent) {
  if ((e.target as HTMLElement).tagName === "svg" || (e.target as HTMLElement).classList.contains("svg-container")) {
    selectedFeature.value = null;
  }
}

function showToast(msg: string) {
  toastMessage.value = msg;
  setTimeout(() => {
    toastMessage.value = "";
  }, 2000);
}

// 视口缩放与拖拽平移
function handleZoom(e: WheelEvent) {
  const delta = e.deltaY > 0 ? -0.1 : 0.1;
  const nextZoom = Math.min(Math.max(0.4, zoomScale.value + delta), 4.5);
  zoomScale.value = Number(nextZoom.toFixed(2));
}

function zoomIn() {
  zoomScale.value = Math.min(4.5, Number((zoomScale.value + 0.2).toFixed(2)));
}

function zoomOut() {
  zoomScale.value = Math.max(0.4, Number((zoomScale.value - 0.2).toFixed(2)));
}

function resetView() {
  zoomScale.value = 1;
  panX.value = 0;
  panY.value = 0;
}

function startPan(e: MouseEvent) {
  if (e.button !== 0) return;
  isPanning = true;
  startMouseX = e.clientX;
  startMouseY = e.clientY;
  initialPanX = panX.value;
  initialPanY = panY.value;
}

function doPan(e: MouseEvent) {
  if (!isPanning) {
    tooltipX.value = e.clientX + 16;
    tooltipY.value = e.clientY + 16;
    return;
  }
  panX.value = initialPanX + (e.clientX - startMouseX);
  panY.value = initialPanY + (e.clientY - startMouseY);
}

function endPan() {
  isPanning = false;
}

// 文件解析加载
function handleFileUpload(e: Event) {
  const input = e.target as HTMLInputElement;
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  if (!file) return;
  fileName.value = file.name;
  
  const reader = new FileReader();
  reader.onload = (event) => {
    const text = event.target?.result as string;
    loadSequenceData(text, file.name);
  };
  reader.readAsText(file);
}

function loadSequenceData(content: string, name: string) {
  isComputing.value = true;
  setTimeout(() => {
    try {
      if (content.includes("LOCUS") || content.includes("FEATURES")) {
        const parsed = parseGenBank(content);
        rawSequence.value = parsed.sequence;
        sequenceLength.value = parsed.sequence.length;
        features.value = parsed.features;
      } else {
        const parsed = parseFasta(content);
        rawSequence.value = parsed.sequence;
        sequenceLength.value = parsed.sequence.length;
        features.value = [];
      }
      fileName.value = name;
      resetView();
    } catch (err) {
      console.error("解析序列失败:", err);
    } finally {
      isComputing.value = false;
    }
  }, 50);
}

// 复制与导出
function copySequence() {
  if (!selectedFeature.value) return;
  const seq = extractFeatureSequence(rawSequence.value, selectedFeature.value.start, selectedFeature.value.end, selectedFeature.value.strand);
  navigator.clipboard.writeText(seq);
  showToast("核酸 CDS 序列已成功复制到剪贴板");
}

function copyTranslation() {
  if (!selectedFeature.value) return;
  let trans = selectedFeature.value.translation;
  if (!trans && rawSequence.value) {
    const dna = extractFeatureSequence(rawSequence.value, selectedFeature.value.start, selectedFeature.value.end, selectedFeature.value.strand);
    trans = translateDNA(dna);
  }
  navigator.clipboard.writeText(trans || "");
  showToast("蛋白质多肽翻译序列已成功复制到剪贴板");
}

function exportImage(format: "png" | "svg") {
  if (!svgRef.value) return;
  const svgEl = svgRef.value;
  const serializer = new XMLSerializer();
  let svgString = serializer.serializeToString(svgEl);

  if (format === "svg") {
    // 注入基础字体与背景定义
    const svgHeader = `<?xml version="1.0" standalone="no"?>\r\n`;
    const blob = new Blob([svgHeader + svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${fileName.value || "genome_map"}.svg`;
    link.click();
    URL.revokeObjectURL(url);
    showToast("SVG 矢量图已成功导出");
  } else {
    const canvas = document.createElement("canvas");
    const bbox = svgEl.getBoundingClientRect();
    const scale = 2;
    canvas.width = (bbox.width || 1200) * scale;
    canvas.height = (bbox.height || 900) * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const img = new Image();
    const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    
    img.onload = () => {
      ctx.drawImage(img, 0, 0, bbox.width, bbox.height);
      URL.revokeObjectURL(url);
      const pngUrl = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = pngUrl;
      link.download = `${fileName.value || "genome_map"}.png`;
      link.click();
      showToast("PNG 高清图片已成功导出");
    };
    img.src = url;
  }
}

// 监听跨模块初始数据加载
watch(
  () => props.initialGbk,
  (newGbk) => {
    if (newGbk) {
      loadSequenceData(newGbk, props.initialName || "Annotated_Phage.gbk");
    }
  },
  { immediate: true }
);
</script>

<style scoped>
.genome-viewer-module {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1e293b;
  position: relative;
  overflow: hidden;
}

/* 顶部轻量 Toast */
.floating-toast {
  position: absolute;
  top: 60px;
  left: 50%;
  transform: translateX(-50%);
  background: #0f172a;
  color: #ffffff;
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  animation: fade-in-down 0.2s ease-out;
}

@keyframes fade-in-down {
  from { opacity: 0; transform: translate(-50%, -10px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}

/* 顶部工具栏 */
.viewer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  z-index: 20;
}

.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: #2563eb;
  color: #ffffff;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.upload-btn:hover {
  background: #1d4ed8;
}

.current-file-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  font-size: 13px;
}

.file-icon-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

.file-name {
  font-weight: 600;
  color: #0f172a;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seq-len, .gc-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
}

.view-mode-tabs {
  display: flex;
  background: #e2e8f0;
  padding: 2px;
  border-radius: 8px;
  gap: 2px;
}

.view-mode-tabs button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.view-mode-tabs button.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.track-toggle-group {
  display: flex;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}

.track-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
  cursor: pointer;
}

.track-btn.active {
  background: #ffffff;
  color: #2563eb;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.toggle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.gc-dot {
  background: #10b981;
}

.export-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.export-btn.primary {
  background: #0f172a;
  color: #ffffff;
  border: 1px solid #0f172a;
}

.export-btn.primary:hover {
  background: #334155;
}

.export-btn.secondary {
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.export-btn.secondary:hover {
  background: #f8fafc;
}

/* 主工作区 */
.viewer-main {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
}

/* 左侧侧边栏 */
.features-sidebar {
  width: 340px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
}

.sidebar-header {
  padding: 14px 16px;
  border-bottom: 1px solid #f1f5f9;
}

.sidebar-title-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-title {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.feat-total-tag {
  font-size: 11px;
  background: #f1f5f9;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}

.filter-box {
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fcfdfe;
}

.search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.search-input-wrap svg {
  position: absolute;
  left: 10px;
}

.search-input-wrap input {
  width: 100%;
  padding: 7px 28px 7px 30px;
  font-size: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  outline: none;
}

.search-input-wrap input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.clear-btn {
  position: absolute;
  right: 8px;
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
}

.filter-selectors {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.filter-select {
  width: 100%;
  padding: 6px 10px;
  font-size: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #334155;
  outline: none;
}

.strand-toggle {
  display: flex;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}

.strand-toggle button {
  flex: 1;
  padding: 4px;
  border: none;
  background: transparent;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  border-radius: 4px;
  cursor: pointer;
}

.strand-toggle button.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.features-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.feature-card {
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--accent-color);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.feature-card:hover {
  border-color: #cbd5e1;
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
}

.feature-card.active {
  background: #f0f9ff;
  border-color: #38bdf8;
  border-left-width: 5px;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.12);
}

.feature-card.dimmed {
  opacity: 0.35;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.locus-badge {
  font-size: 11px;
  font-weight: 700;
  color: #0f172a;
}

.strand-pill {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}

.strand-pill.plus {
  background: #ecfdf5;
  color: #059669;
}

.strand-pill.minus {
  background: #fef2f2;
  color: #dc2626;
}

.pos-range {
  font-size: 11px;
  color: #64748b;
  font-family: monospace;
}

.card-product {
  font-size: 12px;
  font-weight: 500;
  color: #334155;
  line-height: 1.35;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.category-chip {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}

.length-chip {
  font-size: 10px;
  color: #94a3b8;
}

.no-features-tip {
  text-align: center;
  padding: 30px 10px;
  color: #94a3b8;
  font-size: 12px;
}

/* 画布区域 */
.canvas-area {
  flex: 1;
  background: #ffffff;
  position: relative;
  overflow: hidden;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  color: #64748b;
}

.empty-icon-pulse {
  animation: float-pulse 3s infinite ease-in-out;
  margin-bottom: 16px;
}

@keyframes float-pulse {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

.empty-state h3 {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
}

.supported-formats {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  font-size: 12px;
}

.fmt-tag {
  padding: 3px 8px;
  border-radius: 4px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-weight: 600;
  color: #334155;
}

.svg-container {
  width: 100%;
  height: 100%;
  cursor: grab;
  position: relative;
}

.svg-container:active {
  cursor: grabbing;
}

.genome-svg {
  width: 100%;
  height: 100%;
  user-select: none;
}

.track-backbone.outer {
  fill: none;
  stroke: #e2e8f0;
  stroke-width: 1.5;
}

.track-backbone.inner {
  fill: none;
  stroke: #f1f5f9;
  stroke-width: 1.5;
}

.track-split {
  fill: none;
  stroke: #e2e8f0;
  stroke-dasharray: 2 2;
  stroke-width: 1;
}

.tick-text-circular {
  font-size: 11px;
  fill: #475569;
  font-family: monospace;
  font-weight: 600;
}

.linear-backbone {
  stroke: #0f172a;
  stroke-width: 2;
}

.linear-tick-label {
  font-size: 11px;
  fill: #64748b;
  font-family: monospace;
}

.feature-glyph {
  cursor: pointer;
  transition: opacity 0.15s ease, filter 0.15s ease;
}

.feature-glyph:hover {
  filter: brightness(1.15) drop-shadow(0 2px 4px rgba(0, 0, 0, 0.15));
  opacity: 1 !important;
}

.feature-glyph.is-selected {
  filter: drop-shadow(0 0 6px rgba(37, 99, 235, 0.5));
  opacity: 1 !important;
}

.feature-glyph.is-dimmed {
  opacity: 0.18;
}

.selected-highlight-stroke {
  animation: pulse-stroke 2s infinite ease-in-out;
}

@keyframes pulse-stroke {
  0%, 100% { stroke-opacity: 1; }
  50% { stroke-opacity: 0.5; }
}

/* 环形中心数据看板 (紧凑型) */
.center-bg {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.center-title {
  font-size: 12px;
  font-weight: 700;
  fill: #0f172a;
}

.center-length {
  font-size: 14px;
  font-weight: 800;
  fill: #2563eb;
  font-family: monospace;
}

.center-sub {
  font-size: 10px;
  fill: #64748b;
  font-weight: 500;
}

.center-cds-count {
  font-size: 10px;
  fill: #10b981;
  font-weight: 600;
}

/* 悬浮图例徽章栏 */
.floating-legend {
  position: absolute;
  right: 16px;
  top: 16px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  z-index: 10;
  max-width: 240px;
}

.legend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 4px;
}

.reset-legend-btn {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 10px;
  cursor: pointer;
  font-weight: 600;
}

.legend-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.12s ease;
}

.legend-item:hover {
  background: #f1f5f9;
}

.legend-item.active {
  background: #e0f2fe;
  font-weight: 600;
}

.color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.legend-label {
  flex: 1;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.legend-count {
  font-size: 10px;
  color: #94a3b8;
  font-family: monospace;
}

.gc-legend-sub {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid #f1f5f9;
  font-size: 10px;
  color: #64748b;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.gc-legend-title {
  font-weight: 700;
  color: #334155;
  margin-bottom: 2px;
}

.gc-legend-row {
  display: flex;
  align-items: center;
  gap: 5px;
}

.gc-box {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.gc-box.green { background: #10b981; }
.gc-box.gray { background: #64748b; }
.gc-box.purple { background: #8b5cf6; }
.gc-box.orange { background: #f59e0b; }

/* 悬浮微型卡片 Tooltip */
.floating-tooltip {
  position: fixed;
  pointer-events: none;
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(6px);
  color: #ffffff;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  z-index: 50;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  max-width: 280px;
}

.tt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.tt-locus {
  font-weight: 700;
  font-size: 12px;
  color: #38bdf8;
}

.tt-cat-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}

.tt-product {
  font-weight: 500;
  color: #f1f5f9;
  line-height: 1.3;
  margin-bottom: 6px;
}

.tt-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: #94a3b8;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 4px;
}

/* 视口操控悬浮工具组 */
.viewport-controls {
  position: absolute;
  right: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  z-index: 20;
}

.viewport-controls button {
  padding: 8px;
  border: none;
  background: transparent;
  color: #475569;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s ease;
}

.viewport-controls button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.viewport-controls button:not(:last-child) {
  border-bottom: 1px solid #f1f5f9;
}

/* 选中基因深度详情抽屉 */
.feature-inspector-drawer {
  position: absolute;
  left: 20px;
  right: 20px;
  bottom: 20px;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(12px);
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 14px 18px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 220px;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.drawer-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-icon-tag {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.drawer-locus {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.drawer-cat-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.drawer-close {
  border: none;
  background: transparent;
  font-size: 18px;
  color: #94a3b8;
  cursor: pointer;
  line-height: 1;
}

.drawer-close:hover {
  color: #0f172a;
}

.drawer-body {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px 16px;
  font-size: 12px;
}

.info-row {
  display: flex;
  gap: 6px;
}

.info-k {
  color: #64748b;
  font-weight: 600;
  flex-shrink: 0;
}

.info-v {
  color: #334155;
}

.info-v.highlight {
  color: #0f172a;
  font-weight: 600;
}

.info-v.note-text {
  font-family: monospace;
  font-size: 11px;
  color: #475569;
}

.drawer-actions {
  display: flex;
  gap: 10px;
  border-top: 1px solid #f1f5f9;
  padding-top: 8px;
}

.act-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #cbd5e1;
  cursor: pointer;
  transition: all 0.12s ease;
}

.act-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}

/* 全局高阶运算加载遮罩 */
.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 100;
  gap: 12px;
}

.spinner-xl {
  width: 42px;
  height: 42px;
  border: 3px solid #e2e8f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.loading-text {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
