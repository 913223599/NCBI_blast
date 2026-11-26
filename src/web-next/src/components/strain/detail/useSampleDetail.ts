import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from '../../../locales'
import { useStrainStore } from '../../../stores/strain'
import type { StrainRecord } from '../../../stores/strain'
import { useAppStore } from '../../../stores/app'
import { useSequenceStore } from '../../../stores/sequence'
import { useConfirmDialog } from '../../../composables/useConfirmDialog'

export interface SampleDetailProps {
  record: StrainRecord
}

export interface SampleDetailEmits {
  (e: 'close'): void
  (e: 'deleted'): void
}

export const SAMPLE_TYPE_OPTIONS = [
  { value: 'Bacteria', label: '细菌 (Bacteria)' },
  { value: 'Phage', label: '噬菌体 (Phage)' },
  { value: 'Virus', label: '病毒 (Virus)' },
  { value: 'Plasmid', label: '质粒 (Plasmid)' },
  { value: 'Protein', label: '蛋白 (Protein)' },
  { value: 'CellLine', label: '细胞系 (Cell Line)' },
  { value: 'CompetentCell', label: '感受态 (Competent)' },
  { value: 'Other', label: '其他 (Other)' },
] as const

export const SEQUENCE_TYPE_OPTIONS = [
  { value: 'DNA', label: 'DNA (核酸)' },
  { value: 'RNA', label: 'RNA (核酸)' },
  { value: 'Protein', label: 'Protein (蛋白)' },
] as const

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

const METADATA_UNITS: Record<string, string | Record<string, string>> = {
  concentration: {
    Bacteria: 'CFU/mL',
    Fungi: 'CFU/mL',
    Archaea: 'CFU/mL',
    Plasmid: 'ng/μL',
    GenomicDNA: 'ng/μL',
    RNA: 'ng/μL',
    Oligo: 'ng/μL',
    Library: 'ng/μL',
    Protein: 'mg/mL',
    Enzyme: 'mg/mL',
    Antibody: 'mg/mL',
    Peptide: 'mg/mL',
    Antigen: 'mg/mL',
    CellLine: 'cells/mL',
    CompetentCell: 'cells/mL',
    Hybridomas: 'cells/mL',
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
  passageNumber: '代',
}

export function useSampleDetail(props: SampleDetailProps, emit: SampleDetailEmits) {
  const { t } = useI18n()
  const strain = useStrainStore()
  const sequenceStore = useSequenceStore()
  const appStore = useAppStore()
  const confirmDialog = useConfirmDialog()

  const isEditing = ref(false)
  const openDropdown = ref<string | null>(null)
  const associatedSequences = ref<Awaited<ReturnType<typeof sequenceStore.loadSequencesBySample>>>([])
  const showAddGeneForm = ref(false)

  const newGene = reactive({
    seqType: '16S',
    title: '',
    sequence: '',
  })

  const editForm = reactive<{
    name: string
    accession: string
    species: string
    strain: string
    sampleType: StrainRecord['sampleType']
    sequenceType: 'DNA' | 'RNA' | 'Protein'
    sequence: string
    source: string
    host: string
    country: string
    collectionDate: string
    metadata: Record<string, unknown>
  }>({
    name: '',
    accession: '',
    species: '',
    strain: '',
    sampleType: 'Bacteria',
    sequenceType: 'DNA',
    sequence: '',
    source: '',
    host: '',
    country: '',
    collectionDate: '',
    metadata: {},
  })

  const expectedMetadataKeys = computed(() => {
    const baseKeys = ['storageDate', 'storageMedium', 'biosafetyLevel', 'passageNumber', 'containerType', 'description']
    const specificKeys = TYPE_SPECIFIC_KEYS[props.record.sampleType] || []
    const actualKeys = props.record.metadata ? Object.keys(props.record.metadata) : []
    return [...new Set([...baseKeys, ...specificKeys, ...actualKeys])]
  })

  const hasMetadata = computed(() => expectedMetadataKeys.value.length > 0)

  const positionPath = computed(() => {
    const fId = props.record.freezerId || ''
    const bId = props.record.boxId || ''
    const compositeKey = `${fId}|${bId}`
    if (strain.locationMap[compositeKey]) return strain.locationMap[compositeKey]
    if (strain.locationMap[bId]) return strain.locationMap[bId]
    const freezer = strain.freezers.find((f) => f.id === fId)
    return freezer ? `${freezer.name} / 未索引层 / ${bId}` : '未知位置'
  })

  function formatMetadataValue(key: string, val: unknown): string {
    if (val === undefined || val === null || val === '') return '-'
    const unitDef = METADATA_UNITS[key]
    if (!unitDef) return String(val)
    const unit = typeof unitDef === 'string' ? unitDef : unitDef[props.record.sampleType] || ''
    const strVal = String(val).trim()
    if (unit && !strVal.toLowerCase().includes(unit.toLowerCase())) {
      return `${strVal} ${unit}`
    }
    return strVal
  }

  function toggleEditMode(): void {
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
      metadata: { ...(props.record.metadata || {}) },
    })
    isEditing.value = true
  }

  function handleSave(): void {
    if (!editForm.name.trim()) {
      appStore.showNotification('样本名称不能为空', 'error')
      return
    }
    const updatedCount = strain.updateRecord(props.record.id, { ...editForm })
    if (updatedCount > 1) {
      const sampleCode = props.record.sampleCode || props.record.accession
      appStore.showNotification(`已同步更新 ${updatedCount} 条编号为「${sampleCode}」的备份菌株`, 'success')
    } else {
      appStore.showNotification('样本信息已更新', 'success')
    }
    isEditing.value = false
  }

  async function handleDelete(): Promise<void> {
    const ok = await confirmDialog.confirm({
      title: '删除样本',
      message: `确定要删除样本"${props.record.name}"吗？`,
      confirmText: '确认删除',
      danger: true,
    })
    if (ok) {
      strain.removeRecord(props.record.id)
      appStore.showNotification('样本已删除', 'success')
      emit('deleted')
      emit('close')
    }
  }

  function formatDate(dateStr: string): string {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('zh-CN')
  }

  function formatDateTime(dateStr: string): string {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString('zh-CN')
  }

  function getSequenceTypeLabel(): string {
    return SEQUENCE_TYPE_OPTIONS.find((o) => o.value === editForm.sequenceType)?.label || 'DNA'
  }

  function getSampleTypeLabel(type: string): string {
    return SAMPLE_TYPE_OPTIONS.find((o) => o.value === type)?.label.split(' ')[0] || type
  }

  function toggleDropdown(name: string): void {
    openDropdown.value = openDropdown.value === name ? null : name
  }

  function getMetadataLabel(key: string): string {
    return t(`metadata.${key}`)
  }

  function isFullWidthMetadata(key: string, val: unknown): boolean {
    return key === 'description' || key === 'genotype' || (Array.isArray(val) && val.length > 5)
  }

  function selectOption(field: 'sequenceType' | 'sampleType', value: string): void {
    if (field === 'sequenceType') {
      editForm.sequenceType = value as 'DNA' | 'RNA' | 'Protein'
    } else {
      editForm.sampleType = value as StrainRecord['sampleType']
    }
    openDropdown.value = null
  }

  function handleClickOutside(): void {
    openDropdown.value = null
  }

  async function loadAssociatedGenes(): Promise<void> {
    associatedSequences.value = await sequenceStore.loadSequencesBySample(props.record.id)
  }

  async function handleAddGene(): Promise<void> {
    if (!newGene.sequence) return
    const success = await sequenceStore.saveSequence({
      sampleId: props.record.id,
      sampleCode: props.record.sampleCode || props.record.accession || '',
      seqType: newGene.seqType,
      title: newGene.title || `${newGene.seqType} Sequencing`,
      sequence: newGene.sequence,
      seqLen: newGene.sequence.replace(/[\s\r\n]/g, '').length,
      metadata: {},
    })
    if (success) {
      appStore.showNotification('已成功保存至基因数据库并建立关联', 'success')
      showAddGeneForm.value = false
      newGene.title = ''
      newGene.sequence = ''
      loadAssociatedGenes()
    }
  }

  async function handleDeleteGene(id: string): Promise<void> {
    const ok = await confirmDialog.confirm({
      title: '移除关联序列',
      message: '确定要从基因数据库中移除此序列吗？',
      confirmText: '确认移除',
      danger: true,
    })
    if (ok) {
      const success = await sequenceStore.deleteSequence(id)
      if (success) loadAssociatedGenes()
    }
  }

  function copySeq(text: string): void {
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

  return {
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
  }
}
