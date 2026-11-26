<script setup lang="ts">
import type { AnnotationTaskItem } from '../types'
import { useAnnotationResults } from '../composables/useAnnotationResults'

const props = defineProps<{
  task: AnnotationTaskItem
}>()

const emit = defineEmits<{
  (e: 'open-in-viewer', gbkText: string, taskName: string): void
  (e: 'open-structure'): void
  (e: 'download', fileType: string): void
}>()

const {
  searchQuery,
  selectedTypeFilter,
  selectedStrandFilter,
  selectedCategoryFilter,
  selectedEngineFilter,
  currentPage,
  pageSize,
  expandedRowId,
  showSafetyDetails,
  availableCategories,
  availableEngines,
  filteredFeatures,
  pagedFeatures,
  totalPages,
  amrList,
  vfList,
  acrList,
  hasSafetyAudit,
  totalSafetyHits,
  openResultsFolder,
  toggleExpand,
  copyText,
  handleOpenInViewer,
  formatNumber,
} = useAnnotationResults(props, emit)
</script>

<template>
  <div class="annotation-results-container">
    <div class="results-action-bar">
      <div class="task-badge-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span class="task-title-text">{{ task.task_name }}</span>
        <span class="wb-chip info">{{ task.sample_type }}</span>
      </div>

      <div class="action-right">
        <button type="button" class="viewer-btn" @click="handleOpenInViewer" title="在 SnapGene 风格查看器中查看圈图与线性图谱">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
            <path d="M2 12h20" />
          </svg>
          在序列交互可视化中查看
        </button>

        <button type="button" class="structure-btn" @click="emit('open-structure')" title="基于当前注释预测噬菌体尾部形态与卷尺蛋白 (TMP) 分子标尺">
          尾部形态与结构预测
        </button>

        <div class="export-dropdown-group">
          <button type="button" class="wb-btn-primary export-primary" @click="emit('download', 'gbk')">下载 GenBank (.gbk)</button>
          <button type="button" class="wb-btn-outline" @click="emit('download', 'gff')">GFF3</button>
          <button type="button" class="wb-btn-outline" @click="emit('download', 'faa')">蛋白 FASTA</button>
          <button type="button" class="wb-btn-outline" @click="emit('download', 'ffn')">基因 FASTA</button>
          <button type="button" class="wb-btn-outline" @click="emit('download', 'tsv')">TSV 表格</button>
          <button type="button" class="wb-btn-outline" @click="openResultsFolder" title="在 Windows 资源管理器中打开结果所在文件夹">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            打开文件夹
          </button>
        </div>
      </div>
    </div>

    <div class="wb-kpi-grid" v-if="task.summary">
      <div class="wb-kpi-card">
        <div class="kpi-label">基因组全长</div>
        <div class="kpi-value">{{ formatNumber(task.summary.total_length) }} <span class="unit">bp</span></div>
        <div class="kpi-sub">包含 {{ task.summary.num_contigs || 1 }} 条 Contig</div>
      </div>

      <div class="wb-kpi-card">
        <div class="kpi-label">GC 含量</div>
        <div class="kpi-value">{{ task.summary.gc_content || 0 }} <span class="unit">%</span></div>
        <div class="kpi-sub">全序列加权均值</div>
      </div>

      <div class="wb-kpi-card primary">
        <div class="kpi-label">预测 CDS 编码基因</div>
        <div class="kpi-value">{{ formatNumber(task.summary.cds_count) }} <span class="unit">个</span></div>
        <div class="kpi-sub">编码密度: {{ task.summary.coding_density_pct || 0 }}%</div>
      </div>

      <div class="wb-kpi-card success" v-if="task.summary.annotated_count !== undefined">
        <div class="kpi-label">功能注释覆盖度</div>
        <div class="kpi-value">
          <span class="anno-stat-val">{{ task.summary.annotated_count || 0 }}</span>
          <span class="unit">/ {{ task.summary.cds_count || 0 }} ({{ Math.round(((task.summary.annotated_count || 0) / Math.max(1, task.summary.cds_count || 1)) * 100) }}%)</span>
        </div>
        <div class="kpi-sub">假定/未知蛋白: {{ task.summary.hypothetical_count || 0 }} 个</div>
      </div>

      <div class="wb-kpi-card" v-else>
        <div class="kpi-label">RNA / 结构特征</div>
        <div class="kpi-value">
          <span class="rna-stat">tRNA: {{ task.summary.trna_count || 0 }}</span>
          <span class="rna-stat">rRNA: {{ task.summary.rrna_count || 0 }}</span>
        </div>
        <div class="kpi-sub">CRISPR: {{ task.summary.crispr_count || 0 }}</div>
      </div>

      <div class="wb-kpi-card">
        <div class="kpi-label">平均基因长度</div>
        <div class="kpi-value">{{ task.summary.avg_gene_length || 0 }} <span class="unit">bp</span></div>
        <div class="kpi-sub">约 {{ Math.round((task.summary.avg_gene_length || 0) / 3) }} aa</div>
      </div>
    </div>

    <div class="engine-contrib-banner" v-if="task.summary?.engine_contributions && Object.keys(task.summary.engine_contributions).length > 1">
      <div class="contrib-title">多引擎级联互补贡献:</div>
      <div class="contrib-chips">
        <span class="contrib-chip" v-for="(cnt, eng) in task.summary.engine_contributions" :key="eng">
          <span class="eng-name">{{ eng }}</span>
          <span class="eng-cnt">{{ cnt }} 个</span>
        </span>
      </div>
    </div>

    <div class="wb-card safety-audit-card" v-if="hasSafetyAudit && task.safety_audit">
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
          <span class="wb-chip" :class="amrList.length ? 'warn' : ''">CARD 耐药基因: {{ amrList.length }}</span>
          <span class="wb-chip" :class="vfList.length ? 'warn' : ''">VFDB 毒力因子: {{ vfList.length }}</span>
          <span class="wb-chip info" v-if="task.safety_audit.anti_crispr_status">Anti-CRISPR: {{ task.safety_audit.anti_crispr_status }}</span>
          <button v-if="totalSafetyHits > 0" type="button" class="wb-btn-outline" @click="showSafetyDetails = !showSafetyDetails">
            {{ showSafetyDetails ? '收起详情' : `查看详情 (${totalSafetyHits})` }}
          </button>
        </div>
      </div>

      <transition name="slide-fade">
        <div class="safety-details-grid" v-if="showSafetyDetails && totalSafetyHits > 0">
          <div class="wb-surface-muted" v-if="amrList.length">
            <div class="box-title amr">耐药基因 (CARD)</div>
            <div class="box-list">
              <div class="box-item" v-for="(item, idx) in amrList" :key="idx">
                <span class="tag-cds">{{ item.cds_id }}</span>
                <span class="tag-desc">{{ item.description }}</span>
                <span class="tag-meta">相似度: {{ item.identity }}% | E={{ item.evalue }}</span>
              </div>
            </div>
          </div>

          <div class="wb-surface-muted" v-if="vfList.length">
            <div class="box-title vf">毒力因子 (VFDB)</div>
            <div class="box-list">
              <div class="box-item" v-for="(item, idx) in vfList" :key="idx">
                <span class="tag-cds">{{ item.cds_id }}</span>
                <span class="tag-desc">{{ item.description }}</span>
                <span class="tag-meta">相似度: {{ item.identity }}% | E={{ item.evalue }}</span>
              </div>
            </div>
          </div>

          <div class="wb-surface-muted" v-if="acrList.length">
            <div class="box-title acr">Anti-CRISPR (Acr) 逃逸因子 (前 20 条)</div>
            <div class="box-list">
              <div class="box-item" v-for="(item, idx) in acrList.slice(0, 20)" :key="idx">
                <span class="tag-cds">{{ item.cds_id }}</span>
                <span class="tag-desc">{{ item.source || item.description || 'Acr Protein' }}</span>
                <span class="tag-meta">相似度: {{ item.identity }}%</span>
              </div>
            </div>
          </div>
        </div>
      </transition>
    </div>

    <div class="wb-card">
      <div class="table-toolbar">
        <div class="filter-controls">
          <div class="search-input-wrap">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input type="text" v-model="searchQuery" placeholder="搜索 Locus Tag, Product, Gene..." class="search-input" />
          </div>

          <div class="filter-group">
            <label>类型:</label>
            <select v-model="selectedTypeFilter" class="wb-select filter-select">
              <option value="ALL">全部类型</option>
              <option value="CDS">CDS 编码区</option>
              <option value="tRNA">tRNA</option>
              <option value="rRNA">rRNA</option>
              <option value="CRISPR">CRISPR</option>
            </select>
          </div>

          <div class="filter-group" v-if="availableCategories.length > 0">
            <label>功能分类:</label>
            <select v-model="selectedCategoryFilter" class="wb-select filter-select">
              <option value="ALL">全部分类</option>
              <option v-for="cat in availableCategories" :key="cat" :value="cat">{{ cat }}</option>
            </select>
          </div>

          <div class="filter-group" v-if="availableEngines.length > 1">
            <label>补充引擎:</label>
            <select v-model="selectedEngineFilter" class="wb-select filter-select">
              <option value="ALL">全部引擎</option>
              <option v-for="eng in availableEngines" :key="eng" :value="eng">{{ eng }}</option>
            </select>
          </div>

          <div class="filter-group">
            <label>链向:</label>
            <select v-model="selectedStrandFilter" class="wb-select filter-select">
              <option value="ALL">全部 (+/-)</option>
              <option value="+">正链 (+)</option>
              <option value="-">负链 (-)</option>
            </select>
          </div>
        </div>

        <div class="table-counts">显示 {{ filteredFeatures.length }} / {{ task.features?.length || 0 }} 个特征</div>
      </div>

      <div class="table-responsive">
        <table class="feature-table">
          <thead>
            <tr>
              <th width="40">#</th>
              <th width="130">Locus Tag</th>
              <th width="70">类型</th>
              <th width="120">功能分类</th>
              <th width="130">位置区间</th>
              <th width="50">链</th>
              <th width="80">长度(bp)</th>
              <th width="80">蛋白大小</th>
              <th>产物功能描述 (Product)</th>
              <th width="90">补充引擎</th>
              <th width="65">操作</th>
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
                <td><span :class="['type-pill', feat.feature_type.toLowerCase()]">{{ feat.feature_type }}</span></td>
                <td>
                  <span class="cat-pill" v-if="feat.category">{{ feat.category }}</span>
                  <span v-else class="text-muted">-</span>
                </td>
                <td class="cell-pos">{{ formatNumber(feat.start) }} - {{ formatNumber(feat.end) }}</td>
                <td><span :class="['strand-pill', feat.strand === '+' ? 'plus' : 'minus']">{{ feat.strand }}</span></td>
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
                  <span class="engine-badge" v-if="feat.source_engine">{{ feat.source_engine }}</span>
                  <span v-else class="text-muted">-</span>
                </td>
                <td>
                  <button type="button" class="wb-btn-outline expand-btn" @click="toggleExpand(feat.id || String(idx))">
                    {{ expandedRowId === (feat.id || String(idx)) ? '收起' : '详情' }}
                  </button>
                </td>
              </tr>

              <tr v-if="expandedRowId === (feat.id || String(idx))" class="expand-detail-row">
                <td colspan="11">
                  <div class="expand-content">
                    <div class="evidence-box" v-if="feat.notes || feat.evidence_sources?.length || feat.ec_number">
                      <div class="ev-header">注释特征属性与证据链:</div>
                      <div class="ev-items">
                        <div class="ev-row" v-if="feat.phrog">
                          <span class="ev-label">PHROG 编号:</span>
                          <span class="ev-val">PHROG #{{ feat.phrog }} <span v-if="feat.function" class="text-muted">({{ feat.function }})</span></span>
                        </div>
                        <div class="ev-row" v-if="feat.ec_number">
                          <span class="ev-label">EC 酶学编号:</span>
                          <span class="ev-val">{{ feat.ec_number }}</span>
                        </div>
                        <div class="ev-row" v-if="feat.cog">
                          <span class="ev-label">COG 功能分类:</span>
                          <span class="ev-val">{{ feat.cog }}</span>
                        </div>
                        <div class="ev-row" v-if="feat.evidence_sources?.length">
                          <span class="ev-label">各引擎溯源证据:</span>
                          <div class="ev-source-list">
                            <span class="ev-src-tag" v-for="(ev, eIdx) in feat.evidence_sources" :key="eIdx">{{ ev }}</span>
                          </div>
                        </div>
                        <div class="ev-row" v-else-if="feat.notes">
                          <span class="ev-label">证据信息:</span>
                          <span class="ev-val">{{ feat.notes }}</span>
                        </div>
                      </div>
                    </div>

                    <div class="seq-block" v-if="feat.translation">
                      <div class="seq-header">
                        <span>蛋白质翻译序列 ({{ feat.protein_length_aa }} aa)</span>
                        <button type="button" class="wb-btn-outline" @click="copyText(feat.translation)">复制氨基酸序列</button>
                      </div>
                      <pre class="seq-pre">{{ feat.translation }}</pre>
                    </div>

                    <div class="seq-block" v-if="feat.nucleotide_seq">
                      <div class="seq-header">
                        <span>核酸编码序列 ({{ feat.length_bp }} bp)</span>
                        <button type="button" class="wb-btn-outline" @click="copyText(feat.nucleotide_seq)">复制核酸序列</button>
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

      <div class="pagination-bar">
        <div class="page-size-wrap">
          <span>每页条数:</span>
          <select v-model.number="pageSize" class="wb-select filter-select">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </div>

        <div class="page-nav">
          <button type="button" class="wb-btn-outline" :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
          <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
          <button type="button" class="wb-btn-outline" :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotation-results-container, .expand-content { display: flex; flex-direction: column; gap: 14px; }
.results-action-bar, .table-toolbar, .pagination-bar, .safety-header, .seq-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.results-action-bar { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 18px; }
.task-badge-title, .action-right, .export-dropdown-group, .filter-controls, .filter-group, .safety-title, .safety-summary-badges, .page-size-wrap, .page-nav { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.task-title-text { font-size: 16px; font-weight: 700; color: #1e293b; }
.viewer-btn, .structure-btn { display: inline-flex; align-items: center; gap: 6px; color: #ffffff; border: none; padding: 7px 14px; border-radius: 6px; font-size: 13px; font-weight: 700; cursor: pointer; transition: background-color 0.2s; }
.viewer-btn { background: #10b981; }
.viewer-btn:hover { background: #059669; }
.structure-btn { background: #4f46e5; }
.structure-btn:hover { background: #4338ca; }
.export-primary { padding: 6px 12px; font-size: 12px; }
.kpi-label { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 20px; font-weight: 800; color: #1e293b; display: flex; align-items: baseline; gap: 4px; }
.kpi-value .unit, .kpi-sub { font-size: 11px; color: #94a3b8; font-weight: 600; }
.kpi-sub { margin-top: 4px; }
.anno-stat-val { color: #059669; font-weight: 800; }
.rna-stat { font-size: 14px; margin-right: 8px; }
.engine-contrib-banner { display: flex; align-items: center; gap: 12px; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 8px 14px; flex-wrap: wrap; }
.contrib-title { font-size: 12px; font-weight: 700; color: #475569; }
.contrib-chips, .ev-source-list { display: flex; flex-wrap: wrap; gap: 6px; }
.contrib-chip { display: inline-flex; align-items: center; gap: 6px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
.contrib-chip .eng-cnt { background: #eff6ff; color: #2563eb; padding: 1px 5px; border-radius: 4px; font-weight: 700; }
.search-input-wrap { display: flex; align-items: center; gap: 6px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 10px; }
.search-input { border: none; background: transparent; outline: none; font-size: 12px; color: #1e293b; width: 200px; }
.filter-group, .table-counts, .page-size-wrap, .page-info { font-size: 12px; color: #64748b; font-weight: 600; }
.filter-select { padding: 4px 8px; font-size: 12px; }
.table-responsive { overflow-x: auto; border: 1px solid #f1f5f9; border-radius: 8px; }
.feature-table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
.feature-table th { background: #f8fafc; padding: 10px 12px; font-weight: 700; color: #475569; border-bottom: 1px solid #e2e8f0; }
.feature-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; }
.feature-table tr:hover { background: #f8fafc; }
.feature-table tr.expanded { background: #f0f7ff; }
.cell-idx { color: #94a3b8; font-weight: 600; }
.gene-sub { color: #2563eb; font-size: 11px; margin-left: 4px; }
.type-pill { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; }
.type-pill.cds { background: #dbeafe; color: #1e40af; }
.type-pill.trna { background: #dcfce7; color: #166534; }
.type-pill.rrna { background: #fef3c7; color: #92400e; }
.type-pill.crispr { background: #f3e8ff; color: #6b21a8; }
.cat-pill { display: inline-block; background: #f1f5f9; color: #334155; font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; border: 1px solid #e2e8f0; }
.engine-badge { display: inline-block; background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }
.strand-pill { font-weight: 800; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.strand-pill.plus { background: #e0e7ff; color: #3730a3; }
.strand-pill.minus { background: #fee2e2; color: #991b1b; }
.cell-pos, .seq-pre, .tag-cds { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.mw-sub { display: block; font-size: 10px; color: #94a3b8; }
.cell-product { max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.expand-btn { padding: 3px 8px; font-size: 11px; }
.expand-detail-row td { background: #f8fafc; padding: 16px; }
.evidence-box { background: #f8faff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 10px 14px; }
.ev-header { font-size: 11px; font-weight: 700; color: #1e40af; margin-bottom: 6px; }
.ev-items { display: flex; flex-direction: column; gap: 4px; }
.ev-row { display: flex; align-items: baseline; gap: 8px; font-size: 12px; }
.ev-label { font-weight: 700; color: #64748b; min-width: 100px; }
.ev-val { color: #1e293b; }
.ev-src-tag { background: #ffffff; border: 1px solid #cbd5e1; padding: 1px 6px; border-radius: 4px; font-size: 11px; color: #334155; }
.seq-block { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 14px; }
.seq-header { margin-bottom: 8px; font-weight: 700; font-size: 11px; color: #475569; }
.seq-pre { margin: 0; font-size: 11px; line-height: 1.5; color: #1e293b; max-height: 120px; overflow-y: auto; word-break: break-all; white-space: pre-wrap; }
.safety-title { font-weight: 700; font-size: 14px; color: #1e293b; }
.safety-badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px; }
.safety-badge.passed { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
.safety-badge.warning { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
.safety-details-grid { padding-top: 12px; border-top: 1px solid #f1f5f9; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.box-title { font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.box-title.amr { color: #dc2626; }
.box-title.vf { color: #d97706; }
.box-title.acr { color: #2563eb; }
.box-list { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; }
.box-item { display: flex; align-items: center; justify-content: space-between; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; padding: 6px 10px; font-size: 11px; gap: 8px; }
.tag-cds { font-weight: 700; color: #0f172a; background: #f1f5f9; padding: 2px 5px; border-radius: 3px; flex-shrink: 0; }
.tag-desc { flex: 1; color: #334155; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tag-meta { font-size: 10px; color: #64748b; flex-shrink: 0; }
</style>
