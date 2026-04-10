<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>核酸浓度</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.concentration" 
          @input="updateField('concentration', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：500" 
        />
        <span class="unit">ng/μL</span>
      </div>
    </div>
    <div class="form-group">
      <label>宿主菌株 (E.coli Host)</label>
      <input 
        :value="modelValue.hostStrain" 
        @input="updateField('hostStrain', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：DH5α, BL21(DE3)" 
      />
    </div>
    <div class="form-group">
      <label>骨架 (Backbone)</label>
      <input 
        :value="modelValue.backbone" 
        @input="updateField('backbone', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：pET28a" 
      />
    </div>
    <div class="form-group">
      <label>插入片段 (Insert)</label>
      <input 
        :value="modelValue.insertName" 
        @input="updateField('insertName', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：GFP" 
      />
    </div>
    <div class="form-group">
      <label>质粒大小</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.plasmidSize" 
          @input="updateField('plasmidSize', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：5400" 
        />
        <span class="unit">bp</span>
      </div>
    </div>
    <div class="form-group">
      <label>筛选标记 (Markers)</label>
      <input 
        :value="modelValue.markerText" 
        @input="handleMarkerInput(($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：Kan, Zeo" 
      />
    </div>
    <div class="form-group">
      <label>启动子 (Promoter)</label>
      <input 
        :value="modelValue.promoter" 
        @input="updateField('promoter', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：T7, CMV" 
      />
    </div>
    <div class="form-group">
      <label>是表达载体吗？</label>
      <div class="select-box-neo" @click.stop="isOpen = !isOpen">
        {{ modelValue.isExpression ? '✅ 是 (Yes)' : '❌ 否 (No)' }} <span class="arrow">▼</span>
        <div v-if="isOpen" class="dropdown-list">
          <div 
            class="opt" 
            :class="{ selected: modelValue.isExpression === true }"
            @click.stop="selectExpression(true)"
          >是 (Yes)</div>
          <div 
            class="opt" 
            :class="{ selected: modelValue.isExpression === false }"
            @click.stop="selectExpression(false)"
          >否 (No)</div>
        </div>
      </div>
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

function handleMarkerInput(val: string) {
  const list = val.split(',').map(s => s.trim()).filter(Boolean)
  emit('update:modelValue', { ...props.modelValue, markerText: val, marker: list })
}

function selectExpression(val: boolean) {
  updateField('isExpression', val)
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
.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
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
.text-input {
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.85rem;
  width: 100%;
}

.input-with-unit {
  display: flex;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: white;
  overflow: hidden;
}

.input-with-unit .text-input {
  border: none;
  border-radius: 0;
  flex: 1;
  min-width: 0;
}

.input-with-unit .text-input:focus {
  outline: none;
}

.input-with-unit .unit {
  background: #f8fafc;
  padding: 8px 12px;
  border-left: 1px solid #e2e8f0;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 600;
  white-space: nowrap;
}
</style>