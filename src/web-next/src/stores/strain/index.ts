import { defineStore } from 'pinia'
import { computed } from 'vue'
import { useStrainState } from './state'
import { useSyncActions } from './actions-sync'
import { useRecordsActions } from './actions-records'
import { useFreezerActions } from './actions-freezer'
import { useImportActions } from './actions-import'
import type { StrainRecord } from './types'

export const useStrainStore = defineStore('strain', () => {
  // 1. 初始化基础状态
  const s = useStrainState()

  // 2. 桥接循环依赖
  // 定义一个代理函数，允许在 syncModule 初始化之前将其传给 recordsModule
  let realAutoSave: (() => void) | null = null
  const autoSaveProxy = () => {
    if (realAutoSave) realAutoSave()
  }

  // 3. 初始化各模块 Actions
  const recordsModule = useRecordsActions(s, autoSaveProxy)
  const freezerModule = useFreezerActions(s)
  const importModule = useImportActions(s)
  const syncModule = useSyncActions(s, recordsModule)

  // 绑定真正的实现
  realAutoSave = syncModule.autoSave

  // 启动同步监听
  syncModule.setupSync()

  // 4. 计算属性 (Getters)
  const activeFreezer = computed(() => {
    return s.freezers.value.find(f => f.id === s.activeFreezerId.value)
  })

  const fileCount = computed(() => s.files.value.length)
  const hasInput = computed(() => {
    return s.inputMode.value === 'file'
      ? s.files.value.length > 0
      : s.importText.value.trim().length > 0
  })

  // 统计类 Getters
  const hasData = computed(() => s.records.value.length > 0)
  const filteredCount = computed(() => s.filteredRecords.value.length)
  const selectedCount = computed(() => s.selectedRecords.value.size)
  const totalRecords = computed(() => s.records.value.length)
  
  const uniqueSpecies = computed(() => {
    const set = new Set(s.records.value.map(r => r.species).filter(Boolean))
    return Array.from(set).sort()
  })
  
  const uniqueCountries = computed(() => {
    const set = new Set(s.records.value.map(r => r.country).filter(Boolean))
    return Array.from(set).sort()
  })

  // 5. 定义主 Store 暴露的额外逻辑
  function setActiveRecord(record: StrainRecord | null) {
    s.activeRecord.value = record
  }

  function setActiveFreezer(id: string | null) {
    s.activeFreezerId.value = id
  }

  function setSearchFilter(key: keyof typeof s.searchFilters.value, value: any) {
    (s.searchFilters.value as any)[key] = value
    recordsModule.applyFilters()
  }

  function switchInputMode(mode: 'file' | 'text' | 'ncbi') {
    s.inputMode.value = mode
  }

  function clearImportInput() {
    s.importText.value = ''
    s.files.value = []
  }

  function setPendingBlastDraft(draft: any) {
    s.pendingBlastDraft.value = draft
  }

  function consumePendingBlastDraft() {
    const draft = s.pendingBlastDraft.value
    s.pendingBlastDraft.value = null
    return draft
  }

  function exportSelected(format: 'csv' | 'fasta' | 'json'): string {
    const selected = s.records.value.filter((r: StrainRecord) => s.selectedRecords.value.has(r.id))
    if (selected.length === 0) return ''

    switch (format) {
      case 'csv':
        return generateCSV(selected)
      case 'fasta':
        return generateFASTA(selected)
      case 'json':
        return JSON.stringify(selected, null, 2)
      default:
        return ''
    }
  }

  function generateCSV(data: StrainRecord[]): string {
    const headers = ['Accession', 'Name', 'Species', 'Strain', 'Type', 'Source', 'Host', 'Country', 'Date']
    const rows = data.map(r =>
      [r.accession, r.name, r.species, r.strain, r.sampleType, r.source, r.host, r.country, r.collectionDate]
        .map(v => `"${String(v || '').replace(/"/g, '""')}"`)
        .join(',')
    )
    return [headers.join(','), ...rows].join('\n')
  }

  function generateFASTA(data: StrainRecord[]): string {
    return data
      .filter(r => r.sequence)
      .map(r => `>${r.accession} ${r.species} ${r.strain}\n${r.sequence}`)
      .join('\n')
  }

  // 6. 返回所有状态和方法
  return {
    ...s,
    ...recordsModule,
    ...freezerModule,
    ...importModule,
    ...syncModule,
    activeFreezer,
    fileCount,
    hasInput,
    hasData,
    filteredCount,
    selectedCount,
    totalRecords,
    uniqueSpecies,
    uniqueCountries,
    setActiveRecord,
    setActiveFreezer,
    setSearchFilter,
    switchInputMode,
    clearImportInput,
    setPendingBlastDraft,
    consumePendingBlastDraft,
    exportSelected
  }
})
