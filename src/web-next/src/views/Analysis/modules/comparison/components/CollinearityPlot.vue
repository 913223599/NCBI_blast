<script setup lang="ts">
import { onMounted, ref, watch, nextTick } from 'vue';

interface Props {
  alignments: any[];
  metadata: any;
}
const props = defineProps<Props>();
const canvasRef = ref<HTMLCanvasElement | null>(null);

function renderPlot() {
  if (!canvasRef.value || !props.alignments) return;
  const ctx = canvasRef.value.getContext('2d');
  if (!ctx) return;

  const width = canvasRef.value.width;
  const height = canvasRef.value.height;

  ctx.clearRect(0, 0, width, height);

  const maxRef = Math.max(...props.alignments.map(a => Math.max(a.ref_start, a.ref_end)), 1);
  const maxQuery = Math.max(...props.alignments.map(a => Math.max(a.query_start, a.query_end)), 1);

  // 增大边距(Margin)以容纳刻度
  const margin = 50;
  const drawW = width - margin * 2;
  const drawH = height - margin * 2;

  const scaleX = drawW / maxRef;
  const scaleY = drawH / maxQuery;

  // 1. 绘制坐标轴 (深色增强)
  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margin, margin); 
  ctx.lineTo(margin, height - margin); 
  ctx.lineTo(width - margin, height - margin);
  ctx.stroke();

  // 2. 绘制轴刻度终点 (数值指示)
  ctx.fillStyle = '#64748b';
  ctx.font = '10px Inter, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(formatPos(maxQuery), margin - 8, margin + 5);
  ctx.textAlign = 'center';
  ctx.fillText(formatPos(maxRef), width - margin, height - margin + 15);

  // 3. 绘制数据线
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  props.alignments.forEach(aln => {
    const isForward = (aln.ref_start < aln.ref_end) === (aln.query_start < aln.query_end);
    ctx.strokeStyle = isForward ? '#2563eb' : '#9333ea';
    
    ctx.beginPath();
    ctx.moveTo(margin + aln.ref_start * scaleX, (height - margin) - aln.query_start * scaleY);
    ctx.lineTo(margin + aln.ref_end * scaleX, (height - margin) - aln.query_end * scaleY);
    ctx.stroke();
  });
}

function formatPos(val: number) {
  if (val > 1000000) return (val/1000000).toFixed(1) + 'Mb';
  if (val > 1000) return (val/1000).toFixed(1) + 'Kb';
  return val + 'bp';
}

onMounted(() => {
  nextTick(renderPlot);
});

watch(() => props.alignments, renderPlot, { deep: true });
</script>

<template>
  <div class="plot-container">
    <div class="plot-header">
       <h4 class="main-title">Collinearity: {{ metadata?.ref_name }} ↔ {{ metadata?.query_name }}</h4>
       <div class="legend">
          <span class="dot forward"></span> Forward
          <span class="dot reverse" style="margin-left: 12px;"></span> Reverse (RC)
       </div>
    </div>

    <div class="canvas-wrapper">
      <canvas 
        ref="canvasRef" 
        width="1200" 
        height="600" 
        class="collinearity-canvas"
      ></canvas>
      
      <!-- 显式的坐标轴标题 -->
      <div class="label-x">Reference Genome — {{ metadata?.ref_name }}</div>
      <div class="label-y">Query Genome — {{ metadata?.query_name }}</div>
    </div>
  </div>
</template>

<style scoped>
.plot-container { padding: 10px 20px; background: #fbfcfe; display: flex; flex-direction: column; height: 100%; }
.plot-header { margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }

.main-title { margin: 0; font-size: 0.85rem; color: #1e293b; font-weight: 700; }
.legend { font-size: 0.75rem; color: #64748b; font-weight: 600; display: flex; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
.forward { background: #2563eb; }
.reverse { background: #9333ea; }

.canvas-wrapper { position: relative; flex: 1; min-height: 0; }

.collinearity-canvas { 
  width: 100%; 
  height: 100%; 
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
}

.label-x {
  position: absolute;
  bottom: 15px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
}

.label-y {
  position: absolute;
  left: 15px;
  top: 50%;
  transform: rotate(-90deg) translateX(50%);
  transform-origin: left top;
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
  white-space: nowrap;
}
</style>
