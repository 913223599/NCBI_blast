<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>噬菌体效价</label>
      <input 
        :value="modelValue.potency" 
        @input="updateField('potency', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：1x10^12 PFU/ml" 
      />
    </div>
    <div class="form-group">
      <label>宿主菌株 (Host)</label>
      <input 
        :value="modelValue.hostStrain" 
        @input="updateField('hostStrain', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：E. coli MG1655" 
      />
    </div>
    <div class="form-group">
      <label>生活史类型</label>
      <div class="select-box-neo" @click.stop="isOpen = !isOpen">
        {{ getLifestyleLabel() }} <span class="arrow">▼</span>
        <div v-if="isOpen" class="dropdown-list">
          <div 
            class="opt" 
            :class="{ selected: modelValue.lifestyle === 'Virulent' }"
            @click.stop="selectLifestyle('Virulent')"
          >烈性 (Virulent)</div>
          <div 
            class="opt" 
            :class="{ selected: modelValue.lifestyle === 'Temperate' }"
            @click.stop="selectLifestyle('Temperate')"
          >温和 (Temperate)</div>
        </div>
      </div>
    </div>
    <div class="form-group">
      <label>形态分类</label>
      <input 
        :value="modelValue.morphology" 
        @input="updateField('morphology', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：Myoviridae" 
      />
    </div>
    <div class="form-group">
      <label>潜伏期 (min)</label>
      <input 
        :value="modelValue.latentPeriod" 
        @input="updateField('latentPeriod', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：20 min" 
      />
    </div>
    <div class="form-group">
      <label>平均裂解量</label>
      <input 
        :value="modelValue.burstSize" 
        @input="updateField('burstSize', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：100 PFU/cell" 
      />
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

function getLifestyleLabel() {
  if (props.modelValue.lifestyle === 'Virulent') return '烈性 (Virulent)'
  if (props.modelValue.lifestyle === 'Temperate') return '温和 (Temperate)'
  return '请选择类型'
}

function selectLifestyle(val: string) {
  updateField('lifestyle', val)
  isOpen.value = false
}

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
.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}
.text-input {
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.85rem;
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
