<template>
  <div class="position-banner">
    <div class="position-icon">📍</div>
    <div class="position-details">
      <div class="position-path">{{ path }}</div>
      <div class="position-label">{{ label }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  path: string
  label: string
}>()
</script>

<style scoped>
.position-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  background: linear-gradient(135deg, #f8fafc, #f1f5f9);
  padding: 16px;
  border-radius: 12px;
  margin-bottom: 24px;
  border-left: 4px solid #3b82f6;
}

.position-icon {
  font-size: 1.5rem;
}

.position-path {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.position-label {
  font-size: 1.1rem;
  font-weight: 800;
  color: #1e293b;
  margin-top: 2px;
}
</style>
