<template>
  <div class="wb-dialog-overlay" @click.self="emit('close')">
    <div class="wb-dialog-content batch-import-panel">
      <!-- 头部 -->
      <div class="wb-dialog-header">
        <h3 class="title">批量导入样本</h3>
        <button type="button" class="close-btn" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div class="wb-dialog-body import-body">
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
              type="button"
              class="mode-btn"
              :class="{ active: importMode === 'auto' }"
              @click="importMode = 'auto'"
            >
              <span class="mode-icon"></span>
              <div class="mode-info">
                <div class="mode-name">自动分配位置</div>
                <div class="mode-desc">系统自动查找空余位置</div>
              </div>
            </button>
            <button
              type="button"
              class="mode-btn"
              :class="{ active: importMode === 'manual' }"
              @click="importMode = 'manual'"
            >
              <span class="mode-icon">定位</span>
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
          <div class="wb-surface-muted location-selector">
            <div class="form-row">
              <div class="form-group">
                <label>层</label>
                <select v-model="selectedShelfId" class="wb-select text-input">
                  <option value="">选择层</option>
                  <option v-for="shelf in targetFreezer?.shelves" :key="shelf.id" :value="shelf.id">
                    {{ shelf.name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>柜</label>
                <select v-model="selectedCabinetId" class="wb-select text-input" :disabled="!selectedShelfId">
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
                <select v-model="selectedDrawerId" class="wb-select text-input" :disabled="!selectedCabinetId">
                  <option value="">选择抽屉</option>
                  <option v-for="drawer in selectedCabinet?.drawers" :key="drawer.id" :value="drawer.id">
                    {{ drawer.name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>冻存盒</label>
                <select v-model="selectedBoxId" class="wb-select text-input" :disabled="!selectedDrawerId">
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
              <span class="template-label">下载模板:</span>
              <div class="template-btns">
                <button type="button" class="t-btn" @click="downloadTemplate('Bacteria')">微生物/细菌</button>
                <button type="button" class="t-btn" @click="downloadTemplate('Fungi')">真菌</button>
                <button type="button" class="t-btn" @click="downloadTemplate('Phage')">噬菌体</button>
                <button type="button" class="t-btn" @click="downloadTemplate('Virus')">病毒</button>
                <button type="button" class="t-btn" @click="downloadTemplate('Plasmid')">质粒/载体</button>
                <button type="button" class="t-btn" @click="downloadTemplate('CellLine')">细胞系</button>
                <button type="button" class="t-btn" @click="downloadTemplate('General')">通用</button>
              </div>
            </div>
          </div>

          <!-- 文件模式 -->
          <div class="file-upload-area">
            <input
              ref="fileInputRef"
              type="file"
              accept=".xlsx,.csv,.json,.tsv"
              multiple
              style="display: none"
              @change="handleFileUpload"
            />
            <div class="wb-drop-zone upload-dropzone" @click="fileInputRef?.click()">
              <div class="upload-text">点击或拖拽文件到此处</div>
              <div class="upload-hint">支持 .xlsx, .csv, .json, .tsv 格式</div>
            </div>
            <div v-if="selectedFiles.length > 0" class="file-status-bar-group">
              <div v-for="(file, idx) in selectedFiles" :key="idx" class="file-status-bar">
                <div class="file-info">
                  <span class="file-name-label">待导入:</span>
                  <span class="file-name">{{ file.name }}</span>
                </div>
                <button type="button" class="remove-btn" title="移除" @click="removeFile(idx)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
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
      <div class="wb-dialog-footer">
        <button type="button" class="wb-btn-outline btn-cancel" @click="emit('close')">取消</button>
        <button
          type="button"
          class="wb-btn-primary btn-confirm"
          :disabled="!canImport || importing"
          @click="handleImport"
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
import AllocationReceiptDialog from '../../modules/BioSpatial-Coordinator/ui/AllocationReceiptDialog.vue'
import { useBatchImport } from './useBatchImport'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'imported', count: number): void
}>()

const {
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
} = useBatchImport(emit)
</script>

<style scoped>
.batch-import-panel {
  width: 700px;
  max-height: 90vh;
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
  margin: 0 0 8px;
}

.section-header-flex .section-label {
  margin-bottom: 0;
}

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
  font-size: 1.1rem;
  font-weight: 700;
  color: #2563eb;
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

.location-selector {
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
  font-size: 0.85rem;
}

.text-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.file-upload-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.upload-dropzone {
  padding: 36px 20px;
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

.btn-cancel,
.btn-confirm {
  padding: 10px 24px;
  font-size: 0.9rem;
}

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
