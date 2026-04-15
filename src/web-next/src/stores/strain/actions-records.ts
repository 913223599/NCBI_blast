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
    const { 
      keyword, species, sequenceType, country, dateFrom, dateTo,
      minLength, maxLength, integrityOnly 
    } = searchFilters.value

    filteredRecords.value = markRaw(records.value.filter((record: StrainRecord) => {
      // 核心业务：数据完整性检查 (关键字段缺失项)
      if (integrityOnly) {
        const isMissing = !record.accession || !record.species || !record.collectionDate
        if (!isMissing) return false
      }

      // 核心业务：序列长度区间筛选
      if (minLength !== null && minLength !== undefined && minLength !== '') {
        const len = record.sequence?.length || 0
        if (len < Number(minLength)) return false
      }
      if (maxLength !== null && maxLength !== undefined && maxLength !== '') {
        const len = record.sequence?.length || 0
        if (len > Number(maxLength)) return false
      }

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

    // 执行排序
    if (searchFilters.value.sortOrder) {
      const key = searchFilters.value.sortKey as keyof StrainRecord
      const order = searchFilters.value.sortOrder === 'asc' ? 1 : -1
      
      filteredRecords.value.sort((a: StrainRecord, b: StrainRecord) => {
        const valA = String(a[key] || '')
        const valB = String(b[key] || '')
        return valA.localeCompare(valB, undefined, { numeric: true }) * order
      })
    }
  }

  /** 切换排序状态 */
  function toggleSort(key: string) {
    if (searchFilters.value.sortKey === key) {
      if (searchFilters.value.sortOrder === 'asc') searchFilters.value.sortOrder = 'desc'
      else if (searchFilters.value.sortOrder === 'desc') searchFilters.value.sortOrder = null
      else searchFilters.value.sortOrder = 'asc'
    } else {
      searchFilters.value.sortKey = key
      searchFilters.value.sortOrder = 'asc'
    }
    applyFilters()
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

  /** 批量添加样本记录 (带 Promise 支持，用于链式保存) */
  function addRecords(recordsToAdd: any[]): Promise<boolean> {
    if (!recordsToAdd.length) return Promise.resolve(true)
    
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

    // 1. 同步更本地状态
    records.value = [...records.value, ...processedRecords]
    applyFilters()
    
    // 2. 开启护盾并返回保存状态
    setIsUpdating(true)
    return new Promise((resolve) => {
      try {
        const bridge = getBridge()
        bridge.db_save_records_batch(processedRecords, (success: boolean) => {
          if (!success) console.error('[StrainStore] 批量保存数据失败')
          // 注意：此处不再执行 setIsUpdating(false)，交给链式调用的终点处理
          resolve(success)
        })
      } catch (e) {
        setIsUpdating(false)
        console.error('[StrainStore] 批量保存异常:', e)
        resolve(false)
      }
    })
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

  function removeRecordsBatch(ids: string[]) {
    if (!ids.length) return
    records.value = records.value.filter((r: StrainRecord) => !ids.includes(r.id))
    ids.forEach(id => {
      selectedRecords.value.delete(id)
      if (activeRecord.value?.id === id) activeRecord.value = null
    })
    try {
      getBridge().db_delete_records_batch(ids)
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
    toggleSort,
    resetFilters,
    searchByCategory,
    addRecord,
    addRecords,
    updateRecord,
    removeRecord,
    removeRecordsBatch,
    toggleSelect,
    selectAll,
    clearSelection,
    recalibrateCounters,
    async clearAll() {
      const getBridge = (await import('../../bridge')).getBridge;
      const bridge = getBridge()
      await bridge.strain_clear_all()
      records.value = []
      applyFilters()
    }
  }
}
