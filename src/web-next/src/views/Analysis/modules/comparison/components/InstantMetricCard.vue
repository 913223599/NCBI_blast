<script setup lang="ts">
defineProps<{
  title: string;
  value: string;
  subtitle: string;
  highlight?: boolean;
}>();
</script>

<template>
  <div class="metric-card" :class="{ highlight }">
    <p class="metric-title">{{ title }}</p>
    <h3 class="metric-value">{{ value }}</h3>
    <p class="metric-subtitle">{{ subtitle }}</p>
  </div>
</template>

<style scoped>
.metric-card {
  padding: 12px 16px; border-radius: 12px; border: 1px solid #f1f5f9;
  background: white; color: #1e293b; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.metric-card.highlight {
  background: linear-gradient(135deg, #3b82f6, #4f46e5);
  color: white; border: transparent; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.metric-title { font-size: 12px; font-weight: 500; margin-bottom: 2px; color: #64748b; }
.highlight .metric-title { color: #bfdbfe; }

.metric-value { font-size: 20px; font-weight: 800; margin: 0; letter-spacing: -0.01em; }
.metric-subtitle { font-size: 10px; margin-top: 4px; color: #94a3b8; }
.highlight .metric-subtitle { color: #93c5fd; }
</style>
