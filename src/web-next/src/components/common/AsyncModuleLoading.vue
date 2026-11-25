<script setup lang="ts">
import { useI18n } from '../../locales'
const { t } = useI18n()
</script>

<template>
  <div class="async-module-loading" role="status" aria-live="polite">
    <div class="spinner" aria-hidden="true"></div>
    <span>{{ t('common.async_loading') }}</span>
  </div>
</template>

<style scoped>
.async-module-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 260px;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid var(--border-color);
  border-top-color: var(--accent-blue);
  animation: async-spin 0.8s linear infinite;
}

@keyframes async-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
