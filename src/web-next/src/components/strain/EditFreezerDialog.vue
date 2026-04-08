<template>
  <div class="dialog-overlay" @click.self="emit('close')">
    <div class="dialog-content">
      <div class="dialog-header">
        <div class="header-left">
          <div class="icon-wrapper">✏️</div>
          <div>
            <h3 class="dialog-title">编辑冰箱信息</h3>
            <p class="dialog-subtitle">修改冰箱名称、型号和存取位置</p>
          </div>
        </div>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="dialog-body">
        <!-- 基本信息 -->
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

          <div class="form-row">
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
        </div>

        <!-- 结构摘要（不可编辑，仅提示） -->
        <div class="form-section info-section">
          <h4 class="section-label">内部结构（只读）</h4>
          <div class="structure-info">
            <p>该冰箱包含：<strong>{{ freezer.shelves.length }} 层</strong> 基准结构。</p>
            <p class="info-hint">💡 内部层级结构（层/柜/抽屉）目前不支持直接在此修改，如需调整请在管理面板操作或重新添加。</p>
          </div>
        </div>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">取消</button>
        <button class="btn-confirm" @click="handleConfirm" :disabled="!canSubmit">
          保存修改
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { Freezer } from '../../stores/strain'

interface Props {
  freezer: Freezer
}

const props = defineProps<Props>()
const emit = defineEmits(['close', 'updated'])

const strain = useStrainStore()
const appStore = useAppStore()

const form = ref({
  name: props.freezer.name,
  model: props.freezer.model,
  location: props.freezer.location
})

const canSubmit = computed(() => {
  return form.value.name.trim().length > 0
})

function handleConfirm() {
  if (!canSubmit.value) return

  strain.updateFreezer(props.freezer.id, {
    name: form.value.name.trim(),
    model: form.value.model.trim() || '未指定',
    location: form.value.location.trim() || '未指定'
  })

  appStore.showNotification(`已更新冰箱“${form.value.name}”`, 'success')
  emit('updated')
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
  border-radius: 12px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  width: 480px;
  max-height: 85vh;
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

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.icon-wrapper {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
}

.dialog-title {
  font-size: 1.1rem;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 2px 0;
}

.dialog-subtitle {
  font-size: 0.75rem;
  color: #64748b;
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
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.dialog-body {
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
  transition: all 0.2s;
}

.text-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

/* 结构信息 */
.info-section {
  background: #f8fafc;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #e2e8f0;
}

.structure-info p {
  margin: 0 0 8px 0;
  font-size: 0.9rem;
  color: #475569;
}

.info-hint {
  font-size: 0.8rem !important;
  color: #94a3b8 !important;
  margin: 12px 0 0 0 !important;
  line-height: 1.5;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}

.btn-cancel,
.btn-confirm {
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel {
  border: 1px solid #e2e8f0;
  color: #64748b;
  background: white;
}

.btn-cancel:hover {
  background: #f1f5f9;
}

.btn-confirm {
  border: none;
  color: white;
  background: #2563eb;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}

.btn-confirm:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
}

.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
