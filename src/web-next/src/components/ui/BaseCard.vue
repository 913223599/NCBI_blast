<script setup lang="ts">
interface Props {
  title?: string
  loading?: boolean
}

defineProps<Props>()
</script>

<template>
  <div class="base-card">
    <div v-if="title || $slots.header || $slots.actions" class="card-header">
      <div class="header-title">
        <slot name="header">
          <span v-if="title">{{ title }}</span>
        </slot>
      </div>
      <div v-if="$slots.actions" class="header-actions">
        <slot name="actions" />
      </div>
    </div>
    
    <div class="card-body">
      <div v-if="loading" class="loading-overlay">
        <div class="spinner"></div>
      </div>
      <slot />
    </div>

    <div v-if="$slots.footer" class="card-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.base-card {
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: box-shadow 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.base-card:hover {
  
}

.card-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fafbfc;
}

.header-title {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.card-body {
  padding: 16px;
  flex: 1;
  position: relative;
}

.card-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-light);
  background: #fafbfc;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 10;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 3px solid var(--primary-color);
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>