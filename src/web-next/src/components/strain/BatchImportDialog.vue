<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="batch-import-panel">
      <!-- 头部 -->
      <div class="import-header">
        <h3 class="title">📥 批量导入样本</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="import-body">
        <!-- 目标位置选择 -->
        <div class="form-section">
          <h4 class="section-label">选择目标冰箱</h4>
          <div class="select-box-neo" @click.stop="toggleDropdown('freezer')">
            {{ getFreezerLabel() }} <span class="arrow">▼</span>
            <div v-if="openDropdown === 'freezer'" class="dropdown-list">
              <div
                v-for="freezer in strain.freezers"
                :key="freezer.id"
                class="opt"
                :class="{ selected: targetFreezerId === freezer.id }"
                @click.stop="selectFreezer(freezer.id)"
              >
                {{ freezer.name }}
              </div>
            </div>
          </div>
        </div>

        <!-- 导入模式 -->
        <div class="form-section">
          <h4 class="section-label">导入模式</h4>
          <div class="mode-selector">
            <button
              class="mode-btn"
              :class="{ active: importMode === 'auto' }"
              @click="importMode = 'auto'"
            >
              <span class="mode-icon">🤖</span>
              <div class="mode-info">
                <div class="mode-name">自动分配位置</div>
                <div class="mode-desc">系统自动查找空余位置</div>
              </div>
            </button>
            <button
              class="mode-btn"
              :class="{ active: importMode === 'manual' }"
              @click="importMode = 'manual'"
            >
              <span class="mode-icon">📍</span>
              <div class="mode-info">
                <div class="mode-name">指定位置</div>
                <div class="mode-desc">手动选择具体位置</div>
              </div>
            </button>
          </div>
        </div>

        <!-- 手动选择位置（仅手动模式） -->
        <div v-if="importMode === 'manual' && targetFreezerId" class="form-section">
          <h4 class="section-label">选择目标位置</h4>
          <div class="location-selector">
            <div class="form-row">
              <div class="form-group">
                <label>层</label>
                <select v-model="selectedShelfId" class="text-input">
                  <option value="">选择层</option>
                  <option v-for="shelf in targetFreezer?.shelves" :key="shelf.id" :value="shelf.id">
                    {{ shelf.name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>柜</label>
                <select v-model="selectedCabinetId" class="text-input" :disabled="!selectedShelfId">
                  <option value="">选择柜</option>
                  <option v-for="cabinet in selectedShelf?.cabinets" :key="cabinet.id" :value="cabinet.id">
                    {{ cabinet.name }}
                  </option>
                </select>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>抽屉</label>
                <select v-model="selectedDrawerId" class="text-input" :disabled="!selectedCabinetId">
                  <option value="">选择抽屉</option>
                  <option v-for="drawer in selectedCabinet?.drawers" :key="drawer.id" :value="drawer.id">
                    {{ drawer.name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>冻存盒</label>
                <select v-model="selectedBoxId" class="text-input" :disabled="!selectedDrawerId">
                  <option value="">选择冻存盒</option>
                  <option v-for="box in selectedDrawer?.boxes" :key="box.id" :value="box.id">
                    {{ box.name }}
                  </option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div class="form-section">
          <div class="section-header-flex">
            <h4 class="section-label">输入样本数据</h4>
            <div class="template-selector">
              <span class="template-label">📥 下载模板:</span>
              <div class="template-btns">
                <button class="t-btn" @click="downloadTemplate('Bacteria')">微生物/细菌</button>
                <button class="t-btn" @click="downloadTemplate('Fungi')">真菌</button>
                <button class="t-btn" @click="downloadTemplate('Phage')">噬菌体</button>
                <button class="t-btn" @click="downloadTemplate('Virus')">病毒</button>
                <button class="t-btn" @click="downloadTemplate('Plasmid')">质粒/载体</button>
                <button class="t-btn" @click="downloadTemplate('CellLine')">细胞系</button>
                <button class="t-btn" @click="downloadTemplate('General')">通用</button>
              </div>
            </div>
          </div>

          <!-- 文件模式 -->
          <div class="file-upload-area">
            <input
              type="file"
              ref="fileInputRef"
              @change="handleFileUpload"
              accept=".xlsx,.csv,.json,.tsv"
              multiple
              style="display: none"
            />
            <div class="upload-dropzone" @click="fileInputRef?.click()">
              <div class="upload-icon"></div>
              <div class="upload-text">点击或拖拽文件到此处</div>
              <div class="upload-hint">支持 .xlsx, .csv, .json, .tsv 格式</div>
            </div>
            <div v-if="selectedFiles.length > 0" class="file-status-bar-group">
              <div v-for="(file, idx) in selectedFiles" :key="idx" class="file-status-bar">
                <div class="file-info">
                  <span class="file-icon">📄</span>
                  <span class="file-name-label">待导入:</span>
                  <span class="file-name">{{ file.name }}</span>
                </div>
                <button class="remove-btn" @click="removeFile(idx)" title="移除">✕</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 预览 -->
        <div v-if="parsedRecords.length > 0" class="form-section">
          <h4 class="section-label">预览 ({{ parsedRecords.length }} 条记录)</h4>
          <div class="preview-table">
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>Accession</th>
                  <th>物种</th>
                  <th>类型</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(record, index) in parsedRecords.slice(0, 5)" :key="index">
                  <td>{{ record.name }}</td>
                  <td class="mono">{{ record.accession || '-' }}</td>
                  <td>{{ record.species || '-' }}</td>
                  <td>
                    <span class="type-badge" :class="record.sequenceType?.toLowerCase()">
                      {{ record.sequenceType || 'DNA' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="parsedRecords.length > 5" class="more-records">
              + {{ parsedRecords.length - 5 }} 条更多记录
            </div>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="import-footer">
        <button class="btn-cancel" @click="emit('close')">取消</button>
        <button
          class="btn-confirm"
          @click="handleImport"
          :disabled="!canImport || importing"
        >
          {{ importing ? '导入中...' : `导入 ${parsedRecords.length} 条记录` }}
        </button>
      </div>
    </div>

    <!-- 智能分配回执对话框 -->
    <AllocationReceiptDialog
      v-model:show="showReceipt"
      :results="allocationResults"
      @confirm="handleConfirmPlacement"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import ExcelJS from 'exceljs'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { AllocationCoordinator } from '../../modules/BioSpatial-Coordinator'
import AllocationReceiptDialog from '../../modules/BioSpatial-Coordinator/ui/AllocationReceiptDialog.vue'
import { useCodeGenerator } from '../../composables/useCodeGenerator'
import { TopologyScanner } from '../../modules/BioSpatial-Coordinator/core/TopologyScanner'
import type { CategoryCode } from '../../types/codeSystem'

import { ImportTemplateManager } from '../../modules/BioSpatial-Coordinator/core/ImportTemplateManager'

const fileInputRef = ref<HTMLInputElement | null>(null)

const strain = useStrainStore()
const appStore = useAppStore()
const emit = defineEmits(['close', 'imported'])

const openDropdown = ref<string | null>(null)
const targetFreezerId = ref<string>('')
const importMode = ref<'auto' | 'manual'>('auto')
const dataInputMode = ref<'file'>('file')
const selectedFiles = ref<File[]>([])
const parsedRecords = ref<any[]>([])
const importing = ref(false)

const codeGen = useCodeGenerator()

const SAMPLE_TYPE_TO_CATEGORY: Record<string, string> = {
  '细菌': '1', 'Bacteria': '1', '病毒': '2', 'Virus': '2',
  '噬菌体': '3', 'Phage': '3', '真菌': '4', 'Fungi': '4', '质粒/载体': '5', 'Plasmid': '5', 'Vector': '5',
  '细胞': '6', 'CellLine': '6', '核酸': '7', '蛋白/抗体': '8', '样本/其他': '9', 'Other': '9'
}

// 手动位置选择
const selectedShelfId = ref('')
const selectedCabinetId = ref('')
const selectedDrawerId = ref('')
const selectedBoxId = ref('')

// 智能配位相关状态
const showReceipt = ref(false)
const allocationResults = ref<any[]>([])
const finalRecordsToImport = ref<any[]>([])

const targetFreezer = computed(() => 
  strain.freezers.find(f => f.id === targetFreezerId.value) || null
)

const selectedShelf = computed(() => {
  if (!targetFreezer.value) return null
  return targetFreezer.value.shelves.find(s => s.id === selectedShelfId.value) || null
})

const selectedCabinet = computed(() => {
  if (!selectedShelf.value) return null
  return selectedShelf.value.cabinets.find(c => c.id === selectedCabinetId.value) || null
})

const selectedDrawer = computed(() => {
  if (!selectedCabinet.value) return null
  return selectedCabinet.value.drawers.find(d => d.id === selectedDrawerId.value) || null
})

const canImport = computed(() => {
  if (!targetFreezerId.value || parsedRecords.value.length === 0) return false
  if (importMode.value === 'manual') {
    return !!(selectedShelfId.value && selectedCabinetId.value && selectedDrawerId.value && selectedBoxId.value)
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
  // 重置位置选择
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
    parseFiles(newFiles)
    input.value = ''
  }
}

function removeFile(index: number) {
  selectedFiles.value.splice(index, 1)
  if (selectedFiles.value.length === 0) {
    parsedRecords.value = []
  } else {
    // 重新解析所有剩余文件以更新预览 (全量重解析保证顺序和正确性)
    parsedRecords.value = []
    parseFiles(selectedFiles.value)
  }
}

async function parseFiles(files: File[]) {
  for (const file of files) {
    await parseFile(file)
  }
}

async function parseFile(file: File) {
  try {
    let records: any[] = []
    if (file.name.endsWith('.xlsx')) {
      records = await parseXLSX(file)
    } else if (file.name.endsWith('.json')) {
      const text = await file.text()
      records = JSON.parse(text)
    } else {
      const text = await file.text()
      const { records: csvRecords, detectedType } = parseCSV(text)
      records = csvRecords
      if (detectedType) {
        appStore.showNotification(`文件 [${file.name}] 检测到类型: ${detectedType}`, 'info')
      }
    }
    parsedRecords.value = [...parsedRecords.value, ...records]
    appStore.showNotification(`成功解析 [${file.name}] ${records.length} 条记录`, 'success')
  } catch (error) {
    appStore.showNotification(`文件 [${file.name}] 解析失败`, 'error')
    console.error(error)
  }
}

async function parseXLSX(file: File): Promise<any[]> {
  const workbook = new ExcelJS.Workbook()
  const arrayBuffer = await file.arrayBuffer()
  await workbook.xlsx.load(arrayBuffer)
  
  const worksheet = workbook.getWorksheet(1)
  if (!worksheet) return []

  const records: any[] = []
  const headers: string[] = []
  
  // 第一行作为表头
  const firstRow = worksheet.getRow(1)
  firstRow.eachCell((cell, colNumber) => {
    headers[colNumber] = cell.text.trim().toLowerCase()
  })

  // 处理数据行
  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) return // 跳过表头
    
    const record: any = {}
    row.eachCell((cell, colNumber) => {
      const header = headers[colNumber]
      if (header) {
        // Excel 中可能存在 RichText 或 其它复杂类型，统一取 text
        record[header] = cell.text.trim()
      }
    })
    
    if (Object.keys(record).length > 0) {
      records.push(record)
    }
  })

  return records
}

function parseCSV(text: string): { records: any[], detectedType: string | null } {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return { records: [], detectedType: null }
  
  const headers = lines[0]?.split(',').map(h => h.trim().toLowerCase()) || []
  const records: any[] = []

  // --- 智能表头指纹识别 ---
  let detectedType: string | null = null
  if (headers.includes('backbone') || headers.includes('vector')) detectedType = 'Plasmid'
  else if (headers.includes('titer') || headers.includes('potency')) detectedType = 'Virus'
  else if (headers.includes('resistance')) {
     if (headers.includes('culturecondition')) detectedType = 'Bacteria' // 默认微生物
  }
  else if (headers.includes('celltype')) detectedType = 'CellLine'
  else if (headers.includes('hoststrain') && !headers.includes('backbone')) detectedType = 'Phage'
  
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i]?.split(',').map(v => v.trim()) || []
    if (values.length === 0 || (values.length === 1 && values[0] === '')) continue
    const record: any = {}
    
    headers.forEach((header, index) => {
      if (header) record[header] = values[index] || ''
    })

    // 如果识别到了类型且数据中没有明确给，则自动补全
    if (detectedType && !record.sampletype) record.sampletype = detectedType
    
    records.push(record)
  }
  
  return { records, detectedType }
}


async function handleImport() {
  if (!canImport.value || importing.value) return
  
  importing.value = true
  
  // --- 安全阈值：防止 quantity 膨胀导致前端内存溢出 ---
  const MAX_QUANTITY_PER_ROW = 50
  const MAX_TOTAL_EXPANSION = 5000

  try {
    // 1. 系统化数据预处理 (编号申领 + 分类学对齐)
    const processedBatch: any[] = []
    
      for (let recordData of parsedRecords.value) {
        // 1.0 标准化键名 (解决大小写不匹配导致的导入数据丢失问题)
        const normalizedData: Record<string, any> = {}
        for (const [key, val] of Object.entries(recordData)) {
          normalizedData[key.toLowerCase().replace(/\s/g, '').replace(/_/g, '')] = val
        }
        
        // --- 关键改进：支持"备份数量"字段，并增加安全上限 ---
        const qtyRaw = normalizedData.quantity || normalizedData.count || normalizedData.备份数量 || normalizedData.数量 || '1';
        const quantity = Math.min(MAX_QUANTITY_PER_ROW, Math.max(1, parseInt(qtyRaw, 10) || 1));

        // 膨胀总量预检
        if (processedBatch.length + quantity > MAX_TOTAL_EXPANSION) {
          appStore.showNotification(
            `安全限制：总膨胀量已达 ${MAX_TOTAL_EXPANSION} 条上限，后续记录将被跳过。请分批导入。`,
            'warning'
          )
          break
        }

        const sampleType = (normalizedData.sampletype as any) || 'Other'
        const species = normalizedData.species || 'Unknown'
        const genusName = TopologyScanner.getGenus(species)
        const speciesName = species.replace(genusName, '').trim() || 'sp.'
        
        // 映射大类编码
        const categoryCode = (SAMPLE_TYPE_TO_CATEGORY[sampleType] || '9') as CategoryCode
        
        // 1. 精确解析或自动创建属 (BBB)
        let genusEntry = strain.codeLookupEntries.find(
          e => e.level === 2 && e.parentPath === categoryCode && e.name === genusName
        )
        if (!genusEntry) {
          genusEntry = codeGen.lookup.addLookupEntry(2, categoryCode, genusName, genusName) as any
        }
        
        // 2. 精确解析或自动创建种 (CCC)
        let speciesEntry = strain.codeLookupEntries.find(
          e => e.level === 3 && e.parentPath === genusEntry!.fullPath && e.name === speciesName
        )
        if (!speciesEntry) {
          speciesEntry = codeGen.lookup.addLookupEntry(3, genusEntry!.fullPath, speciesName, speciesName) as any
        }

        // 映射来源编码
        let sourceCode = 'XX'
        if (normalizedData.source) {
          const sourceEntry = (strain as any).sourceEntries.find((e: any) => e.name === normalizedData.source)
          if (sourceEntry) {
            sourceCode = sourceEntry.code
          } else {
            const rawCode = String(normalizedData.source).substring(0, 2).toUpperCase()
            if (/^[A-Z0-9]{2}$/.test(rawCode)) sourceCode = rawCode
          }
        }

        // --- 核心逻辑变更：同一行的备份共享同一个 Accession ---
        let finalAccession = normalizedData.accession || normalizedData.id
        let sampleCode = ''
        
        if (!finalAccession || finalAccession.length !== 14) {
          const request = {
            sourceCode: sourceCode,
            categoryCode: categoryCode,
            genusCode: genusEntry!.code,
            speciesCode: speciesEntry!.code,
            passage: parseInt(normalizedData.passagenumber || '0', 10) || 0
          }
          sampleCode = codeGen.commit(request)
          finalAccession = sampleCode 
        }

      // 将 metadata 构建提到 quantity 循环外，避免重复计算
      const metadata: Record<string, any> = {
        biosafetyLevel: normalizedData.biosafetylevel || '',
        passageNumber: normalizedData.passagenumber || '',
        batchNumber: normalizedData.batchnumber || '',
        storageDate: normalizedData.storagedate || '',
        storageMedium: normalizedData.storagemedium || '',
        description: normalizedData.description || ''
      }

      const specialFields: Record<string, string> = {
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
        authentication: 'authentication'
      }

      Object.entries(specialFields).forEach(([rawKey, camelKey]) => {
        if (normalizedData[rawKey] && normalizedData[rawKey] !== '-') {
          metadata[camelKey] = normalizedData[rawKey]
        }
      })

        for (let i = 0; i < quantity; i++) {
          processedBatch.push({
            name: normalizedData.name || 'Unknown',
            accession: finalAccession,
            sampleCode: sampleCode || finalAccession,
            species: species,
            strain: normalizedData.strain || '',
            sampleType: sampleType,
            sequenceType: (normalizedData.sequencetype || normalizedData.sequence_type || 'DNA') as 'DNA' | 'RNA' | 'Protein',
            sequence: normalizedData.sequence || '',
            source: normalizedData.source || '',
            host: normalizedData.host || '',
            country: normalizedData.country || '',
            collectionDate: normalizedData.collectiondate || '',
            metadata: { ...metadata },
            freezerId: targetFreezerId.value,
            codeSource: sourceCode,
            codeCategory: categoryCode,
            codeGenus: genusEntry!.code,
            codeSpecies: speciesEntry!.code,
            codeSerial: parseInt(finalAccession.slice(-4), 10)
          })
        }
      }

    if (importMode.value === 'auto') {
      // 2. 调用已强化的分拨引擎 (执行严格隔离规则)
      const currentFreezers = strain.freezers.filter(f => f.id === targetFreezerId.value)
      const results = AllocationCoordinator.processBatchAssignment(
        processedBatch, 
        { freezers: currentFreezers, records: strain.records }
      )

      allocationResults.value = results
      
      if (results.length === 0) {
        appStore.showNotification('未能在冰箱中找到符合“生物安全隔离”规则的空位（同属只能同种，大类禁止混装）', 'error')
        importing.value = false
        return
      }

      if (results.length < processedBatch.length) {
        appStore.showNotification(`受制于生物安全隔离规则，仅自动分配了 ${results.length}/${processedBatch.length} 条记录`, 'warning')
      }

      // 3. 构建最终入库对象
      finalRecordsToImport.value = results.map(res => ({
        ...res.record,
        boxId: res.allocatedBoxId,
        position: res.positionLabel,
        shelfId: '', 
        cabinetId: '',
        drawerId: ''
      }))

      showReceipt.value = true
    } else {
      // 手动模式：使用已预处理（包含系统编号）的记录
      const recordsToImport: any[] = []
      for (const recordData of processedBatch) {
        recordsToImport.push({
          ...recordData,
          shelfId: selectedShelfId.value,
          cabinetId: selectedCabinetId.value,
          drawerId: selectedDrawerId.value,
          boxId: selectedBoxId.value,
          position: ''
        })
      }
      saveToStore(recordsToImport)
    }
  } catch (error) {
    appStore.showNotification('配位计算失败: ' + error, 'error')
    console.error(error)
  } finally {
    importing.value = false
  }
}

function handleConfirmPlacement() {
  saveToStore(finalRecordsToImport.value)
}

async function downloadTemplate(type: string = 'General') {
  try {
    // 每次下载前从数据库刷新最新的来源列表
    await (strain as any).initFromDatabase()
  } catch (err) {
    console.warn('同步来源词典失败', err)
  }

  const sources = (strain as any).sourceEntries?.map((e: any) => e.name) || []
  
  // 使用模块化管理类生成 Excel
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

async function saveToStore(records: any[]) {
  if (records.length === 0) return
  
  importing.value = true // 使用已有的 importing 状态作为 UI 锁
  try {
    console.log(`[Import] 开始链式入库事务... 总计 ${records.length} 条`)
    
    // 1. 保存样本记录 (内部会开启 setIsUpdating 护盾)
    const success = await strain.addRecords(records)
    
    if (success) {
      console.log('[Import] 样本保存成功，同步刷新拓扑映射...')
      // 2. 刷新物理拓扑 (shouldSave=true)，此过程会继续持有护盾
      strain.refreshFreezerOccupancy(true)
      
      // 3. 补偿计数器校准
      strain.recalibrateCounters()
      
      appStore.showNotification(`成功导入 ${records.length} 条样本并校准拓扑`, 'success')
      emit('imported', records.length)
      emit('close')
    } else {
      appStore.showNotification('部分样本保存失败，请检查数据库连接', 'error')
    }
  } catch (error) {
    console.error('[Import Transaction Error]', error)
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
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.batch-import-panel {
  background: white;
  border-radius: 12px;
  width: 700px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.import-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.title {
  font-size: 1.1rem;
  font-weight: 800;
  color: #0f172a;
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
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.import-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.form-section {
  margin-bottom: 24px;
}

.section-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.download-link {
  font-size: 0.8rem;
  color: #2563eb;
  text-decoration: none;
  font-weight: 600;
  transition: color 0.2s;
}

.download-link:hover {
  color: #1d4ed8;
  text-decoration: underline;
}

/* 模板选择器样式 */
.template-selector {
  display: flex;
  align-items: center;
  gap: 12px;
}

.template-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.template-btns {
  display: flex;
  gap: 6px;
}

.t-btn {
  padding: 4px 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.t-btn:hover {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
  transform: translateY(-1px);
}

/* 导入模式选择 */
.mode-selector {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
}

.mode-btn:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.mode-btn.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.mode-icon {
  font-size: 2rem;
}

.mode-info {
  flex: 1;
  text-align: left;
}

.mode-name {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 2px;
}

.mode-desc {
  font-size: 0.75rem;
  color: #64748b;
}

/* 位置选择 */
.location-selector {
  background: #f8fafc;
  border-radius: 10px;
  padding: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.form-row:last-child {
  margin-bottom: 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.text-input {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.85rem;
  background: white;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
}

.text-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 输入模式标签 */
.input-mode-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.tab-btn {
  padding: 8px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 600;
  color: #64748b;
}

.tab-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

/* 粘贴区域 */
.paste-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-textarea {
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.85rem;
  resize: vertical;
  min-height: 200px;
}

.data-textarea:focus {
  outline: none;
  border-color: #2563eb;
}

.format-hint {
  font-size: 0.75rem;
  color: #94a3b8;
}

/* 文件上传 */
.file-upload-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.upload-dropzone {
  border: 2px dashed #e2e8f0;
  border-radius: 10px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  background: #f8fafc;
}

.upload-dropzone:hover {
  border-color: #2563eb;
  background: #eff6ff;
}

.upload-icon {
  font-size: 3rem;
  margin-bottom: 8px;
}

.upload-icon::before {
  content: '📁';
}

.upload-text {
  font-size: 0.9rem;
  color: #475569;
  margin-bottom: 4px;
  font-weight: 600;
}

.upload-hint {
  font-size: 0.75rem;
  color: #94a3b8;
}

.file-status-bar-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}

.file-status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-left: 4px solid #3b82f6;
  border-radius: 8px;
  transition: all 0.2s;
}

.file-status-bar:hover {
  background: #dbeafe;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.file-icon { font-size: 1.2rem; }

.file-name-label {
  font-size: 0.8rem;
  color: #64748b;
  white-space: nowrap;
}

.file-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remove-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 1.2rem;
  padding: 0 4px;
  transition: color 0.2s;
}

.remove-btn:hover {
  color: #ef4444;
}

/* 预览表格 */
.preview-table {
  background: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

.preview-table table {
  width: 100%;
  border-collapse: collapse;
}

.preview-table th,
.preview-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

.preview-table th {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  background: #f1f5f9;
}

.preview-table td {
  font-size: 0.85rem;
  color: #475569;
}

.preview-table .mono {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.8rem;
}

.type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
}

.type-badge.dna {
  background: #dbeafe;
  color: #1e40af;
}

.type-badge.rna {
  background: #fce7f3;
  color: #be185d;
}

.type-badge.protein {
  background: #fef3c7;
  color: #92400e;
}

.more-records {
  padding: 10px;
  text-align: center;
  font-size: 0.8rem;
  color: #64748b;
  font-weight: 600;
  background: white;
}

/* 底部按钮 */
.import-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.btn-cancel,
.btn-confirm {
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-cancel {
  border: 1px solid #e2e8f0;
  color: #64748b;
  background: white;
}

.btn-cancel:hover {
  background: #f1f5f9;
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
  transform: none;
}

/* 选择冰箱下拉框扩展 */
.select-box-neo {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 0.85rem;
  cursor: pointer;
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.select-box-neo:hover {
  border-color: #cbd5e1;
}

.dropdown-list {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  z-index: 100;
  max-height: 200px;
  overflow-y: auto;
  padding: 4px;
}

.opt {
  padding: 8px 12px;
  font-size: 0.85rem;
  border-radius: 6px;
  color: #475569;
}

.opt:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.opt.selected {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 700;
}
</style>