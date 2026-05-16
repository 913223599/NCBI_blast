<script setup lang="ts">
import { onMounted, ref, watch, nextTick, onBeforeUnmount } from 'vue';
import Plotly from 'plotly.js-dist-min';
import type { Bin } from '../utils/instantAlignment';

const props = defineProps<{
  bins: Bin[];
}>();

const plotDiv = ref<HTMLDivElement | null>(null);

function renderPlot() {
  if (!plotDiv.value || !props.bins?.length) return;

  const x = props.bins.map(b => b.x);
  const y = props.bins.map(b => b.score * 100);

  const trace: any = {
    x: x,
    y: y,
    type: 'scatter',
    mode: 'lines',
    name: 'Similarity',
    fill: 'tozeroy',
    fillcolor: 'rgba(16, 185, 129, 0.1)',
    line: { color: '#10b981', width: 2, shape: 'spline' },
    hovertemplate: 'Position: %{x} bp<br>Similarity: %{y:.1f}%<extra></extra>'
  };

  const layout = {
    margin: { t: 10, b: 40, l: 50, r: 10 },
    xaxis: {
      title: 'Position (bp)',
      gridcolor: '#f1f5f9',
      zeroline: false,
      showline: true,
      linecolor: '#e2e8f0',
      tickfont: { size: 10, color: '#64748b' }
    },
    yaxis: {
      title: 'Similarity (%)',
      range: [0, 105],
      gridcolor: '#f1f5f9',
      zeroline: false,
      showline: true,
      linecolor: '#e2e8f0',
      tickfont: { size: 10, color: '#64748b' }
    },
    plot_bgcolor: '#ffffff',
    paper_bgcolor: '#ffffff',
    hovermode: 'x unified'
  };

  const config = {
    responsive: true,
    displaylogo: false,
    displayModeBar: false
  };

  Plotly.react(plotDiv.value, [trace], layout, config);
}

onMounted(() => {
  nextTick(renderPlot);
});

watch(() => props.bins, () => {
  nextTick(renderPlot);
}, { deep: true });

onBeforeUnmount(() => {
  if (plotDiv.value) Plotly.purge(plotDiv.value);
});
</script>

<template>
  <div class="interactive-similarity-plot">
    <div ref="plotDiv" class="plotly-container"></div>
  </div>
</template>

<style scoped>
.interactive-similarity-plot { width: 100%; height: 100%; }
.plotly-container { width: 100%; height: 100%; min-height: 250px; }
</style>
