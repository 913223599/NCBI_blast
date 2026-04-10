<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-content">
      <!-- 头部 -->
      <div class="dialog-header">
        <div class="header-left">
          <div class="icon-wrapper"></div>
          <div>
            <h3 class="dialog-title">样本详情</h3>
            <p class="dialog-subtitle">{{ record.name }}</p>
          </div>
        </div>
        <div class="header-actions">
          <button class="btn-edit" @click="toggleEditMode" v-if="!isEditing">
            ✏️ 编辑
          </button>
          <button class="btn-save" @click="handleSave" v-if="isEditing">
            💾 保存
          </button>
          <button class="btn-delete" @click="handleDelete">
            🗑️ 删除
          </button>
          <button class="close-btn" @click="emit('close')">✕</button>
        </div>
      </div>

      <div class="dialog-body">
        <!-- 位置信息横幅 -->
        <div class="position-banner">
          <div class="position-icon">📍</div>
          <div class="position-details">
            <div class="position-path">{{ positionPath }}</div>
            <div class="position-label">位置：{{ record.position }}</div>
          </div>
        </div>

        <!-- 只读视图 -->
        <div v-if="!isEditing" class="view-mode">
          <!-- 基本信息 -->
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
                  <span class="sample-type-badge">
                    {{ getSampleTypeLabel(record.sampleType) }}
                  </span>
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

          <!-- 业务元数据 (核心扩展示) -->
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
                  <!-- 数组类型展示为徽章 -->
                  <div v-if="Array.isArray(record.metadata?.[key]) && record.metadata[key].length > 0" class="badge-group">
                    <span v-for="item in record.metadata[key]" :key="item" class="meta-tag">{{ item }}</span>
                  </div>
                  <!-- 布尔类型展示为图标 -->
                  <span v-else-if="typeof record.metadata?.[key] === 'boolean'">
                    {{ record.metadata[key] ? '✅ 是' : '❌ 否' }}
                  </span>
                  <!-- 普通文本 -->
                  <span v-else>{{ formatMetadataValue(key, record.metadata?.[key]) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 来源信息 -->
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

          <!-- 序列数据 (简易预览) -->
          <div v-if="record.sequence" class="info-section">
            <h4 class="section-label">基础序列 (预览)</h4>
            <div class="sequence-display">
              <pre class="sequence-text">{{ record.sequence }}</pre>
            </div>
          </div>

          <!-- 基因数据库关联 (Gene DB) - 核心联动区域 -->
          <div class="info-section gene-db-section">
            <div class="section-header-flex">
              <h4 class="section-label">基因数据库关联 (Gene DB)</h4>
              <button class="btn-add-gene" @click="showAddGeneForm = true" v-if="!showAddGeneForm">+ 关联新测序数据</button>
            </div>

            <!-- 新增基因记录表单 -->
            <div v-if="showAddGeneForm" class="inline-gene-form">
              <div class="form-grid-mini">
                <div class="mini-group">
                  <label>测序类型</label>
                  <select v-model="newGene.seqType" class="mini-select">
                    <option value="16S">16S rRNA</option>
                    <option value="ITS">ITS</option>
                    <option value="WGS">全基因组 (WGS)</option>
                    <option value="Plasmid">质粒全长</option>
                    <option value="TargetGen">目标基因</option>
                  </select>
                </div>
                <div class="mini-group">
                  <label>测序标题/批次</label>
                  <input v-model="newGene.title" class="mini-input" placeholder="如：20240409-16S-A1" />
                </div>
              </div>
              <div class="mini-group mt-2">
                <label>序列内容 (FASTA)</label>
                <textarea v-model="newGene.sequence" class="mini-textarea" rows="4" placeholder="粘贴序列..."></textarea>
              </div>
              <div class="mini-actions">
                <button class="btn-mini-cancel" @click="showAddGeneForm = false">取消</button>
                <button class="btn-mini-confirm" @click="handleAddGene" :disabled="!newGene.sequence">确认保存到基因库</button>
              </div>
            </div>

            <!-- 已关联列表 -->
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
                  <button class="btn-gene-view" @click="copySeq(seq.sequence)">复制</button>
                  <button class="btn-gene-del" @click="handleDeleteGene(seq.id)">移除</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 时间戳 -->
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

        <!-- 编辑模式 -->
        <div v-else class="edit-mode">
          <div class="form-section">
            <h4 class="section-label">基本信息</h4>
            
            <div class="form-group">
              <label>样本名称 <span class="required">*</span></label>
              <input
                v-model="editForm.name"
                class="text-input"
                placeholder="例如：E. coli K-12"
              />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Accession 号</label>
                <input
                  v-model="editForm.accession"
                  class="text-input"
                  placeholder="例如：NC_000913"
                />
              </div>
              <div class="form-group">
                <label>物种名称</label>
                <input
                  v-model="editForm.species"
                  class="text-input"
                  placeholder="例如：Escherichia coli"
                />
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

            <!-- 动态元数据编辑区 -->
            <div class="form-section">
              <div class="section-header-flex">
                <h4 class="section-label">详细业务元数据</h4>
                <span class="type-tag">{{ getSampleTypeLabel(editForm.sampleType) }} 特有字段</span>
              </div>
              
              <div class="metadata-container">
                <BaseMetadataForm v-model="editForm.metadata" />
                <div class="divider"></div>
                <div class="dynamic-metadata-area">
                  <MicrobeForm 
                    v-if="['Bacteria', 'Fungi', 'Archaea'].includes(editForm.sampleType)"
                    v-model="editForm.metadata"
                  />
                  <PhageForm 
                    v-if="editForm.sampleType === 'Phage'"
                    v-model="editForm.metadata"
                  />
                  <GeneticForm 
                    v-if="['Plasmid', 'GenomicDNA', 'RNA', 'Oligo', 'Library'].includes(editForm.sampleType)"
                    v-model="editForm.metadata"
                  />
                  <VirusForm 
                    v-if="editForm.sampleType === 'Virus'"
                    v-model="editForm.metadata"
                  />
                  <ProteinForm 
                    v-if="['Protein', 'Enzyme', 'Antibody', 'Peptide', 'Antigen'].includes(editForm.sampleType)"
                    v-model="editForm.metadata"
                  />
                  <CellForm 
                    v-if="['CellLine', 'CompetentCell', 'Hybridomas'].includes(editForm.sampleType)"
                    v-model="editForm.metadata"
                  />
                </div>
              </div>
            </div>

          <div class="form-section">
            <h4 class="section-label">来源信息</h4>
            
            <div class="form-row">
              <div class="form-group">
                <label>宿主</label>
                <input
                  v-model="editForm.host"
                  class="text-input"
                  placeholder="例如：Human"
                />
              </div>
              <div class="form-group">
                <label>来源国家</label>
                <input
                  v-model="editForm.country"
                  class="text-input"
                  placeholder="例如：China"
                />
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>采集日期</label>
                <input
                  v-model="editForm.collectionDate"
                  class="text-input"
                  type="date"
                />
              </div>
              <div class="form-group">
                <label>来源描述</label>
                <input
                  v-model="editForm.source"
                  class="text-input"
                  placeholder="例如：临床分离株"
                />
              </div>
            </div>

            <div class="form-group">
              <label>序列数据</label>
              <textarea
                v-model="editForm.sequence"
                class="text-input textarea"
                placeholder=">Sequence_Title&#10;ATGCGATCG..."
                rows="6"
              ></textarea>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">关闭</button>
        <button v-if="isEditing" class="btn-save-footer" @click="handleSave">
          保存更改
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { useSequenceStore } from '../../stores/sequence'
import type { StrainRecord } from '../../stores/strain'

import BaseMetadataForm from './forms/BaseMetadataForm.vue'
import MicrobeForm from './forms/MicrobeForm.vue'
import GeneticForm from './forms/GeneticForm.vue'
import VirusForm from './forms/VirusForm.vue'
import ProteinForm from './forms/ProteinForm.vue'
import CellForm from './forms/CellForm.vue'
import PhageForm from './forms/PhageForm.vue'

interface Props {
  record: StrainRecord
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'deleted'])

const strain = useStrainStore()
const sequenceStore = useSequenceStore()
const appStore = useAppStore()

const isEditing = ref(false)
const openDropdown = ref<string | null>(null)

// 基因数据库状态
const associatedSequences = ref<any[]>([])
const showAddGeneForm = ref(false)
const newGene = reactive({
  seqType: '16S',
  title: '',
  sequence: ''
})

const editForm = reactive({
  name: '',
  accession: '',
  species: '',
  strain: '',
  sampleType: 'Bacteria' as any,
  sequenceType: 'DNA' as 'DNA' | 'RNA' | 'Protein',
  sequence: '',
  source: '',
  host: '',
  country: '',
  collectionDate: '',
  metadata: {}
})

const SAMPLE_TYPE_OPTIONS = [
  { value: 'Bacteria', label: '细菌 (Bacteria)' },
  { value: 'Phage', label: '噬菌体 (Phage)' },
  { value: 'Virus', label: '病毒 (Virus)' },
  { value: 'Plasmid', label: '质粒 (Plasmid)' },
  { value: 'Protein', label: '蛋白 (Protein)' },
  { value: 'CellLine', label: '细胞系 (Cell Line)' },
  { value: 'CompetentCell', label: '感受态 (Competent)' },
  { value: 'Other', label: '其他 (Other)' }
]

const METADATA_LABELS: Record<string, string> = {
  storageDate: '入库日期',
  storageMedium: '保存介质',
  passageNumber: '传代次数',
  biosafetyLevel: '安全等级',
  containerType: '容器规格',
  description: '备注说明',
  hostStrain: '宿主菌株',
  genotype: '基因型',
  resistance: '抗性',
  cultureCondition: '培养条件',
  growthTemp: '生长温度',
  backbone: '骨架',
  insertName: '插入片段',
  plasmidSize: '质粒大小',
  marker: '筛选标记',
  isExpression: '表达载体',
  promoter: '启动子',
  titer: '病毒滴度',
  serotype: '血清型',
  potency: '效价浓度',
  envelope: '包膜',
  inactivationMethod: '灭活方法',
  purity: '纯度',
  concentration: '浓度',
  buffer: '缓冲液',
  molecularWeight: '分子量',
  tags: '纯化标签',
  cellType: '细胞类型',
  medium: '培养基',
  doublingTime: '倍增时间',
  authentication: '鉴定编号',
  // 噬菌体
  hostRange: '宿主范围',
  lifestyle: '生活史类型',
  latentPeriod: '潜伏期',
  burstSize: '裂解量',
  morphology: '形态分类'
}

const TYPE_SPECIFIC_KEYS: Record<string, string[]> = {
  Bacteria: ['concentration', 'cultureCondition', 'growthTemp', 'resistance', 'genotype'],
  Fungi: ['concentration', 'cultureCondition', 'growthTemp', 'resistance', 'genotype'],
  Archaea: ['concentration', 'cultureCondition', 'growthTemp', 'resistance', 'genotype'],
  Virus: ['potency', 'titer', 'serotype', 'envelope', 'inactivationMethod'],
  Phage: ['potency', 'hostStrain', 'morphology', 'latentPeriod', 'burstSize', 'lifestyle'],
  Plasmid: ['concentration', 'hostStrain', 'backbone', 'insertName', 'plasmidSize', 'promoter', 'isExpression', 'marker'],
  GenomicDNA: ['concentration', 'hostStrain', 'backbone', 'insertName', 'plasmidSize', 'promoter', 'isExpression', 'marker'],
  RNA: ['concentration', 'hostStrain', 'backbone', 'insertName', 'plasmidSize', 'promoter', 'isExpression', 'marker'],
  Oligo: ['concentration', 'hostStrain', 'backbone', 'insertName', 'plasmidSize', 'promoter', 'isExpression', 'marker'],
  Library: ['concentration', 'hostStrain', 'backbone', 'insertName', 'plasmidSize', 'promoter', 'isExpression', 'marker'],
  Protein: ['concentration', 'purity', 'molecularWeight', 'buffer', 'tags'],
  Enzyme: ['concentration', 'purity', 'molecularWeight', 'buffer', 'tags'],
  Antibody: ['concentration', 'purity', 'molecularWeight', 'buffer', 'tags'],
  Peptide: ['concentration', 'purity', 'molecularWeight', 'buffer', 'tags'],
  Antigen: ['concentration', 'purity', 'molecularWeight', 'buffer', 'tags'],
  CellLine: ['concentration', 'cellType', 'medium', 'doublingTime', 'authentication'],
  CompetentCell: ['concentration', 'cellType', 'medium', 'doublingTime', 'authentication'],
  Hybridomas: ['concentration', 'cellType', 'medium', 'doublingTime', 'authentication'],
}

const expectedMetadataKeys = computed(() => {
  const baseKeys = ['storageDate', 'storageMedium', 'biosafetyLevel', 'passageNumber', 'containerType', 'description']
  const specificKeys = TYPE_SPECIFIC_KEYS[props.record.sampleType] || []
  return [...baseKeys, ...specificKeys]
})

const METADATA_UNITS: Record<string, string | Record<string, string>> = {
  concentration: { 
    Bacteria: 'CFU/mL', Fungi: 'CFU/mL', Archaea: 'CFU/mL', 
    Plasmid: 'ng/μL', GenomicDNA: 'ng/μL', RNA: 'ng/μL', Oligo: 'ng/μL', Library: 'ng/μL',
    Protein: 'mg/mL', Enzyme: 'mg/mL', Antibody: 'mg/mL', Peptide: 'mg/mL', Antigen: 'mg/mL',
    CellLine: 'cells/mL', CompetentCell: 'cells/mL', Hybridomas: 'cells/mL' 
  },
  growthTemp: '°C',
  purity: '%',
  molecularWeight: 'kDa',
  doublingTime: 'h',
  plasmidSize: 'bp',
  potency: { Virus: 'PFU/mL', Phage: 'PFU/mL' },
  titer: 'TCID50/mL',
  latentPeriod: 'min',
  burstSize: 'PFU/cell',
  passageNumber: '代'
}

function formatMetadataValue(key: string, val: any): string {
  if (val === undefined || val === null || val === '') return '-'
  
  const unitDef = METADATA_UNITS[key]
  if (!unitDef) return String(val)
  
  let unit = ''
  if (typeof unitDef === 'string') {
    unit = unitDef
  } else {
    unit = unitDef[props.record.sampleType] || ''
  }
  
  const strVal = String(val).trim()
  if (unit && !strVal.toLowerCase().includes(unit.toLowerCase())) {
    return `${strVal} ${unit}`
  }
  
  return strVal
}

const SEQUENCE_TYPE_OPTIONS = [
  { value: 'DNA', label: 'DNA (核酸)' },
  { value: 'RNA', label: 'RNA (核酸)' },
  { value: 'Protein', label: 'Protein (蛋白)' }
]

// 计算位置路径
const positionPath = computed(() => {
  const freezer = strain.freezers.find(f => f.id === props.record.freezerId)
  if (!freezer) return ''
  
  const shelf = freezer.shelves.find(s => s.id === props.record.shelfId)
  const cabinet = shelf?.cabinets.find(c => c.id === props.record.cabinetId)
  const drawer = cabinet?.drawers.find(d => d.id === props.record.drawerId)
  const box = drawer?.boxes.find(b => b.id === props.record.boxId)
  
  return `${freezer.name} → ${shelf?.name} → ${cabinet?.name} → ${drawer?.name} → ${box?.name}`
})

function toggleEditMode() {
  // 初始化编辑表单
  Object.assign(editForm, {
    name: props.record.name,
    accession: props.record.accession || '',
    species: props.record.species || '',
    strain: props.record.strain || '',
    sampleType: props.record.sampleType,
    sequenceType: props.record.sequenceType,
    sequence: props.record.sequence || '',
    source: props.record.source || '',
    host: props.record.host || '',
    country: props.record.country || '',
    collectionDate: props.record.collectionDate || '',
    metadata: { ...props.record.metadata }
  })
  isEditing.value = true
}

function handleSave() {
  if (!editForm.name.trim()) {
    appStore.showNotification('样本名称不能为空', 'error')
    return
  }

  strain.updateRecord(props.record.id, {
    ...editForm
  })

  appStore.showNotification('样本信息已更新', 'success')
  isEditing.value = false
}

async function handleDelete() {
  if (confirm(`确定要删除样本"${props.record.name}"吗？`)) {
    strain.removeRecord(props.record.id)
    appStore.showNotification('样本已删除', 'success')
    emit('deleted')
    emit('close')
  }
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

function getSequenceTypeLabel(): string {
  return SEQUENCE_TYPE_OPTIONS.find(o => o.value === editForm.sequenceType)?.label || 'DNA'
}

function toggleDropdown(name: string) {
  openDropdown.value = openDropdown.value === name ? null : name
}

function getMetadataLabel(key: string): string {
  return METADATA_LABELS[key] || key
}

function isFullWidthMetadata(key: string, val: any): boolean {
  return key === 'description' || key === 'genotype' || (Array.isArray(val) && val.length > 5)
}

const hasMetadata = computed(() => {
  return expectedMetadataKeys.value.length > 0
})

function getSampleTypeLabel(type: string): string {
  return SAMPLE_TYPE_OPTIONS.find(o => o.value === type)?.label.split(' ')[0] || type
}

function selectOption(field: string, value: string) {
  if (field === 'sequenceType') {
    editForm.sequenceType = value as any
  } else if (field === 'sampleType') {
    editForm.sampleType = value as any
  }
  openDropdown.value = null
}

// 全局点击关闭下拉框
function handleClickOutside() {
  openDropdown.value = null
}

async function loadAssociatedGenes() {
  const result = await sequenceStore.loadSequencesBySample(props.record.id)
  associatedSequences.value = result
}

async function handleAddGene() {
  if (!newGene.sequence) return

  const success = await sequenceStore.saveSequence({
    sampleId: props.record.id,
    sampleCode: props.record.sampleCode || props.record.accession || '',
    seqType: newGene.seqType,
    title: newGene.title || `${newGene.seqType} Sequencing`,
    sequence: newGene.sequence,
    seqLen: newGene.sequence.replace(/[\s\r\n]/g, '').length,
    metadata: {}
  })

  if (success) {
    appStore.showNotification('已成功保存至基因数据库并建立关联', 'success')
    showAddGeneForm.value = false
    newGene.title = ''
    newGene.sequence = ''
    loadAssociatedGenes()
  }
}

async function handleDeleteGene(id: string) {
  if (confirm('确定要从基因数据库中移除此序列吗？')) {
    const success = await sequenceStore.deleteSequence(id)
    if (success) {
      loadAssociatedGenes()
    }
  }
}

function copySeq(text: string) {
  navigator.clipboard.writeText(text)
  appStore.showNotification('序列已复制到剪贴板', 'success')
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  loadAssociatedGenes()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
/* 继承 AddFreezerDialog 的样式 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.dialog-content {
  background: #ffffff;
  border-radius: 12px;
  width: 640px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.icon-wrapper {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #f0fdf4, #dcfce7);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
}

.dialog-title {
  font-size: 1.1rem;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 2px 0;
}

.dialog-subtitle {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-edit,
.btn-save,
.btn-delete {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-edit {
  border: 1px solid #e2e8f0;
  color: #64748b;
  background: white;
}

.btn-edit:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.btn-save {
  border: none;
  color: white;
  background: #10b981;
}

.btn-save:hover {
  background: #059669;
}

.btn-delete {
  border: 1px solid #fee2e2;
  color: #ef4444;
  background: white;
}

.btn-delete:hover {
  background: #fee2e2;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* 位置横幅 */
.position-banner {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.position-icon {
  font-size: 1.5rem;
}

.position-details {
  flex: 1;
}

.position-path {
  font-size: 0.85rem;
  color: #1e40af;
  font-weight: 600;
  margin-bottom: 2px;
}

.position-label {
  font-size: 0.75rem;
  color: #3b82f6;
}

/* 查看模式 */
.view-mode .info-section {
  margin-bottom: 24px;
}

.section-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 16px 0;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-item .label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
}

.info-item .value {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
}

.info-item .value.mono {
  font-family: 'Courier New', monospace;
}

.type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 700;
}

.type-badge.dna {
  background: #dbeafe;
  color: #1e40af;
}

.type-badge.rna {
  background: #fce7f3;
  color: #be185d;
}

.type-badge.protein {
  background: #fef3c7;
  color: #92400e;
}

.sequence-display {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
}

.sequence-text {
  margin: 0;
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
  line-height: 1.6;
  color: #1e293b;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 元数据样式 */
.metadata-section {
  background: #f8fafc;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #e2e8f0;
}

.sample-type-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: white;
  border: 1px solid #e2e8f0;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 0.8rem;
  font-weight: 700;
  color: #475569;
}

.type-icon {
  font-size: 1rem;
}

.badge-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.meta-tag {
  background: #dcfce7;
  color: #166534;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #bbf7d0;
}

.edit-hint-banner {
  margin-top: 16px;
  padding: 10px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: 8px;
  color: #92400e;
  font-size: 0.75rem;
}

/* 编辑模式 */
.form-section {
  margin-bottom: 24px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
  position: relative;
}

.form-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.required {
  color: #dc2626;
}

.text-input {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.9rem;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  font-family: inherit;
  background: #f8fafc;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
  background: white;
}

.text-input.textarea {
  resize: vertical;
  min-height: 100px;
  font-family: 'Courier New', monospace;
  line-height: 1.5;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

/* 底部按钮 */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.btn-cancel,
.btn-save-footer {
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-cancel {
  border: 1px solid #e2e8f0;
  color: #64748b;
  background: white;
}

.btn-cancel:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.btn-save-footer {
  border: none;
  color: white;
  background: #10b981;
}

.btn-save-footer:hover {
  background: #059669;
}

/* 自定义下拉框样式 */
.select-box-neo {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 0.82rem;
  cursor: pointer;
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.select-box-neo:hover {
  border-color: #cbd5e1;
  background: white;
}

.select-box-neo .arrow {
  color: #94a3b8;
  font-size: 0.6rem;
  margin-left: 8px;
}

.dropdown-list {
  position: absolute;
  top: 110%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  z-index: 100;
  max-height: 200px;
  overflow-y: auto;
  padding: 6px;
}

.dropdown-list .opt {
  padding: 10px 12px;
  font-size: 0.82rem;
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.dropdown-list .opt:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.dropdown-list .opt.selected {
  color: #2563eb;
  font-weight: 700;
  background: #eff6ff;
}

/* 动态元数据区域特有样式 */
.section-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-header-flex .section-label {
  margin-bottom: 0;
}

.type-tag {
  background: #f1f5f9;
  color: #475569;
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: 20px;
  font-weight: 700;
  border: 1px solid #e2e8f0;
}

.metadata-container {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
}

.divider {
  height: 1px;
  background: #e2e8f0;
  margin: 20px 0;
}
/* 基因数据库样式 */
.gene-db-section {
  background: #fdf2f8 !important; /* 给基因库一个淡粉色背景增强区分度 */
  border: 1px dashed #f9a8d4;
  border-radius: 12px;
  padding: 16px !important;
}

.btn-add-gene {
  padding: 6px 12px;
  background: #db2777;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
}

.inline-gene-form {
  background: white;
  border: 1px solid #fbcfe8;
  border-radius: 8px;
  padding: 12px;
  margin-top: 12px;
  margin-bottom: 12px;
}

.form-grid-mini {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 12px;
}

.mini-group label {
  display: block;
  font-size: 0.7rem;
  color: #64748b;
  margin-bottom: 4px;
}

.mini-select, .mini-input, .mini-textarea {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 0.8rem;
}

.mini-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.btn-mini-cancel {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-mini-confirm {
  background: #db2777;
  color: white;
  border: none;
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.gene-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gene-empty {
  text-align: center;
  font-size: 0.8rem;
  color: #94a3b8;
  padding: 12px;
}

.gene-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid #fce7f3;
}

.gene-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gene-badge {
  background: #db2777;
  color: white;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.gene-title-row {
  display: flex;
  flex-direction: column;
}

.gene-name {
  font-size: 0.85rem;
  font-weight: 700;
  color: #334155;
}

.gene-len {
  font-size: 0.7rem;
  color: #94a3b8;
}

.gene-actions {
  display: flex;
  gap: 8px;
}

.btn-gene-view, .btn-gene-del {
  background: none;
  border: none;
  font-size: 0.75rem;
  cursor: pointer;
  padding: 2px 4px;
}

.btn-gene-view { color: #2563eb; }
.btn-gene-del { color: #ef4444; }

.mt-2 { margin-top: 8px; }
</style>