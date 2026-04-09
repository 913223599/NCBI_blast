<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>效价 (Potency)</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.potency" 
          @input="updateField('potency', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：1x10^12" 
        />
        <span class="unit">PFU/mL</span>
      </div>
    </div>
    <div class="form-group">
      <label>滴度 (Titer)</label>
      <div class="input-with-unit">
        <input 
          :value="modelValue.titer" 
          @input="updateField('titer', ($event.target as HTMLInputElement).value)"
          class="text-input" 
          placeholder="如：1x10^9" 
        />
        <span class="unit">TCID50/mL</span>
      </div>
    </div>
    <div class="form-group">
      <label>血清型 (Serotype)</label>
      <input 
        :value="modelValue.serotype" 
        @input="updateField('serotype', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：AAV-9, PHP.eb" 
      />
    </div>
    <div class="form-group">
      <label>包膜信息 (Envelope)</label>
      <input 
        :value="modelValue.envelope" 
        @input="updateField('envelope', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：VSV-G" 
      />
    </div>
    <div class="form-group">
      <label>灭活方法</label>
      <input 
        :value="modelValue.inactivationMethod" 
        @input="updateField('inactivationMethod', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：β-丙内酯" 
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
