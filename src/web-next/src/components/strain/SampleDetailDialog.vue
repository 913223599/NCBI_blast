<template>
  <div class="wb-dialog-overlay" @click.self="emit('close')">
    <div class="wb-dialog-content detail-dialog">
      <div class="wb-dialog-header">
        <div class="header-left">
          <div class="icon-wrapper"></div>
          <div>
            <h3 class="dialog-title">样本详情</h3>
            <p class="dialog-subtitle">{{ record.name }}</p>
          </div>
        </div>
        <div class="header-actions">
          <button v-if="!isEditing" type="button" class="wb-btn-outline" @click="toggleEditMode">编辑</button>
          <button v-if="isEditing" type="button" class="btn-save" @click="handleSave">保存</button>
          <button type="button" class="wb-btn-outline danger" @click="handleDelete">删除</button>
          <button type="button" class="close-btn" aria-label="关闭" @click="emit('close')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div class="wb-dialog-body">
        <div class="position-banner">
          <div class="position-icon">定位</div>
          <div class="position-details">
            <div class="position-path">{{ positionPath }}</div>
            <div class="position-label">位置：{{ record.position }}</div>
          </div>
        </div>

        <div v-if="!isEditing" class="view-mode">
          <div class="info-section">
            <h4 class="section-label">基本信息</h4>
            <div class="info-grid">
              <div class="info-item">
                <span class="label">样本名称</span>
                <span class="value">{{ record.name }}</span>
              </div>
              <div class="info-item">
                <span class="label">Accession 号</span>
                <span class="value mono">{{ record.accession || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="label">物种名称</span>
                <span class="value">{{ record.species || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="label">样本类型</span>
                <span class="value">
                  <span class="sample-type-badge">{{ getSampleTypeLabel(record.sampleType) }}</span>
                </span>
              </div>
              <div class="info-item">
                <span class="label">序列类型</span>
                <span class="value">
                  <span v-if="record.sequenceType" class="type-badge" :class="record.sequenceType.toLowerCase()">
                    {{ record.sequenceType }}
                  </span>
                  <span v-else>-</span>
                </span>
              </div>
            </div>
          </div>

          <div v-if="hasMetadata" class="info-section metadata-section">
            <h4 class="section-label">详细业务元数据</h4>
            <div class="info-grid">
              <div
                v-for="key in expectedMetadataKeys"
                :key="key"
                class="info-item"
                :class="{ 'full-width': isFullWidthMetadata(key, record.metadata?.[key]) }"
              >
                <span class="label">{{ getMetadataLabel(key) }}</span>
                <div class="value">
                  <div v-if="Array.isArray(record.metadata?.[key]) && record.metadata[key].length > 0" class="badge-group">
                    <span v-for="item in record.metadata[key]" :key="String(item)" class="meta-tag">{{ item }}</span>
                  </div>
                  <span v-else-if="typeof record.metadata?.[key] === 'boolean'">
                    {{ record.metadata[key] ? '是' : '否' }}
                  </span>
                  <span v-else>{{ formatMetadataValue(key, record.metadata?.[key]) }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="info-section">
            <h4 class="section-label">来源信息</h4>
            <div class="info-grid">
              <div class="info-item">
                <span class="label">宿主</span>
                <span class="value">{{ record.host || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="label">来源国家</span>
                <span class="value">{{ record.country || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="label">采集日期</span>
                <span class="value">{{ formatDate(record.collectionDate) }}</span>
              </div>
              <div class="info-item full-width">
                <span class="label">来源描述</span>
                <span class="value">{{ record.source || '-' }}</span>
              </div>
            </div>
          </div>

          <div v-if="record.sequence" class="info-section">
            <h4 class="section-label">基础序列 (预览)</h4>
            <div class="wb-surface-muted">
              <pre class="sequence-text">{{ record.sequence }}</pre>
            </div>
          </div>

          <div class="info-section gene-db-section">
            <div class="section-header-flex">
              <h4 class="section-label">基因数据库关联 (Gene DB)</h4>
              <button v-if="!showAddGeneForm" type="button" class="btn-add-gene" @click="showAddGeneForm = true">
                + 关联新测序数据
              </button>
            </div>

            <div v-if="showAddGeneForm" class="inline-gene-form">
              <div class="form-grid-mini">
                <div class="mini-group">
                  <label>测序类型</label>
                  <select v-model="newGene.seqType" class="wb-select full-w">
                    <option value="16S">16S rRNA</option>
                    <option value="ITS">ITS</option>
                    <option value="WGS">全基因组 (WGS)</option>
                    <option value="Plasmid">质粒全长</option>
                    <option value="TargetGen">目标基因</option>
                  </select>
                </div>
                <div class="mini-group">
                  <label>测序标题/批次</label>
                  <input v-model="newGene.title" class="wb-input full-w" placeholder="如：20240409-16S-A1" />
                </div>
              </div>
              <div class="mini-group mt-2">
                <label>序列内容 (FASTA)</label>
                <textarea v-model="newGene.sequence" class="wb-textarea" rows="4" placeholder="粘贴序列..."></textarea>
              </div>
              <div class="mini-actions">
                <button type="button" class="wb-btn-outline" @click="showAddGeneForm = false">取消</button>
                <button type="button" class="btn-add-gene" :disabled="!newGene.sequence" @click="handleAddGene">
                  确认保存到基因库
                </button>
              </div>
            </div>

            <div class="gene-list">
              <div v-if="associatedSequences.length === 0 && !showAddGeneForm" class="gene-empty">
                暂未关联基因数据库记录
              </div>
              <div v-for="seq in associatedSequences" :key="seq.id" class="gene-item">
                <div class="gene-main">
                  <div class="gene-badge">{{ seq.seqType }}</div>
                  <div class="gene-title-row">
                    <span class="gene-name">{{ seq.title }}</span>
                    <span class="gene-len">{{ seq.seqLen }} bp</span>
                  </div>
                </div>
                <div class="gene-actions">
                  <button type="button" class="wb-btn-link" @click="copySeq(seq.sequence)">复制</button>
                  <button type="button" class="btn-gene-del" @click="handleDeleteGene(seq.id)">移除</button>
                </div>
              </div>
            </div>
          </div>

          <div class="info-section">
            <h4 class="section-label">系统信息</h4>
            <div class="info-grid">
              <div class="info-item">
                <span class="label">录入时间</span>
                <span class="value">{{ formatDateTime(record.addedAt) }}</span>
              </div>
              <div class="info-item">
                <span class="label">记录 ID</span>
                <span class="value mono">{{ record.id }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="edit-mode">
          <div class="form-section">
            <h4 class="section-label">基本信息</h4>
            <div class="form-group">
              <label>样本名称 <span class="required">*</span></label>
              <input v-model="editForm.name" class="wb-input full-w" placeholder="例如：E. coli K-12" />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Accession 号</label>
                <input v-model="editForm.accession" class="wb-input full-w" placeholder="例如：NC_000913" />
              </div>
              <div class="form-group">
                <label>物种名称</label>
                <input v-model="editForm.species" class="wb-input full-w" placeholder="例如：Escherichia coli" />
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>样本类型</label>
                <div class="select-box-neo" @click.stop="toggleDropdown('sampleType')">
                  {{ getSampleTypeLabel(editForm.sampleType) }} <span class="arrow">▼</span>
                  <div v-if="openDropdown === 'sampleType'" class="dropdown-list">
                    <div
                      v-for="option in SAMPLE_TYPE_OPTIONS"
                      :key="option.value"
                      class="opt"
                      :class="{ selected: editForm.sampleType === option.value }"
                      @click.stop="selectOption('sampleType', option.value)"
                    >
                      {{ option.label }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="form-group">
                <label>序列类型</label>
                <div class="select-box-neo" @click.stop="toggleDropdown('sequenceType')">
                  {{ getSequenceTypeLabel() }} <span class="arrow">▼</span>
                  <div v-if="openDropdown === 'sequenceType'" class="dropdown-list">
                    <div
                      v-for="option in SEQUENCE_TYPE_OPTIONS"
                      :key="option.value"
                      class="opt"
                      :class="{ selected: editForm.sequenceType === option.value }"
                      @click.stop="selectOption('sequenceType', option.value)"
                    >
                      {{ option.label }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="form-section">
            <div class="section-header-flex">
              <h4 class="section-label">详细业务元数据</h4>
              <span class="type-tag">{{ getSampleTypeLabel(editForm.sampleType) }} 特有字段</span>
            </div>
            <div class="wb-surface-muted metadata-container">
              <BaseMetadataForm v-model="editForm.metadata" />
              <div class="divider"></div>
              <div class="dynamic-metadata-area">
                <MicrobeForm v-if="['Bacteria', 'Fungi', 'Archaea'].includes(editForm.sampleType)" v-model="editForm.metadata" />
                <PhageForm v-if="editForm.sampleType === 'Phage'" v-model="editForm.metadata" />
                <GeneticForm v-if="['Plasmid', 'GenomicDNA', 'RNA', 'Oligo', 'Library'].includes(editForm.sampleType)" v-model="editForm.metadata" />
                <VirusForm v-if="editForm.sampleType === 'Virus'" v-model="editForm.metadata" />
                <ProteinForm v-if="['Protein', 'Enzyme', 'Antibody', 'Peptide', 'Antigen'].includes(editForm.sampleType)" v-model="editForm.metadata" />
                <CellForm v-if="['CellLine', 'CompetentCell', 'Hybridomas'].includes(editForm.sampleType)" v-model="editForm.metadata" />
              </div>
            </div>
          </div>

          <div class="form-section">
            <h4 class="section-label">来源信息</h4>
            <div class="form-row">
              <div class="form-group">
                <label>宿主</label>
                <input v-model="editForm.host" class="wb-input full-w" placeholder="例如：Human" />
              </div>
              <div class="form-group">
                <label>来源国家</label>
                <input v-model="editForm.country" class="wb-input full-w" placeholder="例如：China" />
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>采集日期</label>
                <input v-model="editForm.collectionDate" class="wb-input full-w" type="date" />
              </div>
              <div class="form-group">
                <label>来源描述</label>
                <input v-model="editForm.source" class="wb-input full-w" placeholder="例如：临床分离株" />
              </div>
            </div>
            <div class="form-group">
              <label>序列数据</label>
              <textarea v-model="editForm.sequence" class="wb-textarea" placeholder=">Sequence_Title&#10;ATGCGATCG..." rows="6"></textarea>
            </div>
          </div>
        </div>
      </div>

      <div class="wb-dialog-footer">
        <button type="button" class="wb-btn-outline footer-btn" @click="emit('close')">关闭</button>
        <button v-if="isEditing" type="button" class="btn-save footer-btn" @click="handleSave">保存更改</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { StrainRecord } from '../../stores/strain'
import BaseMetadataForm from './forms/BaseMetadataForm.vue'
import MicrobeForm from './forms/MicrobeForm.vue'
import GeneticForm from './forms/GeneticForm.vue'
import VirusForm from './forms/VirusForm.vue'
import ProteinForm from './forms/ProteinForm.vue'
import CellForm from './forms/CellForm.vue'
import PhageForm from './forms/PhageForm.vue'
import {
  SAMPLE_TYPE_OPTIONS,
  SEQUENCE_TYPE_OPTIONS,
  useSampleDetail,
} from './detail/useSampleDetail'

const props = defineProps<{
  record: StrainRecord
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'deleted'): void
}>()

const {
  isEditing,
  openDropdown,
  associatedSequences,
  showAddGeneForm,
  newGene,
  editForm,
  expectedMetadataKeys,
  hasMetadata,
  positionPath,
  formatMetadataValue,
  toggleEditMode,
  handleSave,
  handleDelete,
  formatDate,
  formatDateTime,
  getSequenceTypeLabel,
  getSampleTypeLabel,
  toggleDropdown,
  getMetadataLabel,
  isFullWidthMetadata,
  selectOption,
  handleAddGene,
  handleDeleteGene,
  copySeq,
} = useSampleDetail(props, emit)
</script>

<style scoped>
.detail-dialog { width: 640px; }
.header-left, .header-actions, .gene-main, .gene-actions, .mini-actions { display: flex; align-items: center; gap: 10px; }
.icon-wrapper { width: 40px; height: 40px; background: linear-gradient(135deg, #f0fdf4, #dcfce7); border-radius: 10px; }
.dialog-title { font-size: 1.1rem; font-weight: 800; color: #0f172a; margin: 0 0 2px; }
.dialog-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }
.btn-save { padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; border: none; color: #ffffff; background: #10b981; cursor: pointer; }
.btn-save:hover { background: #059669; }
.footer-btn { padding: 9px 22px; font-size: 0.9rem; }
.close-btn { background: none; border: none; color: #94a3b8; cursor: pointer; padding: 6px 8px; border-radius: 6px; }
.close-btn:hover { background: #f1f5f9; color: #1e293b; }
.position-banner { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; }
.position-icon { font-size: 0.82rem; font-weight: 700; color: #1d4ed8; }
.position-details { flex: 1; }
.position-path { font-size: 0.85rem; color: #1e40af; font-weight: 600; margin-bottom: 2px; }
.position-label { font-size: 0.75rem; color: #3b82f6; }
.info-section, .form-section { margin-bottom: 22px; }
.section-label { font-size: 0.85rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 14px; }
.section-header-flex { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.section-header-flex .section-label { margin-bottom: 0; }
.info-grid, .form-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.info-item, .form-group { display: flex; flex-direction: column; gap: 5px; position: relative; }
.form-group { margin-bottom: 14px; }
.info-item.full-width { grid-column: 1 / -1; }
.info-item .label { font-size: 0.75rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; }
.info-item .value { font-size: 0.9rem; color: #1e293b; font-weight: 500; }
.info-item .value.mono, .sequence-text { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.form-group label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.required { color: #dc2626; }
.full-w { width: 100%; }
.type-badge { display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }
.type-badge.dna { background: #dbeafe; color: #1e40af; }
.type-badge.rna { background: #fce7f3; color: #be185d; }
.type-badge.protein { background: #fef3c7; color: #92400e; }
.sequence-text { margin: 0; font-size: 0.84rem; line-height: 1.6; color: #1e293b; white-space: pre-wrap; word-break: break-all; }
.metadata-section { background: #f8fafc; border-radius: 12px; padding: 16px; border: 1px solid #e2e8f0; }
.sample-type-badge, .type-tag { display: inline-flex; align-items: center; background: #ffffff; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 700; color: #475569; }
.badge-group { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.meta-tag { background: #dcfce7; color: #166534; font-size: 0.7rem; font-weight: 700; padding: 2px 8px; border-radius: 4px; border: 1px solid #bbf7d0; }
.select-box-neo { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px 12px; font-size: 0.82rem; cursor: pointer; position: relative; display: flex; justify-content: space-between; align-items: center; }
.select-box-neo:hover { border-color: #cbd5e1; background: #ffffff; }
.select-box-neo .arrow { color: #94a3b8; font-size: 0.6rem; margin-left: 8px; }
.dropdown-list { position: absolute; top: 110%; left: 0; right: 0; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; z-index: 100; max-height: 200px; overflow-y: auto; padding: 6px; }
.dropdown-list .opt { padding: 8px 10px; font-size: 0.82rem; border-radius: 6px; cursor: pointer; }
.dropdown-list .opt:hover { background: #f1f5f9; color: #2563eb; }
.dropdown-list .opt.selected { color: #2563eb; font-weight: 700; background: #eff6ff; }
.metadata-container { padding: 18px; }
.divider { height: 1px; background: #e2e8f0; margin: 18px 0; }
.view-mode .gene-db-section { background: #fdf2f8; border: 1px dashed #f9a8d4; border-radius: 12px; padding: 16px; }
.btn-add-gene { padding: 6px 12px; background: #db2777; color: #ffffff; border: none; border-radius: 6px; font-size: 0.75rem; font-weight: 600; cursor: pointer; }
.btn-add-gene:disabled { opacity: 0.5; cursor: not-allowed; }
.inline-gene-form { background: #ffffff; border: 1px solid #fbcfe8; border-radius: 8px; padding: 12px; margin: 12px 0; }
.form-grid-mini { display: grid; grid-template-columns: 120px 1fr; gap: 12px; }
.mini-group label { display: block; font-size: 0.72rem; color: #64748b; margin-bottom: 4px; }
.mini-actions { justify-content: flex-end; margin-top: 12px; }
.gene-list { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.gene-empty { text-align: center; font-size: 0.8rem; color: #94a3b8; padding: 12px; }
.gene-item { display: flex; justify-content: space-between; align-items: center; background: #ffffff; padding: 10px 14px; border-radius: 8px; border: 1px solid #fce7f3; }
.gene-badge { background: #db2777; color: #ffffff; font-size: 0.65rem; font-weight: 800; padding: 2px 6px; border-radius: 4px; }
.gene-title-row { display: flex; flex-direction: column; }
.gene-name { font-size: 0.85rem; font-weight: 700; color: #334155; }
.gene-len { font-size: 0.7rem; color: #94a3b8; }
.btn-gene-del { background: none; border: none; font-size: 0.75rem; color: #ef4444; cursor: pointer; padding: 2px 4px; }
.mt-2 { margin-top: 8px; }
</style>
