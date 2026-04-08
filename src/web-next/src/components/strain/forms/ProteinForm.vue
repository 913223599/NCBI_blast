<template>
  <div class="metadata-form-grid">
    <div class="form-group">
      <label>蛋白浓度</label>
      <input 
        :value="modelValue.concentration" 
        @input="updateField('concentration', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：5 mg/ml" 
      />
    </div>
    <div class="form-group">
      <label>纯度 (%)</label>
      <input 
        :value="modelValue.purity" 
        @input="updateField('purity', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：>95%" 
      />
    </div>
    <div class="form-group">
      <label>分子量 (kDa)</label>
      <input 
        :value="modelValue.molecularWeight" 
        @input="updateField('molecularWeight', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：48 kDa" 
      />
    </div>
    <div class="form-group">
      <label>缓冲液 (Buffer)</label>
      <input 
        :value="modelValue.buffer" 
        @input="updateField('buffer', ($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：PBS, 5% Glycerol" 
      />
    </div>
    <div class="form-group">
      <label>纯化标签 (Tags)</label>
      <input 
        :value="modelValue.tagsText" 
        @input="handleTagsInput(($event.target as HTMLInputElement).value)"
        class="text-input" 
        placeholder="如：His, GST, Myc" 
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

function handleTagsInput(val: string) {
  const list = val.split(',').map(s => s.trim()).filter(Boolean)
  emit('update:modelValue', { ...props.modelValue, tagsText: val, tags: list })
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
