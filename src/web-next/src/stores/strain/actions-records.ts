import { getBridge } from '../../bridge'
import type { StrainRecord } from './types'
import { markRaw } from 'vue'
import { useCodeGenerator } from '../../composables/useCodeGenerator'

export function useRecordsActions(state: any, autoSave: () => void) {
  const { 
    records, 
    filteredRecords, 
    searchFilters, 
    selectedRecords, 
    activeRecord,
    setIsUpdating
  } = state

  // 获取 codeGen 实例用于物种路径解析
  const codeGen = useCodeGenerator()
  const lookup = codeGen.lookup
  
  // 获取 codeLookup entries 用于属级别筛选
  function getEntries() {
    return lookup.lookupEntries?.value ?? []
  }

  // shiftSelectRange 的 Map 缓存：避免每次 shift-click 都重建
  let _cachedRecordById: Map<string, StrainRecord> | null = null
  let _cachedAccessionMap: Map<string, string[]> | null = null
  let _mapsDirty = true

  function invalidateLookupMaps() {
    _mapsDirty = true
  }

  function ensureLookupMaps() {
    if (!_mapsDirty && _cachedRecordById && _cachedAccessionMap) return
    const recordById = new Map<string, StrainRecord>()
    const accessionMap = new Map<string, string[]>()
    for (let i = 0, len = records.value.length; i < len; i++) {
      const record = records.value[i]
      recordById.set(record.id, record)
      const acc = record.accession
      if (acc) {
        const list = accessionMap.get(acc)
        if (list) {
          list.push(record.id)
        } else {
          accessionMap.set(acc, [record.id])
        }
      }
    }
    _cachedRecordById = recordById
    _cachedAccessionMap = accessionMap
    _mapsDirty = false
  }

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
      if (species) {
        // 物种筛选：支持三级结构（大类/属/种）
        // species 可能是：
        // - 完整路径（如 "1AKFBXM"）- 物种级别 (level 3)
        // - 属路径（如 "1AKF"）- 属级别 (level 2)
        // - 大类代码（如 "1"）- 大类级别 (level 1)
        
        const selectedEntry = lookup.findByFullPath(species)
        
        let matches = false
        
        if (selectedEntry) {
          // 在 codeLookup 中找到了对应条目，根据层级进行匹配
          if (selectedEntry.level === 3) {
            // 选择了物种级别：通过名称匹配
            // 提取物种名称（去掉括号中的拉丁名）
            const speciesName = (selectedEntry.name || '').split('(')[0]?.trim() || ''
            matches = (!!speciesName && record.name.includes(speciesName)) || 
                      (!!speciesName && !!record.species && record.species.includes(speciesName)) ||
                      `${record.codeCategory}${record.codeGenus}${record.codeSpecies}` === species
          } else if (selectedEntry.level === 2) {
            // 选择了属级别：获取该属下所有物种的名称，然后匹配记录
            const genusName = (selectedEntry.name || '').split('(')[0]?.trim() || ''
            
            // 获取该属下的所有物种
            const entries = getEntries()
            const speciesInGenus = entries.filter(
              e => e.level === 3 && e.parentPath === species && e.enabled
            )
            
            if (speciesInGenus.length > 0) {
              // 有预定义的物种列表，通过名称匹配
              const speciesNames = speciesInGenus.map(sp => (sp.name || '').split('(')[0]?.trim() || '').filter(Boolean)
              matches = speciesNames.some(name => 
                record.name.includes(name) || (record.species ? record.species.includes(name) : false)
              )
            } else {
              // 没有预定义物种，尝试通过属名匹配
              matches = record.name.includes(genusName) || 
                        record.species?.includes(genusName) ||
                        record.codeGenus === selectedEntry.code
            }
          } else if (selectedEntry.level === 1) {
            // 选择了大类级别，匹配该大类下所有物种
            matches = record.codeCategory === species
          }
        } else {
          // 未在 codeLookup 中找到对应条目，尝试作为大类代码处理
          if (species.length === 1) {
            matches = record.codeCategory === species
          }
          // 否则跳过筛选（保持原有行为）
        }
        
        if (!matches) return false
      }
      if (searchFilters.value.sampleType && record.sampleType !== searchFilters.value.sampleType) return false
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
      sampleType: '',
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
      id: `record_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`,
      addedAt: new Date().toISOString()
    }
    records.value = [...records.value, newRecord]
    invalidateLookupMaps()
    
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
    invalidateLookupMaps()
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

  function updateRecord(id: string, updates: Partial<StrainRecord>): number {
    // 查找当前记录的 sampleCode
    const targetRecord = records.value.find((r: StrainRecord) => r.id === id)
    if (!targetRecord) return 0

    const sampleCode = targetRecord.sampleCode || targetRecord.accession
    
    // 如果有 sampleCode，则同步更新所有同号备份菌株
    if (sampleCode && sampleCode.trim()) {
      const backupRecords = records.value.filter(
        (r: StrainRecord) => (r.sampleCode || r.accession) === sampleCode
      )
      
      // 批量更新所有同号记录
      records.value = records.value.map((r: StrainRecord) => {
        if ((r.sampleCode || r.accession) === sampleCode) {
          return { ...r, ...updates }
        }
        return r
      })
      invalidateLookupMaps()
      
      // 将所有更新的记录保存到数据库
      try {
        getBridge().db_save_records_batch(backupRecords.map((r: StrainRecord) => ({ ...r, ...updates })))
      } catch (e) {
        console.error('[StrainStore] 同步更新备份菌株失败:', e)
      }
      
      applyFilters()
      return backupRecords.length
    } else {
      // 没有 sampleCode，只更新单条记录
      records.value = records.value.map((r: StrainRecord) => r.id === id ? { ...r, ...updates } : r)
      invalidateLookupMaps()
      const record = records.value.find((r: StrainRecord) => r.id === id)
      if (record) {
        try {
          getBridge().db_save_record(record)
        } catch (e) {}
      }
      
      applyFilters()
      return 1
    }
  }

  function removeRecord(id: string) {
    records.value = records.value.filter((r: StrainRecord) => r.id !== id)
    invalidateLookupMaps()
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
    invalidateLookupMaps()
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

  /** Shift 键范围选择 */
  function shiftSelectRange(fromId: string, toId: string, allIds: string[]) {
    // 用 indexOf 一次性完成查找 + 存在性判断，避免 includes 的冗余遍历
    const fromIndex = allIds.indexOf(fromId)
    const toIndex = allIds.indexOf(toId)
    
    if (fromIndex === -1 || toIndex === -1) {
      console.warn('[shiftSelectRange] ID not found in list, fallback to toggle')
      toggleSelect(toId)
      return
    }
    
    const startIndex = fromIndex < toIndex ? fromIndex : toIndex
    const endIndex = fromIndex < toIndex ? toIndex : fromIndex
    
    // 使用缓存的 Map，仅在数据变化时重建
    ensureLookupMaps()
    const recordById = _cachedRecordById!
    const accessionMap = _cachedAccessionMap!
    
    // 选中范围内的所有记录，并自动包含同 accession 的所有备份
    const idsToAdd = new Set<string>()
    for (let i = startIndex; i <= endIndex; i++) {
      const id = allIds[i]
      if (!id) continue
      idsToAdd.add(id)
      
      const record = recordById.get(id)
      if (record?.accession) {
        const allBackupIds = accessionMap.get(record.accession)
        if (allBackupIds) {
          for (const bid of allBackupIds) {
            idsToAdd.add(bid)
          }
        }
      }
    }
    
    // 批量添加选中的 ID
    idsToAdd.forEach((id: string) => selectedRecords.value.add(id))
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
    shiftSelectRange,
    selectAll,
    clearSelection,
    recalibrateCounters,
    async clearAll() {
      const getBridge = (await import('../../bridge')).getBridge;
      const bridge = getBridge()
      await bridge.strain_clear_all()
      records.value = []
      invalidateLookupMaps()
      applyFilters()
    }
  }
}
