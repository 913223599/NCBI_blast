/**
 * 批量样本导入逻辑组合式函数
 * 负责 Excel/CSV/JSON 文件解析、智能编号申领、生物安全分区预分配及入库事务。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import ExcelJS from 'exceljs'
import { createLogger } from '../../utils/logger'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { SampleCategory, StrainRecord } from '../../stores/strain/types'
import { AllocationCoordinator } from '../../modules/BioSpatial-Coordinator'
import type { AllocationResult } from '../../modules/BioSpatial-Coordinator/strategies/SpeciesZoningStrategy'
import { useCodeGenerator } from '../../composables/useCodeGenerator'
import { TopologyScanner } from '../../modules/BioSpatial-Coordinator/core/TopologyScanner'
import type { CategoryCode, CodeLookupEntry } from '../../types/codeSystem'
import { ImportTemplateManager } from '../../modules/BioSpatial-Coordinator/core/ImportTemplateManager'

const _log = createLogger('BatchImport')

export type RawImportRow = Record<string, string>
export type ImportDraftRecord = Omit<StrainRecord, 'id' | 'addedAt'>

const SAMPLE_TYPE_TO_CATEGORY: Record<string, CategoryCode> = {
  '细菌': '1',
  Bacteria: '1',
  '病毒': '2',
  Virus: '2',
  '噬菌体': '3',
  Phage: '3',
  '真菌': '4',
  Fungi: '4',
  '质粒/载体': '5',
  Plasmid: '5',
  Vector: '5',
  '细胞': '6',
  CellLine: '6',
  '核酸': '7',
  '蛋白/抗体': '8',
  '样本/其他': '9',
  Other: '9',
}

const SPECIAL_METADATA_FIELDS: Record<string, string> = {
  resistance: 'resistance',
  concentration: 'concentration',
  culturecondition: 'cultureCondition',
  growthtemp: 'growthTemp',
  backbone: 'backbone',
  insertname: 'insertName',
  hoststrain: 'hostStrain',
  marker: 'marker',
  isexpression: 'isExpression',
  titer: 'titer',
  potency: 'potency',
  serotype: 'serotype',
  inactivationmethod: 'inactivationMethod',
  celltype: 'cellType',
  medium: 'medium',
  authentication: 'authentication',
}

const MAX_QUANTITY_PER_ROW = 50
const MAX_TOTAL_EXPANSION = 5000

async function parseXLSXFile(file: File): Promise<RawImportRow[]> {
  const workbook = new ExcelJS.Workbook()
  const arrayBuffer = await file.arrayBuffer()
  await workbook.xlsx.load(arrayBuffer)

  const worksheet = workbook.getWorksheet(1)
  if (!worksheet) return []

  const records: RawImportRow[] = []
  const headers: string[] = []

  const firstRow = worksheet.getRow(1)
  firstRow.eachCell((cell, colNumber) => {
    headers[colNumber] = cell.text.trim().toLowerCase()
  })

  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) return

    const record: RawImportRow = {}
    row.eachCell((cell, colNumber) => {
      const header = headers[colNumber]
      if (header) {
        record[header] = cell.text.trim()
      }
    })

    if (Object.keys(record).length > 0) {
      records.push(record)
    }
  })

  return records
}

function parseCSVContent(text: string): { records: RawImportRow[]; detectedType: string | null } {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return { records: [], detectedType: null }

  const headers = lines[0]?.split(',').map((h) => h.trim().toLowerCase()) || []
  const records: RawImportRow[] = []

  let detectedType: string | null = null
  if (headers.includes('backbone') || headers.includes('vector')) detectedType = 'Plasmid'
  else if (headers.includes('titer') || headers.includes('potency')) detectedType = 'Virus'
  else if (headers.includes('resistance')) {
    if (headers.includes('culturecondition')) detectedType = 'Bacteria'
  } else if (headers.includes('celltype')) detectedType = 'CellLine'
  else if (headers.includes('hoststrain') && !headers.includes('backbone')) detectedType = 'Phage'

  for (let i = 1; i < lines.length; i++) {
    const values = lines[i]?.split(',').map((v) => v.trim()) || []
    if (values.length === 0 || (values.length === 1 && values[0] === '')) continue
    const record: RawImportRow = {}

    headers.forEach((header, index) => {
      if (header) record[header] = values[index] || ''
    })

    if (detectedType && !record.sampletype) record.sampletype = detectedType
    records.push(record)
  }

  return { records, detectedType }
}

export function useBatchImport(emit: {
  (e: 'close'): void
  (e: 'imported', count: number): void
}) {
  const fileInputRef = ref<HTMLInputElement | null>(null)
  const strain = useStrainStore()
  const appStore = useAppStore()
  const codeGen = useCodeGenerator()

  const openDropdown = ref<string | null>(null)
  const targetFreezerId = ref<string>('')
  const importMode = ref<'auto' | 'manual'>('auto')
  const selectedFiles = ref<File[]>([])
  const parsedRecords = ref<RawImportRow[]>([])
  const importing = ref(false)

  // 手动位置选择
  const selectedShelfId = ref('')
  const selectedCabinetId = ref('')
  const selectedDrawerId = ref('')
  const selectedBoxId = ref('')

  // 智能配位相关状态
  const showReceipt = ref(false)
  const allocationResults = ref<AllocationResult[]>([])
  const finalRecordsToImport = ref<ImportDraftRecord[]>([])

  const targetFreezer = computed(
    () => strain.freezers.find((f) => f.id === targetFreezerId.value) || null
  )

  const selectedShelf = computed(() => {
    if (!targetFreezer.value) return null
    return targetFreezer.value.shelves.find((s) => s.id === selectedShelfId.value) || null
  })

  const selectedCabinet = computed(() => {
    if (!selectedShelf.value) return null
    return selectedShelf.value.cabinets.find((c) => c.id === selectedCabinetId.value) || null
  })

  const selectedDrawer = computed(() => {
    if (!selectedCabinet.value) return null
    return selectedCabinet.value.drawers.find((d) => d.id === selectedDrawerId.value) || null
  })

  const canImport = computed(() => {
    if (!targetFreezerId.value || parsedRecords.value.length === 0) return false
    if (importMode.value === 'manual') {
      return Boolean(
        selectedShelfId.value &&
          selectedCabinetId.value &&
          selectedDrawerId.value &&
          selectedBoxId.value
      )
    }
    return true
  })

  function getFreezerLabel(): string {
    if (!targetFreezerId.value) return '选择冰箱'
    return targetFreezer.value?.name || '选择冰箱'
  }

  function toggleDropdown(name: string) {
    openDropdown.value = openDropdown.value === name ? null : name
  }

  function selectFreezer(id: string) {
    targetFreezerId.value = id
    openDropdown.value = null
    selectedShelfId.value = ''
    selectedCabinetId.value = ''
    selectedDrawerId.value = ''
    selectedBoxId.value = ''
  }

  function handleFileUpload(event: Event) {
    const input = event.target as HTMLInputElement
    if (input.files && input.files.length > 0) {
      const newFiles = Array.from(input.files)
      selectedFiles.value = [...selectedFiles.value, ...newFiles]
      void parseFiles(newFiles)
      input.value = ''
    }
  }

  function removeFile(index: number) {
    selectedFiles.value.splice(index, 1)
    parsedRecords.value = []
    if (selectedFiles.value.length > 0) {
      void parseFiles(selectedFiles.value)
    }
  }

  async function parseFiles(files: File[]) {
    for (const file of files) {
      await parseFile(file)
    }
  }

  async function parseFile(file: File) {
    try {
      let records: RawImportRow[] = []
      if (file.name.endsWith('.xlsx')) {
        records = await parseXLSXFile(file)
      } else if (file.name.endsWith('.json')) {
        const text = await file.text()
        const raw = JSON.parse(text) as unknown
        records = Array.isArray(raw) ? (raw as RawImportRow[]) : []
      } else {
        const text = await file.text()
        const { records: csvRecords, detectedType } = parseCSVContent(text)
        records = csvRecords
        if (detectedType) {
          appStore.showNotification(`文件 [${file.name}] 检测到类型: ${detectedType}`, 'info')
        }
      }
      parsedRecords.value = [...parsedRecords.value, ...records]
      appStore.showNotification(`成功解析 [${file.name}] ${records.length} 条记录`, 'success')
    } catch (error) {
      appStore.showNotification(`文件 [${file.name}] 解析失败`, 'error')
      _log.error(`文件 [${file.name}] 解析失败`, error)
    }
  }

  function buildProcessedBatch(): ImportDraftRecord[] {
    const processedBatch: ImportDraftRecord[] = []

    for (const recordData of parsedRecords.value) {
      const normalizedData: Record<string, string> = {}
      for (const [key, val] of Object.entries(recordData)) {
        normalizedData[key.toLowerCase().replace(/\s/g, '').replace(/_/g, '')] = String(val ?? '')
      }

      const qtyRaw =
        normalizedData.quantity ||
        normalizedData.count ||
        normalizedData['备份数量'] ||
        normalizedData['数量'] ||
        '1'
      const quantity = Math.min(MAX_QUANTITY_PER_ROW, Math.max(1, parseInt(qtyRaw, 10) || 1))

      if (processedBatch.length + quantity > MAX_TOTAL_EXPANSION) {
        appStore.showNotification(
          `安全限制：总膨胀量已达 ${MAX_TOTAL_EXPANSION} 条上限，后续记录将被跳过。请分批导入。`,
          'warning'
        )
        break
      }

      const rawType = normalizedData.sampletype || 'Other'
      const sampleType = rawType as SampleCategory
      const species = normalizedData.species || 'Unknown'
      const genusName = TopologyScanner.getGenus(species)
      const speciesName = species.replace(genusName, '').trim() || 'sp.'
      const categoryCode: CategoryCode = SAMPLE_TYPE_TO_CATEGORY[rawType] || '9'

      let genusEntry: CodeLookupEntry | null | undefined = strain.codeLookupEntries.find(
        (e) => e.level === 2 && e.parentPath === categoryCode && e.name === genusName
      )
      if (!genusEntry) {
        genusEntry = codeGen.lookup.addLookupEntry(2, categoryCode, genusName, genusName)
      }
      if (!genusEntry) {
        _log.warn(`无法创建属级编码目录: ${genusName}`)
        continue
      }

      let speciesEntry: CodeLookupEntry | null | undefined = strain.codeLookupEntries.find(
        (e) => e.level === 3 && e.parentPath === genusEntry.fullPath && e.name === speciesName
      )
      if (!speciesEntry) {
        speciesEntry = codeGen.lookup.addLookupEntry(3, genusEntry.fullPath, speciesName, speciesName)
      }
      if (!speciesEntry) {
        _log.warn(`无法创建种级编码目录: ${speciesName}`)
        continue
      }

      let sourceCode = 'XX'
      if (normalizedData.source) {
        const sourceEntry = strain.sourceEntries.find((e) => e.name === normalizedData.source)
        if (sourceEntry) {
          sourceCode = sourceEntry.code
        } else {
          const rawCode = normalizedData.source.substring(0, 2).toUpperCase()
          if (/^[A-Z0-9]{2}$/.test(rawCode)) sourceCode = rawCode
        }
      }

      let finalAccession = normalizedData.accession || normalizedData.id || ''
      let sampleCode = ''

      if (!finalAccession || finalAccession.length !== 14) {
        sampleCode = codeGen.commit({
          sourceCode,
          categoryCode,
          genusCode: genusEntry.code,
          speciesCode: speciesEntry.code,
          passage: parseInt(normalizedData.passagenumber || '0', 10) || 0,
        })
        finalAccession = sampleCode
      }

      const metadata: Record<string, string> = {
        biosafetyLevel: normalizedData.biosafetylevel || '',
        passageNumber: normalizedData.passagenumber || '',
        batchNumber: normalizedData.batchnumber || '',
        storageDate: normalizedData.storagedate || '',
        storageMedium: normalizedData.storagemedium || '',
        description: normalizedData.description || '',
      }

      Object.entries(SPECIAL_METADATA_FIELDS).forEach(([rawKey, camelKey]) => {
        const fieldVal = normalizedData[rawKey]
        if (fieldVal && fieldVal !== '-') {
          metadata[camelKey] = fieldVal
        }
      })

      const seqTypeRaw = normalizedData.sequencetype || normalizedData.sequence_type || 'DNA'
      const sequenceType: 'DNA' | 'RNA' | 'Protein' =
        seqTypeRaw === 'RNA' || seqTypeRaw === 'Protein' ? seqTypeRaw : 'DNA'

      for (let i = 0; i < quantity; i++) {
        processedBatch.push({
          name: normalizedData.name || 'Unknown',
          accession: finalAccession,
          sampleCode: sampleCode || finalAccession,
          species,
          strain: normalizedData.strain || '',
          sampleType,
          sequenceType,
          sequence: normalizedData.sequence || '',
          source: normalizedData.source || '',
          host: normalizedData.host || '',
          country: normalizedData.country || '',
          collectionDate: normalizedData.collectiondate || '',
          metadata: { ...metadata },
          freezerId: targetFreezerId.value,
          codeSource: sourceCode,
          codeCategory: categoryCode,
          codeGenus: genusEntry.code,
          codeSpecies: speciesEntry.code,
          codeSerial: parseInt(finalAccession.slice(-4), 10),
        })
      }
    }

    return processedBatch
  }

  async function handleImport() {
    if (!canImport.value || importing.value) return
    importing.value = true

    try {
      const processedBatch = buildProcessedBatch()

      if (importMode.value === 'auto') {
        const currentFreezers = strain.freezers.filter((f) => f.id === targetFreezerId.value)
        const results = AllocationCoordinator.processBatchAssignment(processedBatch, {
          freezers: currentFreezers,
          records: strain.records,
        })

        allocationResults.value = results

        if (results.length === 0) {
          appStore.showNotification(
            '未能在冰箱中找到符合“生物安全隔离”规则的空位（同属只能同种，大类禁止混装）',
            'error'
          )
          return
        }

        if (results.length < processedBatch.length) {
          appStore.showNotification(
            `受制于生物安全隔离规则，仅自动分配了 ${results.length}/${processedBatch.length} 条记录`,
            'warning'
          )
        }

        finalRecordsToImport.value = results.map((res) => ({
          ...(res.record as ImportDraftRecord),
          boxId: res.allocatedBoxId,
          position: res.positionLabel,
          shelfId: '',
          cabinetId: '',
          drawerId: '',
        }))

        showReceipt.value = true
      } else {
        const recordsToImport: ImportDraftRecord[] = processedBatch.map((recordData) => ({
          ...recordData,
          shelfId: selectedShelfId.value,
          cabinetId: selectedCabinetId.value,
          drawerId: selectedDrawerId.value,
          boxId: selectedBoxId.value,
          position: '',
        }))
        await saveToStore(recordsToImport)
      }
    } catch (error) {
      appStore.showNotification('配位计算失败: ' + String(error), 'error')
      _log.error('配位计算失败', error)
    } finally {
      importing.value = false
    }
  }

  function handleConfirmPlacement() {
    void saveToStore(finalRecordsToImport.value)
  }

  async function downloadTemplate(type: string = 'General') {
    try {
      await strain.initFromDatabase()
    } catch (err) {
      _log.warn('同步来源词典失败', err)
    }

    const sources = strain.sourceEntries.map((e) => e.name)
    const { blob, fileName } = await ImportTemplateManager.generateXLSX(type, sources)

    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', fileName)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  async function saveToStore(records: ImportDraftRecord[]) {
    if (records.length === 0) return

    importing.value = true
    try {
      _log.debug(`[Import] 开始链式入库事务... 总计 ${records.length} 条`)
      const success = await strain.addRecords(records)

      if (success) {
        _log.debug('[Import] 样本保存成功，同步刷新拓扑映射...')
        strain.refreshFreezerOccupancy(true)
        strain.recalibrateCounters()

        appStore.showNotification(`成功导入 ${records.length} 条样本并校准拓扑`, 'success')
        emit('imported', records.length)
        emit('close')
      } else {
        appStore.showNotification('部分样本保存失败，请检查数据库连接', 'error')
      }
    } catch (error) {
      _log.error('[Import Transaction Error]', error)
      appStore.showNotification('事务提交过程中发生异常', 'error')
    } finally {
      importing.value = false
    }
  }

  function handleClickOutside() {
    openDropdown.value = null
  }

  onMounted(() => {
    document.addEventListener('click', handleClickOutside)
  })

  onUnmounted(() => {
    document.removeEventListener('click', handleClickOutside)
  })

  return {
    fileInputRef,
    strain,
    openDropdown,
    targetFreezerId,
    importMode,
    selectedFiles,
    parsedRecords,
    importing,
    selectedShelfId,
    selectedCabinetId,
    selectedDrawerId,
    selectedBoxId,
    showReceipt,
    allocationResults,
    targetFreezer,
    selectedShelf,
    selectedCabinet,
    selectedDrawer,
    canImport,
    getFreezerLabel,
    toggleDropdown,
    selectFreezer,
    handleFileUpload,
    removeFile,
    handleImport,
    handleConfirmPlacement,
    downloadTemplate,
  }
}
