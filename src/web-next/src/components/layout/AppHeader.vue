<script setup lang="ts">
/**
 * AppHeader - 顶部标题栏
 */
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()
</script>

<template>
  <header class="app-header">
    <div class="page-title">{{ appStore.pageTitle }}</div>
    <div class="header-actions">
      <!-- 操作按钮区域 -->
    </div>
  </header>
</template>

<style scoped>
.app-header {
  height: 56px;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
}

.page-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
