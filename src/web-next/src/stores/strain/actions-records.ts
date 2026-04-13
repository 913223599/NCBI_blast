import { getBridge } from '../../bridge'
import type { StrainRecord } from './types'
import { markRaw } from 'vue'

export function useRecordsActions(state: any, autoSave: () => void) {
  const { 
    records, 
    filteredRecords, 
    searchFilters, 
    selectedRecords, 
    activeRecord,
    setIsUpdating
  } = state

  /** 应用过滤器 */
  function applyFilters() {
    const { keyword, species, sequenceType, country, dateFrom, dateTo } = searchFilters.value

    filteredRecords.value = markRaw(records.value.filter((record: StrainRecord) => {
      if (keyword) {
        const kw = keyword.toLowerCase()
        const matchKeyword =
          record.name.toLowerCase().includes(kw) ||
          record.species.toLowerCase().includes(kw) ||
          record.strain.toLowerCase().includes(kw) ||
          record.accession.toLowerCase().includes(kw) ||
          record.source.toLowerCase().includes(kw)
        if (!matchKeyword) return false
      }
      if (species && record.species !== species) return false
      if (sequenceType && record.sequenceType !== sequenceType) return false
      if (country && record.country !== country) return false
      if (dateFrom && record.collectionDate < dateFrom) return false
      if (dateTo && record.collectionDate > dateTo) return false
      return true
    }))
  }

  function resetFilters() {
    searchFilters.value = {
      keyword: '',
      species: '',
      sequenceType: '',
      country: '',
      dateFrom: '',
      dateTo: ''
    }
    applyFilters()
  }

  async function searchByCategory(category: string) {
    if (!category) {
      resetFilters()
      return
    }
    try {
      const bridge = getBridge()
      const result = await (bridge as any).search_strains_by_category(category)
      if (result.success) {
        filteredRecords.value = result.records || []
      }
    } catch (e) {
      console.error('[StrainStore] Taxonomy search failed', e)
      searchFilters.value.keyword = category
      applyFilters()
    }
  }

  function addRecord(record: Omit<StrainRecord, 'id' | 'addedAt'>) {
    const newRecord: StrainRecord = {
      ...record,
      id: `record_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      addedAt: new Date().toISOString()
    }
    records.value = [...records.value, newRecord]
    
    setIsUpdating(true)
    try {
      getBridge().db_save_record(newRecord, () => {
        setIsUpdating(false)
      })
    } catch (e) {
      setIsUpdating(false)
    }

    applyFilters()
    return newRecord
  }

  function addRecords(recordsToAdd: any[]) {
    if (!recordsToAdd.length) return
    
    const now = new Date().toISOString()
    const processedRecords: StrainRecord[] = recordsToAdd.map(data => ({
      id: data.id || Math.random().toString(36).substring(2, 11),
      name: data.name || 'Unknown',
      accession: data.accession || '',
      species: data.species || '',
      strain: data.strain || '',
      sampleType: data.sampleType || 'Other',
      sequenceType: data.sequenceType || 'DNA',
      sequence: data.sequence || '',
      source: data.source || '',
      host: data.host || '',
      country: data.country || '',
      collectionDate: data.collectionDate || '',
      metadata: data.metadata || {},
      freezerId: data.freezerId || '',
      shelfId: data.shelfId || '',
      cabinetId: data.cabinetId || '',
      drawerId: data.drawerId || '',
      boxId: data.boxId || '',
      position: data.position || '',
      sampleCode: data.sampleCode || '',
      codeSource: data.codeSource || '',
      codeCategory: data.codeCategory || '',
      codeGenus: data.codeGenus || '',
      codeSpecies: data.codeSpecies || '',
      codePassage: data.codePassage || 0,
      codeSerial: data.codeSerial || 0,
      addedAt: data.addedAt || now
    }))

    records.value = [...records.value, ...processedRecords]
    
    setIsUpdating(true)
    try {
      const bridge = getBridge()
      bridge.db_save_records_batch(processedRecords, (success: boolean) => {
        setIsUpdating(false)
        if (!success) console.error('[StrainStore] 批量保存失败')
      })
    } catch (e) {
      setIsUpdating(false)
      console.error('[StrainStore] 批量保存异常:', e)
    }

    applyFilters()
  }

  function updateRecord(id: string, updates: Partial<StrainRecord>) {
    records.value = records.value.map((r: StrainRecord) => r.id === id ? { ...r, ...updates } : r)
    const record = records.value.find((r: StrainRecord) => r.id === id)
    if (record) {
      try {
        getBridge().db_save_record(record)
      } catch (e) {}
    }
    applyFilters()
  }

  function removeRecord(id: string) {
    records.value = records.value.filter((r: StrainRecord) => r.id !== id)
    selectedRecords.value.delete(id)
    if (activeRecord.value?.id === id) activeRecord.value = null
    try {
      getBridge().db_delete_record(id)
    } catch (e) {}
    applyFilters()
  }

  function toggleSelect(id: string) {
    if (selectedRecords.value.has(id)) {
      selectedRecords.value.delete(id)
    } else {
      selectedRecords.value.add(id)
    }
  }

  function selectAll() {
    filteredRecords.value.forEach((r: any) => selectedRecords.value.add(r.id))
  }

  function clearSelection() {
    selectedRecords.value.clear()
  }

  function recalibrateCounters() {
    const maxSerials: Record<string, number> = {}
    records.value.forEach((record: any) => {
      if (record.codeCategory && record.codeGenus && record.codeSpecies && record.codeSerial) {
        const key = `${record.codeCategory}${record.codeGenus}${record.codeSpecies}`
        const serial = Number(record.codeSerial)
        if (!maxSerials[key] || serial > maxSerials[key]) {
          maxSerials[key] = serial
        }
      }
    })

    const now = new Date().toISOString()
    state.serialCounters.value = Object.entries(maxSerials).map(([key, maxVal]) => ({
      counterKey: key,
      currentValue: maxVal,
      updatedAt: now
    }))
    autoSave && autoSave()
  }

  return {
    applyFilters,
    resetFilters,
    searchByCategory,
    addRecord,
    addRecords,
    updateRecord,
    removeRecord,
    toggleSelect,
    selectAll,
    clearSelection,
    recalibrateCounters
  }
}
