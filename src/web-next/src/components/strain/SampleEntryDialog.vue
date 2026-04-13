<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-content">
      <!-- 1. 头部 -->
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
          <!-- 2. 左侧：基础与位置信息 (组合模式) -->
          <div class="layout-left">
            <SamplePositionBanner :path="positionPath" :label="positionLabel" />

            <!-- 样本编号 -->
            <div class="form-section">
              <h4 class="section-label">样本编号</h4>
              <SampleCodeInput 
                :initial-selections="initialCategorySelections"
                @update="handleCodeUpdate" 
              />
            </div>

            <!-- 样本核心标识 -->
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
                      <div v-for="opt in SEQUENCE_TYPE_OPTIONS" :key="opt.value" class="select-option" @click.stop="handleDropdownSelect('sequenceType', opt.value)">
                        {{ opt.label }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label>外部/关联 ID</label>
                  <input v-model="form.accession" class="text-input" placeholder="如: ATCC, NCBI登录号..." />
                </div>
                <div class="form-group">
                  <label>物种名称</label>
                  <div class="read-only-field">{{ form.species || '等待编号生成...' }}</div>
                </div>
              </div>
            </div>

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

          <!-- 3. 右侧：动态业务表单 (策略模式) -->
          <div class="layout-right">
            <div v-if="!form.sampleType" class="empty-state-panel">
              <div class="empty-icon">👈</div>
              <h3>暂无业务元数据</h3>
              <p>请先在左侧选择 <strong>大类 (A)</strong> 或样本类型</p>
            </div>
            
            <template v-else>
              <div class="form-section">
                <div class="section-header-flex">
                  <h4 class="section-label">详细业务元数据</h4>
                </div>
                <div class="metadata-container">
                  <BaseMetadataForm v-model="form.metadata" />
                  <div class="divider"></div>
                  <div class="dynamic-metadata-area">
                    <component :is="getDynamicForm()" v-model="form.metadata" />
                  </div>
                </div>
              </div>

              <!-- 4. 序列录入子模块 (已拆分) -->
              <SequenceEntryPanel 
                v-model="form.sequence"
                v-model:sync-enabled="syncToGeneDB"
                v-model:gene-seq-type="geneInfo.seqType"
                v-model:gene-title="geneInfo.title"
              />
            </template>
          </div>
        </div>
      </div>

      <!-- 5. 底部按钮与分装控制 -->
      <div class="dialog-footer">
        <div class="aliquot-control" v-if="canSubmit && (!selectedPositions || selectedPositions.length <= 1)">
          <label>分装管数：</label>
          <div class="number-input">
            <button @click="aliquotCount > 1 && aliquotCount--" class="num-btn">-</button>
            <input v-model.number="aliquotCount" type="number" class="num-text" />
            <button @click="aliquotCount < 100 && aliquotCount++" class="num-btn">+</button>
          </div>
        </div>
        <div class="batch-hint" v-else-if="selectedPositions && selectedPositions.length > 1">
          已选中 <strong>{{ selectedPositions.length }}</strong> 个孔位批量录入
        </div>
        <div class="footer-actions">
          <button class="btn-cancel" @click="emit('close')">取消</button>
          <button class="btn-confirm" @click="handleConfirm" :disabled="!canSubmit">确认录入</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStrainStore, type SampleCategory } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { useSequenceStore } from '../../stores/sequence'
import { useCodeGenerator } from '../../composables/useCodeGenerator'
import { useTaxonomySync } from '../../composables/useTaxonomySync'

// 子组件
import SamplePositionBanner from './SamplePositionBanner.vue'
import SequenceEntryPanel from './SequenceEntryPanel.vue'
import BaseMetadataForm from './forms/BaseMetadataForm.vue'
import MicrobeForm from './forms/MicrobeForm.vue'
import GeneticForm from './forms/GeneticForm.vue'
import VirusForm from './forms/VirusForm.vue'
import ProteinForm from './forms/ProteinForm.vue'
import CellForm from './forms/CellForm.vue'
import PhageForm from './forms/PhageForm.vue'
import SampleCodeInput from './SampleCodeInput.vue'

interface Props {
  freezerId: string; shelfId: string; cabinetId: string; drawerId: string; boxId: string;
  position: string; selectedPositions?: string[];
}
const props = defineProps<Props>()
const emit = defineEmits(['close', 'saved'])

const strain = useStrainStore(); const appStore = useAppStore(); const sequenceStore = useSequenceStore()
const codeGen = useCodeGenerator(); const { attemptTaxonomicMatch, syncTaxonomyToBackend } = useTaxonomySync()

const form = ref({
  name: '', accession: '', species: '', strain: '', sampleType: '' as SampleCategory | '',
  sequenceType: 'DNA' as 'DNA' | 'RNA' | 'Protein', sequence: '', source: '', host: '', country: '', collectionDate: '',
  sampleCode: '', codeSource: '', codeCategory: '', codeGenus: '', codeSpecies: '', codePassage: 0, codeSerial: 0,
  metadata: { storageDate: new Date().toISOString().split('T')[0], biosafetyLevel: 'BSL-1' } as Record<string, any>
})

const aliquotCount = ref(1); const syncToGeneDB = ref(false); const geneInfo = ref({ seqType: '16S', title: '' })
const initialCategorySelections = ref<any>(null); const openDropdown = ref<string | null>(null); const pendingRequest = ref<any>(null)

// 常量定义
const SEQUENCE_TYPE_OPTIONS = [{ value: 'DNA', label: 'DNA (核酸)' }, { value: 'RNA', label: 'RNA (核酸)' }, { value: 'Protein', label: 'Protein (蛋白)' }]
const CATEGORY_CODE_TO_SAMPLE_TYPE: Record<string, SampleCategory> = { '1': 'Bacteria', '2': 'Virus', '3': 'Phage', '4': 'Fungi', '5': 'Plasmid', '6': 'CellLine', '7': 'GenomicDNA', '8': 'Protein', '9': 'Other' }

// 逻辑计算
const positionPath = computed(() => {
  const f = strain.freezers.find(f => f.id === props.freezerId); if (!f) return ''
  const s = f.shelves.find(s => s.id === props.shelfId); const b = s?.cabinets.find(c => c.id === props.cabinetId)?.drawers.find(d => d.id === props.drawerId)?.boxes.find(b => b.id === props.boxId)
  return `${f.name} → ${s?.name} → ... → ${b?.name}`
})
const positionLabel = computed(() => `位置：${props.position}`)
const canSubmit = computed(() => form.value.name.trim().length > 0 && form.value.sampleType !== '')

onMounted(async () => {
  if (strain.pendingBlastDraft) {
    const draft = strain.consumePendingBlastDraft()
    if (!draft) return
    
    // 异步同步物种到后端
    if (draft.species) {
      const syncRes: any = await syncTaxonomyToBackend(draft.species)
      if (syncRes) {
        initialCategorySelections.value = { 
          category: syncRes.codeCategory, 
          genus: syncRes.codeGenus, 
          species: syncRes.codeSpecies 
        }
        form.value.name = syncRes.speciesName; 
        form.value.species = syncRes.speciesName
        
        // 关键修复：同步成功后，必须立即触发一次数据联动，否则 sampleType 为空导致无法提交
        handleCodeUpdate({
          sampleCode: '', // 初始占空，等待 SampleCodeInput 接管
          codeCategory: syncRes.codeCategory,
          codeGenus: syncRes.codeGenus,
          codeSpecies: syncRes.codeSpecies,
          generationRequest: {
            category: syncRes.codeCategory,
            genus: syncRes.codeGenus,
            species: syncRes.codeSpecies
          }
        })
      }
    }

    const match = attemptTaxonomicMatch(draft.species); const consensus = match?.consensus || draft.species
    
    // 深度合并草稿信息，确保 BLAST 的 identity, evalue 等 metadata 不丢失
    Object.assign(form.value, { 
      name: form.value.name || consensus, 
      species: form.value.species || consensus, 
      sequence: draft.sequence || '',
      accession: draft.accession || form.value.accession,
      strain: draft.strain || '',
      metadata: {
        ...form.value.metadata,
        ...(draft.metadata || {})
      }
    })
    
    if (form.value.sequence) { syncToGeneDB.value = true; geneInfo.value.title = `${consensus}_16S` }
  }
})

function getDynamicForm() {
  const type = form.value.sampleType
  if (['Bacteria', 'Fungi', 'Archaea'].includes(type)) return MicrobeForm
  if (type === 'Phage') return PhageForm
  if (['Plasmid', 'GenomicDNA', 'RNA'].includes(type)) return GeneticForm
  if (type === 'Virus') return VirusForm
  if (type === 'Protein') return ProteinForm
  if (['CellLine', 'CompetentCell'].includes(type)) return CellForm
  return null
}

function handleCodeUpdate(data: any) {
  form.value.accession = data.sampleCode; pendingRequest.value = data.generationRequest || null
  const inferred = CATEGORY_CODE_TO_SAMPLE_TYPE[data.codeCategory]; if (inferred) form.value.sampleType = inferred
  const res = codeGen.resolve(data.sampleCode)
  if (res && res.genusName !== '未知属') {
    // 核心改进：如果已经识别到“种”，则直接使用种名（种名通常已包含属名信息），避免冗余堆叠
    const name = res.speciesName !== '未知种' ? res.speciesName : res.genusName
    form.value.species = name
    if (!form.value.name || form.value.name.includes('.')) {
      form.value.name = name
    }
  }
}

function handleConfirm() {
  if (!canSubmit.value) return
  if (pendingRequest.value) {
    try {
      const code = codeGen.commit(pendingRequest.value)
      form.value.sampleCode = code
      form.value.accession = code
    } catch (err: any) {
      console.error('[SampleEntryDialog] 编码提交失败:', err)
      appStore.showNotification(`入库失败: ${err.message}`, 'error')
      return
    }
  }

  // 最终校验：确保 14 位编号已生成
  if (!form.value.sampleCode && !form.value.accession) {
    appStore.showNotification('无法入库：样本编号尚未生成，请检查分类选择是否完整', 'warning')
    return
  }

  // 计算目标位置列表
  const f = strain.freezers.find(f => f.id === props.freezerId)
  const s = f?.shelves.find(s => s.id === props.shelfId)
  const c = s?.cabinets.find(c => c.id === props.cabinetId)
  const d = c?.drawers.find(d => d.id === props.drawerId)
  const box = d?.boxes.find(b => b.id === props.boxId)
  
  if (!box || !box.positions) return
  
  const targetPositions = props.selectedPositions && props.selectedPositions.length > 1 ? [...props.selectedPositions] : []
  if (targetPositions.length === 0) {
    let idx = box.positions.findIndex(p => p.label === props.position)
    while (targetPositions.length < aliquotCount.value && idx >= 0 && idx < box.positions.length) {
      const p = box.positions[idx]
      // 增加 p 的非空校验
      if (p && (!p.occupied || p.label === props.position)) {
        targetPositions.push(p.label)
      }
      idx++
    }
  }

  // 1. 先准备记录并生成本地 ID (以便同步关联序列)
  const generateUUID = () => {
    if (typeof crypto !== 'undefined' && (crypto as any).randomUUID) return (crypto as any).randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
  }
  
  const records = targetPositions.map(pos => ({ 
    ...form.value, 
    id: generateUUID(), 
    freezerId: props.freezerId, 
    shelfId: props.shelfId, 
    cabinetId: props.cabinetId, 
    drawerId: props.drawerId, 
    boxId: props.boxId, 
    position: pos 
  }))
  
  // 2. 提交到库
  strain.addRecords(records)
  
  // 3. 处理序列同步 (增加显式首条记录校验)
  const firstRecord = records[0]
  if (firstRecord && syncToGeneDB.value && form.value.sequence) {
    sequenceStore.saveSequence({ 
      sampleId: firstRecord.id, // 现在 TS 可以确认 firstRecord 存在
      sampleCode: form.value.sampleCode || form.value.accession, 
      seqType: geneInfo.value.seqType, 
      title: geneInfo.value.title || form.value.name, 
      sequence: form.value.sequence, 
      seqLen: form.value.sequence.length,
      metadata: { autoSynced: true, syncedAt: new Date().toISOString() }
    })
  }

  // 4. 更新位置占用
  targetPositions.forEach(p => {
    if (p) {
      strain.updatePositionOccupancy(props.freezerId, props.shelfId, props.cabinetId, props.drawerId, props.boxId, p, true)
    }
  })
  appStore.showNotification(`成功录入 ${records.length} 条样本`, 'success')
  emit('saved'); emit('close')
}

// 基础 UI 下拉控制逻辑保留在容器
function toggleDropdown(n: string) { openDropdown.value = openDropdown.value === n ? null : n }
function handleDropdownSelect(f: string, v: string) { (form.value as any)[f] = v; openDropdown.value = null }
function getSampleTypeLabel() { return form.value.sampleType || '等待识别...' }
function getSequenceTypeLabel() { return SEQUENCE_TYPE_OPTIONS.find(o => o.value === form.value.sequenceType)?.label || 'DNA' }
</script>

<style scoped>
/* 仅保留局部布局样式，详细表单样式已由子组件继承 */
.dialog-overlay { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.dialog-content { background: white; border-radius: 16px; width: 1000px; max-height: 92vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 24px; border-bottom: 1px solid #e2e8f0; }
.header-left { display: flex; align-items: center; gap: 12px; }
.icon-wrapper { width: 40px; height: 40px; background: #eff6ff; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; }
.dialog-title { font-size: 1.1rem; font-weight: 800; margin: 0; }
.dialog-body { flex: 1; overflow-y: auto; }
.dialog-layout { display: flex; }
.layout-left { flex: 1; padding: 24px; border-right: 1px solid #e2e8f0; }
.layout-right { flex: 1.2; padding: 24px; background: #f8fafc; }
.form-section { margin-bottom: 24px; }
.section-label { font-size: 0.85rem; font-weight: 700; color: #64748b; margin-bottom: 16px; }
.form-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.text-input { padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }
.custom-select { position: relative; cursor: pointer; }
.select-trigger { padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px; display: flex; justify-content: space-between; }
.select-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid #e2e8f0; border-radius: 8px; z-index: 100; }
.select-option { padding: 10px 14px; cursor: pointer; }
.select-option:hover { background: #f1f5f9; }
.read-only-field { padding: 10px 14px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; color: #64748b; }
.dialog-footer { display: flex; justify-content: space-between; padding: 16px 24px; border-top: 1px solid #e2e8f0; background: #f8fafc; }
.btn-confirm { background: #2563eb; color: white; border: none; padding: 10px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; }
.btn-cancel { background: white; border: 1px solid #e2e8f0; padding: 10px 24px; border-radius: 8px; cursor: pointer; }
.number-input { display: flex; border: 1px solid #cbd5e1; border-radius: 6px; }
.num-btn { width: 28px; height: 28px; border: none; background: #f1f5f9; cursor: pointer; }
.num-text { width: 40px; text-align: center; border: none; }
</style>