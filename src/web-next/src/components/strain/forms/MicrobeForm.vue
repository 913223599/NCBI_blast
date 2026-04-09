<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>菌液浓度</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.concentration" 
          @input="updateField('concentration', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：1x10^9" 
        />
        <span class="unit">CFU/mL</span>
      </div>
    </div>
    <div class="form-group">
      <label>培养条件</label>
      <input 
        :value="modelValue.cultureCondition" 
        @input="updateField('cultureCondition', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：LB, 220rpm" 
      />
    </div>
    <div class="form-group">
      <label>生长温度</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.growthTemp" 
          @input="updateField('growthTemp', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：37" 
        />
        <span class="unit">°C</span>
      </div>
    </div>
    <div class="form-group">
      <label>抗性信息</label>
      <input 
        :value="modelValue.resistanceText" 
        @input="handleResistanceInput(($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：Amp, Kan (逗号分隔)" 
      />
    </div>
    <div class="form-group full-width">
      <label>基因型</label>
      <textarea 
        :value="modelValue.genotype" 
        @input="updateField('genotype', ($event.target as HTMLTextAreaElement).value)"
        class="textarea-input" 
        placeholder="详细基因型描述..."
      ></textarea>
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

function handleResistanceInput(val: string) {
  const list = val.split(',').map(s => s.trim()).filter(Boolean)
  emit('update:modelValue', { ...props.modelValue, resistanceText: val, resistance: list })
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
