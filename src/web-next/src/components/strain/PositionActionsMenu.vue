<template>
  <div class="position-actions-menu" :style="{ top: `${position.y}px`, left: `${position.x}px` }" @click.stop>
    <div v-if="isOccupied" class="menu-section">
      <div class="menu-item" @click="emit('view')">
        <span class="menu-icon">👁️</span>
        <span class="menu-text">查看样本</span>
      </div>
      <div class="menu-item" @click="emit('edit')">
        <span class="menu-icon">✏️</span>
        <span class="menu-text">编辑样本</span>
      </div>
      <div class="menu-item" @click="emit('unbind')">
        <span class="menu-icon">🔓</span>
        <span class="menu-text">解除绑定</span>
      </div>
    </div>
    
    <div v-else class="menu-section">
      <div class="menu-item primary" @click="emit('add')">
        <span class="menu-icon">➕</span>
        <span class="menu-text">录入样本</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  position: { x: number; y: number }
  isOccupied: boolean
}

defineProps<Props>()
const emit = defineEmits(['view', 'edit', 'unbind', 'add'])
</script>

<style scoped>
.position-actions-menu {
  position: fixed;
  background: white;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  padding: 8px;
  z-index: 10000;
  min-width: 180px;
}

.menu-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.85rem;
  color: #475569;
}

.menu-item:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.menu-item.primary {
  color: #2563eb;
  font-weight: 600;
}

.menu-item.primary:hover {
  background: #eff6ff;
}

.menu-icon {
  font-size: 1.1rem;
}

.menu-text {
  font-weight: 500;
}
</style>
