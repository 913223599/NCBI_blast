<script setup lang="ts">
/**
 * AnnotationResults - 功能注释结果展示面板
 */
import { ref, computed } from 'vue';
import { getBridge } from '../../../../../bridge';
import type { AnnotationTaskItem, FeatureItem } from '../types';

const props = defineProps<{
  task: AnnotationTaskItem;
}>();

const emit = defineEmits<{
  (e: 'open-in-viewer', gbkText: string, taskName: string): void;
  (e: 'download', fileType: string): void;
}>();

function openResultsFolder() {
  const workDir = (props.task as any).work_dir;
  if (workDir) {
    const bridge = getBridge();
    bridge.open_results_dir?.(workDir);
  } else {
    alert(`结果保存在: results/annotations/${props.task.task_id}`);
  }
}

// 筛选与搜索状态
const searchQuery = ref<string>('');
const selectedTypeFilter = ref<string>('ALL');
const selectedStrandFilter = ref<string>('ALL');

// 分页状态
const currentPage = ref<number>(1);
const pageSize = ref<number>(20);

// 展开详情的行 ID
const expandedRowId = ref<string | null>(null);

// 特征过滤计算属性
const filteredFeatures = computed(() => {
  const list = props.task.features || [];
  const q = searchQuery.value.trim().toLowerCase();
  
  return list.filter(item => {
    // 类型过滤
    if (selectedTypeFilter.value !== 'ALL' && item.feature_type !== selectedTypeFilter.value) {
      return false;
    }
    // 链过滤
    if (selectedStrandFilter.value !== 'ALL' && item.strand !== selectedStrandFilter.value) {
      return false;
    }
    // 关键字搜索
    if (q) {
      const matchTag = item.locus_tag?.toLowerCase().includes(q);
      const matchProd = item.product?.toLowerCase().includes(q);
      const matchGene = item.gene_name?.toLowerCase().includes(q);
      return matchTag || matchProd || matchGene;
    }
    return true;
  });
});

// 分页特征
const pagedFeatures = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredFeatures.value.slice(start, start + pageSize.value);
});

const totalPages = computed(() => {
  return Math.ceil(filteredFeatures.value.length / pageSize.value) || 1;
});

function toggleExpand(id: string) {
  expandedRowId.value = expandedRowId.value === id ? null : id;
}

function copyText(text?: string | null) {
  if (!text) return;
  navigator.clipboard.writeText(text);
  alert('序列内容已复制到剪贴板');
}

function handleOpenInViewer() {
  const gbk = props.task.gbk_content || '';
  if (!gbk) {
    alert('未找到可用的 GenBank 数据，请检查注释产物');
    return;
  }
  emit('open-in-viewer', gbk, props.task.task_name || props.task.task_id);
}

// 格式化数字
function formatNumber(num?: number | null): string {
  if (num === undefined || num === null) return '0';
  return num.toLocaleString();
}
</script>

<template>
  <div class="annotation-results-container">
    <!-- 1. 顶部操作工具栏 -->
    <div class="results-action-bar">
      <div class="action-left">
        <div class="task-badge-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <span class="task-title-text">{{ task.task_name }}</span>
          <span class="sample-type-tag">{{ task.sample_type }}</span>
        </div>
      </div>

      <div class="action-right">
        <!-- 在查看器中打开 (核心联动) -->
        <button class="viewer-btn" @click="handleOpenInViewer" title="在 SnapGene 风格查看器中查看圈图与线性图谱">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
            <path d="M2 12h20" />
          </svg>
          在序列交互可视化中查看
        </button>

        <!-- 下载与打开文件夹菜单组 -->
        <div class="export-dropdown-group">
          <button class="export-btn" @click="emit('download', 'gbk')">下载 GenBank (.gbk)</button>
          <button class="export-btn secondary" @click="emit('download', 'gff')">GFF3</button>
          <button class="export-btn secondary" @click="emit('download', 'faa')">蛋白 FASTA</button>
          <button class="export-btn secondary" @click="emit('download', 'ffn')">基因 FASTA</button>
          <button class="export-btn secondary" @click="emit('download', 'tsv')">TSV 表格</button>
          <button class="export-btn folder-btn" @click="openResultsFolder" title="在 Windows 资源管理器中打开结果所在文件夹">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            打开文件夹
          </button>
        </div>
      </div>
    </div>

    <!-- 2. KPI 概览看板 -->
    <div class="kpi-grid" v-if="task.summary">
      <div class="kpi-card">
        <div class="kpi-label">基因组全长</div>
        <div class="kpi-value">{{ formatNumber(task.summary.total_length) }} <span class="unit">bp</span></div>
        <div class="kpi-sub">包含 {{ task.summary.num_contigs }} 条 Contig</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">GC 含量</div>
        <div class="kpi-value">{{ task.summary.gc_content }} <span class="unit">%</span></div>
        <div class="kpi-sub">全序列加权均值</div>
      </div>

      <div class="kpi-card primary">
        <div class="kpi-label">预测 CDS 蛋白编码基因</div>
        <div class="kpi-value">{{ formatNumber(task.summary.cds_count) }} <span class="unit">个</span></div>
        <div class="kpi-sub">编码密度: {{ task.summary.coding_density_pct }}%</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">RNA / 结构特征</div>
        <div class="kpi-value">
          <span class="rna-stat">tRNA: {{ task.summary.trna_count }}</span>
          <span class="rna-stat">rRNA: {{ task.summary.rrna_count }}</span>
        </div>
        <div class="kpi-sub">CRISPR: {{ task.summary.crispr_count }}</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-label">平均基因长度</div>
        <div class="kpi-value">{{ task.summary.avg_gene_length }} <span class="unit">bp</span></div>
        <div class="kpi-sub">约 {{ Math.round(task.summary.avg_gene_length / 3) }} aa</div>
      </div>
    </div>

    <!-- 2.5 深度生物安全审计与防御系统扫描卡片 -->
    <div class="safety-audit-card" v-if="task.safety_audit">
      <div class="safety-header">
        <div class="safety-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" :stroke="task.safety_audit.safety_passed ? '#10b981' : '#f59e0b'" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          <span>生物安全性与宿主防御逃逸审计</span>
          <span class="safety-badge" :class="task.safety_audit.safety_passed ? 'passed' : 'warning'">
            {{ task.safety_audit.safety_passed ? '安全合规 (未检出已知高危耐药/毒力)' : '注意 (检出潜在耐药/毒力风险)' }}
          </span>
        </div>
        <div class="safety-summary-badges">
          <span class="audit-chip" :class="task.safety_audit.amr_genes.length ? 'chip-alert' : 'chip-ok'">
            CARD 耐药基因: {{ task.safety_audit.amr_genes.length }}
          </span>
          <span class="audit-chip" :class="task.safety_audit.virulent_factors.length ? 'chip-alert' : 'chip-ok'">
            VFDB 毒力因子: {{ task.safety_audit.virulent_factors.length }}
          </span>
          <span class="audit-chip chip-info">
            Anti-CRISPR: {{ task.safety_audit.anti_crispr_status }}
          </span>
        </div>
      </div>

      <!-- 详细命中列表展示 (如有) -->
      <div class="safety-details-grid" v-if="task.safety_audit.amr_genes.length || task.safety_audit.virulent_factors.length || task.safety_audit.anti_crispr_genes.length">
        <div class="safety-box" v-if="task.safety_audit.amr_genes.length">
          <div class="box-title amr">耐药基因 (CARD)</div>
          <div class="box-list">
            <div class="box-item" v-for="(item, idx) in task.safety_audit.amr_genes" :key="idx">
              <span class="tag-cds">{{ item.cds_id }}</span>
              <span class="tag-desc">{{ item.description }}</span>
              <span class="tag-meta">相似度: {{ item.identity }}% | E={{ item.evalue }}</span>
            </div>
          </div>
        </div>

        <div class="safety-box" v-if="task.safety_audit.virulent_factors.length">
          <div class="box-title vf">毒力因子 (VFDB)</div>
          <div class="box-list">
            <div class="box-item" v-for="(item, idx) in task.safety_audit.virulent_factors" :key="idx">
              <span class="tag-cds">{{ item.cds_id }}</span>
              <span class="tag-desc">{{ item.description }}</span>
              <span class="tag-meta">相似度: {{ item.identity }}% | E={{ item.evalue }}</span>
            </div>
          </div>
        </div>

        <div class="safety-box" v-if="task.safety_audit.anti_crispr_genes.length">
          <div class="box-title acr">Anti-CRISPR (Acr) 逃逸因子</div>
          <div class="box-list">
            <div class="box-item" v-for="(item, idx) in task.safety_audit.anti_crispr_genes" :key="idx">
              <span class="tag-cds">{{ item.cds_id }}</span>
              <span class="tag-desc">{{ item.source || item.description || 'Acr Protein' }}</span>
              <span class="tag-meta">相似度: {{ item.identity }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 特征数据明细表格 -->
    <div class="features-section">
      <div class="table-toolbar">
        <div class="filter-controls">
          <!-- 搜索 -->
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input 
              type="text" 
              v-model="searchQuery" 
              placeholder="搜索 Locus Tag, Product, Gene..." 
              class="search-input" 
            />
          </div>

          <!-- 类型过滤 -->
          <div class="filter-group">
            <label>类型:</label>
            <select v-model="selectedTypeFilter" class="filter-select">
              <option value="ALL">全部类型</option>
              <option value="CDS">CDS 编码区</option>
              <option value="tRNA">tRNA</option>
              <option value="rRNA">rRNA</option>
              <option value="CRISPR">CRISPR</option>
            </select>
          </div>

          <!-- 链过滤 -->
          <div class="filter-group">
            <label>链向:</label>
            <select v-model="selectedStrandFilter" class="filter-select">
              <option value="ALL">全部 (+/-)</option>
              <option value="+">正链 (+)</option>
              <option value="-">负链 (-)</option>
            </select>
          </div>
        </div>

        <div class="table-counts">
          显示 {{ filteredFeatures.length }} / {{ task.features?.length || 0 }} 个特征
        </div>
      </div>

      <!-- 表格主体 -->
      <div class="table-responsive">
        <table class="feature-table">
          <thead>
            <tr>
              <th width="40">#</th>
              <th width="140">Locus Tag</th>
              <th width="80">类型</th>
              <th width="140">位置区间</th>
              <th width="60">链</th>
              <th width="90">长度(bp)</th>
              <th width="90">蛋白大小</th>
              <th>产物功能描述 (Product)</th>
              <th width="70">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(feat, idx) in pagedFeatures" :key="feat.id || idx">
              <tr :class="{ expanded: expandedRowId === (feat.id || String(idx)) }">
                <td class="cell-idx">{{ (currentPage - 1) * pageSize + idx + 1 }}</td>
                <td class="cell-tag">
                  <strong>{{ feat.locus_tag }}</strong>
                  <span v-if="feat.gene_name" class="gene-sub">({{ feat.gene_name }})</span>
                </td>
                <td>
                  <span :class="['type-pill', feat.feature_type.toLowerCase()]">{{ feat.feature_type }}</span>
                </td>
                <td class="cell-pos">{{ formatNumber(feat.start) }} - {{ formatNumber(feat.end) }}</td>
                <td>
                  <span :class="['strand-pill', feat.strand === '+' ? 'plus' : 'minus']">
                    {{ feat.strand }}
                  </span>
                </td>
                <td>{{ feat.length_bp }} bp</td>
                <td>
                  <template v-if="feat.protein_length_aa">
                    {{ feat.protein_length_aa }} aa
                    <span class="mw-sub">{{ feat.molecular_weight_kda }} kDa</span>
                  </template>
                  <template v-else>-</template>
                </td>
                <td class="cell-product" :title="feat.product">{{ feat.product }}</td>
                <td>
                  <button class="expand-btn" @click="toggleExpand(feat.id || String(idx))">
                    {{ expandedRowId === (feat.id || String(idx)) ? '收起' : '详情' }}
                  </button>
                </td>
              </tr>

              <!-- 展开抽屉：显示序列 -->
              <tr v-if="expandedRowId === (feat.id || String(idx))" class="expand-detail-row">
                <td colspan="9">
                  <div class="expand-content">
                    <div class="seq-block" v-if="feat.translation">
                      <div class="seq-header">
                        <span>蛋白质翻译序列 ({{ feat.protein_length_aa }} aa)</span>
                        <button class="copy-btn" @click="copyText(feat.translation)">复制氨基酸序列</button>
                      </div>
                      <pre class="seq-pre">{{ feat.translation }}</pre>
                    </div>

                    <div class="seq-block" v-if="feat.nucleotide_seq">
                      <div class="seq-header">
                        <span>核酸编码序列 ({{ feat.length_bp }} bp)</span>
                        <button class="copy-btn" @click="copyText(feat.nucleotide_seq)">复制核酸序列</button>
                      </div>
                      <pre class="seq-pre">{{ feat.nucleotide_seq }}</pre>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- 分页控制栏 -->
      <div class="pagination-bar">
        <div class="page-size-wrap">
          <span>每页条数:</span>
          <select v-model.number="pageSize" class="filter-select">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </div>

        <div class="page-nav">
          <button 
            class="page-nav-btn" 
            :disabled="currentPage <= 1" 
            @click="currentPage--"
          >
            上一页
          </button>
          <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
          <button 
            class="page-nav-btn" 
            :disabled="currentPage >= totalPages" 
            @click="currentPage++"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotation-results-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.results-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.task-badge-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-title-text {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
}

.sample-type-tag {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.action-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.viewer-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #10b981;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.25);
  transition: all 0.2s;
}

.viewer-btn:hover {
  background: #059669;
  transform: translateY(-1px);
}

.export-dropdown-group {
  display: flex;
  gap: 6px;
}

.export-btn {
  background: #2563eb;
  color: white;
  border: none;
  padding: 7px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.export-btn:hover {
  background: #1d4ed8;
}

.export-btn.secondary {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #475569;
}

.export-btn.secondary:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.export-btn.folder-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
}

.export-btn.folder-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.kpi-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
}

.kpi-card.primary {
  border-color: #93c5fd;
  background: #f8faff;
}

.kpi-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.kpi-value {
  font-size: 20px;
  font-weight: 800;
  color: #1e293b;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.kpi-value .unit {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
}

.kpi-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
}

.rna-stat {
  font-size: 14px;
  margin-right: 8px;
}

.features-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 4px 10px;
}

.search-input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 12px;
  color: #1e293b;
  width: 200px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.filter-select {
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #1e293b;
  background: white;
  outline: none;
}

.table-counts {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.table-responsive {
  overflow-x: auto;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
}

.feature-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  text-align: left;
}

.feature-table th {
  background: #f8fafc;
  padding: 10px 12px;
  font-weight: 700;
  color: #475569;
  border-bottom: 1px solid #e2e8f0;
}

.feature-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}

.feature-table tr:hover {
  background: #f8fafc;
}

.feature-table tr.expanded {
  background: #f0f7ff;
}

.cell-idx {
  color: #94a3b8;
  font-weight: 600;
}

.gene-sub {
  color: #2563eb;
  font-size: 11px;
  margin-left: 4px;
}

.type-pill {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
}

.type-pill.cds { background: #dbeafe; color: #1e40af; }
.type-pill.trna { background: #dcfce7; color: #166534; }
.type-pill.rrna { background: #fef3c7; color: #92400e; }
.type-pill.crispr { background: #f3e8ff; color: #6b21a8; }

.strand-pill {
  font-weight: 800;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}

.strand-pill.plus { background: #e0e7ff; color: #3730a3; }
.strand-pill.minus { background: #fee2e2; color: #991b1b; }

.cell-pos {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.mw-sub {
  display: block;
  font-size: 10px;
  color: #94a3b8;
}

.cell-product {
  max-width: 260px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.expand-btn {
  background: transparent;
  border: 1px solid #cbd5e1;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.expand-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.expand-detail-row td {
  background: #f8fafc;
  padding: 16px;
}

.expand-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.seq-block {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
}

.seq-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-weight: 700;
  font-size: 11px;
  color: #475569;
}

.copy-btn {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #2563eb;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
}

.copy-btn:hover {
  background: #eff6ff;
}

.seq-pre {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  color: #1e293b;
  max-height: 120px;
  overflow-y: auto;
  word-break: break-all;
  white-space: pre-wrap;
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
}

.page-size-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
}

.page-nav {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-nav-btn {
  background: white;
  border: 1px solid #cbd5e1;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}

.page-nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}
</style>
