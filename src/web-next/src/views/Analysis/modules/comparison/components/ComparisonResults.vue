<script setup lang="ts">
import { ref, computed } from 'vue';
import InstantMetricCard from './InstantMetricCard.vue';
import SyntenyPlot from './SyntenyPlot.vue';
import InteractiveSimilarityPlot from './InteractiveSimilarityPlot.vue';
import SequenceAlignment from './SequenceAlignment.vue';
import type { AlignmentResult } from '../utils/instantAlignment';
import { convertToAlignments } from '../utils/instantAlignment';

const props = defineProps<{
  result: AlignmentResult;
}>();

const alignments = computed(() => convertToAlignments(props.result));
const expandedVarIdx = ref<number | null>(null);

function toggleVariant(idx: number) {
  expandedVarIdx.value = expandedVarIdx.value === idx ? null : idx;
}
</script>

<template>
  <div class="comparison-results-report space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-700">
    <!-- 头部：分析报告标题 -->
    <div class="report-header">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      <h2 class="title">分析报告</h2>
    </div>

    <!-- 第一行：核心指标 -->
    <div class="metrics-grid">
      <InstantMetricCard 
        title="序列 1 长度" 
        :value="`${(result.len1 / 1000).toFixed(1)} kb`" 
        :subtitle="`${result.len1} bp`" 
      />
      <InstantMetricCard 
        title="序列 2 长度" 
        :value="`${(result.len2 / 1000).toFixed(1)} kb`" 
        :subtitle="`${result.len2} bp`" 
      />
      <InstantMetricCard 
        title="相对方向与起始点" 
        :value="result.globalSim < 0.01 ? '无显著相关' : (result.mainStrand === '+' ? '正向同源' : '反向互补')" 
        :subtitle="result.globalSim < 0.01 ? '相似度过低，无法判定' : `方向纯度: ${(result.strandRatio * 100).toFixed(1)}%`" 
        :class="{ 'warning-text': result.globalSim < 0.01 }"
      />
      <InstantMetricCard 
        title="全局近似相似度" 
        :value="`${(result.globalSim * 100).toFixed(2)}%`" 
        subtitle="无视起始位置差异" 
        highlight 
      />
    </div>

    <!-- 第二行：可视化图表 (交互式窗) -->
    <div class="viz-grid">
      <div class="viz-card">
        <h3 class="viz-title">
          <svg class="icon blue" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          共线性点阵图 (Dot Plot)
        </h3>
        <p class="viz-hint">若图呈断裂的平行对角线，说明两序列起始位置不同（环状结构）。</p>
        <div class="canvas-container">
          <SyntenyPlot 
            :alignments="alignments" 
            :metadata="{ ref_name: 'Sequence 1', query_name: 'Sequence 2' }" 
          />
        </div>
      </div>

      <div class="viz-card">
        <h3 class="viz-title">
          <svg class="icon green" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          局部相似度趋势 (Sliding Window)
        </h3>
        <p class="viz-hint">基于 {{ result.binSize }} bp 窗口。低谷区域为潜在变异位点。</p>
        <div class="chart-container">
          <InteractiveSimilarityPlot :bins="result.bins" />
        </div>
      </div>
    </div>

    <!-- 第三行：变异位点详情列表 -->
    <div class="variants-card">
      <div class="card-header">
        <h3 class="viz-title">
          <svg class="icon red" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          核心差异与微观序列对比 (Variant Details)
        </h3>
        <p class="viz-hint">点击列表展开查看具体变异的碱基。当前敏感度阈值：{{ (result.variantThreshold * 100).toFixed(0) }}%。</p>
      </div>

      <div class="table-wrapper">
        <table class="variants-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>序列1 区间 (bp)</th>
              <th>序列2 对应起始 (bp)</th>
              <th>区域长度</th>
              <th>局部得分</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="result.variants.length > 0">
              <template v-for="(v, idx) in result.variants" :key="idx">
                <tr 
                  class="row-main" 
                  :class="{ active: expandedVarIdx === idx }"
                  @click="toggleVariant(idx)"
                >
                  <td class="col-idx">{{ idx + 1 }}</td>
                  <td>{{ v.start.toLocaleString() }} - {{ v.end.toLocaleString() }}</td>
                  <td class="text-slate-400">{{ v.s2_start_pos.toLocaleString() }}</td>
                  <td class="font-bold">{{ (v.end - v.start).toLocaleString() }}</td>
                  <td>
                    <span :class="v.score < 0.9 ? 'text-rose-600 font-bold' : 'text-slate-700'">
                      {{ (v.score * 100).toFixed(1) }}%
                    </span>
                  </td>
                  <td class="col-action">
                    <svg v-if="expandedVarIdx === idx" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
                    <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                  </td>
                </tr>
                <tr v-if="expandedVarIdx === idx" class="row-detail">
                  <td colspan="6" class="detail-cell">
                    <div class="detail-content">
                      <h4 class="detail-title">序列碱基对比 (Sequence Alignment)</h4>
                      <SequenceAlignment 
                        :s1="v.s1_sub" 
                        :s2="v.s2_sub" 
                        :s1-start="v.start" 
                        :strand="result.mainStrand" 
                      />
                    </div>
                  </td>
                </tr>
              </template>
            </template>
            <tr v-else>
              <td colspan="6" class="empty-cell">未检测到显著变异，序列高度一致。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.comparison-results-report { width: 100%; }

.report-header { display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px; color: #1e293b; }
.report-header .title { font-size: 1.1rem; font-weight: 800; margin: 0; }

.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }

.viz-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; align-items: stretch; }
.viz-card { background: white; border-radius: 16px; border: 1px solid #f1f5f9; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); display: flex; flex-direction: column; height: 100%; }
.viz-title { font-size: 0.95rem; font-weight: 700; display: flex; align-items: center; gap: 6px; margin: 0; color: #334155; line-height: 1.2; }
.viz-title .icon.blue { color: #4f46e5; }
.viz-title .icon.green { color: #10b981; }
.viz-title .icon.red { color: #ef4444; }
.viz-hint { font-size: 0.72rem; color: #94a3b8; margin: 4px 0 12px; min-height: 1.5em; }

.canvas-container { position: relative; width: 100%; flex: 1; min-height: 300px; background: #f8fafc; border-radius: 10px; border: 1px solid #e2e8f0; overflow: hidden; }
.chart-container { position: relative; width: 100%; flex: 1; min-height: 300px; background: #f8fafc; border-radius: 10px; border: 1px solid #e2e8f0; }

.variants-card { background: white; border-radius: 16px; border: 1px solid #f1f5f9; box-shadow: 0 1px 3px rgba(0,0,0,0.02); overflow: hidden; }
.variants-card .card-header { padding: 16px 20px; border-bottom: 1px solid #f8fafc; }

.table-wrapper { width: 100%; overflow-x: hidden; }
.variants-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
.variants-table th { background: #f8fafc; padding: 10px 20px; text-align: left; color: #64748b; font-weight: 600; font-size: 12px; }
.variants-table td { padding: 10px 20px; border-bottom: 1px solid #f1f5f9; color: #334155; }

.row-main { cursor: pointer; transition: all 0.2s; }
.row-main:hover { background: #f5f3ff; }
.row-main.active { background: #f5f3ff; }
.col-idx { color: #94a3b8; font-family: monospace; }
.col-action { color: #3b82f6; text-align: center; }

.detail-cell { padding: 0 !important; overflow: hidden; }
.detail-content { 
  padding: 24px; 
  border-bottom: 2px solid #eef2ff; 
  width: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.detail-title { font-size: 13px; font-weight: 800; color: #1e293b; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.detail-title::before { content: ""; width: 3px; height: 14px; background: #4f46e5; border-radius: 2px; }

.empty-cell { padding: 32px; text-align: center; color: #94a3b8; font-style: italic; }

@media (max-width: 1024px) {
  .metrics-grid { grid-template-columns: 1fr 1fr; }
  .viz-grid { grid-template-columns: 1fr; }
}
</style>
