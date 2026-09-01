<script setup lang="ts">
/**
 * TraceChromatogramViewer.vue
 * 专业 Sanger 测序四通道色谱峰图 Canvas 交互式查看器
 * 支持：
 * - A (绿) / C (蓝) / G (黑) / T (红) 四通道平滑曲线
 * - 峰顶 Basecall 字符与 Phred 质量柱
 * - 动态缩放 (Zoom) 与平移 (Pan)
 * - 次峰 (Secondary Peak) 高亮与比率 Tooltip
 */
import { ref, onMounted, watch, computed } from 'vue';
import type { SampleDeconvResult, PeakDetail } from '../types';

const props = defineProps<{
  sample: SampleDeconvResult;
}>();

const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);

// 显示通道控制
const showA = ref(true);
const showC = ref(true);
const showG = ref(true);
const showT = ref(true);

// 缩放级别: 像素/采样点 (默认 1.8)
const zoomLevel = ref<number>(1.8);
const verticalScale = ref<number>(1.0);
const canvasHeight = ref<number>(190);

// 悬浮位点信息
const hoveredPeak = ref<PeakDetail | null>(null);
const tooltipPos = ref<{ x: number; y: number }>({ x: 0, y: 0 });

const peaks = computed(() => props.sample.peaks || []);
const traces = computed(() => props.sample.trace_summary?.traces || { A: [], C: [], G: [], T: [] });
const step = computed(() => props.sample.trace_summary?.step || 1);

// 颜色定义
const COLOR_A = '#10b981'; // 绿
const COLOR_C = '#2563eb'; // 蓝
const COLOR_G = '#1e293b'; // 黑
const COLOR_T = '#dc2626'; // 红

function renderCanvas() {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const sampledLen = traces.value.A.length;
  if (sampledLen === 0) return;

  const totalWidth = Math.max(800, sampledLen * zoomLevel.value);
  const height = canvasHeight.value;

  // 处理高清屏 DPI
  const dpr = window.devicePixelRatio || 1;
  canvas.width = totalWidth * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${totalWidth}px`;
  canvas.style.height = `${height}px`;

  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, totalWidth, height);

  // 1. 绘制背景与辅助网格
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, totalWidth, height);

  // 质量基准线 (顶部 44px 为碱基和质量条区，下方为色谱曲线区)
  const baseAreaHeight = 44;
  const traceAreaTop = baseAreaHeight;
  const traceAreaHeight = Math.max(50, height - traceAreaTop - 10);

  ctx.strokeStyle = '#f1f5f9';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, traceAreaTop);
  ctx.lineTo(totalWidth, traceAreaTop);
  ctx.stroke();

  // 2. 寻找通道信号最大值用于归一化高度
  let maxSignal = 100;
  for (const b of ['A', 'C', 'G', 'T'] as const) {
    const arr = traces.value[b];
    if (arr && arr.length > 0) {
      const localMax = Math.max(...arr);
      if (localMax > maxSignal) maxSignal = localMax;
    }
  }

  const normY = (val: number) => {
    const scaled = (val / maxSignal) * traceAreaHeight * verticalScale.value;
    return height - 10 - Math.min(traceAreaHeight, scaled);
  };

  // 3. 绘制 4 通道色谱曲线
  const drawTraceLine = (arr: number[], color: string) => {
    if (!arr || arr.length === 0) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.lineJoin = 'round';
    ctx.beginPath();

    for (let i = 0; i < arr.length; i++) {
      const val = arr[i] ?? 0;
      const x = i * zoomLevel.value;
      const y = normY(val);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  };

  if (showG.value) drawTraceLine(traces.value.G, COLOR_G);
  if (showC.value) drawTraceLine(traces.value.C, COLOR_C);
  if (showT.value) drawTraceLine(traces.value.T, COLOR_T);
  if (showA.value) drawTraceLine(traces.value.A, COLOR_A);

  // 4. 绘制峰顶碱基与质量条
  for (const p of peaks.value) {
    const sampleIdx = p.pos / step.value;
    const x = sampleIdx * zoomLevel.value;

    // 绘制垂直引导参考点 (弱虚线)
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 0.8;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(x, traceAreaTop);
    ctx.lineTo(x, height - 10);
    ctx.stroke();
    ctx.setLineDash([]);

    // 绘制质量柱 (0~50 Phred score)
    const qHeight = Math.min(18, (p.quality / 50) * 18);
    ctx.fillStyle = p.quality >= 30 ? '#10b981' : p.quality >= 20 ? '#f59e0b' : '#ef4444';
    ctx.fillRect(x - 2, 22 - qHeight, 4, qHeight);

    // 绘制碱基文字
    ctx.font = 'bold 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';

    // 颜色依据主碱基
    let bColor = '#475569';
    if (p.primary_base === 'A') bColor = COLOR_A;
    else if (p.primary_base === 'C') bColor = COLOR_C;
    else if (p.primary_base === 'G') bColor = COLOR_G;
    else if (p.primary_base === 'T') bColor = COLOR_T;

    ctx.fillStyle = bColor;
    ctx.fillText(p.primary_base, x, 38);

    // 若有显著次峰，在上方标出简并码或次峰
    if (p.ratio >= 0.30) {
      ctx.fillStyle = '#dc2626';
      ctx.font = '9px sans-serif';
      ctx.fillText(p.iupac_base, x, 8);
    }
  }
}

function handleMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value;
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left;

  const targetSampleIdx = mouseX / zoomLevel.value;
  const targetPos = targetSampleIdx * step.value;

  // 寻找最近的 peak
  let closest: PeakDetail | null = null;
  let minDist = 999999;

  for (const p of peaks.value) {
    const dist = Math.abs(p.pos - targetPos);
    if (dist < minDist && dist < 15 * step.value) {
      minDist = dist;
      closest = p;
    }
  }

  if (closest) {
    hoveredPeak.value = closest;
    tooltipPos.value = {
      x: e.clientX,
      y: e.clientY
    };
  } else {
    hoveredPeak.value = null;
  }
}

function handleMouseLeave() {
  hoveredPeak.value = null;
}

onMounted(() => {
  renderCanvas();
});

watch([() => props.sample, zoomLevel, verticalScale, canvasHeight, showA, showC, showG, showT], () => {
  renderCanvas();
});
</script>

<template>
  <div class="chromatogram-container" ref="containerRef">
    <!-- 顶部控制栏 -->
    <div class="trace-toolbar">
      <div class="channel-toggles">
        <span class="toolbar-label">通道控制:</span>
        <label class="channel-pill ch-a" :class="{ active: showA }">
          <input type="checkbox" v-model="showA" />
          <span class="dot"></span> A (腺嘌呤)
        </label>
        <label class="channel-pill ch-c" :class="{ active: showC }">
          <input type="checkbox" v-model="showC" />
          <span class="dot"></span> C (胞嘧啶)
        </label>
        <label class="channel-pill ch-g" :class="{ active: showG }">
          <input type="checkbox" v-model="showG" />
          <span class="dot"></span> G (鸟嘌呤)
        </label>
        <label class="channel-pill ch-t" :class="{ active: showT }">
          <input type="checkbox" v-model="showT" />
          <span class="dot"></span> T (胸腺嘧啶)
        </label>
      </div>

      <div class="zoom-controls">
        <span class="toolbar-label">水平缩放:</span>
        <input type="range" min="0.8" max="4.0" step="0.2" v-model.number="zoomLevel" class="mini-slider" />
        <span class="scale-text">{{ zoomLevel.toFixed(1) }}x</span>

        <span class="divider"></span>

        <span class="toolbar-label">峰高缩放:</span>
        <input type="range" min="0.5" max="3.0" step="0.2" v-model.number="verticalScale" class="mini-slider" />
        <span class="scale-text">{{ verticalScale.toFixed(1) }}x</span>

        <span class="divider"></span>

        <span class="toolbar-label">图表高度:</span>
        <input type="range" min="150" max="360" step="10" v-model.number="canvasHeight" class="mini-slider" />
        <span class="scale-text">{{ canvasHeight }}px</span>
      </div>
    </div>

    <!-- 滚动 Canvas 画布区 -->
    <div class="canvas-scroll-wrapper" @mousemove="handleMouseMove" @mouseleave="handleMouseLeave">
      <canvas ref="canvasRef"></canvas>
    </div>

    <!-- 悬停 Tooltip -->
    <div 
      v-if="hoveredPeak" 
      class="trace-tooltip"
      :style="{ left: `${tooltipPos.x + 15}px`, top: `${tooltipPos.y - 40}px` }"
    >
      <div class="tt-header">
        <span class="pos-badge">位点 #{{ hoveredPeak.index }}</span>
        <span class="q-badge" :class="hoveredPeak.quality >= 30 ? 'q-high' : 'q-low'">Q{{ hoveredPeak.quality }}</span>
      </div>
      <div class="tt-body">
        <div>主峰呼叫: <strong>{{ hoveredPeak.primary_base }}</strong> (信号 {{ hoveredPeak.primary_val }})</div>
        <div v-if="hoveredPeak.secondary_base !== '-'">
          次峰碱基: <strong style="color: #dc2626;">{{ hoveredPeak.secondary_base }}</strong> (信号 {{ hoveredPeak.secondary_val }}, 占比 {{ (hoveredPeak.ratio * 100).toFixed(1) }}%)
        </div>
        <div v-if="hoveredPeak.ratio >= 0.30">
          IUPAC 简并: <strong>{{ hoveredPeak.iupac_base }}</strong>
        </div>
        <div class="tt-orig">仪器原始 Basecall: {{ hoveredPeak.orig_base }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chromatogram-container {
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.trace-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.78rem;
  flex-wrap: wrap;
  gap: 12px;
}

.channel-toggles, .zoom-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  color: #64748b;
  font-weight: 600;
}

.channel-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  background: white;
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  font-size: 0.75rem;
  transition: all 0.15s;
}

.channel-pill input {
  display: none;
}

.channel-pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  opacity: 0.4;
}

.channel-pill.active .dot {
  opacity: 1;
}

.ch-a.active { border-color: #10b981; color: #065f46; background: #ecfdf5; }
.ch-a .dot { background: #10b981; }

.ch-c.active { border-color: #2563eb; color: #1e40af; background: #eff6ff; }
.ch-c .dot { background: #2563eb; }

.ch-g.active { border-color: #1e293b; color: #0f172a; background: #f1f5f9; }
.ch-g .dot { background: #1e293b; }

.ch-t.active { border-color: #dc2626; color: #991b1b; background: #fef2f2; }
.ch-t .dot { background: #dc2626; }

.mini-slider {
  width: 80px;
  cursor: pointer;
  accent-color: #2563eb;
}

.scale-text {
  font-family: monospace;
  color: #475569;
  font-size: 0.75rem;
  min-width: 28px;
}

.divider {
  width: 1px;
  height: 16px;
  background: #cbd5e1;
  margin: 0 4px;
}

.canvas-scroll-wrapper {
  overflow-x: auto;
  overflow-y: hidden;
  background: white;
  min-height: 240px;
  position: relative;
}

.canvas-scroll-wrapper canvas {
  display: block;
}

.trace-tooltip {
  position: fixed;
  z-index: 1000;
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(4px);
  color: white;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.75rem;
  pointer-events: none;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 180px;
}

.tt-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  padding-bottom: 4px;
  margin-bottom: 4px;
}

.pos-badge { font-weight: 700; color: #93c5fd; }
.q-badge { padding: 1px 6px; border-radius: 4px; font-weight: 700; font-size: 0.7rem; }
.q-high { background: #059669; color: white; }
.q-low { background: #dc2626; color: white; }

.tt-body div { line-height: 1.4; }
.tt-orig { color: #94a3b8; font-size: 0.7rem; border-top: 1px dashed rgba(255, 255, 255, 0.15); margin-top: 4px; padding-top: 3px; }
</style>
