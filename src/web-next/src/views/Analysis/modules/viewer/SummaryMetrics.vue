<script setup lang="ts">
defineProps<{
  id: number;
  vars: number;
  rotation?: boolean;
}>();
</script>

<template>
  <div class="metrics-grid">
    <div class="metric-card theme-light-blue">
      <div class="content">
        <span class="label">核苷酸序列一致性 (IDENTITY)</span>
        <div class="value-row">
          <div class="value">{{ id }}%</div>
          <div class="status-indicator" :class="{ perfect: id === 100 }">
             {{ id === 100 ? '完美一致' : '高度相似' }}
          </div>
        </div>
        <div class="progress-track">
          <div class="progress-bar" :style="{ width: id + '%' }"></div>
        </div>
      </div>
    </div>

    <div class="metric-card border-card">
      <div class="content">
        <span class="label">检测到差异变异点 (VARIANTS)</span>
        <div class="value-row">
          <div class="value">{{ vars }}</div>
          <div class="badge-variants" v-if="vars > 0">SNPs/INDELs</div>
        </div>
        <p class="desc">基于 Minimap2 交叉验证检测出的突变位点</p>
      </div>
    </div>

    <div class="metric-card border-card" v-if="rotation">
      <div class="content">
        <span class="label">起点偏移核准 (Rotation)</span>
        <div class="value text-success">已校正</div>
        <p class="desc">检测到由于物理成环特性导致的序列平移</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.metrics-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.metric-card {
  position: relative;
  background: white;
  border-radius: 20px;
  padding: 24px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.theme-light-blue {
  background: #eff6ff;
  border: 1px solid #dbeafe;
}

.border-card {
  border: 1px solid #f1f5f9;
}

.label {
  display: block;
  font-size: 0.65rem;
  font-weight: 800;
  color: #64748b;
  margin-bottom: 12px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.value { font-size: 2.2rem; font-weight: 950; letter-spacing: -0.02em; color: #1e293b; }
.value.text-success { color: #16a34a; }

.value-row { display: flex; align-items: baseline; gap: 12px; }

.status-indicator {
  font-size: 0.7rem;
  font-weight: 900;
  color: #3b82f6;
  background: white;
  padding: 4px 10px;
  border-radius: 20px;
}
.status-indicator.perfect { color: #059669; }

.badge-variants { font-size: 0.65rem; font-weight: 900; color: #b91c1c; background: #fef2f2; padding: 2px 8px; border-radius: 6px; }

.desc { font-size: 0.75rem; color: #94a3b8; margin: 8px 0 0; }

.progress-track {
  width: 100%;
  height: 6px;
  background: white;
  border-radius: 10px;
  margin-top: 20px;
  border: 1px solid #dbeafe;
}
.progress-bar {
  height: 100%;
  background: #2563eb;
  border-radius: 10px;
}
</style>
