<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-content">
      <div class="dialog-header">
        <h3 class="dialog-title">添加 -80°C 冰箱</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="dialog-body">
        <div class="dialog-columns">
          <!-- 左侧：基本信息 -->
          <div class="left-column">
            <div class="form-section">
              <h4 class="section-label">基本信息</h4>
              
              <div class="form-group">
                <label>冰箱名称 <span class="required">*</span></label>
                <input
                  v-model="form.name"
                  class="text-input"
                  placeholder="例如：A区-01号冰箱"
                  maxlength="50"
                />
              </div>

              <div class="form-group">
                <label>型号</label>
                <input
                  v-model="form.model"
                  class="text-input"
                  placeholder="例如：Thermo U57"
                />
              </div>
              <div class="form-group">
                <label>位置</label>
                <input
                  v-model="form.location"
                  class="text-input"
                  placeholder="例如：实验室A区"
                />
              </div>
            </div>

            <div class="config-summary">
              <div class="summary-label">📊 结构概览</div>
              <div class="summary-stats">
                <div class="stat-item">
                  <span class="stat-value">{{ shelvesCount }}</span>
                  <span class="stat-label">层</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ shelvesCount * cabinetsPerShelf }}</span>
                  <span class="stat-label">柜</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ shelvesCount * cabinetsPerShelf * drawersPerCabinet }}</span>
                  <span class="stat-label">抽屉</span>
                </div>
                <div class="stat-item highlight">
                  <span class="stat-value">{{ getTotalBoxes() }}</span>
                  <span class="stat-label">总盒数</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：结构配置 -->
          <div class="right-column">
            <div class="form-section">
              <h4 class="section-label">内部结构配置</h4>
              
              <div class="shelf-config">
                <div class="config-grid">
                  <div class="form-group">
                    <label>总层数</label>
                    <input
                      v-model.number="shelvesCount"
                      type="number"
                      class="text-input"
                      min="1"
                      max="10"
                    />
                  </div>
                  <div class="form-group">
                    <label>每层柜数</label>
                    <input
                      v-model.number="cabinetsPerShelf"
                      type="number"
                      class="text-input"
                      min="1"
                      max="20"
                    />
                  </div>
                  <div class="form-group">
                    <label>每柜抽屉数</label>
                    <input
                      v-model.number="drawersPerCabinet"
                      type="number"
                      class="text-input"
                      min="1"
                      max="50"
                    />
                  </div>
                  <div class="form-group">
                    <label>每抽屉盒数</label>
                    <input
                      v-model.number="boxesPerDrawer"
                      type="number"
                      class="text-input"
                      min="1"
                      max="10"
                    />
                  </div>
                  <div class="form-group col-span-2">
                    <label>冻存盒规格</label>
                    <div class="select-box-neo" @click.stop="toggleDropdown">
                      {{ getBoxSizeLabel() }} <span class="arrow">▼</span>
                      <div v-if="isOpen" class="dropdown-list">
                        <div
                          v-for="option in BOX_SIZE_OPTIONS"
                          :key="option.value"
                          class="opt"
                          :class="{ selected: defaultBoxSize === option.value }"
                          @click.stop="selectBoxSize(option.value as any)"
                        >
                          {{ option.label }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div v-if="defaultBoxSize === 'custom'" class="form-row">
                  <div class="form-group">
                    <label>行数</label>
                    <input
                      v-model.number="customBoxRows"
                      type="number"
                      class="text-input"
                      min="1"
                      max="20"
                    />
                  </div>
                  <div class="form-group">
                    <label>列数</label>
                    <input
                      v-model.number="customBoxCols"
                      type="number"
                      class="text-input"
                      min="1"
                      max="20"
                    />
                  </div>
                </div>

                <div class="config-hint-box">
                  <span class="hint-icon">💡</span>
                  <p>系统将自动根据上述配置生成层级化的存储空间模型。您可以稍后手动调整细节。</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">取消</button>
        <button class="btn-confirm" @click="handleConfirm" :disabled="!canSubmit">
          确认添加
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

const strain = useStrainStore()
const appStore = useAppStore()

const emit = defineEmits(['close', 'added'])

const form = ref({
  name: '',
  model: '',
  location: ''
})

const shelvesCount = ref(3)
const cabinetsPerShelf = ref(4)
const drawersPerCabinet = ref(10)
const boxesPerDrawer = ref(5) // 默认每抽屉5个冻存盒
const defaultBoxSize = ref<'9x9' | '10x10' | 'custom'>('9x9')
const customBoxRows = ref(9)
const customBoxCols = ref(9)

// 下拉框状态
const isOpen = ref(false)

const BOX_SIZE_OPTIONS = [
  { value: '9x9', label: '9 × 9 (81位)' },
  { value: '10x10', label: '10 × 10 (100位)' },
  { value: 'custom', label: '自定义' }
]

function getBoxSizeLabel(): string {
  return BOX_SIZE_OPTIONS.find(o => o.value === defaultBoxSize.value)?.label || '9 × 9 (81位)'
}

function toggleDropdown(event: Event) {
  event.stopPropagation()
  isOpen.value = !isOpen.value
}

function selectBoxSize(value: '9x9' | '10x10' | 'custom') {
  defaultBoxSize.value = value
  isOpen.value = false
}

// 全局点击关闭下拉框
if (typeof document !== 'undefined') {
  document.addEventListener('click', () => {
    isOpen.value = false
  })
}

const canSubmit = computed(() => {
  return form.value.name.trim().length > 0
})

function getBoxDimensions(): { rows: number; cols: number } {
  if (defaultBoxSize.value === '9x9') return { rows: 9, cols: 9 }
  if (defaultBoxSize.value === '10x10') return { rows: 10, cols: 10 }
  return { rows: customBoxRows.value, cols: customBoxCols.value }
}

function getTotalBoxes(): number {
  return shelvesCount.value * cabinetsPerShelf.value * drawersPerCabinet.value * boxesPerDrawer.value
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

function handleConfirm() {
  if (!canSubmit.value) return

  const { rows, cols } = getBoxDimensions()
  
  // 创建冰箱结构
  const shelves: any[] = []
  for (let s = 1; s <= shelvesCount.value; s++) {
    const cabinets: any[] = []
    for (let c = 1; c <= cabinetsPerShelf.value; c++) {
      const drawers: any[] = []
      for (let d = 1; d <= drawersPerCabinet.value; d++) {
        const boxes: any[] = []
        // 每个抽屉可以放置多个冻存盒
        for (let b = 1; b <= boxesPerDrawer.value; b++) {
          const box: any = {
            id: `box_${s}_${c}_${d}_${b}`,
            name: `Box-${String(s).padStart(2, '0')}-${String(c).padStart(2, '0')}-${String(d).padStart(2, '0')}-${String(b).padStart(2, '0')}`,
            rows,
            cols,
            positions: generateBoxPositions(rows, cols)
          }
          boxes.push(box)
        }
        drawers.push({
          id: `drawer_${s}_${c}_${d}`,
          name: `抽屉-${String(d).padStart(2, '0')}`,
          boxes
        })
      }
      cabinets.push({
        id: `cabinet_${s}_${c}`,
        name: `柜-${String(c).padStart(2, '0')}`,
        drawers
      })
    }
    shelves.push({
      id: `shelf_${s}`,
      name: `第${s}层`,
      cabinets
    })
  }

  // 创建冰箱
  const freezer = strain.addFreezer({
    name: form.value.name.trim(),
    model: form.value.model.trim() || '未指定',
    location: form.value.location.trim() || '未指定',
    shelves
  })

  appStore.showNotification(`已添加冰箱“${freezer.name}”`, 'success')
  emit('added', freezer.id)
  emit('close')
}
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.dialog-content {
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  width: 850px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.dialog-title {
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
  transition: all 0.2s;
  margin-left: auto;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  scrollbar-width: thin;
  scrollbar-color: #e2e8f0 transparent;
}

.dialog-body::-webkit-scrollbar {
  width: 6px;
}

.dialog-body::-webkit-scrollbar-thumb {
  background-color: #e2e8f0;
  border-radius: 10px;
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
  margin: 0 0 16px 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.form-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}

.required {
  color: #dc2626;
}

.text-input {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.9rem;
  transition: border-color 0.2s;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.dialog-columns {
  display: flex;
  gap: 32px;
}

.left-column {
  flex: 1.2;
}

.right-column {
  flex: 2;
  border-left: 1px solid #e2e8f0;
  padding-left: 32px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.config-hint-box {
  margin-top: 20px;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.hint-icon {
  font-size: 1rem;
}

.config-hint-box p {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.5;
}

.config-summary {
  margin-top: 16px;
  padding: 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.summary-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  margin-bottom: 12px;
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-item {
  text-align: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.stat-item.highlight {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  border: 1px solid #3b82f6;
}

.stat-value {
  display: block;
  font-size: 1.25rem;
  font-weight: 800;
  color: #1e293b;
  margin-bottom: 2px;
}

.stat-item.highlight .stat-value {
  color: #1e40af;
}

.stat-label {
  display: block;
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
}

.shelves-preview {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.preview-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 8px;
}

.preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.shelf-preview-item {
  padding: 6px 12px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #475569;
}

.more-indicator {
  padding: 6px 12px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #94a3b8;
  display: flex;
  align-items: center;
}

.dialog-footer {
  padding: 16px 24px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel,
.btn-confirm {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel {
  border: 1px solid #e2e8f0;
  font-weight: 600;
  color: #64748b;
  background: white;
}

.btn-cancel:hover {
  background: #f8fafc;
}

.btn-confirm {
  border: none;
  font-weight: 700;
  color: white;
  background: #2563eb;
}

.btn-confirm:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 自定义下拉框样式 - 与 BLAST 模块一致 */
.form-group {
  position: relative;
}

.select-box-neo {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 0.82rem;
  cursor: pointer;
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: border-color 0.2s;
}

.select-box-neo:hover {
  border-color: #cbd5e1;
}

.select-box-neo .arrow {
  color: #94a3b8;
  font-size: 0.6rem;
  margin-left: 8px;
}

.dropdown-list {
  position: absolute;
  top: 110%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
  z-index: 200;
  max-height: 250px;
  overflow-y: auto;
  padding: 6px;
}

.dropdown-list .opt {
  padding: 10px 12px;
  font-size: 0.82rem;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropdown-list .opt:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.dropdown-list .opt.selected {
  color: #2563eb;
  font-weight: 700;
  background: #eff6ff;
}
</style>
