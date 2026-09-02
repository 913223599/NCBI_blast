<script setup lang="ts">
/**
 * AssemblyResults - 基因组组装结果看板 (紧凑精致版 + Contig 分段明细)
 */
import { ref, computed } from 'vue';
import type { AssemblyResultData, AssemblyTaskItem, ContigDetailItem } from '../types';

const props = defineProps<{
  task: AssemblyTaskItem;
  result: AssemblyResultData | null;
}>();

const emit = defineEmits<{
  (e: 'download'): void;
  (e: 'openFolder'): void;
}>();

const copiedName = ref<string | null>(null);

const stats = computed(() => {
  const rStats = props.result?.stats;
  const tResults = props.task?.results;
  const raw = { ...(tResults || {}), ...(rStats || {}) };
  const rawDepth = raw.avg_depth ?? rStats?.avg_depth ?? tResults?.avg_depth;
  const parsedDepth = (rawDepth !== undefined && rawDepth !== null && !isNaN(Number(rawDepth))) ? Number(rawDepth) : 0;
  const rawMax = raw.max_contig_length ?? rStats?.max_contig_length ?? tResults?.max_contig_length ?? (raw.contigs === 1 ? raw.total_length : raw.n50) ?? raw.total_length ?? 0;

  return {
    total_length: raw.total_length || 0,
    contigs: raw.contigs || 1,
    max_contig_length: Number(rawMax),
    n50: raw.n50 || 0,
    gc_percent: raw.gc_percent || 0,
    avg_depth: parsedDepth,
    is_circular: !!raw.is_circular
  };
});

// Contig 列表 (优先从 result.contigs 获取，兜底从 stats 构造)
const contigList = computed<ContigDetailItem[]>(() => {
  if (props.result?.contigs && props.result.contigs.length > 0) {
    return props.result.contigs;
  }
  // 兜底：若只有 1 条 contig 且未拉取到明细
  if (stats.value.total_length > 0) {
    return [{
      name: 'contig_1',
      header: 'contig_1',
      length: stats.value.total_length,
      gc_percent: stats.value.gc_percent,
      depth: stats.value.avg_depth,
      is_circular: stats.value.is_circular,
      length_ratio: 100.0
    }];
  }
  return [];
});

function formatNumber(num?: number): string {
  if (num === undefined || num === null) return '0';
  return Number(num).toLocaleString();
}

function formatKb(bp?: number): string {
  if (!bp) return '0 bp';
  if (bp >= 1000000) return `${(bp / 1000000).toFixed(2)} Mb`;
  if (bp >= 1000) return `${(bp / 1000).toFixed(1)} kb`;
  return `${bp} bp`;
}

function copyFastaPath() {
  const p = props.result?.fasta_path;
  if (p) {
    navigator.clipboard.writeText(p);
  }
}

// 复制单个 Contig 序列
function copyContig(c: ContigDetailItem) {
  const fastaText = c.sequence 
    ? `>${c.header || c.name}\n${c.sequence}\n`
    : `>${c.name} length=${c.length} gc=${c.gc_percent}%\n`;
  navigator.clipboard.writeText(fastaText);
  copiedName.value = c.name;
  setTimeout(() => {
    if (copiedName.value === c.name) {
      copiedName.value = null;
    }
  }, 2000);
}

// 单独下载某个 Contig 的 FASTA 文件
function downloadContig(c: ContigDetailItem) {
  const fastaText = c.sequence 
    ? `>${c.header || c.name}\n${c.sequence}\n`
    : `>${c.name} length=${c.length}\n`;
  const blob = new Blob([fastaText], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${props.task.name || 'assembly'}_${c.name}.fasta`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="assembly-compact-container">
    <!-- 顶部紧凑综合状态条 -->
    <div class="results-header-card">
      <div class="header-left">
        <div class="status-badge-circle">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <div class="header-info">
          <div class="title-line">
            <h2 class="task-title">{{ task.name }}</h2>
            <span class="pill-success">组装完成</span>
            <span v-if="stats.is_circular" class="pill-circular">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="12" cy="12" r="10" />
              </svg>
              环状完整拓扑
            </span>
          </div>
          <div class="meta-line">
            <span>平台: <b>{{ task.tech || 'NGS' }}</b></span>
            <span class="dot">·</span>
            <span>类型: <b>{{ task.sample_type || 'BACTERIA' }}</b></span>
            <span class="dot">·</span>
            <span>耗时: <b>{{ task.duration_seconds ? `${Math.round(task.duration_seconds)}s` : '完成' }}</b></span>
          </div>
        </div>
      </div>

      <div class="header-right">
        <button class="btn-secondary" @click="emit('openFolder')" title="在文件管理器中定位产物所在目录">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          <span>打开所在目录</span>
        </button>
        <button class="btn-primary" @click="emit('download')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>下载 FASTA</span>
        </button>
      </div>
    </div>

    <!-- 紧凑型 5 宫格核心指标网格 -->
    <div class="compact-metrics-grid">
      <!-- 1. Contigs 数量 -->
      <div class="c-metric-card border-blue">
        <span class="c-label">Contigs 数量</span>
        <div class="c-val-box">
          <span class="c-val">{{ stats.contigs || 1 }}</span>
          <span class="c-unit">片段</span>
        </div>
        <span class="c-hint">{{ stats.contigs === 1 ? '单条全长闭环' : '多片段集合' }}</span>
      </div>

      <!-- 2. 基因组总长度 -->
      <div class="c-metric-card border-emerald">
        <span class="c-label">基因组总长度</span>
        <div class="c-val-box">
          <span class="c-val">{{ formatNumber(stats.total_length) }}</span>
          <span class="c-unit">bp</span>
        </div>
        <span class="c-hint">约 {{ formatKb(stats.total_length) }}</span>
      </div>

      <!-- 3. 最长 Contig 长度 -->
      <div class="c-metric-card border-cyan">
        <span class="c-label">最长 Contig 长度</span>
        <div class="c-val-box">
          <span class="c-val">{{ formatNumber(stats.max_contig_length) }}</span>
          <span class="c-unit">bp</span>
        </div>
        <span class="c-hint">单片段峰值 {{ formatKb(stats.max_contig_length) }}</span>
      </div>

      <!-- 4. N50 连续性 -->
      <div class="c-metric-card border-purple">
        <span class="c-label">N50 连续性指标</span>
        <div class="c-val-box">
          <span class="c-val">{{ formatNumber(stats.n50) }}</span>
          <span class="c-unit">bp</span>
        </div>
        <span class="c-hint">评价 {{ formatKb(stats.n50) }}</span>
      </div>

      <!-- 5. GC 含量 -->
      <div class="c-metric-card border-amber">
        <span class="c-label">GC 含量</span>
        <div class="c-val-box">
          <span class="c-val">{{ stats.gc_percent || 0 }}</span>
          <span class="c-unit">%</span>
        </div>
        <span class="c-hint">G+C 碱基占比</span>
      </div>
    </div>

    <!-- 紧凑型 Contig 片段明细表格 -->
    <div v-if="contigList.length > 0" class="contigs-table-card">
      <div class="table-header-row">
        <div class="table-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
          <span>Contig 片段明细</span>
          <span class="count-badge">共 {{ contigList.length }} 个片段</span>
        </div>
      </div>

      <div class="table-wrapper scroll-v">
        <table class="contigs-table">
          <thead>
            <tr>
              <th style="width: 22%;">片段名称</th>
              <th style="width: 28%;">长度 (bp) / 占比</th>
              <th style="width: 14%;">GC 含量</th>
              <th style="width: 14%;">测序深度</th>
              <th style="width: 12%;">拓扑结构</th>
              <th style="width: 10%; text-align: right;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, idx) in contigList" :key="c.name">
              <td class="col-name">
                <span class="idx-tag">#{{ idx + 1 }}</span>
                <span class="name-text" :title="c.name">{{ c.name }}</span>
              </td>
              <td class="col-len">
                <div class="len-info">
                  <span class="len-num">{{ formatNumber(c.length) }} bp</span>
                  <div class="mini-bar-wrap">
                    <div class="mini-bar-fill" :style="{ width: `${Math.max(4, c.length_ratio)}%` }"></div>
                  </div>
                  <span class="len-ratio">{{ c.length_ratio }}%</span>
                </div>
              </td>
              <td class="col-gc">
                <span class="gc-val">{{ c.gc_percent }}%</span>
              </td>
              <td class="col-depth">
                <span 
                  class="depth-badge"
                  :class="{
                    'depth-high': c.depth >= 100,
                    'depth-mid': c.depth >= 30 && c.depth < 100,
                    'depth-low': c.depth < 30
                  }"
                  :title="c.depth >= 100 ? '高测序深度 (主染色体/核心靶序列)' : (c.depth < 30 ? '低测序深度 (背景杂质/宿主残余)' : '中等测序深度')"
                >
                  {{ c.depth > 0 ? c.depth.toFixed(1) : '-' }}x
                </span>
              </td>
              <td class="col-topo">
                <span v-if="c.is_circular" class="topo-circ">环状 Circular</span>
                <span v-else class="topo-linear">线性 Linear</span>
              </td>
              <td class="col-actions">
                <div class="action-btn-group">
                  <button 
                    class="act-btn" 
                    :class="{ 'is-copied': copiedName === c.name }"
                    @click="copyContig(c)" 
                    :title="copiedName === c.name ? '已复制序列' : '复制 FASTA 序列'"
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    <span>{{ copiedName === c.name ? '已复制' : '复制' }}</span>
                  </button>
                  <button 
                    class="act-btn icon-only" 
                    @click="downloadContig(c)" 
                    title="单独下载该片段 FASTA"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 紧凑型 FASTA 路径与复制条 -->
    <div v-if="result?.fasta_path" class="compact-path-strip">
      <span class="path-title">产物文件:</span>
      <span class="path-value" :title="result.fasta_path">{{ result.fasta_path }}</span>
      <button class="btn-copy" @click="copyFastaPath" title="复制文件路径">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
        <span>复制路径</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.assembly-compact-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

/* 顶部信息条 */
.results-header-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-badge-circle {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #dcfce7;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-title {
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.pill-success {
  background: #dcfce7;
  color: #15803d;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
}

.pill-circular {
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.meta-line {
  font-size: 0.72rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 6px;
}
.meta-line b { color: #334155; }
.dot { color: #cbd5e1; }

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-secondary {
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.15s;
}
.btn-secondary:hover {
  background: #f1f5f9;
  color: #0f172a;
  border-color: #94a3b8;
}

.btn-primary {
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  background: #2563eb;
  color: white;
  border: none;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 0.15s;
}
.btn-primary:hover {
  background: #1d4ed8;
}

/* 紧凑 5 宫格网格 (一行自适应横排) */
.compact-metrics-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

@media (max-width: 1100px) {
  .compact-metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .compact-metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.c-metric-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-left-width: 3px;
}

.border-blue { border-left-color: #3b82f6; }
.border-emerald { border-left-color: #10b981; }
.border-cyan { border-left-color: #06b6d4; }
.border-purple { border-left-color: #8b5cf6; }
.border-amber { border-left-color: #f59e0b; }
.border-indigo { border-left-color: #6366f1; }

.c-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
}

.c-val-box {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.c-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.12rem;
  font-weight: 800;
  color: #0f172a;
}

.c-unit {
  font-size: 0.7rem;
  color: #64748b;
  font-weight: 500;
}

.c-hint {
  font-size: 0.65rem;
  color: #94a3b8;
}

/* Contig 列表表格卡片 */
.contigs-table-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.table-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.table-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  font-weight: 700;
  color: #1e293b;
}

.count-badge {
  font-size: 0.68rem;
  font-weight: 500;
  color: #64748b;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}

.table-wrapper {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
}

.contigs-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.75rem;
}

.contigs-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  padding: 6px 10px;
  position: sticky;
  top: 0;
  z-index: 1;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.7rem;
}

.contigs-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f8fafc;
  vertical-align: middle;
}

.contigs-table tr:hover {
  background: #f8fafc;
}

.col-name {
  display: flex;
  align-items: center;
  gap: 6px;
}

.idx-tag {
  font-size: 0.65rem;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
}

.name-text {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.len-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.len-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #0f172a;
  min-width: 75px;
}

.mini-bar-wrap {
  flex: 1;
  max-width: 70px;
  height: 5px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.mini-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #06b6d4);
  border-radius: 3px;
}

.len-ratio {
  font-size: 0.68rem;
  color: #64748b;
  min-width: 38px;
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
}

.gc-val {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #334155;
}

.depth-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-block;
}

.depth-high {
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #e0e7ff;
}

.depth-mid {
  color: #0284c7;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
}

.depth-low {
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}

.topo-circ {
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
}

.topo-linear {
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
}

.action-btn-group {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.act-btn {
  height: 22px;
  padding: 0 6px;
  border-radius: 4px;
  background: white;
  border: 1px solid #cbd5e1;
  font-size: 0.68rem;
  color: #334155;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  transition: all 0.15s;
}

.act-btn.icon-only {
  padding: 0 5px;
}

.act-btn:hover {
  background: #f1f5f9;
  color: #2563eb;
  border-color: #93c5fd;
}

.act-btn.is-copied {
  background: #dcfce7;
  color: #15803d;
  border-color: #86efac;
}

/* 紧凑路径栏 */
.compact-path-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 5px 10px;
}

.path-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

.path-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.btn-copy {
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 0.68rem;
  color: #475569;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.btn-copy:hover {
  background: #f1f5f9;
  color: #2563eb;
  border-color: #93c5fd;
}
</style>
