<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  modelValue?: string | number | null
  label?: string
  placeholder?: string
  error?: string
  disabled?: boolean
  type?: string
  required?: boolean
  prefix?: string
  suffix?: string
  name?: string
  autocomplete?: string
  min?: number
  max?: number
  step?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  label: '',
  placeholder: '',
  error: '',
  disabled: false,
  type: 'text',
  required: false,
  prefix: '',
  suffix: '',
  name: '',
  autocomplete: 'off',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
  (e: 'change', event: Event): void
  (e: 'blur', event: FocusEvent): void
  (e: 'focus', event: FocusEvent): void
}>()

const inputId = computed(() => `input-${props.name || (Math.random().toString(36).substr(2, 9))}`)

function handleInput(e: Event) {
  const target = e.target as HTMLInputElement
  const val = props.type === 'number' ? (target.value ? parseFloat(target.value) : '') : target.value
  emit('update:modelValue', val)
}
</script>

<template>
  <div class="form-group" :class="{ 'has-error': !!error, 'is-disabled': disabled }">
    <label v-if="label" :for="inputId" class="form-label">
      {{ label }} <span v-if="required" class="required">*</span>
    </label>
    <div class="input-wrapper">
      <span v-if="prefix" class="prefix">{{ prefix }}</span>
      <input
        :id="inputId"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :name="name"
        :autocomplete="autocomplete"
        :min="min"
        :max="max"
        :step="step"
        class="form-control"
        :class="{ 'with-prefix': !!prefix, 'with-suffix': !!suffix }"
        @input="handleInput"
        @change="$emit('change', $event)"
        @blur="$emit('blur', $event)"
        @focus="$emit('focus', $event)"
      />
      <span v-if="suffix" class="suffix">{{ suffix }}</span>
    </div>
    <span v-if="error" class="error-msg">{{ error }}</span>
  </div>
</template>

<style scoped>
.form-group {
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}

.required {
  color: #ef4444;
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.form-control {
  width: 100%;
  padding: 0.625rem 0.75rem;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--text-primary);
  background-color: white;
  background-clip: padding-box;
  border: 1px solid var(--border-color);
  border-radius: 0.375rem;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.with-prefix { padding-left: 2rem; }
.with-suffix { padding-right: 2rem; }

.prefix, .suffix {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-secondary);
  font-size: 0.875rem;
}
.prefix { left: 0.75rem; }
.suffix { right: 0.75rem; }

.form-control:focus {
  border-color: var(--primary-color);
  outline: 0;
  
}

.form-control:disabled {
  background-color: #f3f4f6;
  opacity: 1;
  cursor: not-allowed;
}

.has-error .form-control {
  border-color: #ef4444;
}

.has-error .form-control:focus {
  
}

.error-msg {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.875rem;
  color: #ef4444;
}
</style>