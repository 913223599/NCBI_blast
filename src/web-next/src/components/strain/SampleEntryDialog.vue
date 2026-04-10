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

            <!-- 样本编号 -->
            <div class="form-section">
              <h4 class="section-label">样本编号</h4>
              <SampleCodeInput 
                :initial-selections="initialCategorySelections"
                @update="handleCodeUpdate" 
              />
            </div>

            <!-- 核心标识 -->
            <div class="form-section">
              <h4 class="section-label">样本核心信息</h4>
              
              <div class="form-group required">
                <label>样本名称 <span class="required-mark">*</span></label>
                <input v-model="form.name" class="text-input" placeholder="例如: E. coli K-12" />
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label>样本类型</label>
                  <div class="read-only-field">{{ getSampleTypeLabel() }}</div>
                </div>
                <div class="form-group">
                  <label>序列类型</label>
                  <div class="custom-select" @click.stop="toggleDropdown('sequenceType')">
                    <div class="select-trigger">
                      {{ getSequenceTypeLabel() }}
                      <span class="arrow">▾</span>
                    </div>
                    <div v-if="openDropdown === 'sequenceType'" class="select-dropdown">
                      <div
                        v-for="opt in SEQUENCE_TYPE_OPTIONS"
                        :key="opt.value"
                        class="select-option"
                        @click.stop="handleDropdownSelect('sequenceType', opt.value)"
                      >
                        {{ opt.label }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label>外部/关联 ID (可选)</label>
                  <input v-model="form.accession" class="text-input" placeholder="如: ATCC编号, NCBI登录号..." />
                </div>
                <div class="form-group">
                  <label>物种名称 (由编号自动生成)</label>
                  <div class="read-only-field">{{ form.species || '等待编号生成...' }}</div>
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
            <!-- 空状态提示 -->
            <div v-if="!form.sampleType" class="empty-state-panel">
              <div class="empty-icon">👈</div>
              <h3>暂无业务元数据</h3>
              <p>请先在左侧选择 <strong>大类 (A)</strong> 或 <strong>样本类型</strong><br>系统将自动为您加载对应的可填字段</p>
            </div>
            
            <template v-else>
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
                
                <!-- 基因库同步选项 -->
                <div class="gene-sync-opt" v-if="form.sequence">
                  <label class="checkbox-container">
                    <input type="checkbox" v-model="syncToGeneDB" />
                    <span class="checkmark"></span>
                    <span class="checkbox-label">同步录入到基因数据库 (Gene DB)</span>
                  </label>
                  
                <div v-if="syncToGeneDB" class="gene-details-panel">
                  <div class="form-row">
                    <div class="form-group">
                      <label>测序类型</label>
                      <div class="custom-select" @click.stop="toggleDropdown('seqType')">
                        <div class="select-trigger">
                          {{ getGeneSeqTypeLabel() }}
                          <span class="arrow">▾</span>
                        </div>
                        <div v-if="openDropdown === 'seqType'" class="select-dropdown">
                          <div
                            v-for="opt in GENE_SEQ_TYPE_OPTIONS"
                            :key="opt.value"
                            class="select-option"
                            @click.stop="handleDropdownSelect('seqType', opt.value)"
                          >
                            {{ opt.label }}
                          </div>
                        </div>
                      </div>
                    </div>
                    <div class="form-group">
                      <label>测序标题/批次</label>
                      <input v-model="geneInfo.title" class="text-input" placeholder="默认：[样本编号]-[类型]" />
                    </div>
                  </div>
                </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="dialog-footer">
        <div class="aliquot-control" v-if="canSubmit && (!selectedPositions || selectedPositions.length <= 1)">
          <label>分装录入管数：</label>
          <div class="number-input">
            <button @click="aliquotCount > 1 && aliquotCount--" class="num-btn">-</button>
            <input v-model.number="aliquotCount" type="number" min="1" max="100" class="num-text" />
            <button @click="aliquotCount < 100 && aliquotCount++" class="num-btn">+</button>
          </div>
          <span class="aliquot-hint" v-if="aliquotCount > 1">自动往后填充连续空位</span>
        </div>
        <!-- 批量说明 -->
        <div class="batch-hint" v-else-if="selectedPositions && selectedPositions.length > 1">
          已选中 <strong>{{ selectedPositions.length }}</strong> 个孔位进行批量录入
        </div>
        <div class="footer-actions">
          <button class="btn-cancel" @click="emit('close')">取消</button>
          <button class="btn-confirm" @click="handleConfirm" :disabled="!canSubmit">
            确认录入 {{ aliquotCount > 1 ? `(${aliquotCount} 管)` : '' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { useSequenceStore } from '../../stores/sequence'
import { useCodeGenerator } from '../../composables/useCodeGenerator'
import type { SampleCategory } from '../../stores/strain'

// 导入子表单组件
import BaseMetadataForm from './forms/BaseMetadataForm.vue'
import MicrobeForm from './forms/MicrobeForm.vue'
import GeneticForm from './forms/GeneticForm.vue'
import VirusForm from './forms/VirusForm.vue'
import ProteinForm from './forms/ProteinForm.vue'
import CellForm from './forms/CellForm.vue'
import PhageForm from './forms/PhageForm.vue'
import SampleCodeInput from './SampleCodeInput.vue'

interface Props {
  freezerId: string
  shelfId: string
  cabinetId: string
  drawerId: string
  boxId: string
  position: string
  selectedPositions?: string[]
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'saved'])

// 表单数据
const form = ref({
  name: '',
  accession: '',
  species: '',
  strain: '',
  sampleType: '' as SampleCategory | '',
  sequenceType: 'DNA' as 'DNA' | 'RNA' | 'Protein',
  sequence: '',
  source: '',
  host: '',
  country: '',
  collectionDate: '',
  // 编号系统字段
  sampleCode: '',
  codeSource: '',
  codeCategory: '',
  codeGenus: '',
  codeSpecies: '',
  codePassage: 0,
  codeSerial: 0,
  metadata: {
    storageDate: new Date().toISOString().split('T')[0],
    storageMedium: '20% Glycerol',
    biosafetyLevel: 'BSL-1',
    concentration: '',
    titer: '',
    potency: ''
  } as Record<string, any>
})

const strain = useStrainStore()
const appStore = useAppStore()
const codeGen = useCodeGenerator()

// --- 录入状态控制 ---
const aliquotCount = ref(1)

// 初始编码选择建议 (来自 BLAST 等识别结果)
const initialCategorySelections = ref<any>(null)

/**
 * 尝试根据学名自动匹配编号库中的属/种编码
 * 支持解析复合鉴定字符串，例如 "Aeromonas hydrophila(94%), Aeromonas encheleia(2%)"
 */
function attemptTaxonomicMatch(fullIdentification: string) {
  if (!fullIdentification) return null
  
  // 1. 提取推举共识 (第一组匹配项)
  // 正则匹配: 字母+空格+字母 (忽略并兼容开头可能的标记字符和末尾的百分比)
  const consensusMatch = fullIdentification.trim().match(/^[\*\s]*([A-Za-z]+)\s+([A-Za-z\.\-_0-9]+)/)
  if (!consensusMatch) return null
  
  const genusPart = consensusMatch[1]
  const speciesPart = consensusMatch[2]
  
  if (!genusPart || !speciesPart) return null
  
  const selections: any = {
    category: '1', // 默认大类: 细菌 (1)
    source: '01',   // 默认来源: 内部
    passage: 0
  }

  // 清洗种名，去掉结尾可能存在的逗号或括号残余
  const cleanSpecies = speciesPart.replace(/[,\(\)].*$/, '')

  try {
    // 1. 查找属 (Level 2)
    const lowerGenus = genusPart.toLowerCase()
    const genusEntries = strain.codeLookupEntries.filter(
      e => e.level === 2 && 
      (e.latinName?.toLowerCase() === lowerGenus || e.name === genusPart)
    )
    
    if (genusEntries.length > 0) {
      const matchedGenus = genusEntries[0]
      if (!matchedGenus) return null

      selections.genus = matchedGenus.code
      selections.category = matchedGenus.parentPath // 自动对齐实际的大类
      
      // 2. 查找属下的种 (Level 3)
      if (cleanSpecies) {
        const lowerSpecies = cleanSpecies.toLowerCase()
        const parentPath = matchedGenus.fullPath
        const speciesEntries = strain.codeLookupEntries.filter(
          e => e.level === 3 && 
          e.parentPath === parentPath &&
          (e.latinName?.toLowerCase() === lowerSpecies || e.name === cleanSpecies)
        )
        if (speciesEntries.length > 0) {
          const matchedSpecies = speciesEntries[0]
          if (matchedSpecies) {
            selections.species = matchedSpecies.code
          }
        }
      }
    }
    
    return {
      selections: selections.genus ? selections : null,
      consensus: `${genusPart} ${cleanSpecies}`.trim()
    }
  } catch (e) {
    console.warn('[Taxonomic Match] Failed:', e)
    return null
  }
}

onMounted(() => {
  // 检测是否有来自 BLAST 的待入库草稿
  if (strain.pendingBlastDraft) {
    const draft = strain.consumePendingBlastDraft()
    if (draft) {
      // 自动尝试从鉴定结果匹配物种共识和编号系统
      const matchResult = attemptTaxonomicMatch(draft.species)
      const consensusName = matchResult?.consensus || draft.species
      
      Object.assign(form.value, {
        name: consensusName, // 使用共识名称作为样本名
        species: consensusName, // 使用共识名称作为物种名
        accession: draft.accession || '',
        strain: draft.strain || '',
        sequence: draft.sequence || ''
      })
      
      if (matchResult?.selections) {
        initialCategorySelections.value = matchResult.selections
      }
      
      // 合并元数据 (保留原始比对列表供参考，可存入 description 或 metadata)
      if (draft.metadata) {
        form.value.metadata = {
          ...form.value.metadata,
          ...draft.metadata,
          original_identification: draft.species // 保留完整比对列表备份
        }
      }
      
      appStore.showNotification(`已推举物种共识: ${consensusName}`, 'success')
    }
  }
})

// 基因库同步状态
const syncToGeneDB = ref(false)
const geneInfo = ref({
  seqType: '16S',
  title: ''
})

const sequenceStore = useSequenceStore()

// 编号生成凭证
const pendingRequest = ref<any>(null)

// 下拉框状态
const openDropdown = ref<string | null>(null)

const SEQUENCE_TYPE_OPTIONS = [
  { value: 'DNA', label: 'DNA (核酸)' },
  { value: 'RNA', label: 'RNA (核酸)' },
  { value: 'Protein', label: 'Protein (蛋白)' }
]

const GENE_SEQ_TYPE_OPTIONS = [
  { value: '16S', label: '16S rRNA' },
  { value: 'ITS', label: 'ITS' },
  { value: 'WGS', label: '全基因组 (WGS)' },
  { value: 'Plasmid', label: '质粒全长' },
  { value: 'TargetGen', label: '目标基因' }
]

// 编号大类 ID 与 业务类型 (SampleCategory) 的映射
const CATEGORY_CODE_TO_SAMPLE_TYPE: Record<string, SampleCategory> = {
  '1': 'Bacteria',
  '2': 'Virus',
  '3': 'Phage',
  '4': 'Fungi',
  '5': 'Plasmid',
  '6': 'CellLine',
  '7': 'GenomicDNA',
  '8': 'Protein',
  '9': 'Other'
}

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
  return form.value.name.trim().length > 0 && form.value.sampleType !== ''
})

function getSequenceTypeLabel(): string {
  return SEQUENCE_TYPE_OPTIONS.find(o => o.value === form.value.sequenceType)?.label || 'DNA'
}

function getGeneSeqTypeLabel(): string {
  return GENE_SEQ_TYPE_OPTIONS.find(o => o.value === geneInfo.value.seqType)?.label || '16S rRNA'
}

function getSampleTypeLabel(): string {
  if (!form.value.sampleType) return '等待识别或选择...'
  return SAMPLE_TYPE_OPTIONS.find(o => o.value === form.value.sampleType)?.label.split(' ')[0] || form.value.sampleType
}

function toggleDropdown(name: string) {
  openDropdown.value = openDropdown.value === name ? null : name
}

function handleDropdownSelect(field: string, value: string) {
  if (field === 'sequenceType') {
    form.value.sequenceType = value as any
  } else if (field === 'sampleType') {
    form.value.sampleType = value as any
  } else if (field === 'seqType') {
    geneInfo.value.seqType = value as any
  }
  openDropdown.value = null
}

/** 编号组件回调 */
function handleCodeUpdate(data: any): void {
  // 1. 同步预览编号到 accession
  form.value.accession = data.sampleCode 
  
  // 2. 暂存生成凭据
  pendingRequest.value = data.generationRequest || null

  // 3. 自动根据编号推断样本类型（用于切换右侧表单）
  if (data.codeCategory) {
    const inferredType = CATEGORY_CODE_TO_SAMPLE_TYPE[data.codeCategory]
    if (inferredType) {
      form.value.sampleType = inferredType
    }
  }

  // 4. 解析物种名称（属 + 种）
  const resolved = codeGen.resolve(data.sampleCode)
  if (resolved && resolved.genusName !== '未知属') {
    // 只有当从编号中解析出已知的属名时，才同步物种字段
    const resolvedName = `${resolved.genusName} ${resolved.speciesName}`.trim()
    form.value.species = resolvedName
    
    // 如果样本名称目前还是默认的长 ID 格式，则同步更新为推举名称
    const isOriginalLongId = form.value.name.includes('.') && form.value.name.length > 10
    if (!form.value.name || isOriginalLongId) {
      form.value.name = resolvedName
    }
  }

  // 5. 同步所有解析出的元数据
  Object.assign(form.value, {
    sampleCode: data.sampleCode,
    codeSource: data.codeSource,
    codeCategory: data.codeCategory,
    codeGenus: data.codeGenus,
    codeSpecies: data.codeSpecies,
    codePassage: data.codePassage,
    codeSerial: data.codeSerial
  })
}

function handleConfirm() {
  if (!canSubmit.value) return

  // 如果有 Pending 的生成请求，在此刻正式 Commit（消耗流水号）
  if (pendingRequest.value) {
    try {
      const finalCode = codeGen.commit(pendingRequest.value)
      const parsed = codeGen.parse(finalCode)!
      
      form.value.sampleCode = finalCode
      form.value.accession = finalCode
      form.value.codeSerial = parsed.serial
      
      console.log(`[SampleEntryDialog] 编号正式 Commit: ${finalCode}`)
    } catch (e) {
      appStore.showNotification('编号提交失败，请重试', 'error')
      return
    }
  }

  // 查找对应的盒
  const freezer = strain.freezers.find(f => f.id === props.freezerId)
  const shelf = freezer?.shelves.find(s => s.id === props.shelfId)
  const cabinet = shelf?.cabinets.find(c => c.id === props.cabinetId)
  const drawer = cabinet?.drawers.find(d => d.id === props.drawerId)
  const box = drawer?.boxes.find(b => b.id === props.boxId)

  if (!box) {
    appStore.showNotification('未找到目标冻存盒信息', 'error')
    return
  }

  const targetPositions: string[] = []
  
  if (props.selectedPositions && props.selectedPositions.length > 1) {
    // 优先使用拖拽多选的位置
    targetPositions.push(...props.selectedPositions)
  } else {
    // 否则执行原有的连续填充逻辑
    const startIndex = box.positions.findIndex((p: any) => p.label === props.position)
    if (startIndex === -1) {
      appStore.showNotification('起始位置无效', 'error')
      return
    }

    let currentIndex = startIndex
    while (targetPositions.length < aliquotCount.value && currentIndex < box.positions.length) {
      const pos = box.positions[currentIndex]
      if (pos && (!pos.occupied || pos.label === props.position)) {
        targetPositions.push(pos.label)
      }
      currentIndex++
    }
  }

  // 记录实际入库的数据
  let savedCount = 0

  targetPositions.forEach((posLabel) => {
    // 创建样本记录
    const record = strain.addRecord({
      ...form.value,
      sampleType: form.value.sampleType as SampleCategory,
      freezerId: props.freezerId,
      shelfId: props.shelfId,
      cabinetId: props.cabinetId,
      drawerId: props.drawerId,
      boxId: props.boxId,
      position: posLabel
    })

    // 同步到基因库 (仅第一管，避免重复录入序列)
    if (syncToGeneDB.value && savedCount === 0 && form.value.sequence) {
      sequenceStore.saveSequence({
        sampleId: record.id,
        sampleCode: form.value.sampleCode || form.value.accession || '',
        seqType: geneInfo.value.seqType,
        title: geneInfo.value.title || `${record.sampleCode || record.name}-${geneInfo.value.seqType}`,
        sequence: form.value.sequence,
        seqLen: form.value.sequence.replace(/[\s\r\n]/g, '').length,
        metadata: {
          autoSynced: true,
          syncedAt: new Date().toISOString()
        }
      })
    }

    // 更新位置占用状态
    strain.updatePositionOccupancy(
      props.freezerId,
      props.shelfId,
      props.cabinetId,
      props.drawerId,
      props.boxId,
      posLabel,
      true,
      record.id
    )
    savedCount++
  })

  if (savedCount < (props.selectedPositions?.length || aliquotCount.value)) {
    appStore.showNotification(`部分位置录入失败，仅成功录入 ${savedCount} 管`, 'warning')
  } else if (savedCount > 1) {
    appStore.showNotification(`成功将 "${form.value.name}" 批量录入到 ${savedCount} 个指定位置`, 'success')
  } else {
    appStore.showNotification(`样本 "${form.value.name}" 已成功录入`, 'success')
  }

  emit('saved')
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
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
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
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  font-family: inherit;
  background: #f8fafc;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
  background: white;
  
}

.custom-select {
  position: relative;
  width: 100%;
}

.select-trigger {
  padding: 10px 14px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #1e293b;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  min-height: 40px;
}

.select-trigger:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  
  z-index: 1001; /* 确保高于其他表单项 */
  overflow: hidden;
  animation: dropdownIn 0.2s ease-out;
}

.select-option {
  padding: 10px 14px;
  font-size: 0.88rem;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.select-option:hover {
  background: #f1f5f9;
  color: #2563eb;
}

@keyframes dropdownIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.read-only-field {
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #475569;
  font-size: 0.88rem;
  font-weight: 600;
  min-height: 40px;
  display: flex;
  align-items: center;
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
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.aliquot-control {
  display: flex;
  align-items: center;
  gap: 12px;
}

.aliquot-control label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
}

.number-input {
  display: flex;
  align-items: center;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  overflow: hidden;
}

.num-btn {
  background: #f1f5f9;
  border: none;
  width: 28px;
  height: 28px;
  font-size: 1.1rem;
  cursor: pointer;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.num-btn:hover {
  background: #e2e8f0;
}

.num-btn:active {
  background: #cbd5e1;
}

.num-text {
  width: 40px;
  height: 28px;
  border: none;
  border-left: 1px solid #cbd5e1;
  border-right: 1px solid #cbd5e1;
  text-align: center;
  font-size: 0.9rem;
  font-weight: 600;
  color: #0f172a;
}

.num-text:focus {
  outline: none;
}

.num-text::-webkit-inner-spin-button, 
.num-text::-webkit-outer-spin-button { 
  -webkit-appearance: none; 
  margin: 0; 
}

.aliquot-hint {
  font-size: 0.75rem;
  color: #3b82f6;
  background: #eff6ff;
  padding: 4px 8px;
  border-radius: 4px;
}

.batch-hint {
  font-size: 0.85rem;
  color: #64748b;
  background: #f0f9ff;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid #bae6fd;
}

.batch-hint strong {
  color: #0369a1;
}

.footer-actions {
  display: flex;
  gap: 12px;
  margin-left: auto;
}

.btn-cancel,
.btn-confirm {
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

.btn-confirm {
  border: none;
  color: white;
  background: #2563eb;
  
}

.btn-confirm:hover:not(:disabled) {
  background: #1d4ed8;
  
}

.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 基因库同步样式 */
.gene-sync-opt {
  margin-top: 12px;
  padding: 12px;
  background: #f1f5f9;
  border-radius: 8px;
  border: 1px dashed #cbd5e1;
}

.gene-details-panel {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 复选框美化 */
.checkbox-container {
  display: flex;
  align-items: center;
  position: relative;
  padding-left: 28px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  user-select: none;
}

.checkbox-container input {
  position: absolute;
  opacity: 0;
  cursor: pointer;
  height: 0;
  width: 0;
}

.checkmark {
  position: absolute;
  top: 0;
  left: 0;
  height: 18px;
  width: 18px;
  background-color: #fff;
  border: 2px solid #cbd5e1;
  border-radius: 4px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.checkbox-container:hover input ~ .checkmark {
  border-color: #2563eb;
}

.checkbox-container input:checked ~ .checkmark {
  background-color: #2563eb;
  border-color: #2563eb;
}

.checkmark:after {
  content: "";
  position: absolute;
  display: none;
}

.checkbox-container input:checked ~ .checkmark:after {
  display: block;
}

.checkbox-container .checkmark:after {
  left: 5px;
  top: 1px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
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
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}

/* 空状态样式 */
.empty-state-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px;
  text-align: center;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px dashed #cbd5e1;
}

.empty-state-panel .empty-icon {
  font-size: 3rem;
  margin-bottom: 16px;
  animation: bounceLeft 2s infinite;
}

@keyframes bounceLeft {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(-10px); }
}

.empty-state-panel h3 {
  font-size: 1.1rem;
  color: #334155;
  margin-bottom: 8px;
}

.empty-state-panel p {
  font-size: 0.85rem;
  color: #64748b;
  line-height: 1.6;
}
</style>