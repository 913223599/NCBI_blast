/**
 * Strain Store - 菌毒种库状态管理
 * 管理菌毒种库的冰箱保藏、序列数据和元数据
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { saveToStorage, loadFromStorage } from '../utils/storage'

export interface FreezerBox {
  id: string
  name: string // 例如："Box-01"
  rows: number // 行数，例如 9 或 10
  cols: number // 列数，例如 9 或 10
  positions: Array<{ // 具体位置
    row: number
    col: number
    label: string // 例如: "A1", "B2"
    occupied: boolean
    sampleId?: string
  }>
}

export interface FreezerDrawer {
  id: string
  name: string // 例如："抽屉-01"
  boxes: FreezerBox[] // 该抽屉中的冻存盒
}

export interface FreezerCabinet {
  id: string
  name: string // 例如："柜-01"
  drawers: FreezerDrawer[] // 该柜中的抽屉
}

export interface FreezerShelf {
  id: string
  name: string // 例如："第1层"
  cabinets: FreezerCabinet[] // 该层中的柜
}

export interface Freezer {
  id: string
  name: string // 冰箱名称
  model: string // 型号
  location: string // 位置
  shelves: FreezerShelf[] // 层配置
  createdAt: string
  updatedAt: string
}

/** 样本分类枚举 */
export type SampleCategory = 
  | 'Bacteria' | 'Phage' | 'Virus' | 'Fungi' | 'Archaea' 
  | 'Plasmid' | 'GenomicDNA' | 'RNA' | 'Oligo' | 'Library'
  | 'Protein' | 'Enzyme' | 'Antibody' | 'Peptide' | 'Antigen'
  | 'CompetentCell' | 'CellLine' | 'Tissue' | 'Fluid' | 'Environmental'
  | 'Exosome' | 'Vesicle' | 'Organelle' | 'Other'

/** 通用基础元数据 */
export interface BaseMetadata {
  description?: string
  storageMedium?: string // 甘油、DMSO、PBS 等
  passageNumber?: string // 传代次数
  biosafetyLevel?: 'BSL-1' | 'BSL-2' | 'BSL-3' | 'BSL-4'
  containerType?: string // 冻存管规格
  batchNumber?: string // 批次号
  concentration?: string // 浓度
  titer?: string // 滴度
  potency?: string // 效价/活性
  storageDate?: string // 冻存入库时间
}

/** 细菌/真菌元数据 */
export interface MicrobeMetadata extends BaseMetadata {
  hostStrain?: string // 宿主菌
  genotype?: string // 基因型
  resistance?: string[] // 抗性
  cultureCondition?: string // 培养条件
  growthTemp?: string // 生长温度
}

/** 质粒/遗传材料元数据 */
export interface GeneticMetadata extends BaseMetadata {
  backbone?: string // 骨架
  insertName?: string // 插入片段
  plasmidSize?: string // 大小
  marker?: string[] // 筛选标记
  isExpression?: boolean // 是否表达载体
  promoter?: string // 启动子
}

/** 病毒元数据 */
export interface VirusMetadata extends BaseMetadata {
  serotype?: string // 血清型
  envelope?: string // 包膜
  inactivationMethod?: string // 灭活方法
}

/** 噬菌体元数据 */
export interface PhageMetadata extends BaseMetadata {
  hostRange?: string // 宿主范围
  hostStrain?: string // 具体显示宿主
  lifestyle?: 'Virulent' | 'Temperate' // 烈性/温和
  latentPeriod?: string // 潜伏期
  burstSize?: string // 裂解量
  morphology?: string // 形态分类
}

/** 蛋白质/抗体元数据 */
export interface ProteinMetadata extends BaseMetadata {
  purity?: string // 纯度
  buffer?: string // 缓冲液
  molecularWeight?: string // 分子量
  tags?: string[] // 标签 (His/GST/etc)
}

/** 细胞元数据 */
export interface CellMetadata extends BaseMetadata {
  cellType?: string // 细胞类型
  medium?: string // 培养基
  doublingTime?: string // 倍增时间
  authentication?: string // 鉴定报告编号
}

export interface StrainRecord {
  id: string
  accession: string       // 这里现在主要作为"外部登录号"使用
  name: string
  species: string
  strain: string          // 株/品系

  // === 14位新编码系统字段 ===
  sampleCode?: string      // 完整 14 位编号: XXABBBCCCPNNNN
  codeSource?: string      // 来源 (XX)
  codeCategory?: string    // 大类 (A)
  codeGenus?: string       // 属 (BBB)
  codeSpecies?: string     // 种 (CCC)
  codePassage?: number     // 传代 (P)
  codeSerial?: number      // 流水号 (NNNN)

  sampleType: SampleCategory
  sequenceType: 'DNA' | 'RNA' | 'Protein'
  sequence: string
  source: string
  host: string
  country: string
  collectionDate: string
  metadata: Record<string, any>
  freezerId?: string
  shelfId?: string
  cabinetId?: string
  drawerId?: string
  boxId?: string
  position?: string
  addedAt: string
}

export interface SearchFilters {
  keyword: string
  species: string
  sequenceType: string
  country: string
  dateFrom: string
  dateTo: string
}

export interface ImportTask {
  taskId: string
  fileName: string
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled'
  progress: number
  recordCount: number
  startTime: string
}

import { getBridge, onEvent } from '../bridge'

export const useStrainStore = defineStore('strain', () => {
  /* ======== 冰箱管理 ======== */
  const freezers = ref<Freezer[]>([])
  const activeFreezerId = ref<string | null>(null)

  /* ======== 数据状态 ======== */
  const records = ref<StrainRecord[]>([])
  
  // === 编码系统状态 (P1: 持久化支持) ===
  const codeLookupEntries = ref<any[]>([]) // 存储 CodeLookupEntry[]
  const sourceEntries = ref<any[]>([])      // 存储 SourceEntry[]
  const serialCounters = ref<any[]>([])     // 存储 SerialCounter[]
  const codeConfig = ref({
    assignMode: 'sequential',
    serialDigits: 4,
    version: '1.0.0'
  })
  const isInitialized = ref(false)
  const filteredRecords = ref<StrainRecord[]>([])
  const searchFilters = ref<SearchFilters>({
    keyword: '',
    species: '',
    sequenceType: '',
    country: '',
    dateFrom: '',
    dateTo: ''
  })

  /* ======== 导入状态 ======== */
  const importTasks = ref<ImportTask[]>([])
  const activeTaskId = ref<string | null>(null)
  const inputMode = ref<'file' | 'text' | 'ncbi'>('file')
  const importText = ref('')

  /* ======== 选择状态 ======== */
  const selectedRecords = ref<Set<string>>(new Set())
  const activeRecord = ref<StrainRecord | null>(null)
  const pendingBlastDraft = ref<any>(null)

  // 初始化时从数据库加载数据
  function initFromDatabase(): Promise<void> {
    return new Promise((resolve) => {
        try {
          const bridge = getBridge()
          bridge.db_load_all(async (jsonStr: string) => {
            try {
              if (jsonStr && jsonStr !== 'null') {
                  const data = JSON.parse(jsonStr)
                  freezers.value = data.freezers || []
                  records.value = data.records || []
                  
                  // 加载编码系统数据
                  if (data.codeLookup) {
                    codeLookupEntries.value = data.codeLookup.entries || []
                    sourceEntries.value = data.codeLookup.sources || []
                    serialCounters.value = data.codeLookup.counters || []
                    codeConfig.value = data.codeLookup.config || codeConfig.value
                  }
                  
                  // 注入内置默认数据
                  if (codeLookupEntries.value.length === 0) {
                    const { BUILTIN_LOOKUP_ENTRIES, BUILTIN_SOURCE_ENTRIES } = await import('../data/builtinCodes')
                    codeLookupEntries.value = [...BUILTIN_LOOKUP_ENTRIES]
                    sourceEntries.value = [...BUILTIN_SOURCE_ENTRIES]
                  }

                  applyFilters()
                  isInitialized.value = true
                  console.log('[StrainStore] 菌株库加载完成')
              }
              resolve()
            } catch (e) {
              isInitialized.value = true
              console.error('[Strain Store] Failed to parse DB data', e)
              resolve()
            }
          })

          // 注册全局翻译回调
          onEvent((type: string, data: any) => {
            if (type === 'translation_done') {
                const { original, translated } = data as { original: string, translated: string };
                if (!original || !translated) return;

                // 更新编码对照表中的匹配项
                let changed = false;
                codeLookupEntries.value.forEach(entry => {
                    const latin = entry.latinName || entry.name;
                    if (latin === original && entry.name !== translated) {
                        // 格式化为：中文(拉丁文)
                        entry.name = `${translated}(${original})`;
                        changed = true;
                    }
                });

                if (changed) {
                    autoSave();
                }
            }
          });
        } catch (e) {
          console.warn('[Strain Store] Bridge not ready, falling back to LocalStorage')
          const storedData = loadFromStorage()
          if (storedData) {
            freezers.value = storedData.freezers
            records.value = storedData.records
            
            // 加载备用存储中的编码数据
            if ((storedData as any).codeLookup) {
              codeLookupEntries.value = (storedData as any).codeLookup.entries || []
              sourceEntries.value = (storedData as any).codeLookup.sources || []
              serialCounters.value = (storedData as any).codeLookup.counters || []
            }
          }
          resolve()
        }
    })
  }

  // 自动保存数据 - 防抖 300ms
  let autoSaveTimer: ReturnType<typeof setTimeout> | null = null
  function autoSave() {
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      const codeLookupData = {
        entries: codeLookupEntries.value,
        sources: sourceEntries.value,
        counters: serialCounters.value,
        config: codeConfig.value
      }

      saveToStorage({
        freezers: freezers.value,
        records: records.value,
        // 增加编码系统数据的备份
        codeLookup: codeLookupData
      } as any)

      try {
        const bridge = getBridge()
        if (bridge && bridge.db_save_code_lookup) {
          bridge.db_save_code_lookup(JSON.stringify(codeLookupData))
        }
      } catch (e) {}

      autoSaveTimer = null
    }, 300)
  }

  /* ======== 统计 ======== */
  const totalRecords = computed(() => records.value.length)
  const filteredCount = computed(() => filteredRecords.value.length)
  const selectedCount = computed(() => selectedRecords.value.size)

  /* ======== 计算属性 ======== */
  const uniqueSpecies = computed(() => {
    const speciesSet = new Set(records.value.map(r => r.species).filter(Boolean))
    return Array.from(speciesSet).sort()
  })

  const uniqueCountries = computed(() => {
    const countrySet = new Set(records.value.map(r => r.country).filter(Boolean))
    return Array.from(countrySet).sort()
  })

  const hasData = computed(() => records.value.length > 0)
  const activeFreezer = computed(() => 
    freezers.value.find(f => f.id === activeFreezerId.value) || null
  )

  /* ======== Actions: 冰箱管理 ======== */
  function addFreezer(freezer: Omit<Freezer, 'id' | 'createdAt' | 'updatedAt'>) {
    const newFreezer: Freezer = {
      ...freezer,
      id: `freezer_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }
    freezers.value.push(newFreezer)
    
    // 同步到数据库
    try {
      getBridge().db_save_freezer(JSON.stringify(newFreezer))
    } catch (e) {}
    
    autoSave() // 自动保存
    return newFreezer
  }

  function updateFreezer(id: string, updates: Partial<Freezer>) {
    const freezer = freezers.value.find(f => f.id === id)
    if (freezer) {
      Object.assign(freezer, updates, { updatedAt: new Date().toISOString() })
      
      // 同步到数据库
      try {
        getBridge().db_save_freezer(JSON.stringify(freezer))
      } catch (e) {}

      autoSave() // 自动保存
    }
  }

  function removeFreezer(id: string) {
    freezers.value = freezers.value.filter(f => f.id !== id)
    if (activeFreezerId.value === id) {
      activeFreezerId.value = null
    }
    
    // 同步到数据库
    try {
      getBridge().db_delete_freezer(id)
    } catch (e) {}

    // 同时删除该冰箱下的所有记录
    records.value = records.value.filter(r => r.freezerId !== id)
    autoSave() // 自动保存
  }

  function setActiveFreezer(id: string | null) {
    activeFreezerId.value = id
  }

  // 添加/移除层级结构
  function addShelfToFreezer(freezerId: string, shelf: Omit<FreezerShelf, 'id' | 'cabinets'>) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const newShelf: FreezerShelf = {
        ...shelf,
        id: `shelf_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        cabinets: []
      }
      freezer.shelves.push(newShelf)
      freezer.updatedAt = new Date().toISOString()
      autoSave() // 自动保存
      return newShelf
    }
    return null
  }

  function removeShelfFromFreezer(freezerId: string, shelfId: string) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      freezer.shelves = freezer.shelves.filter(s => s.id !== shelfId)
      freezer.updatedAt = new Date().toISOString()
      // 同时删除该层的所有记录
      records.value = records.value.filter(r => r.shelfId !== shelfId)
      autoSave() // 自动保存
    }
  }

  function addCabinetToShelf(freezerId: string, shelfId: string, cabinet: Omit<FreezerCabinet, 'id' | 'drawers'>) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        const newCabinet: FreezerCabinet = {
          ...cabinet,
          id: `cabinet_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          drawers: []
        }
        shelf.cabinets.push(newCabinet)
        freezer.updatedAt = new Date().toISOString()
        autoSave() // 自动保存
        return newCabinet
      }
    }
    return null
  }

  function removeCabinetFromShelf(freezerId: string, shelfId: string, cabinetId: string) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        shelf.cabinets = shelf.cabinets.filter(c => c.id !== cabinetId)
        freezer.updatedAt = new Date().toISOString()
        // 同时删除该柜的所有记录
        records.value = records.value.filter(r => r.cabinetId !== cabinetId)
        autoSave() // 自动保存
      }
    }
  }

  function addDrawerToCabinet(freezerId: string, shelfId: string, cabinetId: string, drawer: Omit<FreezerDrawer, 'id' | 'boxes'>) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        const cabinet = shelf.cabinets.find(c => c.id === cabinetId)
        if (cabinet) {
          const newDrawer: FreezerDrawer = {
            ...drawer,
            id: `drawer_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            boxes: []
          }
          cabinet.drawers.push(newDrawer)
          freezer.updatedAt = new Date().toISOString()
          autoSave() // 自动保存
          return newDrawer
        }
      }
    }
    return null
  }

  function removeDrawerFromCabinet(freezerId: string, shelfId: string, cabinetId: string, drawerId: string) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        const cabinet = shelf.cabinets.find(c => c.id === cabinetId)
        if (cabinet) {
          cabinet.drawers = cabinet.drawers.filter(d => d.id !== drawerId)
          freezer.updatedAt = new Date().toISOString()
          // 同时删除该抽屉的所有记录
          records.value = records.value.filter(r => r.drawerId !== drawerId)
          autoSave() // 自动保存
        }
      }
    }
  }

  function addBoxToDrawer(freezerId: string, shelfId: string, cabinetId: string, drawerId: string, box: Omit<FreezerBox, 'id' | 'positions'>) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        const cabinet = shelf.cabinets.find(c => c.id === cabinetId)
        if (cabinet) {
          const drawer = cabinet.drawers.find(d => d.id === drawerId)
          if (drawer) {
            const newBox: FreezerBox = {
              ...box,
              id: `box_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
              positions: generateBoxPositions(box.rows, box.cols)
            }
            drawer.boxes.push(newBox)
            freezer.updatedAt = new Date().toISOString()
            autoSave() // 自动保存
            return newBox
          }
        }
      }
    }
    return null
  }

  function removeBoxFromDrawer(freezerId: string, shelfId: string, cabinetId: string, drawerId: string, boxId: string) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (freezer) {
      const shelf = freezer.shelves.find(s => s.id === shelfId)
      if (shelf) {
        const cabinet = shelf.cabinets.find(c => c.id === cabinetId)
        if (cabinet) {
          const drawer = cabinet.drawers.find(d => d.id === drawerId)
          if (drawer) {
            drawer.boxes = drawer.boxes.filter(b => b.id !== boxId)
            freezer.updatedAt = new Date().toISOString()
            // 同时删除该盒的所有记录
            records.value = records.value.filter(r => r.boxId !== boxId)
            autoSave() // 自动保存
          }
        }
      }
    }
  }

  function generateBoxPositions(rows: number, cols: number) {
    const positions = []
    const rowLabels = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    
    for (let r = 0; r < rows; r++) {
      for (let c = 1; c <= cols; c++) {
        positions.push({
          row: r,
          col: c,
          label: `${rowLabels[r]}${c}`,
          occupied: false
        })
      }
    }
    return positions
  }

  /* ======== Actions: 数据管理 ======== */
  function addRecord(record: Omit<StrainRecord, 'id' | 'addedAt'>) {
    const newRecord: StrainRecord = {
      ...record,
      id: `record_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      addedAt: new Date().toISOString()
    }
    records.value.push(newRecord)
    
    // 同步到数据库
    try {
      getBridge().db_save_record(JSON.stringify(newRecord))
    } catch (e) {}

    applyFilters()
    autoSave()
    return newRecord
  }

  function addRecords(newRecords: StrainRecord[]) {
    records.value.push(...newRecords)
    
    // 批量同步到数据库
    try {
      const bridge = getBridge()
      newRecords.forEach(r => bridge.db_save_record(JSON.stringify(r)))
    } catch (e) {}

    applyFilters()
    autoSave()
  }

  function removeRecord(id: string) {
    const record = records.value.find(r => r.id === id)
    if (record) {
      // 释放关联位置（内部不再单独 autoSave，由本函数末尾统一触发）
      if (record.freezerId && record.shelfId && record.cabinetId && record.drawerId && record.boxId && record.position) {
        updatePositionOccupancy(
          record.freezerId,
          record.shelfId,
          record.cabinetId,
          record.drawerId,
          record.boxId,
          record.position,
          false,
          undefined
        )
      }

      // 同步到数据库
      try {
        getBridge().db_delete_record(id)
      } catch (e) {}
    }

    // 批量更新内存状态（一次性触发响应式）
    records.value = records.value.filter(r => r.id !== id)
    selectedRecords.value.delete(id)
    if (activeRecord.value?.id === id) {
      activeRecord.value = null
    }
    applyFilters()
    autoSave() // 防抖，300ms 内多次调用只执行一次
  }

  function updateRecord(id: string, updates: Partial<StrainRecord>) {
    const record = records.value.find(r => r.id === id)
    if (record) {
      // 如果修改了位置信息，需要更新占用状态
      if (updates.freezerId !== undefined || 
          updates.shelfId !== undefined || 
          updates.cabinetId !== undefined || 
          updates.drawerId !== undefined || 
          updates.boxId !== undefined || 
          updates.position !== undefined) {
        // 释放旧位置
        if (record.freezerId && record.shelfId && record.cabinetId && record.drawerId && record.boxId && record.position) {
          updatePositionOccupancy(
            record.freezerId,
            record.shelfId,
            record.cabinetId,
            record.drawerId,
            record.boxId,
            record.position,
            false,
            undefined
          )
        }
        // 占用新位置（如果提供了）
        const newFreezerId = updates.freezerId || record.freezerId
        const newShelfId = updates.shelfId || record.shelfId
        const newCabinetId = updates.cabinetId || record.cabinetId
        const newDrawerId = updates.drawerId || record.drawerId
        const newBoxId = updates.boxId || record.boxId
        const newPosition = updates.position || record.position
        
        if (newFreezerId && newShelfId && newCabinetId && newDrawerId && newBoxId && newPosition) {
          updatePositionOccupancy(
            newFreezerId,
            newShelfId,
            newCabinetId,
            newDrawerId,
            newBoxId,
            newPosition,
            true,
            record.id
          )
        }
      }
      
      Object.assign(record, updates)
      
      // 同步到数据库
      try {
        getBridge().db_save_record(JSON.stringify(record))
      } catch (e) {}

      applyFilters()
      autoSave()
    }
  }

  // 更新位置占用状态
  function updatePositionOccupancy(
    freezerId: string,
    shelfId: string,
    cabinetId: string,
    drawerId: string,
    boxId: string,
    positionLabel: string,
    occupied: boolean,
    sampleId?: string
  ) {
    const freezer = freezers.value.find(f => f.id === freezerId)
    if (!freezer) return
    
    for (const shelf of freezer.shelves) {
      if (shelf.id === shelfId) {
        for (const cabinet of shelf.cabinets) {
          if (cabinet.id === cabinetId) {
            for (const drawer of cabinet.drawers) {
              if (drawer.id === drawerId) {
                for (const box of drawer.boxes) {
                  if (box.id === boxId) {
                    const pos = box.positions.find(p => p.label === positionLabel)
                    if (pos) {
                      pos.occupied = occupied
                      pos.sampleId = sampleId
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    // 同步冰箱结构到数据库 (因为结构嵌套在 freezer 对象中)
    try {
      getBridge().db_save_freezer(JSON.stringify(freezer))
    } catch (e) {}

    // 注意：不在此处调用 autoSave()，由上层调用方统一控制
    // 避免 removeRecord -> updatePositionOccupancy -> autoSave 的重复写入
  }

  function clearAll() {
    records.value = []
    filteredRecords.value = []
    selectedRecords.value.clear()
    activeRecord.value = null

    // 同步到数据库
    try {
      getBridge().db_clear_all()
    } catch (e) {}

    autoSave() // 自动保存
  }

  /* ======== Actions: 搜索筛选 ======== */
  function applyFilters() {
    const { keyword, species, sequenceType, country, dateFrom, dateTo } = searchFilters.value

    filteredRecords.value = records.value.filter(record => {
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
    })
  }

  function setSearchFilter(key: keyof SearchFilters, value: string) {
    searchFilters.value[key] = value
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
    filteredRecords.value = [...records.value]
  }

  /**
   * 按分类学类别搜索 (调用 ETE4 后端)
   * @param category 分类名称 (例如: Bacillota, Enterobacterales)
   */
  async function searchByCategory(category: string) {
    if (!category) {
        resetFilters()
        return
    }
    
    try {
        const bridge = getBridge()
        // TypeScript 可能会报错说 search_strains_by_category 不存在（如果不重新生成 .d.ts）
        // 这里采用 (bridge as any) 绕过，或确认类型已更新
        const resultJson = await (bridge as any).search_strains_by_category(category)
        const result = JSON.parse(resultJson)
        
        if (result.success) {
            // 后端直接返回了符合该分类及其子类的所有记录
            filteredRecords.value = result.records || []
            console.log(`[StrainStore] Taxonomy search: ${category} found ${filteredRecords.value.length} matches.`);
        }
    } catch (e) {
        console.error('[StrainStore] Taxonomy search failed', e)
        // 降级回普通关键词搜索
        searchFilters.value.keyword = category
        applyFilters()
    }
  }

  /* ======== Actions: 选择管理 ======== */
  function toggleSelect(id: string) {
    if (selectedRecords.value.has(id)) {
      selectedRecords.value.delete(id)
    } else {
      selectedRecords.value.add(id)
    }
  }

  function selectAll() {
    filteredRecords.value.forEach(r => selectedRecords.value.add(r.id))
  }

  function clearSelection() {
    selectedRecords.value.clear()
  }

  function setActiveRecord(record: StrainRecord | null) {
    activeRecord.value = record
  }

  /* ======== Actions: 导入管理 ======== */
  function addImportTask(task: ImportTask) {
    importTasks.value.unshift(task)
    activeTaskId.value = task.taskId
  }

  function updateTaskStatus(taskId: string, status: string, progress: number) {
    const task = importTasks.value.find(t => t.taskId === taskId)
    if (task) {
      task.status = status as ImportTask['status']
      task.progress = progress
    }
  }

  function removeTask(taskId: string) {
    importTasks.value = importTasks.value.filter(t => t.taskId !== taskId)
    if (activeTaskId.value === taskId) {
      activeTaskId.value = importTasks.value[0]?.taskId ?? null
    }
  }

  function clearTasks() {
    importTasks.value = []
    activeTaskId.value = null
  }

  function setPendingBlastDraft(draft: any) {
    pendingBlastDraft.value = draft
  }

  function consumePendingBlastDraft() {
    const draft = pendingBlastDraft.value
    pendingBlastDraft.value = null
    return draft
  }

  /* ======== Actions: 导入输入 ======== */
  function switchInputMode(mode: 'file' | 'text' | 'ncbi') {
    inputMode.value = mode
  }

  function setImportText(text: string) {
    importText.value = text
  }

  function clearImportInput() {
    importText.value = ''
  }

  /* ======== 维护功能：流水号重校准 ======== */
  /**
   * 扫描所有样本，将计数器重置为每个分类下的最大已用编号
   */
  function recalibrateCounters() {
    const maxSerials: Record<string, number> = {}

    // 1. 扫描所有记录，记录每个路径的最大流水号
    records.value.forEach(record => {
      if (record.codeCategory && record.codeGenus && record.codeSpecies && record.codeSerial) {
        const key = `${record.codeCategory}${record.codeGenus}${record.codeSpecies}`
        const serial = Number(record.codeSerial)
        if (!maxSerials[key] || serial > maxSerials[key]) {
          maxSerials[key] = serial
        }
      }
    })

    // 2. 更新计数器列表
    const now = new Date().toISOString()
    const updatedCounters = Object.entries(maxSerials).map(([key, maxVal]) => ({
      counterKey: key,
      currentValue: maxVal,
      updatedAt: now
    }))

    serialCounters.value = updatedCounters
    autoSave()
    console.log(`[Strain Store] 计数器重校准完成，更新了 ${updatedCounters.length} 个分类路径`)
  }

  /* ======== Actions: 导出 ======== */
  function exportSelected(format: 'csv' | 'fasta' | 'json'): string {
    const selected = records.value.filter(r => selectedRecords.value.has(r.id))
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
      [r.accession, r.name, r.species, r.strain, r.sequenceType, r.source, r.host, r.country, r.collectionDate]
        .map(v => `"${(v || '').replace(/"/g, '""')}"`)
        .join(',')
    )
    return [headers.join(','), ...rows].join('\n')
  }

  function generateFASTA(data: StrainRecord[]): string {
    return data.map(r => `>${r.accession} | ${r.name} | ${r.species}\n${r.sequence}`).join('\n\n')
  }

  return {
    // State
    freezers,
    activeFreezerId,
    records,
    codeLookupEntries,
    sourceEntries,
    serialCounters,
    codeConfig,
    isInitialized,
    filteredRecords,
    searchFilters,
    selectedRecords,
    activeRecord,
    pendingBlastDraft,

    // NEW IDENTIFICATION DRAFT SUPPORT
    setPendingBlastDraft,
    consumePendingBlastDraft,

    // Computed
    totalRecords,
    filteredCount,
    selectedCount,
    uniqueSpecies,
    uniqueCountries,
    hasData,
    activeFreezer,

    // Actions: Freezer
    addFreezer,
    updateFreezer,
    removeFreezer,
    setActiveFreezer,
    addShelfToFreezer,
    removeShelfFromFreezer,
    addCabinetToShelf,
    removeCabinetFromShelf,
    addDrawerToCabinet,
    removeDrawerFromCabinet,
    addBoxToDrawer,
    removeBoxFromDrawer,

    // Actions: Records
    addRecord,
    addRecords,
    removeRecord,
    updateRecord,
    updatePositionOccupancy,
    autoSave,
    clearAll,
    applyFilters,
    recalibrateCounters,
    setSearchFilter,
    resetFilters,
    searchByCategory,
    toggleSelect,
    selectAll,
    clearSelection,
    setActiveRecord,
    exportSelected,

    // Actions: Import
    importTasks,
    activeTaskId,
    inputMode,
    importText,
    addImportTask,
    updateTaskStatus,
    removeTask,
    clearTasks,
    switchInputMode,
    setImportText,
    clearImportInput,

    initFromDatabase
  }
})
