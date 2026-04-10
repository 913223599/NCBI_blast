<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'icon'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  loading?: boolean
  icon?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'primary',
  size: 'md',
  disabled: false,
  loading: false
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const classes = computed(() => {
  return [
    'base-btn',
    `btn-${props.variant}`,
    `size-${props.size}`,
    { 'is-loading': props.loading, 'is-disabled': props.disabled }
  ]
})
</script>

<template>
  <button :class="classes" :disabled="disabled || loading" @click="emit('click', $event)">
    <span v-if="loading" class="spinner"></span>
    <span v-else-if="icon" class="icon">{{ icon }}</span>
    <span class="content">
      <slot />
    </span>
  </button>
</template>

<style scoped>
.base-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  white-space: nowrap;
  user-select: none;
}

.base-btn:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.is-disabled {
  opacity: 0.6;
  cursor: not-allowed;
  pointer-events: none;
}

/* Sizes */
.size-sm { padding: 4px 8px; font-size: 0.75rem; height: 28px; }
.size-md { padding: 8px 16px; font-size: 0.875rem; height: 36px; }
.size-lg { padding: 10px 20px; font-size: 1rem; height: 44px; }

/* Variants */
.btn-primary {
  background: var(--primary-color);
  color: white;
  
}
.btn-primary:hover:not(.is-disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
}

.btn-secondary {
  background: white;
  border-color: var(--border-color);
  color: var(--text-primary);
  
}
.btn-secondary:hover:not(.is-disabled) {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.btn-outline {
  background: transparent;
  border-color: var(--primary-color);
  color: var(--primary-color);
}
.btn-outline:hover:not(.is-disabled) {
  background: rgba(59, 130, 246, 0.05);
}

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}
.btn-ghost:hover:not(.is-disabled) {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary);
}

.btn-danger {
  background: #ef4444;
  color: white;
}
.btn-danger:hover:not(.is-disabled) {
  background: #dc2626;
}

.btn-icon {
  padding: 4px;
  width: 28px;
  height: 28px;
  border-radius: 4px;
  color: var(--text-secondary);
  background: transparent;
}
.btn-icon:hover:not(.is-disabled) {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-primary);
}
.size-md.btn-icon { width: 36px; height: 36px; }
.size-lg.btn-icon { width: 44px; height: 44px; }

/* Spinner */
.spinner {
  width: 1em;
  height: 1em;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>