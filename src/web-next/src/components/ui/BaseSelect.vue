<script setup lang="ts">
import { computed } from 'vue'

interface Option {
  label: string
  value: string | number
  disabled?: boolean
}

interface Props {
  modelValue?: string | number | null
  label?: string
  options?: Option[]
  placeholder?: string
  error?: string
  disabled?: boolean
  required?: boolean
  id?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '', // Default to empty string for HTML select
  label: '',
  options: () => [],
  placeholder: '请选择',
  error: '',
  disabled: false,
  required: false,
  id: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
  (e: 'change', event: Event): void
}>()

const inputId = computed(() => props.id || `select-${Math.random().toString(36).substr(2, 9)}`)

function handleChange(e: Event) {
  const target = e.target as HTMLSelectElement
  emit('update:modelValue', target.value)
  emit('change', e)
}
</script>

<template>
  <div class="form-group" :class="{ 'has-error': !!error, 'is-disabled': disabled }">
    <label v-if="label" :for="inputId" class="form-label">
      {{ label }} <span v-if="required" class="required">*</span>
    </label>
    <div class="select-wrapper">
      <select
        :id="inputId"
        :value="modelValue"
        :disabled="disabled"
        class="form-select"
        @change="handleChange"
      >
        <option value="" disabled>{{ placeholder }}</option>
        <option 
          v-for="opt in options" 
          :key="opt.value" 
          :value="opt.value"
          :disabled="opt.disabled"
        >
          {{ opt.label }}
        </option>
      </select>
      <div class="select-arrow">▼</div>
    </div>
    <span v-if="error" class="error-msg">{{ error }}</span>
  </div>
</template>

<style scoped>
.form-group {
  margin-bottom: 1rem;
}

.form-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}

.required { color: #ef4444; }

.select-wrapper {
  position: relative;
  width: 100%;
}

.form-select {
  display: block;
  width: 100%;
  padding: 0.625rem 2rem 0.625rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--text-primary);
  background-color: white;
  background-image: none;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  appearance: none;
  -webkit-appearance: none;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
}

.select-arrow {
  position: absolute;
  top: 50%;
  right: 0.75rem;
  transform: translateY(-50%);
  color: var(--text-secondary);
  pointer-events: none;
  font-size: 0.75rem;
}

.form-select:focus {
  border-color: var(--primary-color);
  outline: 0;
  box-shadow: 0 0 0 0.2rem rgba(59, 130, 246, 0.25);
}

.form-select:disabled {
  background-color: #f3f4f6;
  opacity: 1;
}

.has-error .form-select {
  border-color: #ef4444;
}

.has-error .form-select:focus {
  box-shadow: 0 0 0 0.2rem rgba(239, 68, 68, 0.25);
}

.error-msg {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.875rem;
  color: #ef4444;
}
</style>
