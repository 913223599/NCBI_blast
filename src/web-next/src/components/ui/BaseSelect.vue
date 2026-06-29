<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

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
  modelValue: '',
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
  (e: 'change', value: string | number): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const inputId = computed(() => props.id || `select-${Math.random().toString(36).substr(2, 9)}`)

const selectedLabel = computed(() => {
  const opt = props.options.find(o => o.value === props.modelValue)
  return opt ? opt.label : props.placeholder
})

function toggleDropdown() {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

function selectOption(opt: Option) {
  if (opt.disabled) return
  emit('update:modelValue', opt.value)
  emit('change', opt.value)
  isOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
  if (selectRef.value && !selectRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="form-group" :class="{ 'has-error': !!error, 'is-disabled': disabled }" ref="selectRef">
    <label v-if="label" :for="inputId" class="form-label">
      {{ label }} <span v-if="required" class="required">*</span>
    </label>
    
    <div class="custom-select-container">
      <div 
        class="select-trigger" 
        :class="{ 'is-open': isOpen, 'is-disabled': disabled }"
        @click="toggleDropdown"
      >
        <span class="selected-text">{{ selectedLabel }}</span>
        <span class="select-arrow">▼</span>
      </div>

      <transition name="dropdown-fade">
        <div v-if="isOpen" class="select-dropdown">
          <div 
            v-for="opt in (options || [])"
            :key="opt.value"
            class="select-option"
            :class="{ 'is-selected': opt.value === modelValue, 'is-disabled': opt.disabled }"
            @click="selectOption(opt)"
          >
            {{ opt.label }}
          </div>
          <div v-if="!options || options.length === 0" class="empty-options">
            无可用选项
          </div>
        </div>
      </transition>
    </div>
    
    <span v-if="error" class="error-msg">{{ error }}</span>
  </div>
</template>

<style scoped>
.form-group {
  margin-bottom: 0.75rem;
  width: 100%;
}

.form-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
  color: #64748b;
}

.required { color: #ef4444; }

.custom-select-container {
  position: relative;
  width: 100%;
}

.select-trigger {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  background-color: white;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  user-select: none;
}

.select-trigger:hover:not(.is-disabled) {
  border-color: var(--accent-blue);
  background: #f8fafc;
}

.select-trigger.is-open {
  border-color: var(--accent-blue);
  
}

.select-trigger.is-disabled {
  background-color: #f1f5f9;
  cursor: not-allowed;
  opacity: 0.7;
}

.selected-text {
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.select-arrow {
  font-size: 0.65rem;
  color: #94a3b8;
  margin-left: 8px;
  transition: transform 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.is-open .select-arrow {
  transform: rotate(180deg);
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  
  z-index: 1000;
  max-height: 200px;
  overflow-y: auto;
  padding: 4px;
}

.select-option {
  padding: 8px 12px;
  font-size: 0.85rem;
  color: var(--text-primary);
  border-radius: 4px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.select-option:hover:not(.is-disabled) {
  background: #eff6ff;
  color: var(--accent-blue);
}

.select-option.is-selected {
  background: #3b82f6;
  color: white;
}

.select-option.is-disabled {
  color: #cbd5e1;
  cursor: not-allowed;
}

.empty-options {
  padding: 12px;
  text-align: center;
  font-size: 0.8rem;
  color: #94a3b8;
}

.error-msg {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: #ef4444;
}

/* Scrollbar Style */
.select-dropdown::-webkit-scrollbar { width: 4px; }
.select-dropdown::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 10px; }

/* Animation */
.dropdown-fade-enter-active,
.dropdown-fade-leave-active {
  transition: opacity 0.15s, transform 0.15s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.dropdown-fade-enter-from,
.dropdown-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>