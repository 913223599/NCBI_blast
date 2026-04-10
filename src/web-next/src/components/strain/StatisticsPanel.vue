<template>
  <div class="statistics-panel">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card primary">
        <div class="stat-icon"></div>
        <div class="stat-content">
          <div class="stat-label">冰箱总数</div>
          <div class="stat-value">{{ strain.freezers.length }}</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="stat-icon"></div>
        <div class="stat-content">
          <div class="stat-label">样本总数</div>
          <div class="stat-value">{{ strain.records.length }}</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="stat-icon"></div>
        <div class="stat-content">
          <div class="stat-label">存储位总数</div>
          <div class="stat-value">{{ totalStorageCapacity }}</div>
        </div>
      </div>
      <div class="stat-card info">
        <div class="stat-icon"></div>
        <div class="stat-content">
          <div class="stat-label">使用率</div>
          <div class="stat-value">{{ usageRate }}%</div>
        </div>
      </div>
    </div>

    <!-- 冰箱使用率 -->
    <div class="stats-section">
      <h3 class="section-title">📊 冰箱使用率</h3>
      <div v-if="strain.freezers.length === 0" class="empty-hint">
        <p>暂无冰箱数据</p>
      </div>
      <div v-else class="freezer-usage-list">
        <div
          v-for="freezer in strain.freezers"
          :key="freezer.id"
          class="freezer-usage-item"
        >
          <div class="usage-header">
            <div class="freezer-name">{{ freezer.name }}</div>
            <div class="usage-percent">{{ getFreezerUsageRate(freezer) }}%</div>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill"
              :style="{ transform: `scaleX(${(getFreezerUsageRate(freezer)) / 100})`, transformOrigin: 'left' }"
              :class="getUsageLevel(getFreezerUsageRate(freezer))"
            ></div>
          </div>
          <div class="usage-details">
            <span>{{ getUsedSlots(freezer) }} / {{ getTotalSlots(freezer) }} 已占用</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 样本类型分布 -->
    <div class="stats-section">
      <h3 class="section-title">🧬 样本类型分布</h3>
      <div class="type-distribution">
        <div class="type-item">
          <div class="type-header">
            <span class="type-label">DNA</span>
            <span class="type-count">{{ typeCount.DNA }}</span>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill dna"
              :style="{ transform: `scaleX(${(getTypePercentage('DNA')) / 100})`, transformOrigin: 'left' }"
            ></div>
          </div>
        </div>
        <div class="type-item">
          <div class="type-header">
            <span class="type-label">RNA</span>
            <span class="type-count">{{ typeCount.RNA }}</span>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill rna"
              :style="{ transform: `scaleX(${(getTypePercentage('RNA')) / 100})`, transformOrigin: 'left' }"
            ></div>
          </div>
        </div>
        <div class="type-item">
          <div class="type-header">
            <span class="type-label">Protein</span>
            <span class="type-count">{{ typeCount.Protein }}</span>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill protein"
              :style="{ transform: `scaleX(${(getTypePercentage('Protein')) / 100})`, transformOrigin: 'left' }"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 来源国家分布 -->
    <div v-if="strain.uniqueCountries.length > 0" class="stats-section">
      <h3 class="section-title">🌍 来源国家分布</h3>
      <div class="country-list">
        <div
          v-for="country in strain.uniqueCountries.slice(0, 10)"
          :key="country"
          class="country-item"
        >
          <span class="country-name">{{ country }}</span>
          <span class="country-count">{{ getCountryCount(country) }}</span>
        </div>
      </div>
    </div>

    <!-- 导出按钮 -->
    <div class="export-section">
      <button class="btn-export" @click="handleExportStats">
        📥 导出统计报告
      </button>
      <button class="btn-export" @click="handleExportConfig">
        📄 导出冰箱配置
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { Freezer } from '../../stores/strain'

const strain = useStrainStore()
const appStore = useAppStore()

// 总存储容量
const totalStorageCapacity = computed(() => {
  let total = 0
  for (const freezer of strain.freezers) {
    total += getTotalSlots(freezer)
  }
  return total
})

// 总体使用率
const usageRate = computed(() => {
  if (totalStorageCapacity.value === 0) return 0
  return Math.round((strain.records.length / totalStorageCapacity.value) * 100)
})

// 样本类型统计
const typeCount = computed(() => ({
  DNA: strain.records.filter(r => r.sequenceType === 'DNA').length,
  RNA: strain.records.filter(r => r.sequenceType === 'RNA').length,
  Protein: strain.records.filter(r => r.sequenceType === 'Protein').length
}))

function getTypePercentage(type: keyof typeof typeCount.value): number {
  if (strain.records.length === 0) return 0
  return Math.round((typeCount.value[type] / strain.records.length) * 100)
}

function getTotalSlots(freezer: Freezer): number {
  let total = 0
  for (const shelf of freezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      for (const drawer of cabinet.drawers) {
        for (const box of drawer.boxes) {
          total += box.rows * box.cols
        }
      }
    }
  }
  return total
}

function getUsedSlots(freezer: Freezer): number {
  return strain.records.filter(r => r.freezerId === freezer.id).length
}

function getFreezerUsageRate(freezer: Freezer): number {
  const total = getTotalSlots(freezer)
  if (total === 0) return 0
  return Math.round((getUsedSlots(freezer) / total) * 100)
}

function getUsageLevel(rate: number): string {
  if (rate >= 80) return 'high'
  if (rate >= 50) return 'medium'
  return 'low'
}

function getCountryCount(country: string): number {
  return strain.records.filter(r => r.country === country).length
}

function handleExportStats() {
  const stats = {
    totalFreezers: strain.freezers.length,
    totalRecords: strain.records.length,
    totalCapacity: totalStorageCapacity.value,
    usageRate: usageRate.value,
    typeDistribution: typeCount.value,
    countries: strain.uniqueCountries.map(c => ({
      name: c,
      count: getCountryCount(c)
    }))
  }
  
  const data = JSON.stringify(stats, null, 2)
  downloadFile(data, 'statistics_report.json', 'application/json')
  appStore.showNotification('统计报告已导出', 'success')
}

function handleExportConfig() {
  const config = {
    freezers: strain.freezers,
    exportDate: new Date().toISOString()
  }
  
  const data = JSON.stringify(config, null, 2)
  downloadFile(data, 'freezer_config.json', 'application/json')
  appStore.showNotification('冰箱配置已导出', 'success')
}

function downloadFile(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.statistics-panel {
  padding: 20px;
  overflow-y: auto;
  height: 100%;
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.stat-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  
}

.stat-card.primary {
  border-left: 4px solid #2563eb;
}

.stat-card.success {
  border-left: 4px solid #10b981;
}

.stat-card.warning {
  border-left: 4px solid #f59e0b;
}

.stat-card.info {
  border-left: 4px solid #8b5cf6;
}

.stat-icon {
  font-size: 2rem;
}

.stat-card.primary .stat-icon::before { content: '🧊'; }
.stat-card.success .stat-icon::before { content: '🧬'; }
.stat-card.warning .stat-icon::before { content: '📦'; }
.stat-card.info .stat-icon::before { content: '📊'; }

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 0.75rem;
  color: #64748b;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 800;
  color: #1e293b;
}

/* 统计区块 */
.stats-section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  
}

.section-title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 16px 0;
}

.empty-hint {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
}

/* 冰箱使用率列表 */
.freezer-usage-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.freezer-usage-item {
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.usage-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.freezer-name {
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
}

.usage-percent {
  font-size: 0.85rem;
  font-weight: 700;
  color: #2563eb;
}

.progress-bar {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: transform 0.3s; backface-visibility: hidden; -webkit-backface-visibility: hidden; transform-origin: left; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.progress-fill.low {
  background: #10b981;
}

.progress-fill.medium {
  background: #f59e0b;
}

.progress-fill.high {
  background: #ef4444;
}

.progress-fill.dna {
  background: #2563eb;
}

.progress-fill.rna {
  background: #ec4899;
}

.progress-fill.protein {
  background: #f59e0b;
}

.usage-details {
  font-size: 0.75rem;
  color: #64748b;
}

/* 样本类型分布 */
.type-distribution {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.type-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.type-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.type-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
}

.type-count {
  font-size: 0.85rem;
  font-weight: 700;
  color: #2563eb;
}

/* 国家列表 */
.country-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.country-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
}

.country-name {
  font-size: 0.85rem;
  color: #475569;
}

.country-count {
  font-size: 0.85rem;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 2px 8px;
  border-radius: 4px;
}

/* 导出按钮 */
.export-section {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

.btn-export {
  flex: 1;
  padding: 12px 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-export:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #1e293b;
}
</style>