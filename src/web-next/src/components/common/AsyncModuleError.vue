<script setup lang="ts">
import { useI18n } from '../../locales'
const { t } = useI18n()
</script>

<template>
  <div class="async-module-error" role="alert">
    <h3>{{ t('common.async_error_title') }}</h3>
    <p>{{ t('common.async_error_desc') }}</p>
  </div>
</template>

<style scoped>
.async-module-error {
  max-width: 420px;
  margin: 64px auto;
  padding: 24px;
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}

.async-module-error h3 {
  font-size: 1rem;
  color: var(--error-color);
  margin-bottom: 8px;
}

.async-module-error p {
  font-size: 0.85rem;
  color: var(--text-secondary);
}
</style>
