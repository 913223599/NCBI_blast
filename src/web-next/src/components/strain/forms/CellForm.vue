<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>细胞密度/浓度</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.concentration" 
          @input="updateField('concentration', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：1x10^6" 
        />
        <span class="unit">cells/mL</span>
      </div>
    </div>
    <div class="form-group">
      <label>细胞类型</label>
      <input 
        :value="modelValue.cellType" 
        @input="updateField('cellType', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：Adherent, Suspension" 
      />
    </div>
    <div class="form-group">
      <label>培养基 (Medium)</label>
      <input 
        :value="modelValue.medium" 
        @input="updateField('medium', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：DMEM + 10% FBS" 
      />
    </div>
    <div class="form-group">
      <label>倍增时间</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.doublingTime" 
          @input="updateField('doublingTime', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：24" 
        />
        <span class="unit">h</span>
      </div>
    </div>
    <div class="form-group">
      <label>STR 鉴定编号</label>
      <input 
        :value="modelValue.authentication" 
        @input="updateField('authentication', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="STR 报告 ID" 
      />
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  modelValue: any
}>()

const emit = defineEmits(['update:modelValue'])

function updateField(key: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
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