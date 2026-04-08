<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>效价 (Potency)</label>
      <input 
        :value="modelValue.potency" 
        @input="updateField('potency', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：1x10^12 PFU/ml" 
      />
    </div>
    <div class="form-group">
      <label>滴度 (Titer)</label>
      <input 
        :value="modelValue.titer" 
        @input="updateField('titer', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：1x10^9" 
      />
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
}
</style>
