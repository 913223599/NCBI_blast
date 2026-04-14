import { ref, shallowRef } from 'vue'
import type { 
  Freezer, 
  StrainRecord, 
  SearchFilters, 
  ImportTask 
} from './types'

export function useStrainState() {
  /* ======== 冰箱管理 ======== */
  const freezers = shallowRef<Freezer[]>([])
  const activeFreezerId = ref<string | null>(null)

  /* ======== 数据状态 ======== */
  const records = shallowRef<StrainRecord[]>([])
  
  // === 编码系统状态 ===
  const codeLookupEntries = ref<any[]>([]) 
  const sourceEntries = ref<any[]>([])      
  const serialCounters = ref<any[]>([])     
  const codeConfig = ref({
    assignMode: 'sequential',
    serialDigits: 4,
    version: '1.0.0'
  })
  const isInitialized = ref(false)
  const filteredRecords = shallowRef<StrainRecord[]>([])
  const searchFilters = ref<SearchFilters>({
    keyword: '',
    species: '',
    sequenceType: '',
    country: '',
    dateFrom: '',
    dateTo: '',
    minLength: null,
    maxLength: null,
    integrityOnly: false,
    sortKey: 'accession',
    sortOrder: null
  })

  /* ======== 导入状态 ======== */
  const files = ref<string[]>([]) // 待处理文件列表
  const importTasks = ref<ImportTask[]>([])
  const activeTaskId = ref<string | null>(null)
  const inputMode = ref<'file' | 'text' | 'ncbi'>('file')
  const importText = ref('')

  /* ======== 选择状态 ======== */
  const selectedRecords = ref<Set<string>>(new Set())
  const activeRecord = ref<StrainRecord | null>(null)
  const pendingBlastDraft = ref<any>(null)
  const locationMap = ref<Record<string, string>>({}) // ID -> Name 快速索引

  /* ======== 运行时标志 ======== */
  let isPerformingLocalUpdate = false
  let lastLocalUpdateTime = 0

  return {
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
    files,
    importTasks,
    activeTaskId,
    inputMode,
    importText,
    selectedRecords,
    activeRecord,
    pendingBlastDraft,
    locationMap,
    getIsUpdating: () => isPerformingLocalUpdate,
    getLastLocalUpdateTime: () => lastLocalUpdateTime,
    setIsUpdating: (val: boolean) => { 
      isPerformingLocalUpdate = val 
      if (val) lastLocalUpdateTime = Date.now()
    }
  }
}
