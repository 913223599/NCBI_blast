<script setup lang="ts">
import { onMounted, ref, watch, nextTick, computed, onBeforeUnmount } from 'vue';
import Plotly from 'plotly.js-dist-min';

interface Alignment {
  ref_start: number; ref_end: number; query_start: number; query_end: number;
  length: number; identity: number; strand: string; ref_id: string; query_id: string;
}
interface Props { 
  alignments: Alignment[]; 
  metadata: any; 
  title?: string;
}
const props = defineProps<Props>();

const plotDiv = ref<HTMLDivElement | null>(null);

function formatPos(val: number) {
  if (val > 1e6) return (val / 1e6).toFixed(1) + ' Mb';
  if (val > 1e3) return (val / 1e3).toFixed(1) + ' Kb';
  return val + ' bp';
}

const displayRefName = computed(() => {
  const ids = new Set(props.alignments?.map(a => a.ref_id).filter(Boolean) || []);
  if (ids.size > 1) return `Multiple Sequences (${ids.size})`;
  return props.metadata?.ref_name || [...ids][0] || 'Reference';
});

const displayQueryName = computed(() => {
  const ids = new Set(props.alignments?.map(a => a.query_id).filter(Boolean) || []);
  if (ids.size > 1) return `Multiple Sequences (${ids.size})`;
  return props.metadata?.query_name || [...ids][0] || 'Query';
});

function getSequenceMapping() {
  const refLengths = new Map<string, number>();
  const queryLengths = new Map<string, number>();
  props.alignments?.forEach(a => {
    refLengths.set(a.ref_id, Math.max(refLengths.get(a.ref_id) || 0, a.ref_start, a.ref_end));
    queryLengths.set(a.query_id, Math.max(queryLengths.get(a.query_id) || 0, a.query_start, a.query_end));
  });

  const refOffsets = new Map<string, number>();
  let currentRef = 0;
  for (const [id, len] of refLengths) { refOffsets.set(id, currentRef); currentRef += len; }
  
  const queryOffsets = new Map<string, number>();
  let currentQuery = 0;
  for (const [id, len] of queryLengths) { queryOffsets.set(id, currentQuery); currentQuery += len; }

  return { refOffsets, queryOffsets, maxRef: currentRef || 1, maxQuery: currentQuery || 1 };
}

function renderPlot() {
  if (!plotDiv.value || !props.alignments?.length) return;

  const { refOffsets, queryOffsets, maxRef, maxQuery } = getSequenceMapping();

  const xFwd: (number | null)[] = [], yFwd: (number | null)[] = [], textFwd: string[] = [];
  const xRev: (number | null)[] = [], yRev: (number | null)[] = [], textRev: string[] = [];

  props.alignments.forEach(aln => {
    const isForward = aln.strand === '+' || ((aln.ref_start < aln.ref_end) === (aln.query_start < aln.query_end));
    const rOffset = refOffsets.get(aln.ref_id) || 0;
    const qOffset = queryOffsets.get(aln.query_id) || 0;

    const x1 = rOffset + aln.ref_start;
    const x2 = rOffset + aln.ref_end;
    const y1 = qOffset + aln.query_start;
    const y2 = qOffset + aln.query_end;

    // 自定义高亮提示框的 HTML
    const hoverText = `<b>Ref:</b> ${aln.ref_id || 'Ref'} (${formatPos(aln.ref_start)} - ${formatPos(aln.ref_end)})<br>` +
                      `<b>Query:</b> ${aln.query_id || 'Query'} (${formatPos(aln.query_start)} - ${formatPos(aln.query_end)})<br>` +
                      `<b>Identity:</b> ${aln.identity?.toFixed(1)}%<br>` +
                      `<b>Length:</b> ${formatPos(aln.length)}`;

    if (isForward) {
      xFwd.push(x1, x2, null);
      yFwd.push(y1, y2, null);
      textFwd.push(hoverText, hoverText, '');
    } else {
      xRev.push(x1, x2, null);
      yRev.push(y1, y2, null);
      textRev.push(hoverText, hoverText, '');
    }
  });

  const traces: any[] = [];
  if (xFwd.length > 0) {
    traces.push({
      x: xFwd, y: yFwd, text: textFwd, hoverinfo: 'text',
      mode: 'lines', name: 'Forward',
      line: { color: '#4f46e5', width: 2 }
    });
  }
  if (xRev.length > 0) {
    traces.push({
      x: xRev, y: yRev, text: textRev, hoverinfo: 'text',
      mode: 'lines', name: 'Reverse (RC)',
      line: { color: '#d97706', width: 2 }
    });
  }

  const shapes: any[] = [];
  // Reference 分界线
  for (const [id, offset] of refOffsets) {
    if (offset === 0) continue;
    shapes.push({
      type: 'line', x0: offset, x1: offset, y0: 0, y1: maxQuery,
      line: { color: '#cbd5e1', dash: 'dot', width: 1 }
    });
  }
  // Query 分界线
  for (const [id, offset] of queryOffsets) {
    if (offset === 0) continue;
    shapes.push({
      type: 'line', x0: 0, x1: maxRef, y0: offset, y1: offset,
      line: { color: '#cbd5e1', dash: 'dot', width: 1 }
    });
  }

  // 动态生成不包含 0 的刻度值，实现原点“单零”效果
  const getXAxisTicks = (max: number) => {
    if (max <= 0) return [];
    // 智能步长：取 2, 5, 10 的倍数
    const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
    let step = magnitude / 2;
    if (max / step > 10) step = magnitude;
    if (max / step < 3) step = magnitude / 5;
    
    const ticks = [];
    for (let v = step; v <= max; v += step) {
      ticks.push(Math.floor(v));
    }
    return ticks;
  };

  const layout: any = {
    title: { 
      text: props.title || `<b>Collinearity:</b> ${displayRefName.value} &#x2194; ${displayQueryName.value}`, 
      font: { size: 13, color: '#475569', family: 'Inter, sans-serif' },
      y: 0.98, x: 0.02, xanchor: 'left'
    },
    xaxis: {
      title: { text: `Reference (bp)`, font: { size: 10, color: '#94a3b8' } },
      gridcolor: '#f8fafc',
      zeroline: true,
      zerolinecolor: '#cbd5e1',
      showline: true,
      linecolor: '#cbd5e1',
      tickfont: { size: 9, color: '#94a3b8' },
      range: [0, maxRef],
      automargin: true,
      rangemode: 'tozero'
    },
    yaxis: {
      title: { text: `Query (bp)`, font: { size: 10, color: '#94a3b8' } },
      gridcolor: '#f8fafc',
      zeroline: true,
      zerolinecolor: '#cbd5e1',
      showline: true,
      linecolor: '#cbd5e1',
      tickfont: { size: 9, color: '#94a3b8' },
      range: [0, maxQuery],
      automargin: true,
      rangemode: 'tozero'
    },
    shapes: shapes,
    hovermode: 'closest',
    margin: { t: 40, b: 80, l: 60, r: 20 },
    legend: { 
      orientation: 'h',
      x: 0.5, y: -0.25, 
      xanchor: 'center', yanchor: 'top',
      font: { size: 10, color: '#64748b' } 
    },
    plot_bgcolor: '#ffffff',
    paper_bgcolor: '#ffffff',
    autosize: true
  };

  const config = {
    responsive: true,
    displaylogo: false,
    scrollZoom: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    toImageButtonOptions: { format: 'png', filename: 'SyntenyPlot_Export', height: 1080, width: 1920, scale: 1 }
  };

  Plotly.react(plotDiv.value, traces, layout, config as any);
}

onMounted(() => {
  nextTick(renderPlot);
});

watch(() => props.alignments, () => {
  nextTick(renderPlot);
}, { deep: true });

onBeforeUnmount(() => {
  if (plotDiv.value) {
    Plotly.purge(plotDiv.value);
  }
});
</script>

<template>
  <div class="synteny-plot-wrapper">
    <div ref="plotDiv" class="plotly-container"></div>
  </div>
</template>

<style scoped>
.synteny-plot-wrapper { 
  display: flex;
  flex-direction: column;
  width: 100%; 
  height: 100%; 
  background: white; 
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  position: relative;
}

.plotly-container { 
  flex: 1;
  width: 100%; 
  min-height: 320px;
}
</style>
