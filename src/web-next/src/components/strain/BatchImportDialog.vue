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

        <!-- 数据输入 -->
        <div class="form-section">
          <h4 class="section-label">输入样本数据</h4>
          <div class="input-mode-tabs">
            <button
              class="tab-btn"
              :class="{ active: dataInputMode === 'paste' }"
              @click="dataInputMode = 'paste'"
            >
              📋 粘贴数据
            </button>
            <button
              class="tab-btn"
              :class="{ active: dataInputMode === 'file' }"
              @click="dataInputMode = 'file'"
            >
              📁 上传文件
            </button>
          </div>

          <!-- 粘贴模式 -->
          <div v-if="dataInputMode === 'paste'" class="paste-area">
            <textarea
              v-model="pasteData"
              class="data-textarea"
              placeholder="粘贴CSV或JSON格式数据...&#10;&#10;CSV示例：&#10;name,accession,species,sequence_type&#10;Sample1,NC_000001,Escherichia coli,DNA&#10;&#10;JSON示例：&#10;[{&quot;name&quot;:&quot;Sample1&quot;,&quot;accession&quot;:&quot;NC_000001&quot;,&quot;species&quot;:&quot;Escherichia coli&quot;,&quot;sequenceType&quot;:&quot;DNA&quot;}]"
              rows="12"
            ></textarea>
            <div class="format-hint">
              支持 CSV 和 JSON 格式。CSV需要包含表头，字段包括：name, accession, species, strain, sequenceType, source, host, country, collectionDate
            </div>
          </div>

          <!-- 文件模式 -->
          <div v-if="dataInputMode === 'file'" class="file-upload-area">
            <input
              type="file"
              ref="fileInput"
              @change="handleFileUpload"
              accept=".csv,.json,.tsv"
              style="display: none"
            />
            <div class="upload-dropzone" @click="fileInput?.click()">
              <div class="upload-icon"></div>
              <div class="upload-text">点击或拖拽文件到此处</div>
              <div class="upload-hint">支持 .csv, .json, .tsv 格式</div>
            </div>
            <div v-if="selectedFile" class="file-info">
              <span class="file-name"></span>
              <button class="remove-file-btn" @click="removeFile">✕</button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

const fileInput = ref<HTMLInputElement | null>(null)

const strain = useStrainStore()
const appStore = useAppStore()
const emit = defineEmits(['close', 'imported'])

const openDropdown = ref<string | null>(null)
const targetFreezerId = ref<string>('')
const importMode = ref<'auto' | 'manual'>('auto')
const dataInputMode = ref<'paste' | 'file'>('paste')
const pasteData = ref('')
const selectedFile = ref<File | null>(null)
const parsedRecords = ref<any[]>([])
const importing = ref(false)

// 手动位置选择
const selectedShelfId = ref('')
const selectedCabinetId = ref('')
const selectedDrawerId = ref('')
const selectedBoxId = ref('')

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
  if (input.files && input.files[0]) {
    selectedFile.value = input.files[0]
    parseFile(selectedFile.value)
  }
}

function removeFile() {
  selectedFile.value = null
  parsedRecords.value = []
}

async function parseFile(file: File) {
  try {
    const text = await file.text()
    if (file.name.endsWith('.json')) {
      parsedRecords.value = JSON.parse(text)
    } else {
      parsedRecords.value = parseCSV(text)
    }
    appStore.showNotification(`成功解析 ${parsedRecords.value.length} 条记录`, 'success')
  } catch (error) {
    appStore.showNotification('文件解析失败，请检查格式', 'error')
    console.error(error)
  }
}

function parseCSV(text: string): any[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  
  const headers = lines[0]?.split(',').map(h => h.trim()) || []
  const records = []
  
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i]?.split(',').map(v => v.trim()) || []
    if (values.length < headers.length) continue
    const record: any = {}
    headers.forEach((header, index) => {
      record[header] = values[index] || ''
    })
    records.push(record)
  }
  
  return records
}

// 监听粘贴数据变化
watch(pasteData, (newValue) => {
  if (!newValue.trim()) {
    parsedRecords.value = []
    return
  }
  
  try {
    if (newValue.trim().startsWith('[')) {
      parsedRecords.value = JSON.parse(newValue)
    } else {
      parsedRecords.value = parseCSV(newValue)
    }
  } catch {
    parsedRecords.value = []
  }
})

async function handleImport() {
  if (!canImport.value || importing.value) return
  
  importing.value = true
  
  try {
    const recordsToImport = []
    
    for (const recordData of parsedRecords.value) {
      const record = {
        name: recordData.name || 'Unknown',
        accession: recordData.accession || '',
        species: recordData.species || '',
        strain: recordData.strain || '',
        sampleType: (recordData.sampleType as any) || 'Other',
        sequenceType: (recordData.sequenceType || recordData.sequence_type || 'DNA') as 'DNA' | 'RNA' | 'Protein',
        sequence: recordData.sequence || '',
        source: recordData.source || '',
        host: recordData.host || '',
        country: recordData.country || '',
        collectionDate: recordData.collectionDate || '',
        metadata: {},
        freezerId: targetFreezerId.value,
        shelfId: importMode.value === 'manual' ? selectedShelfId.value : '',
        cabinetId: importMode.value === 'manual' ? selectedCabinetId.value : '',
        drawerId: importMode.value === 'manual' ? selectedDrawerId.value : '',
        boxId: importMode.value === 'manual' ? selectedBoxId.value : '',
        position: ''
      }
      
      // 自动模式下查找空闲位置 (改进逻辑：排除已选中的位置)
      if (importMode.value === 'auto') {
        const position = findFreePosition(recordsToImport.map(r => r.boxId + '_' + r.position))
        if (!position) {
          appStore.showNotification('存储空间不足', 'warning')
          break
        }
        record.shelfId = position.shelfId
        record.cabinetId = position.cabinetId
        record.drawerId = position.drawerId
        record.boxId = position.boxId
        record.position = position.position
      }
      
      recordsToImport.push(record)
    }
    
    if (recordsToImport.length > 0) {
      strain.addRecords(recordsToImport)
      appStore.showNotification(`成功导入 ${recordsToImport.length} 条样本`, 'success')
      emit('imported', recordsToImport.length)
      emit('close')
    }
  } catch (error) {
    appStore.showNotification('导入失败: ' + error, 'error')
    console.error(error)
  } finally {
    importing.value = false
  }
}

function findFreePosition(excludeIds: string[] = []): { shelfId: string; cabinetId: string; drawerId: string; boxId: string; position: string } | null {
  if (!targetFreezer.value) return null
  
  for (const shelf of targetFreezer.value.shelves) {
    for (const cabinet of shelf.cabinets) {
      for (const drawer of cabinet.drawers) {
        for (const box of drawer.boxes) {
          for (const pos of box.positions) {
            const posId = box.id + '_' + pos.label
            if (!pos.occupied && !excludeIds.includes(posId)) {
              return {
                shelfId: shelf.id,
                cabinetId: cabinet.id,
                drawerId: drawer.id,
                boxId: box.id,
                position: pos.label
              }
            }
          }
        }
      }
    }
  }
  return null
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

.section-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 12px 0;
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

.file-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: #eff6ff;
  border-radius: 8px;
  border: 1px solid #bfdbfe;
}

.file-name::before {
  content: '📄 ';
}

.remove-file-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 1rem;
}

.remove-file-btn:hover {
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