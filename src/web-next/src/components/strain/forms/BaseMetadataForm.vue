<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>入库日期</label>
      <input 
        type="date"
        :value="modelValue.storageDate" 
        @input="updateField('storageDate', ($event.target as HTMLInputElement).value)"
        class="text-input" 
      />
    </div>
    <div class="form-group">
      <label>保存介质</label>
      <input 
        :value="modelValue.storageMedium" 
        @input="updateField('storageMedium', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：20% 甘油" 
      />
    </div>
    <div class="form-group">
      <label>生物安全等级</label>
      <div class="select-box-neo" @click.stop="isOpen = !isOpen">
        {{ modelValue.biosafetyLevel || 'BSL-1' }} <span class="arrow">▼</span>
        <div v-if="isOpen" class="dropdown-list">
          <div 
            v-for="opt in ['BSL-1', 'BSL-2', 'BSL-3', 'BSL-4']" 
            :key="opt" 
            class="opt"
            :class="{ selected: modelValue.biosafetyLevel === opt }"
            @click.stop="selectBiosafety(opt)"
          >
            {{ opt }}
          </div>
        </div>
      </div>
    </div>

    <div class="form-group">
      <label>传代次数</label>
      <input 
        :value="modelValue.passageNumber" 
        @input="updateField('passageNumber', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：P3" 
      />
    </div>
    <div class="form-group">
      <label>容器规格</label>
      <input 
        :value="modelValue.containerType" 
        @input="updateField('containerType', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：2ml 冻存管" 
      />
    </div>
    
    <div class="form-group full-width">
      <label>备注说明</label>
      <textarea 
        :value="modelValue.description" 
        @input="updateField('description', ($event.target as HTMLTextAreaElement).value)"
        class="textarea-input" 
        placeholder="其他补充信息..."
      ></textarea>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  modelValue: any
}>()

const emit = defineEmits(['update:modelValue'])
const isOpen = ref(false)

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

function selectBiosafety(val: string) {
  updateField('biosafetyLevel', val)
  isOpen.value = false
}

// 全局点击关闭下拉框
const closeDropdown = () => { isOpen.value = false }
onMounted(() => document.addEventListener('click', closeDropdown))
onUnmounted(() => document.removeEventListener('click', closeDropdown))
</script>

<style scoped>
.metadata-form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-group.full-width {
  grid-column: span 2;
}
.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}
.text-input, .textarea-input {
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.85rem;
  background: white;
}
.textarea-input {
  resize: vertical;
  min-height: 60px;
}

/* 自定义下拉框 */
.select-box-neo {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 0.85rem;
  cursor: pointer;
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.select-box-neo .arrow {
  color: #94a3b8;
  font-size: 0.6rem;
}
.dropdown-list {
  position: absolute;
  top: 110%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 100;
  padding: 4px;
}
.dropdown-list .opt {
  padding: 8px 10px;
  font-size: 0.82rem;
  border-radius: 4px;
  cursor: pointer;
}
.dropdown-list .opt:hover {
  background: #f1f5f9;
}
.dropdown-list .opt.selected {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}
</style>
