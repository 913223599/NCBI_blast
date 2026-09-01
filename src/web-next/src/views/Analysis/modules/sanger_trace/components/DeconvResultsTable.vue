<script setup lang="ts">
/**
 * DeconvResultsTable.vue
 * Sanger 峰图分析与解峰结果列表组件
 */
import { ref, computed } from 'vue';
import type { SampleDeconvResult, DiagnosisCategory } from '../types';

const props = defineProps<{
  samples: SampleDeconvResult[];
  selectedSampleId: string;
}>();

const emit = defineEmits<{
  (e: 'selectSample', sample: SampleDeconvResult): void;
  (e: 'exportFasta', selectedSamples: SampleDeconvResult[], mode: string): void;
  (e: 'sendToBlast', selectedSamples: SampleDeconvResult[]): void;
}>();

// 筛选与搜索
const searchQuery = ref('');
const filterCategory = ref<string>('ALL');
const hideCleanSingle = ref<boolean>(false);

// 排序字段与升降序 (默认按 sample_id 自然顺序升序)
const sortField = ref<'sample_id' | 'avg_quality' | 'avg_secondary_ratio' | 'machine_diff_count'>('sample_id');
const sortAsc = ref<boolean>(true);

function toggleSort(field: 'sample_id' | 'avg_quality' | 'avg_secondary_ratio' | 'machine_diff_count') {
  if (sortField.value === field) {
    sortAsc.value = !sortAsc.value;
  } else {
    sortField.value = field;
    sortAsc.value = true;
  }
}

// 选中的样本复选框
const checkedIds = ref<Set<string>>(new Set());

// 复制提示
const copySuccess = ref(false);

// 自然排序比较器
function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

const filteredSamples = computed(() => {
  const list = props.samples.filter(s => {
    // 快速过滤单峰正常样本
    if (hideCleanSingle.value && s.diagnosis?.category === 'CLEAN_SINGLE') {
      return false;
    }
    if (filterCategory.value === 'ONLY_DOUBLE') {
      if (s.diagnosis?.category === 'CLEAN_SINGLE') return false;
    } else if (filterCategory.value !== 'ALL' && s.diagnosis?.category !== filterCategory.value) {
      return false;
    }
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase();
      const matchName = s.sample_id?.toLowerCase().includes(q) || s.filename?.toLowerCase().includes(q);
      const matchCat = s.diagnosis?.category?.toLowerCase().includes(q);
      return matchName || matchCat;
    }
    return true;
  });

  list.sort((a, b) => {
    let cmp = 0;
    if (sortField.value === 'sample_id') {
      cmp = naturalCompare(a.sample_id || a.filename || '', b.sample_id || b.filename || '');
    } else if (sortField.value === 'avg_quality') {
      cmp = (a.avg_quality || 0) - (b.avg_quality || 0);
    } else if (sortField.value === 'avg_secondary_ratio') {
      cmp = (a.avg_secondary_ratio || 0) - (b.avg_secondary_ratio || 0);
    } else if (sortField.value === 'machine_diff_count') {
      cmp = (a.machine_diff_count || 0) - (b.machine_diff_count || 0);
    }
    return sortAsc.value ? cmp : -cmp;
  });

  return list;
});

// 分页与每页条数 (默认 50 条，充分展示所有样本)
const pageSize = ref<number>(50);
const currentPage = ref<number>(1);

const totalPages = computed(() => {
  if (pageSize.value <= 0) return 1;
  return Math.ceil(filteredSamples.value.length / pageSize.value) || 1;
});

const paginatedSamples = computed(() => {
  if (pageSize.value <= 0) return filteredSamples.value;
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredSamples.value.slice(start, start + pageSize.value);
});

const isAllChecked = computed(() => {
  if (filteredSamples.value.length === 0) return false;
  return filteredSamples.value.every(s => checkedIds.value.has(s.sample_id));
});

function toggleCheckAll() {
  if (isAllChecked.value) {
    filteredSamples.value.forEach(s => checkedIds.value.delete(s.sample_id));
  } else {
    filteredSamples.value.forEach(s => checkedIds.value.add(s.sample_id));
  }
}

function toggleCheck(sampleId: string) {
  if (checkedIds.value.has(sampleId)) {
    checkedIds.value.delete(sampleId);
  } else {
    checkedIds.value.add(sampleId);
  }
}

function selectByCategory(cat: string) {
  filterCategory.value = cat;
  currentPage.value = 1;
  checkedIds.value.clear();
  if (cat === 'ALL') {
    props.samples.forEach(s => checkedIds.value.add(s.sample_id));
  } else if (cat === 'ONLY_DOUBLE') {
    props.samples.filter(s => s.diagnosis?.category !== 'CLEAN_SINGLE').forEach(s => checkedIds.value.add(s.sample_id));
  } else {
    props.samples.filter(s => s.diagnosis?.category === cat).forEach(s => checkedIds.value.add(s.sample_id));
  }
}

const checkedSamplesList = computed(() => {
  return props.samples.filter(s => checkedIds.value.has(s.sample_id));
});

function getCategoryBadge(cat: DiagnosisCategory) {
  switch (cat) {
    case 'CLEAN_SINGLE':
      return { text: '单峰极佳', cls: 'badge-clean' };
    case 'HETERO_INDEL':
      return { text: '杂合 InDel 移码', cls: 'badge-indel' };
    case 'MIXED_TEMPLATE':
      return { text: '复合模板/混合菌', cls: 'badge-mixed' };
    case 'PARTIAL_POLYMORPHISM':
      return { text: '局部 SNP 杂合', cls: 'badge-snp' };
    case 'LOW_SNR':
    default:
      return { text: '低信噪比/衰减', cls: 'badge-low' };
  }
}

async function copySeq(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copySuccess.value = true;
    setTimeout(() => { copySuccess.value = false; }, 2000);
  } catch (e) {
    console.error('Copy failed:', e);
  }
}
</script>

<template>
  <div class="deconv-results-panel">
    <!-- 筛选控制栏 -->
    <div class="table-header-controls">
      <div class="left-controls">
        <input 
          type="text" 
          v-model="searchQuery" 
          placeholder="搜索样本名称 / 编号..." 
          class="search-input"
        />

        <div class="category-filters">
          <button 
            class="filter-pill" 
            :class="{ active: filterCategory === 'ALL' && !hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('ALL')"
          >
            全部 ({{ samples.length }})
          </button>
          <button 
            class="filter-pill pill-double" 
            :class="{ active: filterCategory === 'ONLY_DOUBLE' || hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('ONLY_DOUBLE')"
            title="过滤单峰正常样本，仅查看需解峰/双峰/杂合样本"
          >
            🔥 过滤单峰 / 仅双峰 ({{ samples.filter(s => s.diagnosis?.category !== 'CLEAN_SINGLE').length }})
          </button>
          <button 
            class="filter-pill pill-indel" 
            :class="{ active: filterCategory === 'HETERO_INDEL' && !hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('HETERO_INDEL')"
          >
            InDel 移码 ({{ samples.filter(s => s.diagnosis?.category === 'HETERO_INDEL').length }})
          </button>
          <button 
            class="filter-pill pill-mixed" 
            :class="{ active: filterCategory === 'MIXED_TEMPLATE' && !hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('MIXED_TEMPLATE')"
          >
            复合模板/双峰 ({{ samples.filter(s => s.diagnosis?.category === 'MIXED_TEMPLATE').length }})
          </button>
          <button 
            class="filter-pill pill-snp" 
            :class="{ active: filterCategory === 'PARTIAL_POLYMORPHISM' && !hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('PARTIAL_POLYMORPHISM')"
          >
            局部杂合 ({{ samples.filter(s => s.diagnosis?.category === 'PARTIAL_POLYMORPHISM').length }})
          </button>
          <button 
            class="filter-pill pill-clean" 
            :class="{ active: filterCategory === 'CLEAN_SINGLE' && !hideCleanSingle }"
            @click="hideCleanSingle = false; selectByCategory('CLEAN_SINGLE')"
          >
            单峰正常 ({{ samples.filter(s => s.diagnosis?.category === 'CLEAN_SINGLE').length }})
          </button>
        </div>
      </div>

      <div class="right-actions">
        <span class="selection-count">已选 {{ checkedSamplesList.length }} 项</span>
        <button 
          class="btn-action-primary" 
          :disabled="checkedSamplesList.length === 0"
          @click="emit('sendToBlast', checkedSamplesList)"
        >
          一键送入 BLAST 分析
        </button>
        <button 
          class="btn-action-secondary" 
          :disabled="checkedSamplesList.length === 0"
          @click="emit('exportFasta', checkedSamplesList, 'alleles')"
        >
          导出 FASTA 序列
        </button>
      </div>
    </div>

    <!-- 样本表格 -->
    <div class="table-scroll-wrapper scroll-v">
      <table class="deconv-table">
        <thead>
          <tr>
            <th width="40" class="col-center">
              <input type="checkbox" :checked="isAllChecked" @change="toggleCheckAll" />
            </th>
            <th width="180" class="sortable-th" @click="toggleSort('sample_id')">
              样本 ID
              <span class="sort-indicator" v-if="sortField === 'sample_id'">{{ sortAsc ? '▲' : '▼' }}</span>
            </th>
            <th width="130">诊断分类</th>
            <th width="120">解峰诊断说明</th>
            <th width="80" class="col-center sortable-th" @click="toggleSort('avg_quality')">
              质量分
              <span class="sort-indicator" v-if="sortField === 'avg_quality'">{{ sortAsc ? '▲' : '▼' }}</span>
            </th>
            <th width="90" class="col-center sortable-th" @click="toggleSort('avg_secondary_ratio')">
              次峰均值
              <span class="sort-indicator" v-if="sortField === 'avg_secondary_ratio'">{{ sortAsc ? '▲' : '▼' }}</span>
            </th>
            <th width="90" class="col-center sortable-th" @click="toggleSort('machine_diff_count')">
              误判修正
              <span class="sort-indicator" v-if="sortField === 'machine_diff_count'">{{ sortAsc ? '▲' : '▼' }}</span>
            </th>
            <th>解峰生成序列 (Alleles)</th>
            <th width="90" class="col-center">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr 
            v-for="s in paginatedSamples" 
            :key="s.sample_id"
            :class="{ active: selectedSampleId === s.sample_id, 'row-error': !s.success }"
            @click="emit('selectSample', s)"
          >
            <td class="col-center" @click.stop>
              <input 
                type="checkbox" 
                :checked="checkedIds.has(s.sample_id)" 
                @change="toggleCheck(s.sample_id)" 
              />
            </td>
            <td class="sample-id-cell">
              <strong>{{ s.sample_id }}</strong>
              <span class="sub-filename">{{ s.filename }}</span>
            </td>
            <td>
              <span :class="['cat-badge', getCategoryBadge(s.diagnosis?.category).cls]">
                {{ getCategoryBadge(s.diagnosis?.category).text }}
              </span>
            </td>
            <td class="diagnosis-desc-cell">
              <div class="diag-action">{{ s.diagnosis?.action }}</div>
              <div v-if="s.diagnosis?.is_indel" class="indel-tag">
                Shift: {{ s.diagnosis.indel_shift > 0 ? `+${s.diagnosis.indel_shift}` : s.diagnosis.indel_shift }} bp ({{ s.diagnosis.indel_match_rate }}% 匹配)
              </div>
            </td>
            <td class="col-center mono">
              <span :class="s.avg_quality >= 30 ? 'q-high' : s.avg_quality >= 20 ? 'q-mid' : 'q-low'">
                Q{{ s.avg_quality }}
              </span>
            </td>
            <td class="col-center mono">
              {{ (s.avg_secondary_ratio * 100).toFixed(1) }}%
            </td>
            <td class="col-center mono">
              <span v-if="s.machine_diff_count > 0" class="diff-badge">
                +{{ s.machine_diff_count }} bp
              </span>
              <span v-else class="diff-zero">0</span>
            </td>
            <td class="alleles-cell" @click.stop>
              <div class="alleles-container">
                <div 
                  v-for="a in s.sequences?.alleles" 
                  :key="a.allele_id"
                  class="allele-chip"
                  :class="`chip-${a.type || 'primary'}`"
                >
                  <span class="allele-name">{{ a.label }}:</span>
                  <span class="allele-len">{{ a.length }} bp</span>
                  <button 
                    class="btn-copy-chip" 
                    title="复制序列"
                    @click="copySeq(a.sequence)"
                  >
                    复制
                  </button>
                </div>
              </div>
            </td>
            <td class="col-center" @click.stop>
              <button 
                class="btn-view-trace" 
                @click="emit('selectSample', s)"
              >
                查看峰图
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 表格底部工具栏与分页控制 -->
    <div class="table-pagination-bar">
      <div class="page-info">
        共 <strong>{{ filteredSamples.length }}</strong> 项样本
        <span v-if="filteredSamples.length > 0">
          (当前显示 {{ Math.min(filteredSamples.length, (currentPage - 1) * (pageSize > 0 ? pageSize : 1) + 1) }} ~ {{ pageSize > 0 ? Math.min(filteredSamples.length, currentPage * pageSize) : filteredSamples.length }} 项)
        </span>
      </div>
      <div class="page-controls">
        <span class="ctrl-label">每页行数:</span>
        <select v-model.number="pageSize" class="page-size-select" @change="currentPage = 1">
          <option :value="15">15 行</option>
          <option :value="30">30 行</option>
          <option :value="50">50 行 (推荐)</option>
          <option :value="100">100 行</option>
          <option :value="-1">全部展开显示</option>
        </select>
        
        <div v-if="pageSize > 0 && totalPages > 1" class="page-nav">
          <button :disabled="currentPage <= 1" @click="currentPage--" class="btn-page">上一页</button>
          <span class="cur-page">{{ currentPage }} / {{ totalPages }}</span>
          <button :disabled="currentPage >= totalPages" @click="currentPage++" class="btn-page">下一页</button>
        </div>
      </div>
    </div>

    <!-- 复制成功提示浮层 -->
    <div v-if="copySuccess" class="toast-notice">序列已复制到剪贴板</div>
  </div>
</template>

<style scoped>
.deconv-results-panel {
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  min-height: 520px;
}

.table-header-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  gap: 12px;
  flex-wrap: wrap;
}

.left-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}

.search-input {
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  font-size: 0.8rem;
  width: 220px;
}

.category-filters {
  display: flex;
  gap: 6px;
}

.filter-pill {
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  background: white;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}

.filter-pill.active {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.pill-double {
  border-color: #cbd5e1;
  background: #fdf4ff;
  color: #a21caf;
}
.pill-double.active {
  background: linear-gradient(135deg, #9333ea, #c026d3);
  border-color: #9333ea;
  color: white;
  box-shadow: 0 2px 6px rgba(168, 85, 247, 0.3);
}

.pill-indel.active { background: #ea580c; border-color: #ea580c; }
.pill-mixed.active { background: #7c3aed; border-color: #7c3aed; }
.pill-snp.active { background: #d97706; border-color: #d97706; }
.pill-clean.active { background: #059669; border-color: #059669; }

.right-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.selection-count {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 600;
}

.btn-action-primary {
  padding: 7px 14px;
  border-radius: 8px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  font-weight: 600;
  font-size: 0.78rem;
  border: none;
  cursor: pointer;
}

.btn-action-primary:disabled, .btn-action-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-action-secondary {
  padding: 7px 14px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
  font-size: 0.78rem;
  border: 1px solid #bfdbfe;
  cursor: pointer;
}

.table-scroll-wrapper {
  flex: 1;
  min-height: 460px;
  overflow-y: auto;
}

.deconv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.deconv-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
  padding: 8px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  position: sticky;
  top: 0;
  z-index: 10;
  user-select: none;
}

.sortable-th {
  cursor: pointer;
  transition: color 0.15s;
}

.sortable-th:hover {
  color: #2563eb;
  background: #f1f5f9;
}

.sort-indicator {
  display: inline-block;
  font-size: 0.65rem;
  margin-left: 4px;
  color: #2563eb;
}

.deconv-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.deconv-table tr {
  cursor: pointer;
  transition: background 0.1s;
}

.deconv-table tr:hover {
  background: #f8fafc;
}

.deconv-table tr.active {
  background: #eff6ff;
}

.col-center { text-align: center; }
.mono { font-family: monospace; font-size: 0.82rem; }

.sample-id-cell {
  display: flex;
  flex-direction: column;
}

.sub-filename {
  font-size: 0.7rem;
  color: #94a3b8;
}

.cat-badge {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}

.badge-clean { background: #ecfdf5; color: #059669; }
.badge-indel { background: #fff7ed; color: #c2410c; }
.badge-mixed { background: #f5f3ff; color: #6d28d9; }
.badge-snp { background: #fefce8; color: #a16207; }
.badge-low { background: #f1f5f9; color: #64748b; }

.diagnosis-desc-cell {
  font-size: 0.75rem;
  max-width: 220px;
}

.diag-action { color: #334155; line-height: 1.3; }
.indel-tag {
  display: inline-block;
  margin-top: 2px;
  font-weight: 700;
  color: #ea580c;
  font-size: 0.7rem;
}

.q-high { color: #059669; font-weight: 700; }
.q-mid { color: #d97706; font-weight: 700; }
.q-low { color: #dc2626; font-weight: 700; }

.diff-badge {
  background: #fef2f2;
  color: #dc2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 0.75rem;
}

.diff-zero { color: #94a3b8; }

.alleles-container {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.allele-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.72rem;
}

.allele-chip.chip-primary { background: #eff6ff; border: 1px solid #bfdbfe; }
.allele-chip.chip-secondary { background: #f5f3ff; border: 1px solid #ddd6fe; }
.allele-chip.chip-indel_primary { background: #ecfdf5; border: 1px solid #a7f3d0; }
.allele-chip.chip-indel_secondary { background: #fff7ed; border: 1px solid #fed7aa; }
.allele-chip.chip-iupac { background: #f8fafc; border: 1px solid #e2e8f0; }

.allele-name { color: #1e293b; font-weight: 600; }
.allele-len { color: #64748b; font-family: monospace; }
.btn-copy-chip {
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 0.65rem;
  font-weight: 600;
  cursor: pointer;
  color: #475569;
  transition: all 0.15s;
}
.btn-copy-chip:hover { color: #2563eb; border-color: #2563eb; background: #eff6ff; }

.btn-view-trace {
  padding: 4px 8px;
  border-radius: 6px;
  background: #eff6ff;
  color: #2563eb;
  border: none;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.btn-view-trace:hover { background: #2563eb; color: white; }

.table-pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  font-size: 0.76rem;
  color: #64748b;
  flex-wrap: wrap;
  gap: 10px;
}

.page-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ctrl-label {
  color: #475569;
  font-weight: 600;
}

.page-size-select {
  padding: 3px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
  font-size: 0.75rem;
  color: #1e293b;
  cursor: pointer;
}

.page-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-page {
  padding: 3px 8px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 0.72rem;
  color: #334155;
  cursor: pointer;
  font-weight: 600;
}

.btn-page:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-page:not(:disabled):hover {
  background: #eff6ff;
  border-color: #2563eb;
  color: #2563eb;
}

.cur-page {
  font-family: monospace;
  font-weight: 700;
  color: #1e293b;
}

.toast-notice {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #0f172a;
  color: white;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.8rem;
  box-shadow: 0 10px 25px rgba(0,0,0,0.2);
  z-index: 1000;
}
</style>
