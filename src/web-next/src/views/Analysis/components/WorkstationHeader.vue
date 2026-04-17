<script setup lang="ts">
defineProps<{
  title: string;
  subtitle?: string;
  isIdentity?: boolean;
}>();

const emit = defineEmits<{
  (e: 'back'): void;
}>();
</script>

<template>
  <header class="workstation-header">
    <div class="header-left">
      <button class="btn-back" @click="emit('back')" title="返回列表">
        <span class="icon">⇽</span>
      </button>
      <div class="title-area">
        <div class="main-title">
          {{ title }}
          <span v-if="isIdentity" class="badge-identity">一致性验证成功</span>
        </div>
        <div class="subtitle" v-if="subtitle">{{ subtitle }}</div>
      </div>
    </div>
    
    <div class="header-right">
      <div class="engine-badge">
        <span class="pulse-dot"></span>
        MINIMAP2 CORE
      </div>
    </div>
  </header>
</template>

<style scoped>
.workstation-header {
  height: 72px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 32px;
  background: white;
  border-bottom: 1px solid #f1f5f9;
  z-index: 10;
}

.header-left { display: flex; align-items: center; gap: 20px; }

.btn-back {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: 1px solid #f1f5f9;
  background: white;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.btn-back:hover { background: #f8fafc; border-color: #cbd5e1; color: #1e293b; }
.btn-back .icon { font-size: 20px; }

.title-area { display: flex; flex-direction: column; gap: 2px; }
.main-title { font-size: 1.1rem; font-weight: 850; color: #0f172a; display: flex; align-items: center; gap: 12px; }
.subtitle { font-size: 0.75rem; color: #94a3b8; font-family: monospace; }

.badge-identity {
  font-size: 10px;
  background: #ecfdf5;
  color: #059669;
  padding: 2px 8px;
  border-radius: 20px;
  border: 1px solid #d1fae5;
  font-weight: 800;
  text-transform: uppercase;
}

.header-right { display: flex; gap: 16px; align-items: center; }

.engine-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.7rem;
  font-weight: 900;
  color: #64748b;
  background: #f1f5f9;
  padding: 6px 12px;
  border-radius: 8px;
  letter-spacing: 0.05em;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  background: #3b82f6;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
  70% { box-shadow: 0 0 0 10px rgba(59, 130, 246, 0); }
  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}
</style>
