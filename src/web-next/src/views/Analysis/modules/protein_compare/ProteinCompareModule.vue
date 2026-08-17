<script setup lang="ts">
/**
 * ProteinCompareModule - 核心蛋白跨样本比对与变异分析工作台
 * 职责：对比两个噬菌体/细菌注释结果中的尾丝、裂解酶、衣壳等关键蛋白，展示氨基酸变异、突变位点及导出 CSV
 */
import { ref, computed, onMounted } from 'vue';
import { getBridge } from '../../../../bridge';
import type { 
  ComparableTaskItem, 
  ProteinComparisonResultPayload, 
  ProteinComparisonRowItem 
} from './types';

// 1. 状态管理
const availableTasks = ref<ComparableTaskItem[]>([]);
const isTasksLoading = ref<boolean>(false);
const isComparing = ref<boolean>(false);
const errorMessage = ref<string | null>(null);

// 选择的样本
const sampleAId = ref<string>('');
const sampleBId = ref<string>('');

// 选中的分类筛选
const selectedCategory = ref<string>('all');
const searchQuery = ref<string>('');
const statusFilter = ref<string>('ALL');

// 比对结果数据
const comparisonResult = ref<ProteinComparisonResultPayload | null>(null);

// 展开查看序列详情的行 ID
const expandedRowKey = ref<string | null>(null);

// 支持的功能分类定义
const categories = [
  { key: 'all', label: '全部蛋白 (All CDS)' },
  { key: 'tail_fiber', label: '尾丝与宿主识别 (Tail Fiber)' },
  { key: 'lysis', label: '裂解系统与溶菌酶 (Lysis System)' },
  { key: 'capsid_head', label: '衣壳与头部形态发生 (Capsid & Head)' },
  { key: 'replication', label: 'DNA 复制与修饰酶 (Replication)' },
  { key: 'packaging', label: '基因组包装末端酶 (Packaging)' }
];

// 2. 初始化载入可比对的任务列表
onMounted(async () => {
  await fetchTasks();
});

async function fetchTasks() {
  isTasksLoading.value = true;
  errorMessage.value = null;
  try {
    const bridge = getBridge();
    const res = await bridge.get_comparable_annotation_tasks?.();
    if (res && res.success) {
      availableTasks.value = res.data || [];
    }
  } catch (err: any) {
    console.warn('[ProteinCompare] 获取任务列表失败:', err);
    errorMessage.value = `获取已完成注释任务列表失败: ${err.message}`;
  } finally {
    isTasksLoading.value = false;
  }
}

// 3. 执行跨样本比对
async function executeComparison() {
  if (!sampleAId.value || !sampleBId.value) {
    errorMessage.value = '请先选择要进行比对的样本 A 与 样本 B';
    return;
  }

  if (sampleAId.value === sampleBId.value) {
    errorMessage.value = '样本 A 与 样本 B 不能为同一条任务，请选择两个不同的样本';
    return;
  }

  isComparing.value = true;
  errorMessage.value = null;
  expandedRowKey.value = null;

  try {
    const bridge = getBridge();
    const taskA = availableTasks.value.find(t => t.task_id === sampleAId.value);
    const taskB = availableTasks.value.find(t => t.task_id === sampleBId.value);

    const res = await bridge.run_protein_comparison?.({
      sample_a_id: sampleAId.value,
      sample_b_id: sampleBId.value,
      sample_a_name: taskA?.task_name || sampleAId.value,
      sample_b_name: taskB?.task_name || sampleBId.value,
      category: selectedCategory.value
    });

    if (res && res.success && res.data) {
      comparisonResult.value = res.data;
    } else {
      throw new Error(res?.detail || res?.message || '比对未返回有效数据');
    }
  } catch (err: any) {
    errorMessage.value = `比对执行失败: ${err.message}`;
  } finally {
    isComparing.value = false;
  }
}

// 切换分类筛选
async function selectCategoryTab(catKey: string) {
  selectedCategory.value = catKey;
  // 仅在用户已经执行过比对时，切换分类才重新计算
  if (comparisonResult.value && sampleAId.value && sampleBId.value) {
    await executeComparison();
  }
}

// 4. 过滤与搜索结果表格
const filteredRows = computed(() => {
  if (!comparisonResult.value) return [];
  let rows = comparisonResult.value.rows || [];

  // 状态过滤
  if (statusFilter.value !== 'ALL') {
    rows = rows.filter(r => r.match_status === statusFilter.value);
  }

  // 搜索过滤 (Locus Tag, Product, Mutations)
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase().trim();
    rows = rows.filter(r => 
      r.sample_a_tag.toLowerCase().includes(q) ||
      r.sample_a_product.toLowerCase().includes(q) ||
      (r.sample_b_tag && r.sample_b_tag.toLowerCase().includes(q)) ||
      (r.sample_b_product && r.sample_b_product.toLowerCase().includes(q)) ||
      r.category_label.toLowerCase().includes(q)
    );
  }

  return rows;
});

// 分页状态
const currentPage = ref<number>(1);
const pageSize = ref<number>(15);

const paginatedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredRows.value.slice(start, start + pageSize.value);
});

const totalPages = computed(() => {
  return Math.ceil(filteredRows.value.length / pageSize.value) || 1;
});

// 5. 导出 CSV 文件
async function exportCsvReport() {
  if (!comparisonResult.value || !sampleAId.value || !sampleBId.value) return;
  try {
    const url = `/api/analysis/protein_compare/export_csv`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sample_a_id: sampleAId.value,
        sample_b_id: sampleBId.value,
        sample_a_name: comparisonResult.value.sample_a_name,
        sample_b_name: comparisonResult.value.sample_b_name,
        category: selectedCategory.value
      })
    });

    if (!resp.ok) throw new Error('导出下载失败');

    const blob = await resp.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = `Protein_Comparison_${sampleAId.value}_${sampleBId.value}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  } catch (err: any) {
    alert(`导出 CSV 失败: ${err.message}`);
  }
}

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'identical': return 'badge-identical';
    case 'highly_conserved': return 'badge-conserved';
    case 'divergent': return 'badge-divergent';
    default: return 'badge-unique';
  }
}

function getStatusLabel(status: string) {
  switch (status) {
    case 'identical': return '100% 完全相同';
    case 'highly_conserved': return '高度保守 (≥95%)';
    case 'divergent': return '显著分歧 (<95%)';
    case 'unique_a': return '样本 A 独有';
    case 'unique_b': return '样本 B 独有';
    default: return status;
  }
}

function toggleExpandRow(row: ProteinComparisonRowItem) {
  const key = `${row.sample_a_id}_${row.sample_b_id || 'none'}`;
  if (expandedRowKey.value === key) {
    expandedRowKey.value = null;
  } else {
    expandedRowKey.value = key;
  }
}

function copyText(text: string) {
  navigator.clipboard.writeText(text);
  alert('氨基酸序列已复制到剪贴板');
}
</script>

<template>
  <div class="protein-compare-container">
    <!-- 1. 顶部操作与样本选择器 -->
    <header class="compare-header-card">
      <div class="header-main-row">
        <div class="title-wrap">
          <div class="icon-box">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.2">
              <path d="M16 3h5v5" />
              <path d="M4 20L21 3" />
              <path d="M21 16v5h-5" />
              <path d="M15 15l6 6" />
              <path d="M4 4l5 5" />
            </svg>
          </div>
          <div>
            <h2>核心蛋白跨样本比对分析</h2>
            <p>对比两个基因组注释结果中尾丝、裂解酶、衣壳与复制酶等核心序列的同源性、一致性与点突变</p>
          </div>
        </div>

        <div class="header-actions">
          <button 
            class="action-btn primary" 
            :disabled="isComparing || !sampleAId || !sampleBId || sampleAId === sampleBId"
            @click="executeComparison"
          >
            <svg v-if="!isComparing" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            <span v-if="isComparing" class="btn-spinner"></span>
            <span>{{ isComparing ? '比对计算中...' : (comparisonResult ? '重新比对' : '开始比对') }}</span>
          </button>

          <button 
            class="action-btn secondary" 
            :disabled="!comparisonResult"
            @click="exportCsvReport"
            title="导出为 CSV 报告"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            <span>导出 CSV</span>
          </button>
        </div>
      </div>

      <!-- 样本选择下拉选择器 -->
      <div class="sample-selection-grid">
        <div class="sample-box">
          <div class="sample-header">
            <span class="sample-tag tag-a">基准样本 (Sample A)</span>
            <span v-if="sampleAId" class="sample-info">
              {{ availableTasks.find(t => t.task_id === sampleAId)?.cds_count || 0 }} CDS
            </span>
          </div>
          <select v-model="sampleAId" class="sample-select">
            <option value="" disabled>-- 请选择基准注释任务 --</option>
            <option v-for="t in availableTasks" :key="t.task_id" :value="t.task_id">
              {{ t.task_name }} ({{ t.sample_type }}, {{ t.cds_count }} CDS) - {{ t.task_id }}
            </option>
          </select>
        </div>

        <div class="vs-divider">
          <span>VS</span>
        </div>

        <div class="sample-box">
          <div class="sample-header">
            <span class="sample-tag tag-b">对比目标 (Sample B)</span>
            <span v-if="sampleBId" class="sample-info">
              {{ availableTasks.find(t => t.task_id === sampleBId)?.cds_count || 0 }} CDS
            </span>
          </div>
          <select v-model="sampleBId" class="sample-select">
            <option value="" disabled>-- 请选择比对目标注释任务 --</option>
            <option v-for="t in availableTasks" :key="t.task_id" :value="t.task_id">
              {{ t.task_name }} ({{ t.sample_type }}, {{ t.cds_count }} CDS) - {{ t.task_id }}
            </option>
          </select>
        </div>
      </div>

      <!-- 错误警告提示 -->
      <div v-if="errorMessage" class="error-banner">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span>{{ errorMessage }}</span>
      </div>
    </header>

    <!-- 2. 功能分类选项卡 -->
    <div class="category-tabs-bar">
      <button 
        v-for="cat in categories" 
        :key="cat.key"
        :class="['cat-tab', { active: selectedCategory === cat.key }]"
        @click="selectCategoryTab(cat.key)"
      >
        <span>{{ cat.label }}</span>
        <span 
          v-if="comparisonResult && comparisonResult.category_summary[cat.key]" 
          class="cat-count-badge"
        >
          {{ comparisonResult.category_summary[cat.key]?.total || 0 }}
        </span>
      </button>
    </div>

    <!-- 3. KPI 统计概览卡片 -->
    <div v-if="comparisonResult" class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-title">比对总对数</div>
        <div class="kpi-value highlight">{{ comparisonResult.total_compared_pairs }}</div>
        <div class="kpi-sub">包含全部分类蛋白质</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">100% 完全相同</div>
        <div class="kpi-value text-green">{{ comparisonResult.identical_count }}</div>
        <div class="kpi-sub">序列 0 差异</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">高度保守 (≥95%)</div>
        <div class="kpi-value text-blue">{{ comparisonResult.conserved_count }}</div>
        <div class="kpi-sub">存在微小点突变</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">显著分歧 (&lt;95%)</div>
        <div class="kpi-value text-orange">{{ comparisonResult.divergent_count }}</div>
        <div class="kpi-sub">受体结合/结构变异</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-title">平均序列相似度</div>
        <div class="kpi-value">{{ comparisonResult.average_identity_pct }}%</div>
        <div class="kpi-sub">双向全局对齐均值</div>
      </div>
    </div>

    <!-- 4. 比对明细数据表格 -->
    <section v-if="comparisonResult" class="table-section-card">
      <div class="table-toolbar">
        <div class="search-box">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input 
            type="text" 
            v-model="searchQuery" 
            placeholder="搜索 Locus Tag, Product, 蛋白功能关键词..." 
            class="search-input"
          />
        </div>

        <div class="filter-group">
          <label>匹配状态:</label>
          <select v-model="statusFilter" class="filter-select">
            <option value="ALL">全部状态</option>
            <option value="identical">100% 完全相同</option>
            <option value="highly_conserved">高度保守 (≥95%)</option>
            <option value="divergent">显著分歧 (&lt;95%)</option>
            <option value="unique_a">样本 A 独有</option>
            <option value="unique_b">样本 B 独有</option>
          </select>
          <span class="count-tag">共 {{ filteredRows.length }} 条记录</span>
        </div>
      </div>

      <div class="table-wrapper">
        <table class="compare-table">
          <thead>
            <tr>
              <th width="40">#</th>
              <th width="120">功能大类</th>
              <th width="140">匹配状态</th>
              <th width="130">相似度 (Identity)</th>
              <th>样本 A ({{ comparisonResult.sample_a_name }})</th>
              <th>样本 B ({{ comparisonResult.sample_b_name }})</th>
              <th width="140">变异详情</th>
              <th width="80">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(row, idx) in paginatedRows" :key="`${row.sample_a_id}_${row.sample_b_id}_${idx}`">
              <tr :class="{ 'row-expanded': expandedRowKey === `${row.sample_a_id}_${row.sample_b_id || 'none'}` }">
                <td class="col-num">{{ (currentPage - 1) * pageSize + idx + 1 }}</td>
                <td>
                  <span class="cat-badge">{{ row.category_label.split(' ')[0] }}</span>
                </td>
                <td>
                  <span :class="['status-pill', getStatusBadgeClass(row.match_status)]">
                    {{ getStatusLabel(row.match_status) }}
                  </span>
                </td>
                <td>
                  <div class="ident-bar-wrap">
                    <div class="ident-bar-track">
                      <div 
                        class="ident-bar-fill" 
                        :class="getStatusBadgeClass(row.match_status)"
                        :style="{ width: `${row.identity_pct}%` }"
                      ></div>
                    </div>
                    <span class="ident-text">{{ row.identity_pct }}%</span>
                  </div>
                </td>
                <td class="col-protein">
                  <div class="protein-tag-row">
                    <span class="tag-code">{{ row.sample_a_tag }}</span>
                    <span class="tag-len">{{ row.sample_a_len }} aa</span>
                  </div>
                  <div class="protein-name" :title="row.sample_a_product">{{ row.sample_a_product }}</div>
                </td>
                <td class="col-protein">
                  <template v-if="row.sample_b_tag">
                    <div class="protein-tag-row">
                      <span class="tag-code">{{ row.sample_b_tag }}</span>
                      <span class="tag-len">{{ row.sample_b_len }} aa</span>
                    </div>
                    <div class="protein-name" :title="row.sample_b_product">{{ row.sample_b_product }}</div>
                  </template>
                  <template v-else>
                    <span class="missing-text">[未检出对应同源序列]</span>
                  </template>
                </td>
                <td>
                  <div v-if="row.diff_count === 0" class="diff-chip zero">0 差异</div>
                  <div v-else class="diff-chip has-diff" :title="row.mutations.map(m => m.description).join('\n')">
                    {{ row.diff_count }} 处变异
                  </div>
                </td>
                <td>
                  <button class="expand-btn" @click="toggleExpandRow(row)">
                    {{ expandedRowKey === `${row.sample_a_id}_${row.sample_b_id || 'none'}` ? '收起' : '详情' }}
                  </button>
                </td>
              </tr>

              <!-- 展开的序列与突变详情 -->
              <tr v-if="expandedRowKey === `${row.sample_a_id}_${row.sample_b_id || 'none'}`" class="detail-row">
                <td colspan="8">
                  <div class="detail-container">
                    <div class="mutation-box" v-if="row.mutations && row.mutations.length > 0">
                      <div class="box-head">突变位点明细 (共 {{ row.mutations.length }} 处):</div>
                      <div class="mutation-tags">
                        <span v-for="(m, mIdx) in row.mutations" :key="mIdx" class="mut-tag">
                          {{ m.description }}
                        </span>
                      </div>
                    </div>

                    <div class="seq-compare-grid">
                      <div class="seq-box">
                        <div class="seq-head">
                          <span>样本 A 氨基酸序列 ({{ row.sample_a_len }} aa)</span>
                          <button class="copy-btn" @click="copyText(row.sample_a_seq)">复制</button>
                        </div>
                        <div class="seq-content">{{ row.sample_a_seq || '无序列' }}</div>
                      </div>

                      <div class="seq-box">
                        <div class="seq-head">
                          <span>样本 B 氨基酸序列 ({{ row.sample_b_len }} aa)</span>
                          <button v-if="row.sample_b_seq" class="copy-btn" @click="copyText(row.sample_b_seq)">复制</button>
                        </div>
                        <div class="seq-content">{{ row.sample_b_seq || '无序列' }}</div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- 分页栏 -->
      <div class="pagination-bar">
        <div class="page-size-wrap">
          <span>每页显示:</span>
          <select v-model="pageSize" class="page-select">
            <option :value="10">10 条</option>
            <option :value="15">15 条</option>
            <option :value="30">30 条</option>
            <option :value="50">50 条</option>
          </select>
        </div>

        <div class="page-nav">
          <button class="page-btn" :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
          <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
          <button class="page-btn" :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
        </div>
      </div>
    </section>

    <!-- 空状态 -->
    <div v-else-if="!isComparing" class="empty-placeholder">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3">
        <path d="M16 3h5v5" />
        <path d="M4 20L21 3" />
        <path d="M21 16v5h-5" />
        <path d="M15 15l6 6" />
        <path d="M4 4l5 5" />
      </svg>
      <h3>请选择要比对的两个样本并点击“开始比对”</h3>
      <p>系统将自动对齐尾丝蛋白、裂解酶、衣壳蛋白等关键基因并输出高精度变异图谱</p>
    </div>
  </div>
</template>

<style scoped>
.protein-compare-container {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 顶部选择卡片 */
.compare-header-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.header-main-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 20px;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 14px;
}

.icon-box {
  width: 44px;
  height: 44px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.title-wrap h2 {
  margin: 0;
  font-size: 17px;
  color: #1e293b;
  font-weight: 700;
}

.title-wrap p {
  margin: 2px 0 0;
  font-size: 12px;
  color: #64748b;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.primary {
  background: #2563eb;
  color: white;
  border: none;
}

.action-btn.primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.action-btn.secondary {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.action-btn.secondary:hover:not(:disabled) {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 样本选择器 */
.sample-selection-grid {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 18px;
}

.sample-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sample-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sample-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.sample-tag.tag-a {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}

.sample-tag.tag-b {
  background: #f0fdf4;
  color: #16a34a;
  border: 1px solid #bbf7d0;
}

.sample-info {
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
}

.sample-select {
  width: 100%;
  padding: 8px 12px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  color: #1e293b;
  outline: none;
}

.vs-divider {
  font-size: 12px;
  font-weight: 800;
  color: #94a3b8;
  padding: 0 4px;
}

.error-banner {
  margin-top: 14px;
  padding: 10px 14px;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  color: #dc2626;
  border-radius: 6px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 分类选项卡 */
.category-tabs-bar {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.cat-tab {
  background: white;
  border: 1px solid #e2e8f0;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
  white-space: nowrap;
}

.cat-tab:hover {
  background: #f8fafc;
  color: #1e293b;
}

.cat-tab.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #2563eb;
  font-weight: 700;
}

.cat-count-badge {
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
}

/* KPI 看板 */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.kpi-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.kpi-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.kpi-value {
  font-size: 22px;
  font-weight: 800;
  color: #1e293b;
  margin: 4px 0 2px;
}

.kpi-value.highlight { color: #2563eb; }
.kpi-value.text-green { color: #16a34a; }
.kpi-value.text-blue { color: #0284c7; }
.kpi-value.text-orange { color: #ea580c; }

.kpi-sub {
  font-size: 11px;
  color: #94a3b8;
}

/* 表格区域 */
.table-section-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  width: 320px;
}

.search-input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 12px;
  width: 100%;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.filter-select {
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
  font-size: 12px;
  color: #334155;
  outline: none;
}

.count-tag {
  font-weight: 600;
  color: #334155;
  margin-left: 8px;
}

.table-wrapper {
  overflow-x: auto;
}

.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  text-align: left;
}

.compare-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
}

.compare-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.col-num {
  color: #94a3b8;
  font-weight: 600;
}

.cat-badge {
  background: #f1f5f9;
  color: #475569;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.status-pill {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  display: inline-block;
}

.status-pill.badge-identical {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.status-pill.badge-conserved {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}

.status-pill.badge-divergent {
  background: #fff7ed;
  color: #ea580c;
  border: 1px solid #fed7aa;
}

.status-pill.badge-unique {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.ident-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ident-bar-track {
  width: 60px;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}

.ident-bar-fill {
  height: 100%;
}

.ident-bar-fill.badge-identical { background: #10b981; }
.ident-bar-fill.badge-conserved { background: #3b82f6; }
.ident-bar-fill.badge-divergent { background: #f97316; }
.ident-bar-fill.badge-unique { background: #94a3b8; }

.ident-text {
  font-weight: 700;
  color: #1e293b;
}

.col-protein {
  max-width: 240px;
}

.protein-tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.tag-code {
  font-family: monospace;
  font-size: 11px;
  font-weight: 700;
  color: #0f172a;
}

.tag-len {
  font-size: 10px;
  color: #64748b;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
}

.protein-name {
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.missing-text {
  color: #94a3b8;
  font-style: italic;
}

.diff-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  display: inline-block;
}

.diff-chip.zero {
  background: #f8fafc;
  color: #94a3b8;
}

.diff-chip.has-diff {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
  cursor: help;
}

.expand-btn {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.expand-btn:hover {
  background: #e2e8f0;
}

/* 展开详情 */
.detail-row td {
  background: #f8fafc;
  padding: 16px 20px;
}

.detail-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mutation-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
}

.box-head {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 6px;
}

.mutation-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mut-tag {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fee2e2;
  font-size: 11px;
  font-family: monospace;
  padding: 2px 6px;
  border-radius: 4px;
}

.seq-compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.seq-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}

.seq-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 6px;
}

.copy-btn {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  cursor: pointer;
}

.seq-content {
  font-family: monospace;
  font-size: 11px;
  color: #1e293b;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
  line-height: 1.4;
  background: #f8fafc;
  padding: 8px;
  border-radius: 4px;
}

/* 分页 */
.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.page-size-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
}

.page-select {
  padding: 3px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 12px;
}

.page-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-btn {
  background: white;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.empty-placeholder {
  background: white;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  padding: 60px 20px;
  text-align: center;
}

.empty-placeholder h3 {
  margin: 12px 0 6px;
  color: #1e293b;
  font-size: 15px;
}

.empty-placeholder p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}
</style>
