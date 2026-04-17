<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue';

interface Block {
  qs: number;
  qe: number;
  ts: number;
  te: number;
  strand: string;
  id: number;
}

const props = defineProps<{
  blocks: Block[];
  qLen: number;
  tLen: number;
}>();

const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);

function draw() {
  const canvas = canvasRef.value;
  const container = containerRef.value;
  if (!canvas || !container) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // 设置画布尺寸
  const rect = container.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  // 清空画布
  ctx.clearRect(0, 0, rect.width, rect.height);

  const padding = 50;
  const plotWidth = rect.width - padding * 2;
  const plotHeight = rect.height - padding * 2;

  // 坐标转换函数
  const scaleX = (val: number) => padding + (val / props.tLen) * plotWidth;
  const scaleY = (val: number) => padding + plotHeight - (val / props.qLen) * plotHeight;

  // 绘制坐标轴
  ctx.strokeStyle = '#e2e8f0';
  ctx.lineWidth = 1;
  ctx.strokeRect(padding, padding, plotWidth, plotHeight);

  // 绘制网格线
  ctx.setLineDash([5, 5]);
  for (let i = 1; i < 5; i++) {
    const x = padding + (i / 5) * plotWidth;
    ctx.beginPath();
    ctx.moveTo(x, padding);
    ctx.lineTo(x, padding + plotHeight);
    ctx.stroke();

    const y = padding + (i / 5) * plotHeight;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(padding + plotWidth, y);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // 绘制比对线
  props.blocks.forEach(block => {
    ctx.beginPath();
    ctx.lineWidth = 2;
    // 正向用蓝色，反向用紫色
    ctx.strokeStyle = block.strand === '+' ? '#3b82f6' : '#a855f7';
    
    const x1 = scaleX(block.ts);
    const x2 = scaleX(block.te);
    const y1 = scaleY(block.qs);
    const y2 = scaleY(block.qe);

    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  });

  // 绘制标签
  ctx.fillStyle = '#64748b';
  ctx.font = '12px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Target Genome (Reference)', rect.width / 2, rect.height - 15);
  
  ctx.save();
  ctx.translate(15, rect.height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Query Genome (Assembly)', 0, 0);
  ctx.restore();

  // 绘制刻度
  ctx.font = '10px tabular-nums';
  ctx.fillText('0', padding, rect.height - padding + 15);
  ctx.fillText(`${(props.tLen / 1000).toFixed(1)} kb`, padding + plotWidth, rect.height - padding + 15);
  ctx.fillText(`${(props.qLen / 1000).toFixed(1)} kb`, 35, padding);
}

const resizeObserver = new ResizeObserver(() => draw());

onMounted(() => {
  if (containerRef.value) resizeObserver.observe(containerRef.value);
  draw();
});

onUnmounted(() => {
  resizeObserver.disconnect();
});

watch(() => props.blocks, draw, { deep: true });
</script>

<template>
  <div ref="containerRef" class="dotplot-canvas-wrapper">
    <canvas ref="canvasRef"></canvas>
  </div>
</template>

<style scoped>
.dotplot-canvas-wrapper {
  width: 100%;
  height: 500px;
  background: white;
  border-radius: 12px;
  position: relative;
  overflow: hidden;
}
canvas {
  width: 100% !important;
  height: 100% !important;
  display: block;
}
</style>
