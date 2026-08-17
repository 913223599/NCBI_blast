<template>
  <div class="genome-viewer-module">
    <!-- 全局加载遮罩 -->
    <div v-if="isComputing" class="loading-overlay">
      <div class="spinner-xl"></div>
      <div class="loading-text">正在进行高强度基因组运算...</div>
    </div>

    <!-- 顶部工具栏 -->
    <header class="viewer-toolbar">
      <div class="toolbar-left">
        <div class="file-upload-mini">
          <input type="file" id="seq-upload" hidden @change="handleFileUpload" accept=".fasta,.fa,.gbk,.gb,.gff" />
          <label for="seq-upload" class="upload-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            打开序列文件
          </label>
        </div>
        <div v-if="fileName" class="current-file">
          <span class="file-icon">🧬</span>
          <span class="file-name">{{ fileName }}</span>
          <span class="seq-len">{{ formatLength(sequenceLength) }}</span>
        </div>
      </div>

      <div class="toolbar-center" v-if="sequenceLength > 0">
        <div class="view-switcher">
          <button :class="{ active: viewMode === 'circular' }" @click="viewMode = 'circular'">环形图谱</button>
          <button :class="{ active: viewMode === 'linear' }" @click="viewMode = 'linear'">线性图谱</button>
        </div>
      </div>

      <div class="toolbar-right">
        <button v-if="sequenceLength > 0" class="export-btn" @click="exportImage">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1M16 10l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          导出图片
        </button>
      </div>
    </header>

    <div class="viewer-main">
      <!-- 侧边栏 -->
      <aside class="features-sidebar">
        <div class="sidebar-header">
          <span>基因特征定位 (SnapGene 风格)</span>
        </div>

        <div class="viewer-controls">
          <div class="control-group">
            <label>搜索特征</label>
            <input type="text" v-model="searchQuery" placeholder="输入基因名定位..." />
          </div>
        </div>

        <div class="features-list">
          <div v-for="(feat, idx) in filteredFeatures" :key="idx" class="feature-item"
            :class="{ active: selectedFeature === feat }" :style="{ borderLeftColor: getFeatureColor(feat.type) }"
            @click="selectFeature(feat)">
            <div class="feat-top" style="align-items: center; margin-bottom: 4px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="feat-type">{{ feat.type }}</span>
                <span class="feat-strand" :class="feat.strand === '+' ? 'plus' : 'minus'" style="padding: 2px 6px; border-radius: 4px; background: #f8fafc; border: 1px solid #f1f5f9; line-height: 1;">
                  {{ feat.strand === '+' ? '▶ 正向' : '◀ 反向' }}
                </span>
              </div>
              <span class="feat-range">{{ feat.start }}-{{ feat.end }}</span>
            </div>
            <div class="feat-name" style="margin: 0; line-height: 1.4;">{{ feat.name || 'Unnamed' }}</div>
          </div>
        </div>
      </aside>

      <!-- 画布区域 -->
      <section class="canvas-area" ref="canvasArea">
        <div v-if="!sequenceLength" class="empty-state">
          <div class="empty-icon">🧬</div>
          <h3>科研级序列查看器已就绪</h3>
          <p>请点击左上角“打开序列文件”加载数据</p>
          <p class="empty-sub">支持 GBK/GB/FASTA 格式，纯前端极速渲染</p>
        </div>

        <div v-else class="svg-container" @wheel="handleZoom" @mousedown="startPan" @mousemove="doPan" @mouseup="endPan"
          @mouseleave="endPan" @click="handleCanvasClick">

          <!-- SnapGene toolbar -->
          <div class="sg-toolbar" :style="{ left: toolbarX + 'px', top: toolbarY + 'px', transform: 'none' }" @mousedown.stop>
            <div class="sg-drag-handle" @mousedown.stop.prevent="startDragToolbar" title="拖动">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                 <circle cx="8" cy="6" r="2"/><circle cx="16" cy="6" r="2"/>
                 <circle cx="8" cy="12" r="2"/><circle cx="16" cy="12" r="2"/>
                 <circle cx="8" cy="18" r="2"/><circle cx="16" cy="18" r="2"/>
              </svg>
            </div>
            
            <!-- Enzymes button -->
            <div class="sg-btn-wrap" @mouseenter="activePanel = 'enzyme'" @mouseleave="activePanel = ''">
              <button class="sg-btn" :class="{ active: showEnzymes }" title="内切酶位点">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>
                <span class="sg-arrow">&#9656;</span>
              </button>
              <div class="sg-flyout" v-show="activePanel === 'enzyme'">
                <div class="sg-flyout-inner">
                  <label class="sg-menu-item" :class="{ checked: showEnzymes }">
                    <input type="checkbox" v-model="showEnzymes" /> 常见内切酶位点
                  </label>
                </div>
              </div>
            </div>

            <!-- Feature display button -->
            <div class="sg-btn-wrap" @mouseenter="activePanel = 'feature'" @mouseleave="activePanel = ''">
              <button class="sg-btn" :class="{ active: true }" title="特征显示">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <span class="sg-arrow">&#9656;</span>
              </button>
              <div class="sg-flyout" v-show="activePanel === 'feature'">
                <div class="sg-flyout-inner">
                  <div class="sg-menu-item checked">显示特征图形</div>
                  <div class="sg-menu-item checked">显示特征标签</div>
                </div>
              </div>
            </div>

            <!-- GC content button -->
            <div class="sg-btn-wrap" @mouseenter="activePanel = 'gc'" @mouseleave="activePanel = ''">
              <button class="sg-btn" :class="{ active: showGC }" title="GC 含量">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                <span class="sg-arrow">&#9656;</span>
              </button>
              <div class="sg-flyout" v-show="activePanel === 'gc'">
                <div class="sg-flyout-inner">
                  <label class="sg-menu-item" :class="{ checked: showGC }">
                    <input type="checkbox" v-model="showGC" /> GC 含量与偏斜
                  </label>
                </div>
              </div>
            </div>

            <!-- ORF button -->
            <div class="sg-btn-wrap" @mouseenter="activePanel = 'orf'" @mouseleave="activePanel = ''">
              <button class="sg-btn" :class="{ active: selectedORFFrames.length > 0 }" title="ORF 阅读框架">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3l4 4-4 4M7 21l-4-4 4-4"/><path d="M21 7H9M3 17h12"/></svg>
                <span class="sg-arrow">&#9656;</span>
              </button>
              <div class="sg-flyout" v-show="activePanel === 'orf'">
                <div class="sg-flyout-inner">
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.length === 0 }" @click="selectedORFFrames = []">只有开放阅读框架</div>
                  <div class="sg-divider"></div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('+1') }" @click="toggleFrame('+1')">仅 框架 +1</div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('+2') }" @click="toggleFrame('+2')">仅 框架 +2</div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('+3') }" @click="toggleFrame('+3')">仅 框架 +3</div>
                  <div class="sg-divider"></div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('-1') }" @click="toggleFrame('-1')">仅 框架 -1</div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('-2') }" @click="toggleFrame('-2')">仅 框架 -2</div>
                  <div class="sg-menu-item" :class="{ checked: selectedORFFrames.includes('-3') }" @click="toggleFrame('-3')">仅 框架 -3</div>
                  <div class="sg-divider"></div>
                  <div class="sg-menu-item" @click="selectedORFFrames = ['+1','+2','+3']">顶部 3 个框架</div>
                  <div class="sg-menu-item" @click="selectedORFFrames = ['-1','-2','-3']">底部 3 个框架</div>
                  <div class="sg-menu-item" @click="selectedORFFrames = ['+1','+2','+3','-1','-2','-3']">所有 6 个框架</div>
                </div>
              </div>
            </div>

            <!-- Position numbers button -->
            <div class="sg-btn-wrap">
              <button class="sg-btn" :class="{ active: showPositions }" @click="showPositions = !showPositions" title="显示位置">
                <span style="font-size: 10px; font-weight: 700; line-height: 1;">(123)</span>
              </button>
            </div>
          </div>
          <!-- 环形视图 -->
          <svg v-if="viewMode === 'circular'" ref="svgRef" width="100%" height="100%" class="genome-svg">
            <svg x="50%" y="50%" overflow="visible">
              
              <!-- 图形层 (逻辑原生缩放) -->
              <g :transform="`translate(${panX}, ${panY})`">
                <!-- 轨道基准线 -->
                <circle cx="0" cy="0" :r="zoomedBaseRadius" class="backbone" vector-effect="non-scaling-stroke" />
                
                <!-- 刻度线 -->
                <g class="rulers">
                  <line 
                    v-for="(tick, i) in ticks" :key="'tick'+i"
                    :x1="tick.x1" :y1="tick.y1" :x2="tick.x2" :y2="tick.y2"
                    stroke="#94a3b8" :stroke-width="tick.major ? 2 : 1"
                    vector-effect="non-scaling-stroke"
                  />
                </g>

                <!-- 附加轨道：GC 与 Skew -->
                <g class="gc-layer" v-if="showGC">
                  <path :d="gcPaths.gcPathData" fill="none" stroke="#3b82f6" stroke-width="1.5" opacity="0.8" vector-effect="non-scaling-stroke" />
                  <path :d="gcPaths.gcSkewPathData" fill="none" stroke="#f59e0b" stroke-width="1.5" opacity="0.8" vector-effect="non-scaling-stroke" />
                  <circle v-if="currentLayout.getLayer('main-gc')" cx="0" cy="0" :r="(currentLayout.getLayer('main-gc')!.bounds.innerR + currentLayout.getLayer('main-gc')!.bounds.outerR)/2" fill="none" stroke="#cbd5e1" stroke-dasharray="4" vector-effect="non-scaling-stroke" />
                  <circle v-if="currentLayout.getLayer('main-gc-skew')" cx="0" cy="0" :r="(currentLayout.getLayer('main-gc-skew')!.bounds.innerR + currentLayout.getLayer('main-gc-skew')!.bounds.outerR)/2" fill="none" stroke="#cbd5e1" stroke-dasharray="4" vector-effect="non-scaling-stroke" />
                </g>

                <!-- 附加轨道：Enzymes (线段置于底层) -->
                <g class="enzyme-layer" v-if="showEnzymes">
                   <template v-for="(f, i) in renderCircularEnzymes" :key="'enz_path'+i">
                     <path v-if="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())"
                       :d="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())?.line" 
                       fill="none" :stroke="f.color" stroke-width="1.5"
                       vector-effect="non-scaling-stroke"
                     />
                   </template>
                </g>

                <!-- 附加轨道：ORF -->
                <g class="orf-layer" v-if="selectedORFFrames.length > 0">
                  <template v-for="frame in selectedORFFrames" :key="'orf_layer_' + frame">
                    <path 
                      v-for="(f, i) in filteredOrfFeatures.filter(x => x.frame === frame)" :key="'orf'+frame+i"
                      :d="getCircularPath(f, sequenceLength, currentLayout.getLayer('main-orf-'+frame)!.bounds)"
                      :fill="f.color"
                      :opacity="selectedFeature && selectedFeature === f ? 0.9 : 0.3"
                      class="feature-path"
                      @click.stop="selectFeature(f)"
                    ><title>{{ f.name }} [{{ f.start }}..{{ f.end }}]</title></path>
                  </template>
                </g>

                <!-- 特征图形 -->
                <g class="features-layer">
                  <path 
                    v-for="(f, i) in renderFeatures" 
                    :key="'f'+i"
                    :d="getCircularPath(f, sequenceLength, currentLayout.getLayer('main-cds')!.rows[f.track] || currentLayout.getLayer('main-cds')!.bounds)"
                    :fill="getFeatureColor(f.type)"
                    :opacity="selectedFeature && selectedFeature !== f ? 0.3 : 0.85"
                    class="feature-path"
                    @click.stop="selectFeature(f)"
                  >
                    <title>{{ f.name }} [{{ f.start }}..{{ f.end }}]</title>
                  </path>
                </g>
                
                <!-- 选中特征的高亮描边 -->
                <path 
                  v-if="selectedFeature && selectedFeature.type === 'CDS'"
                  :d="getCircularPath(selectedFeature, sequenceLength, currentLayout.getLayer('main-cds')!.rows[selectedFeature.track] || currentLayout.getLayer('main-cds')!.bounds)"
                  fill="none" stroke="#0f172a" stroke-width="2"
                  vector-effect="non-scaling-stroke"
                  style="pointer-events: none;"
                />
              </g>

              <!-- 文本层 (绝对14px，规避浏览器缩小限制) -->
              <g :transform="`translate(${panX}, ${panY})`" v-if="showPositions">
                <!-- 刻度文本 -->
                <text 
                  v-for="(tick, i) in majorTicks" :key="'text'+i"
                  :x="tick.tx" :y="tick.ty" 
                  :text-anchor="tick.anchor" 
                  dominant-baseline="middle"
                  :transform="`rotate(${tick.rot}, ${tick.tx}, ${tick.ty})`"
                  class="tick-text"
                  style="font-size: 14px;"
                >{{ tick.label }}</text>

                <g v-if="showEnzymes">
                  <template v-for="(f, i) in renderCircularEnzymes" :key="'enz_text'+i">
                    <text v-if="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())"
                      :x="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())!.textX" 
                      :y="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())!.textY"
                      :text-anchor="getEnzymeCircularLabel(f, sequenceLength, zoomedBaseRadius, currentLayout.getOuterBoundary())!.anchor"
                      dominant-baseline="middle"
                      style="font-size: 14px; font-weight: 700;"
                      :fill="f.color"
                    >{{ f.name }}</text>
                  </template>
                </g>
              </g>
              
            </svg>
          </svg>

          <!-- 线性视图 -->
          <svg v-else ref="svgRef" width="100%" height="100%" class="genome-svg linear-svg">
            <!-- 垂直居中 -->
            <svg x="0" y="50%" overflow="visible">
              <g :transform="`translate(${panX}, 0)`">
                <line x1="0" y1="0" :x2="computedLinearWidth" y2="0" class="backbone" />
                <!-- 线性刻度 -->
                <g class="rulers">
                  <line v-for="(tick, i) in ticks" :key="'ltick' + i" :x1="tick.lx" y1="-5" :x2="tick.lx"
                    :y2="tick.major ? 5 : 2" stroke="#94a3b8" :stroke-width="tick.major ? 2 : 1" />
                  <text v-for="(tick, i) in majorTicks" :key="'ltext' + i" :x="tick.lx" y="-15" text-anchor="middle"
                    class="tick-text" style="font-size: 14px;">{{ tick.label }}</text>
                </g>

              <!-- 附加图形：Enzymes 置于底层 -->
              <g class="enzyme-layer" v-if="showEnzymes">
                <template v-for="(f, i) in renderLinearEnzymes" :key="'lenz' + i">
                  <path :d="getEnzymeLinearLabel(f, sequenceLength, computedLinearWidth)?.line" fill="none"
                    :stroke="f.color" stroke-width="1.5" opacity="0.6" />
                  <text :x="getEnzymeLinearLabel(f, sequenceLength, computedLinearWidth)?.textX"
                    :y="getEnzymeLinearLabel(f, sequenceLength, computedLinearWidth)?.textY" text-anchor="middle"
                    font-size="14" :fill="f.color" font-weight="700">{{ f.name }}</text>
                </template>
              </g>

              <g class="orf-layer" v-if="selectedORFFrames.length > 0">
                <template v-for="frame in selectedORFFrames" :key="'lorf_layer_' + frame">
                  <path v-for="(f, i) in filteredOrfFeatures.filter(x => x.frame === frame)" :key="'lorf' + frame + i"
                    :d="getLinearPath(f, sequenceLength, computedLinearWidth, { linearY: currentLayout.getLayer('main-orf-'+frame)!.bounds.linearY, rowHeight: trackWidth })" 
                    :fill="f.color"
                    :opacity="selectedFeature && selectedFeature === f ? 0.9 : 0.3"
                    class="feature-path"
                    @click.stop="selectFeature(f)"
                  />
                </template>
              </g>

              <!-- 特征图形 -->
              <g class="features-layer">
                <path v-for="(f, i) in renderFeatures" :key="'lf' + i"
                  :d="getLinearPath(f, sequenceLength, computedLinearWidth, { linearY: currentLayout.getLayer('main-cds')!.rows[f.track]?.linearY ?? currentLayout.getLayer('main-cds')!.bounds.linearY, rowHeight: trackWidth })" :fill="getFeatureColor(f.type)"
                  :opacity="selectedFeature && selectedFeature !== f ? 0.3 : 0.85" class="feature-path"
                  @click.stop="selectFeature(f)">
                  <title>{{ f.name }} [{{ f.start }}..{{ f.end }}]</title>
                </path>
              </g>
                <!-- 选中高亮 -->
                <path v-if="selectedFeature && selectedFeature.type === 'CDS'"
                  :d="getLinearPath(selectedFeature, sequenceLength, computedLinearWidth, { linearY: currentLayout.getLayer('main-cds')!.rows[selectedFeature.track]?.linearY ?? currentLayout.getLayer('main-cds')!.bounds.linearY, rowHeight: trackWidth })" fill="none"
                  stroke="#0f172a" stroke-width="2" style="pointer-events: none;" />
              </g>
            </svg>
          </svg>
        </div>

        <!-- 悬浮信息面板 -->
        <div class="feature-tooltip" v-if="selectedFeature">
          <h4>{{ selectedFeature.name || 'Unnamed Feature' }}</h4>
          <div class="tt-row"><span>Type:</span> {{ selectedFeature.type }}</div>
          <div class="tt-row"><span>Range:</span> {{ selectedFeature.start }} - {{ selectedFeature.end }}</div>
          <div class="tt-row"><span>Strand:</span> {{ selectedFeature.strand === '+' ? 'Forward (+)' : 'Reverse (-)' }}
          </div>

          <div class="tt-actions" v-if="rawSequence">
            <button @click="handleCopySequence" class="action-btn">复制 DNA 序列</button>
            <button @click="handleCopyTranslation" class="action-btn"
              v-if="selectedFeature.type === 'CDS'">复制氨基酸翻译</button>
          </div>
          <button class="close-tt" @click="selectedFeature = null">✖</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, triggerRef, onMounted } from 'vue';
import { parseGenBank, parseFasta } from './utils/parser';
import { calculateGC, calculateORFs, calculateEnzymes } from './utils/calculations';
import { getCircularPath, getLinearPath, getEnzymeCircularLabel, getEnzymeLinearLabel, getFeatureColor, formatLength } from './utils/render';
import { extractFeatureSequence, translateDNA } from './utils/sequence';
import { TrackLayoutEngine } from './core/TrackLayoutEngine';

const props = defineProps<{
  initialGbk?: string;
  initialName?: string;
}>();

// --- State ---
const fileName = ref('');
const sequenceLength = ref(0);
const rawSequence = ref('');
const features = ref<any[]>([]);
const viewMode = ref<'circular' | 'linear'>('circular');
const searchQuery = ref('');
const selectedFeature = ref<any>(null);
const isComputing = ref(false);

const showGC = ref(false);
const selectedORFFrames = ref<string[]>([]);
const showEnzymes = ref(true);
const showPositions = ref(true);
const activePanel = ref('');

// Toolbar drag state
const toolbarX = ref(12);
const toolbarY = ref(200);
let isDraggingToolbar = false;
let tbDragStartX = 0;
let tbDragStartY = 0;
let initialTbX = 0;
let initialTbY = 0;

function startDragToolbar(e: MouseEvent) {
  isDraggingToolbar = true;
  tbDragStartX = e.clientX;
  tbDragStartY = e.clientY;
  initialTbX = toolbarX.value;
  initialTbY = toolbarY.value;
  document.addEventListener('mousemove', onDragToolbar);
  document.addEventListener('mouseup', stopDragToolbar);
}

function onDragToolbar(e: MouseEvent) {
  if (!isDraggingToolbar) return;
  toolbarX.value = initialTbX + (e.clientX - tbDragStartX);
  toolbarY.value = initialTbY + (e.clientY - tbDragStartY);
}

function stopDragToolbar() {
  isDraggingToolbar = false;
  document.removeEventListener('mousemove', onDragToolbar);
  document.removeEventListener('mouseup', stopDragToolbar);
}

function toggleFrame(frame: string) {
  const idx = selectedORFFrames.value.indexOf(frame);
  if (idx >= 0) {
    selectedORFFrames.value.splice(idx, 1);
  } else {
    selectedORFFrames.value.push(frame);
  }
}

const gcPathData = ref('');
const gcSkewPathData = ref('');
const orfFeatures = ref<any[]>([]);
const enzymeFeatures = ref<any[]>([]);

const layoutEngine = ref(new TrackLayoutEngine());
const layoutTrigger = ref(0);

// Dynamic base radius scaled with zoomLevel
const zoomedBaseRadius = computed(() => baseRadius * zoomLevel.value);

// Computed view layout
const currentLayout = computed(() => {
  layoutTrigger.value; // subscribe to trigger
  return layoutEngine.value.resolveLayout(zoomedBaseRadius.value);
});
const baseRadius = 350;
const trackWidth = 14;
const linearWidth = 1200;

// --- Canvas Interaction ---
const zoomLevel = ref(1);
const panX = ref(0);
const panY = ref(0);
let isDragging = false;
let startX = 0;
let startY = 0;
let dragStartX = 0;
let dragStartY = 0;

// --- Computed ---
const renderFeatures = computed(() => {
  return features.value; // Here we could add logic for Hidden Legend Toggles
});

const computedLinearWidth = computed(() => linearWidth * zoomLevel.value);

const filteredFeatures = computed(() => {
  // 将勾选的 ORF 也无缝汇入左侧列表，支持搜索和点击
  let activeList = features.value;
  if (selectedORFFrames.value.length > 0) {
    activeList = [...activeList, ...filteredOrfFeatures.value].sort((a, b) => a.start - b.start);
  }

  if (!searchQuery.value) return activeList.slice(0, 200);
  
  const q = searchQuery.value.toLowerCase();
  return activeList.filter(f =>
    (f.name && f.name.toLowerCase().includes(q)) ||
    f.type.toLowerCase().includes(q)
  ).slice(0, 200);
});

// 解析引擎
// 解析引擎
function loadFromText(text: string, name: string, isGbk: boolean) {
  if (!text) return;
  fileName.value = name || 'Annotated_Genome';

  let parsed;
  if (isGbk) {
    parsed = parseGenBank(text);
  } else {
    parsed = parseFasta(text);
  }

  rawSequence.value = parsed.sequence;
  sequenceLength.value = parsed.sequence.length;

  // 清空旧缓存并重置视图
  gcPathData.value = ''; gcSkewPathData.value = '';
  orfFeatures.value = []; enzymeFeatures.value = [];
  showGC.value = false; selectedORFFrames.value = []; showEnzymes.value = false;
  
  // Reset layout engine
  layoutEngine.value = new TrackLayoutEngine();
  layoutEngine.value.addGroup('main', 0);

  const trackEnds = new Array(20).fill(0);
  const sortedFeatures = parsed.features.sort((a: any, b: any) => a.start - b.start);

  let maxTrack = 0;
  sortedFeatures.forEach((f: any) => {
    let assignedTrack = 0;
    for (let i = 0; i < 20; i++) {
      if (f.start > trackEnds[i] + 100) {
        assignedTrack = i;
        trackEnds[i] = f.end;
        break;
      }
    }
    f.track = assignedTrack;
    if (assignedTrack > maxTrack) maxTrack = assignedTrack;
  });
  
  layoutEngine.value.setLayer({
    id: 'main-cds', groupId: 'main', type: 'feature', direction: 'outer',
    rowHeight: trackWidth + 4, rowCount: maxTrack + 1, gap: 10, order: 0
  });
  layoutTrigger.value++;

  features.value = sortedFeatures;
  zoomLevel.value = 1; panX.value = 0; panY.value = 0;
  selectedFeature.value = null;
}

function handleFileUpload(e: any) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (event) => {
    const text = event.target?.result as string;
    const ext = file.name.split('.').pop()?.toLowerCase();
    const isGbk = !!(ext && ['gbk', 'gb', 'genbank'].includes(ext));
    loadFromText(text, file.name, isGbk);
  };
  reader.readAsText(file);
}

onMounted(() => {
  if (props.initialGbk) {
    loadFromText(props.initialGbk, props.initialName || 'Annotated_Genome.gbk', true);
  }
});

watch(() => props.initialGbk, (newVal) => {
  if (newVal) {
    loadFromText(newVal, props.initialName || 'Annotated_Genome.gbk', true);
  }
});

// 附加计算监听
watch(showGC, (val) => {
  if (val) {
    layoutEngine.value.setLayer({ id: 'main-gc', groupId: 'main', type: 'graph', direction: 'inner', rowHeight: 40, rowCount: 1, gap: 5, order: Date.now() });
    layoutEngine.value.setLayer({ id: 'main-gc-skew', groupId: 'main', type: 'graph', direction: 'inner', rowHeight: 40, rowCount: 1, gap: 10, order: Date.now() + 1 });
    layoutTrigger.value++;
    
    layoutTrigger.value++;
  } else {
    layoutEngine.value.removeLayer('main-gc');
    layoutEngine.value.removeLayer('main-gc-skew');
    layoutTrigger.value++;
  }
});

const gcPaths = computed(() => {
  if (!showGC.value || !rawSequence.value) return { gcPathData: '', gcSkewPathData: '' };
  const layoutMap = currentLayout.value;
  return calculateGC(rawSequence.value, layoutMap.getLayer('main-gc')!.bounds, layoutMap.getLayer('main-gc-skew')!.bounds);
});

watch(() => [...selectedORFFrames.value], (val, oldVal) => {
  // Diff to add or remove tracks in layout engine dynamically
  const added = val.filter(x => !(oldVal || []).includes(x));
  const removed = (oldVal || []).filter(x => !val.includes(x));
  
  for (const frame of added) {
    layoutEngine.value.setLayer({
      id: 'main-orf-' + frame, groupId: 'main', type: 'feature', direction: 'inner',
      rowHeight: trackWidth + 4, rowCount: 1, gap: 2, order: Date.now()
    });
  }
  for (const frame of removed) {
    layoutEngine.value.removeLayer('main-orf-' + frame);
  }
  layoutTrigger.value++;

  if (val.length > 0 && orfFeatures.value.length === 0 && rawSequence.value) {
    orfFeatures.value = calculateORFs(rawSequence.value, features.value);
  }
}, { deep: true });

const filteredOrfFeatures = computed(() => {
  return orfFeatures.value.filter(f => selectedORFFrames.value.includes(f.frame));
});

watch(showEnzymes, (val) => {
  if (val && enzymeFeatures.value.length === 0 && rawSequence.value) {
    enzymeFeatures.value = calculateEnzymes(rawSequence.value);
  }
});

// 动态比例尺步长计算
function getNiceStep(target: number) {
  if (target <= 0) return 100;
  const exponent = Math.floor(Math.log10(target));
  const fraction = target / Math.pow(10, exponent);
  let niceFraction;
  if (fraction < 1.5) niceFraction = 1;
  else if (fraction < 3) niceFraction = 2;
  else if (fraction < 7) niceFraction = 5;
  else niceFraction = 10;
  return Math.max(1, niceFraction * Math.pow(10, exponent));
}

// 刻度生成 (响应式缩放与美观整数)
const ticks = computed(() => {
  if (!sequenceLength.value) return [];
  const res = [];

  // 目标是每隔约 150 像素放置一个主刻度
  const isCircular = viewMode.value === 'circular';
  const widthPx = isCircular ? (2 * Math.PI * baseRadius) * zoomLevel.value : computedLinearWidth.value;

  const targetBp = (150 / widthPx) * sequenceLength.value;
  const majorStep = getNiceStep(targetBp) || 1000;
  const minorStep = Math.max(1, Math.floor(majorStep / 5)); // 每主刻度包含 5 个小刻度

  for (let val = 0; val <= sequenceLength.value; val += minorStep) {
    const angle = (val / sequenceLength.value) * 360;
    const isMajor = Math.abs(Math.round(val) % majorStep) < (minorStep * 0.1);
    const rad = (angle - 90) * Math.PI / 180;

    const r1 = zoomedBaseRadius.value;
    const r2 = isMajor ? zoomedBaseRadius.value - 15 : zoomedBaseRadius.value - 8;
    const lx = (val / sequenceLength.value) * computedLinearWidth.value;

    res.push({
      val: Math.round(val), angle, major: isMajor,
      x1: Math.cos(rad) * r1, y1: Math.sin(rad) * r1,
      x2: Math.cos(rad) * r2, y2: Math.sin(rad) * r2, lx
    });
  }
  return res;
});

const majorTicks = computed(() => {
  return ticks.value.filter(t => t.major).map(t => {
    const rad = (t.angle - 90) * Math.PI / 180;
    const r3 = zoomedBaseRadius.value - 22; // 将文字放置在刻度线内侧

    // 计算文字方向，使其始终呈现放射状，并且不倒字
    const rot = t.angle > 180 ? t.angle + 90 : t.angle - 90;
    const anchor = t.angle > 180 ? 'start' : 'end';

    return {
      ...t,
      tx: Math.cos(rad) * r3,
      ty: Math.sin(rad) * r3,
      rot,
      anchor,
      label: formatLength(t.val)
    };
  });
});

// 内切酶动态避让计算 (基于真实物理坐标与2D包围盒探测)
const renderCircularEnzymes = computed(() => {
  if (!sequenceLength.value || !enzymeFeatures.value.length) return [];
  const sorted = [...enzymeFeatures.value].sort((a, b) => a.start - b.start);
  
  const placedBoxes: { x: number, y: number, w: number, h: number }[] = [];
  
  return sorted.map(enz => {
     const angle = ((enz.start + enz.end) / 2 / sequenceLength.value) * 360;
     const rad = (angle - 90) * Math.PI / 180;
     const isRightHalf = angle <= 180;
     
     // 近似文字尺寸
     const textW = enz.name.length * 8 + 10;
     const textH = 16;
     
     let level = 0;
     while (level < 20) {
         // 完全基于 TrackLayoutEngine 外边界进行排布
         const r2 = currentLayout.value.getOuterBoundary() + 20 + level * 15;
         const p2y = Math.sin(rad) * r2;
         const p2x = Math.cos(rad) * r2;
         
         const hLength = 15;
         const p3x = p2x + (isRightHalf ? hLength : -hLength);
         
         const textX = p3x + (isRightHalf ? 4 : -4);
         const textY = p2y;
         
         // 映射回屏幕绝对像素
         const screenX = textX;
         const screenY = textY;
         
         const boxX = isRightHalf ? screenX : screenX - textW;
         const boxY = screenY - textH / 2;
         
         let collision = false;
         for (const box of placedBoxes) {
             // 2D 碰撞检测 (2px 物理安全间距)
             if (boxX < box.x + box.w + 2 &&
                 boxX + textW + 2 > box.x &&
                 boxY < box.y + box.h + 2 &&
                 boxY + textH + 2 > box.y) {
                 collision = true;
                 break;
             }
         }
         
         if (!collision) {
             placedBoxes.push({ x: boxX, y: boxY, w: textW, h: textH });
             break;
         }
         level++;
     }
     return { ...enz, labelLevel: level };
  });
});

const renderLinearEnzymes = computed(() => {
  if (!sequenceLength.value || !enzymeFeatures.value.length) return [];
  const sorted = [...enzymeFeatures.value].sort((a, b) => a.start - b.start);
  const placedBoxes: { x: number, y: number, w: number, h: number }[] = [];
  
  return sorted.map(enz => {
      const x = ((enz.start + enz.end) / 2 / sequenceLength.value) * computedLinearWidth.value;
      const textW = enz.name.length * 8 + 10;
      const textH = 16;
      
      let level = 0;
      while (level < 20) {
          const textY = -40 - level * 15 - 5;
          const boxX = x - textW / 2;
          const boxY = textY - textH / 2;
          
          let collision = false;
          for (const box of placedBoxes) {
              if (boxX < box.x + box.w + 4 &&
                  boxX + textW + 4 > box.x &&
                  boxY < box.y + box.h + 2 &&
                  boxY + textH + 2 > box.y) {
                  collision = true;
                  break;
              }
          }
          
          if (!collision) {
              placedBoxes.push({ x: boxX, y: boxY, w: textW, h: textH });
              break;
          }
          level++;
      }
      return { ...enz, labelLevel: level };
  });
});

function selectFeature(feat: any) { selectedFeature.value = feat; }

function handleCopySequence() {
  if (!selectedFeature.value) return;
  const seq = extractFeatureSequence(rawSequence.value, selectedFeature.value.start, selectedFeature.value.end, selectedFeature.value.strand);
  navigator.clipboard.writeText(seq);
  alert('DNA 序列已复制到剪贴板！');
}

function handleCopyTranslation() {
  if (!selectedFeature.value) return;
  const seq = extractFeatureSequence(rawSequence.value, selectedFeature.value.start, selectedFeature.value.end, selectedFeature.value.strand);
  navigator.clipboard.writeText(translateDNA(seq));
  alert('翻译结果 (AA) 已复制到剪贴板！');
}

function handleZoom(e: WheelEvent) {
  e.preventDefault();
  const zoomDirection = e.deltaY > 0 ? -0.1 : 0.1;
  zoomLevel.value = Math.max(0.5, Math.min(10, zoomLevel.value + zoomDirection));
}

function startPan(e: MouseEvent) {
  isDragging = true;
  startX = e.clientX - panX.value; startY = e.clientY - panY.value;
  dragStartX = e.clientX; dragStartY = e.clientY;
}

function doPan(e: MouseEvent) {
  if (!isDragging) return;
  panX.value = e.clientX - startX; panY.value = e.clientY - startY;
}

function endPan() { isDragging = false; }

function handleCanvasClick(e: MouseEvent) {
  const dist = Math.abs(e.clientX - dragStartX) + Math.abs(e.clientY - dragStartY);
  if (dist < 5) selectedFeature.value = null;
}

function exportImage() { alert('高清导出功能已准备就绪。'); }
</script>

<style scoped>
.genome-viewer-module {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
  position: relative;
}

.viewer-toolbar {
  height: 56px;
  padding: 0 20px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.upload-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
}

.upload-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 6px rgba(59, 130, 246, 0.4);
}

.current-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: white;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.file-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.seq-len {
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}

.view-switcher {
  display: flex;
  background: #e2e8f0;
  padding: 4px;
  border-radius: 8px;
}

.view-switcher button {
  padding: 6px 20px;
  border: none;
  background: transparent;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.view-switcher button.active {
  background: white;
  color: #0f172a;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.export-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid #cbd5e1;
  background: white;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.export-btn:hover {
  background: #f8fafc;
}

.viewer-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.features-sidebar {
  width: 300px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.sidebar-header {
  padding: 16px;
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
  border-bottom: 1px solid #e2e8f0;
}

.viewer-controls {
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.control-group label {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
  font-weight: 700;
}

.control-group input[type="text"] {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}

.control-group input[type="text"]:focus {
  border-color: #3b82f6;
}

.features-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.feature-item {
  padding: 12px;
  border-left: 4px solid #cbd5e1;
  background: white;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  border-right: 1px solid #f1f5f9;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}

.feature-item:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.feature-item.active {
  background: #eff6ff;
  border-color: #3b82f6 !important;
}

.feat-top {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 800;
}

.feat-type {
  color: #64748b;
}

.feat-range {
  color: #94a3b8;
  font-family: monospace;
}

.feat-name {
  font-size: 13px;
  color: #0f172a;
  font-weight: 700;
  margin: 4px 0;
  word-break: break-all;
}

.feat-strand {
  font-size: 10px;
  font-weight: 800;
}

.feat-strand.plus {
  color: #10b981;
}

.feat-strand.minus {
  color: #f59e0b;
}

.canvas-area {
  flex: 1;
  background: #ffffff;
  position: relative;
  overflow: hidden;
  background-image: radial-gradient(#f1f5f9 1px, transparent 1px);
  background-size: 20px 20px;
}

.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #0f172a;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
  filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.1));
}

.empty-state h3 {
  font-size: 20px;
  font-weight: 800;
  margin-bottom: 8px;
}

.empty-sub {
  font-size: 13px;
  color: #64748b;
  margin-top: 16px;
  padding: 6px 12px;
  background: #f8fafc;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
}

.svg-container {
  width: 100%;
  height: 100%;
  cursor: grab;
}

.svg-container:active {
  cursor: grabbing;
}

.genome-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.backbone {
  fill: none;
  stroke: #cbd5e1;
  stroke-width: 2;
}

.tick-text {
  font-size: 10px;
  fill: #64748b;
  font-weight: 600;
  font-family: 'Inter', sans-serif;
}

.feature-path {
  transition: opacity 0.2s;
  cursor: pointer;
  stroke: rgba(0, 0, 0, 0.1);
  stroke-width: 1;
}

.feature-path:hover {
  opacity: 1 !important;
  stroke: #0f172a;
  stroke-width: 1.5;
}

.feature-tooltip {
  position: absolute;
  top: 24px;
  right: 24px;
  background: rgba(15, 23, 42, 0.65);
  color: white;
  padding: 16px 24px;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
  min-width: 300px;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  pointer-events: auto;
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.feature-tooltip h4 {
  margin: 0 0 12px 0;
  font-size: 15px;
  font-weight: 800;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.tt-row {
  font-size: 13px;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  color: #cbd5e1;
}

.tt-row span {
  font-weight: 700;
  color: #94a3b8;
}

.close-tt {
  position: absolute;
  top: 12px;
  right: 12px;
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;
  transition: color 0.2s;
}

.close-tt:hover {
  color: white;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.8);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
  border-radius: 16px;
}

.spinner-xl {
  width: 40px;
  height: 40px;
  border: 4px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 16px;
}

.loading-text {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.toggles {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.toggle-btn {
  font-size: 12px;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.toggle-btn input {
  width: 14px;
  height: 14px;
  cursor: pointer;
}

.tt-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.action-btn {
  flex: 1;
  padding: 6px;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(59, 130, 246, 0.5);
  color: #60a5fa;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: rgba(59, 130, 246, 0.4);
  color: white;
}

/* SnapGene-style floating toolbar */
.sg-toolbar {
  position: absolute;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 2px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.sg-drag-handle {
  width: 100%;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  color: #94a3b8;
  margin-bottom: 2px;
}
.sg-drag-handle:active {
  cursor: grabbing;
}
.sg-drag-handle:hover {
  color: #64748b;
  background: #e2e8f0;
  border-radius: 4px;
}

.sg-btn-wrap {
  position: relative;
}

.sg-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: #64748b;
  transition: all 0.15s;
  position: relative;
  gap: 2px;
  padding: 0 4px;
}

.sg-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.sg-btn.active {
  background: #2563eb;
  border-color: #1d4ed8;
  color: white;
}

.sg-arrow {
  font-size: 8px;
  opacity: 0.6;
  position: absolute;
  right: 2px;
  top: 2px;
}

.sg-btn.active .sg-arrow {
  color: rgba(255,255,255,0.7);
}

.sg-flyout {
  position: absolute;
  left: 100%;
  top: -4px;
  padding-left: 6px;
  z-index: 100;
}

.sg-flyout-inner {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.12);
  padding: 6px 0;
  min-width: 180px;
  white-space: nowrap;
}

.sg-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px 6px 28px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
  position: relative;
  transition: background 0.1s;
  user-select: none;
}

.sg-menu-item:hover {
  background: #eff6ff;
}

.sg-menu-item.checked::before {
  content: '\2713';
  position: absolute;
  left: 10px;
  font-weight: 700;
  color: #2563eb;
  font-size: 12px;
}

.sg-menu-item input[type="checkbox"] {
  display: none;
}

.sg-divider {
  height: 1px;
  background: #f1f5f9;
  margin: 4px 0;
}
</style>
