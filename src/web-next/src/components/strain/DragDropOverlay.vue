<template>
  <div class="drag-overlay" v-if="visible">
    <div class="drag-content">
      <div class="drag-icon"></div>
      <h3>{{ title }}</h3>
      <p>{{ description }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  title?: string
  description?: string
}>()
</script>

<style scoped>
.drag-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(37, 99, 235, 0.1);
  /* backdrop-filter removed to fix WebEngine flickering */
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  pointer-events: none;
}

.drag-content {
  background: white;
  border-radius: 16px;
  padding: 40px 60px;
  text-align: center;
  border: 3px dashed #2563eb;
}

.drag-icon {
  font-size: 4rem;
  margin-bottom: 16px;
}

.drag-icon::before {
  content: '📦';
}

.drag-content h3 {
  font-size: 1.5rem;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.drag-content p {
  font-size: 0.9rem;
  color: #64748b;
  margin: 0;
}
</style>