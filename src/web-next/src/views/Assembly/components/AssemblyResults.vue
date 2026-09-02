<script setup lang="ts">
/**
 * AssemblyResults - 基因组组装结果看板与产物导出面板
 */
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import type { AssemblyResultData, AssemblyTaskItem } from '../types';

const props = defineProps<{
  task: AssemblyTaskItem;
  result: AssemblyResultData | null;
}>();

const emit = defineEmits<{
  (e: 'download'): void;
}>();

const router = useRouter();

const stats = computed(() => {
  return props.result?.stats || props.task.results || {
    total_length: 0,
    contigs: 0,
    n50: 0,
    gc_percent: 0,
    avg_depth: 0,
    is_circular: false
  };
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

// 复制产物路径到剪贴板
function copyFastaPath() {
  const p = props.result?.fasta_path;
  if (p) {
    navigator.clipboard.writeText(p);
    alert('FASTA 文件路径已复制到剪贴板');
  }
}

// 一键跳转到功能注释模块
function navigateToAnnotation() {
  if (props.result?.fasta_path) {
    router.push({
      path: '/analysis',
      query: { 
        module: 'annotation',
        fasta_path: props.result.fasta_path,
        task_name: props.task.name
      }
    });
  } else {
    router.push('/analysis');
  }
}

// 一键跳转到 BLAST 比对模块
function navigateToBlast() {
  router.push('/blast');
}
</script>

<template>
  <div class="assembly-results-container scroll-v">
    <!-- 顶部状态卡片 -->
    <div class="results-hero-card">
      <div class="hero-main">
        <div class="success-icon-box">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <div class="hero-text">
          <div class="hero-title-row">
            <h2 class="hero-title">{{ task.name }}</h2>
            <span class="completed-tag">组装完成</span>
            <span v-if="stats.is_circular" class="circular-tag">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="12" cy="12" r="10" />
              </svg>
              环状完整拓扑 (Circular)
            </span>
          </div>
          <p class="hero-meta">
            平台: <b>{{ task.tech || 'NGS' }}</b> · 
            类型: <b>{{ task.sample_type || 'BACTERIA' }}</b> · 
            耗时: <b>{{ task.duration_seconds ? `${Math.round(task.duration_seconds)}s` : '完成' }}</b>
          </p>
        </div>
      </div>

      <div class="hero-actions">
        <button class="primary-download-btn" @click="emit('download')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>下载 FASTA 产物</span>
        </button>
      </div>
    </div>

    <!-- 核心统计指标卡片看板 -->
    <div class="metrics-grid">
      <!-- 1. Contigs 数量 -->
      <div class="metric-card">
        <div class="metric-top">
          <span class="m-label">Contigs 数量</span>
          <div class="m-icon bg-blue">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </svg>
          </div>
        </div>
        <div class="m-val-row">
          <span class="m-value">{{ stats.contigs || 1 }}</span>
          <span class="m-unit">个片段</span>
        </div>
        <span class="m-sub">{{ stats.contigs === 1 ? '单条闭环/全长拼接' : '多片段 Contigs 集合' }}</span>
      </div>

      <!-- 2. 总长度 -->
      <div class="metric-card">
        <div class="metric-top">
          <span class="m-label">基因组总长度</span>
          <div class="m-icon bg-emerald">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2">
              <line x1="4" y1="12" x2="20" y2="12" />
              <polyline points="14 6 20 12 14 18" />
              <polyline points="10 18 4 12 10 6" />
            </svg>
          </div>
        </div>
        <div class="m-val-row">
          <span class="m-value">{{ formatNumber(stats.total_length) }}</span>
          <span class="m-unit">bp</span>
        </div>
        <span class="m-sub">约 {{ formatKb(stats.total_length) }}</span>
      </div>

      <!-- 3. N50 指标 -->
      <div class="metric-card">
        <div class="metric-top">
          <span class="m-label">N50 指标</span>
          <div class="m-icon bg-purple">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2">
              <path d="M18 20V10M12 20V4M6 20v-6" />
            </svg>
          </div>
        </div>
        <div class="m-val-row">
          <span class="m-value">{{ formatNumber(stats.n50) }}</span>
          <span class="m-unit">bp</span>
        </div>
        <span class="m-sub">连续性评价: {{ formatKb(stats.n50) }}</span>
      </div>

      <!-- 4. GC 含量 -->
      <div class="metric-card">
        <div class="metric-top">
          <span class="m-label">GC 含量</span>
          <div class="m-icon bg-amber">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
          </div>
        </div>
        <div class="m-val-row">
          <span class="m-value">{{ stats.gc_percent || 0 }}</span>
          <span class="m-unit">%</span>
        </div>
        <span class="m-sub">鸟嘌呤-胞嘧啶碱基占比</span>
      </div>

      <!-- 5. 测序深度 -->
      <div class="metric-card">
        <div class="metric-top">
          <span class="m-label">加权平均覆盖深度</span>
          <div class="m-icon bg-indigo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" stroke-width="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </div>
        </div>
        <div class="m-val-row">
          <span class="m-value">{{ stats.avg_depth || 1.0 }}</span>
          <span class="m-unit">x</span>
        </div>
        <span class="m-sub">全域有效测序深度支持</span>
      </div>
    </div>

    <!-- 产物路径与下游操作卡片 -->
    <div class="next-steps-card">
      <div class="ns-header">
        <h3 class="ns-title">产物文件与下游流水线直通</h3>
        <p class="ns-desc">组装生成的 FASTA 文件可直接带入功能注释引擎或 BLAST 进行物种同源鉴定。</p>
      </div>

      <div class="path-bar" v-if="result?.fasta_path">
        <span class="path-label">产物路径:</span>
        <span class="path-text" :title="result.fasta_path">{{ result.fasta_path }}</span>
        <button class="copy-path-btn" @click="copyFastaPath">复制路径</button>
      </div>

      <div class="pipeline-links-row">
        <!-- 功能注释 -->
        <div class="pipeline-card" @click="navigateToAnnotation">
          <div class="pl-icon pl-anno">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <div class="pl-content">
            <span class="pl-title">一键发送至功能注释工作台</span>
            <span class="pl-desc">执行 Prokka / Pharokka / PHOLD 多引擎级联注释与 SnapGene 序列可视化</span>
          </div>
          <span class="pl-arrow">→</span>
        </div>

        <!-- BLAST 比对 -->
        <div class="pipeline-card" @click="navigateToBlast">
          <div class="pl-icon pl-blast">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
          <div class="pl-content">
            <span class="pl-title">一键发送至 BLAST 比对鉴定</span>
            <span class="pl-desc">比对 NCBI / SILVA 核心数据库确定菌株物种归属与同源性</span>
          </div>
          <span class="pl-arrow">→</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assembly-results-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
}

.results-hero-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
}
.hero-main {
  display: flex;
  align-items: center;
  gap: 16px;
}
.success-icon-box {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: #dcfce7;
  display: flex;
  align-items: center;
  justify-content: center;
}
.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hero-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}
.completed-tag {
  background: #dcfce7;
  color: #15803d;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}
.circular-tag {
  background: #eff6ff;
  color: #2563eb;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.hero-meta {
  font-size: 0.8rem;
  color: #64748b;
  margin: 4px 0 0 0;
}
.hero-meta b { color: #334155; }

.primary-download-btn {
  height: 40px;
  padding: 0 18px;
  border-radius: 8px;
  background: #2563eb;
  color: white;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s;
}
.primary-download-btn:hover {
  background: #1d4ed8;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}
.metric-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.metric-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.m-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}
.m-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bg-blue { background: #eff6ff; }
.bg-emerald { background: #ecfdf5; }
.bg-purple { background: #f5f3ff; }
.bg-amber { background: #fffbeb; }
.bg-indigo { background: #eef2ff; }

.m-val-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.m-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.5rem;
  font-weight: 800;
  color: #0f172a;
}
.m-unit {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 500;
}
.m-sub {
  font-size: 0.7rem;
  color: #94a3b8;
}

.next-steps-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ns-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}
.ns-desc {
  font-size: 0.78rem;
  color: #64748b;
  margin: 2px 0 0 0;
}

.path-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
}
.path-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}
.path-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.copy-path-btn {
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 0.72rem;
  color: #334155;
  cursor: pointer;
  white-space: nowrap;
}
.copy-path-btn:hover {
  background: #f1f5f9;
  color: #2563eb;
  border-color: #93c5fd;
}

.pipeline-links-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.pipeline-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.pipeline-card:hover {
  border-color: #3b82f6;
  background: #f0fdf4;
  transform: translateY(-1px);
}
.pl-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.pl-anno { background: #dbeafe; color: #2563eb; }
.pl-blast { background: #e0e7ff; color: #4f46e5; }

.pl-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.pl-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #1e293b;
}
.pl-desc {
  font-size: 0.72rem;
  color: #64748b;
  line-height: 1.4;
}
.pl-arrow {
  font-size: 1.1rem;
  color: #94a3b8;
  transition: transform 0.2s;
}
.pipeline-card:hover .pl-arrow {
  color: #2563eb;
  transform: translateX(3px);
}
</style>
