<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-content">
      <!-- 头部 -->
      <div class="dialog-header">
        <div class="header-left">
          <div class="icon-wrapper">🧬</div>
          <div>
            <h3 class="dialog-title">录入样本</h3>
            <p class="dialog-subtitle">{{ positionPath }}</p>
          </div>
        </div>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="dialog-body">
        <div class="dialog-layout">
          <!-- 左侧：基础与位置信息 -->
          <div class="layout-left">
            <!-- 位置信息 -->
            <div class="position-banner">
              <div class="position-icon">📍</div>
              <div class="position-details">
                <div class="position-path">{{ positionPath }}</div>
                <div class="position-label">{{ positionLabel }}</div>
              </div>
            </div>

            <!-- 核心标识 -->
            <div class="form-section">
              <h4 class="section-label">样本核心信息</h4>
              
              <div class="form-group required">
                <label>样本名称 <span class="required-mark">*</span></label>
                <input v-model="form.name" class="text-input" placeholder="例如：E. coli K-12" />
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label>样本类型</label>
                  <div class="select-box-neo" @click.stop="toggleDropdown('sampleType')">
                    {{ getSampleTypeLabel() }} <span class="arrow">▼</span>
                    <div v-if="openDropdown === 'sampleType'" class="dropdown-list">
                      <div
                        v-for="option in SAMPLE_TYPE_OPTIONS"
                        :key="option.value"
                        class="opt"
                        :class="{ selected: form.sampleType === option.value }"
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
                        :class="{ selected: form.sequenceType === option.value }"
                        @click.stop="selectOption('sequenceType', option.value)"
                      >
                        {{ option.label }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label>Accession (登录号)</label>
                  <input v-model="form.accession" class="text-input" placeholder="NC_xxxxxx" />
                </div>
                <div class="form-group">
                  <label>物种名称</label>
                  <input v-model="form.species" class="text-input" placeholder="生物学名" />
                </div>
              </div>
            </div>

            <!-- 来源信息 -->
            <div class="form-section">
              <h4 class="section-label">来源与采集</h4>
              <div class="form-row">
                <div class="form-group">
                  <label>宿主/来源</label>
                  <input v-model="form.host" class="text-input" placeholder="Human, Soil..." />
                </div>
                <div class="form-group">
                  <label>采集日期</label>
                  <input v-model="form.collectionDate" class="text-input" type="date" />
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：动态元数据表单 -->
          <div class="layout-right">
            <div class="form-section">
              <div class="section-header-flex">
                <h4 class="section-label">详细业务元数据</h4>
                <span class="type-tag">{{ getSampleTypeLabel() }} 特有字段</span>
              </div>
              
              <div class="metadata-container">
                <!-- 通用基础字段 (所有类型都显示) -->
                <BaseMetadataForm v-model="form.metadata" />
                
                <div class="divider"></div>

                <!-- 针对不同类型的动态表单内容 -->
                <div class="dynamic-metadata-area">
                  <MicrobeForm 
                    v-if="['Bacteria', 'Fungi', 'Archaea'].includes(form.sampleType)"
                    v-model="form.metadata"
                  />
                  <PhageForm 
                    v-if="form.sampleType === 'Phage'"
                    v-model="form.metadata"
                  />
                  <GeneticForm 
                    v-if="['Plasmid', 'GenomicDNA', 'RNA', 'Oligo', 'Library'].includes(form.sampleType)"
                    v-model="form.metadata"
                  />
                  <VirusForm 
                    v-if="form.sampleType === 'Virus'"
                    v-model="form.metadata"
                  />
                  <ProteinForm 
                    v-if="['Protein', 'Enzyme', 'Antibody', 'Peptide', 'Antigen'].includes(form.sampleType)"
                    v-model="form.metadata"
                  />
                  <CellForm 
                    v-if="['CellLine', 'CompetentCell', 'Hybridomas'].includes(form.sampleType)"
                    v-model="form.metadata"
                  />
                </div>
              </div>
            </div>

            <!-- 序列文本支持 -->
            <div class="form-section">
              <h4 class="section-label">序列数据 (FASTA)</h4>
              <textarea
                v-model="form.sequence"
                class="text-input textarea"
                placeholder=">Sequence_Title&#10;ATGCGATCG..."
                rows="4"
              ></textarea>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">取消</button>
        <button class="btn-confirm" @click="handleConfirm" :disabled="!canSubmit">
          确认录入
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { SampleCategory } from '../../stores/strain'

// 导入子表单自组件
import BaseMetadataForm from './forms/BaseMetadataForm.vue'
import MicrobeForm from './forms/MicrobeForm.vue'
import GeneticForm from './forms/GeneticForm.vue'
import VirusForm from './forms/VirusForm.vue'
import ProteinForm from './forms/ProteinForm.vue'
import CellForm from './forms/CellForm.vue'
import PhageForm from './forms/PhageForm.vue'

interface Props {
  freezerId: string
  shelfId: string
  cabinetId: string
  drawerId: string
  boxId: string
  position: string
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'saved'])

const strain = useStrainStore()
const appStore = useAppStore()

// 表单数据
const form = ref({
  name: '',
  accession: '',
  species: '',
  strain: '',
  sampleType: 'Bacteria' as SampleCategory,
  sequenceType: 'DNA' as 'DNA' | 'RNA' | 'Protein',
  sequence: '',
  source: '',
  host: '',
  country: '',
  collectionDate: '',
  metadata: {
    storageDate: new Date().toISOString().split('T')[0],
    storageMedium: '20% Glycerol',
    biosafetyLevel: 'BSL-1',
    concentration: '',
    titer: '',
    potency: ''
  } as Record<string, any>
})

// 下拉框状态
const openDropdown = ref<string | null>(null)

const SEQUENCE_TYPE_OPTIONS = [
  { value: 'DNA', label: 'DNA (核酸)' },
  { value: 'RNA', label: 'RNA (核酸)' },
  { value: 'Protein', label: 'Protein (蛋白)' }
]

const SAMPLE_TYPE_OPTIONS = [
  { value: 'Bacteria', label: '细菌 (Bacteria)' },
  { value: 'Phage', label: '噬菌体 (Phage)' },
  { value: 'Virus', label: '病毒 (Virus)' },
  { value: 'Plasmid', label: '质粒 (Plasmid)' },
  { value: 'Protein', label: '蛋白 (Protein)' },
  { value: 'CellLine', label: '细胞系 (Cell Line)' },
  { value: 'CompetentCell', label: '感受态 (Competent)' },
  { value: 'Exosome', label: '外泌体 (Exosome)' },
  { value: 'Tissue', label: '组织 (Tissue)' },
  { value: 'Other', label: '其他 (Other)' }
]

// 计算位置路径
const positionPath = computed(() => {
  const freezer = strain.freezers.find(f => f.id === props.freezerId)
  if (!freezer) return ''
  
  const shelf = freezer.shelves.find(s => s.id === props.shelfId)
  const cabinet = shelf?.cabinets.find(c => c.id === props.cabinetId)
  const drawer = cabinet?.drawers.find(d => d.id === props.drawerId)
  const box = drawer?.boxes.find(b => b.id === props.boxId)
  
  return `${freezer.name} → ${shelf?.name} → ${cabinet?.name} → ${drawer?.name} → ${box?.name}`
})

const positionLabel = computed(() => {
  return `位置：${props.position}`
})

// 表单验证
const canSubmit = computed(() => {
  return form.value.name.trim().length > 0
})

function getSequenceTypeLabel(): string {
  return SEQUENCE_TYPE_OPTIONS.find(o => o.value === form.value.sequenceType)?.label || 'DNA'
}

function getSampleTypeLabel(): string {
  return SAMPLE_TYPE_OPTIONS.find(o => o.value === form.value.sampleType)?.label || '其他'
}

function toggleDropdown(name: string) {
  openDropdown.value = openDropdown.value === name ? null : name
}

function selectOption(field: string, value: string) {
  if (field === 'sequenceType') {
    form.value.sequenceType = value as any
  } else if (field === 'sampleType') {
    form.value.sampleType = value as any
    // 切换类型时可以考虑重置 metadata 的特定部分，但保留基础部分
  }
  openDropdown.value = null
}

function handleConfirm() {
  if (!canSubmit.value) return

  // 创建样本记录
  const record = strain.addRecord({
    ...form.value,
    freezerId: props.freezerId,
    shelfId: props.shelfId,
    cabinetId: props.cabinetId,
    drawerId: props.drawerId,
    boxId: props.boxId,
    position: props.position
  })

  // 更新位置占用状态
  strain.updatePositionOccupancy(
    props.freezerId,
    props.shelfId,
    props.cabinetId,
    props.drawerId,
    props.boxId,
    props.position,
    true,
    record.id
  )

  appStore.showNotification(`样本"${form.value.name}"已成功录入`, 'success')
  emit('saved', record)
  emit('close')
}

// 全局点击关闭下拉框
function handleClickOutside() {
  openDropdown.value = null
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
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
  border-radius: 16px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  width: 960px;
  max-height: 92vh;
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
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
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

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

.dialog-layout {
  display: flex;
  height: 100%;
}

.layout-left {
  flex: 1;
  padding: 24px;
  border-right: 1px solid #e2e8f0;
  background: white;
}

.layout-right {
  flex: 1.2;
  padding: 24px;
  background: #f8fafc;
}

.section-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.type-tag {
  font-size: 0.7rem;
  background: #dbeafe;
  color: #1e40af;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 700;
}

.metadata-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.divider {
  height: 1px;
  background: #e2e8f0;
}

.dynamic-metadata-area {
  min-height: 100px;
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

/* 表单样式 */
.form-section {
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

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
  position: relative;
}

.form-group.required label {
  color: #1e293b;
}

.form-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.required-mark {
  color: #dc2626;
  margin-left: 2px;
}

.text-input {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.9rem;
  transition: all 0.2s;
  font-family: inherit;
  background: #f8fafc;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
  background: white;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.text-input.textarea {
  resize: vertical;
  min-height: 100px;
  font-family: 'Courier New', monospace;
  line-height: 1.5;
}

.field-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-top: 4px;
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
.btn-confirm {
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
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

.btn-confirm {
  border: none;
  color: white;
  background: #2563eb;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
}

.btn-confirm:hover:not(:disabled) {
  background: #1d4ed8;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
  transition: all 0.2s;
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
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
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
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 8px;
}

.opt-icon {
  width: 1.2rem;
  text-align: center;
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
</style>
