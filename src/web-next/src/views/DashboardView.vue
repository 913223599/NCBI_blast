<script setup lang="ts">
/**
 * DashboardView - 仪表盘视图
 * 从旧版 index.html #dashboard-view 迁移
 * 包含欢迎横幅 + 功能导航卡片
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { useI18n } from '../locales'

const router = useRouter()
const appStore = useAppStore()
const { t } = useI18n()

interface ActionCard {
  id: string
  titleKey: string
  descKey: string
  route: string
  icon: string
  gradient: string
}

const actionCards = computed<ActionCard[]>(() => [
  {
    id: 'blast',
    titleKey: 'dash.blast.title',
    descKey: 'dash.blast.desc',
    route: '/blast',
    icon: '🔍',
    gradient: 'linear-gradient(135deg, #3b82f6 0%, #6366f1 100%)'
  },
  {
    id: 'tree',
    titleKey: 'dash.tree.title',
    descKey: 'dash.tree.desc',
    route: '/tree',
    icon: '🌳',
    gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
  }
])

function navigateTo(card: ActionCard): void {
  router.push(card.route)
  appStore.setPageTitle(t(card.titleKey))
}
</script>

<template>
  <div class="dashboard-view">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div class="welcome-left">
        <h1>Welcome to NCBI BLAST <span class="pro-badge">Pro</span></h1>
        <p>Professional Alignment & Sequence Analysis Suite</p>
      </div>
      <div class="welcome-decoration">
        <svg viewBox="0 0 24 24" class="deco-icon">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      </div>
    </div>

    <!-- 功能卡片 -->
    <div class="section-title">{{ t('dash.quick') }}</div>
    <div class="cards-grid">
      <div
        v-for="card in actionCards"
        :key="card.id"
        class="action-card"
        @click="navigateTo(card)"
      >
        <div class="card-icon" :style="{ background: card.gradient }">
          {{ card.icon }}
        </div>
        <div class="card-body">
          <h3>{{ t(card.titleKey) }}</h3>
          <p>{{ t(card.descKey) }}</p>
        </div>
        <div class="card-arrow">→</div>
      </div>
    </div>

    <!-- 状态信息 -->
    <div class="section-title">{{ t('dash.sys') }}</div>
    <div class="info-grid">
      <div class="info-card">
        <div class="info-label">{{ t('dash.sys.v') }}</div>
        <div class="info-value">v2.0-next</div>
      </div>
      <div class="info-card">
        <div class="info-label">{{ t('dash.sys.arch') }}</div>
        <div class="info-value">Vue 3 SPA</div>
      </div>
      <div class="info-card">
        <div class="info-label">{{ t('dash.sys.render') }}</div>
        <div class="info-value">统一 DOM</div>
      </div>
      <div class="info-card">
        <div class="info-label">{{ t('dash.sys.tool') }}</div>
        <div class="info-value">Vite 7</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-view {
  padding: var(--space-lg);
  max-width: 960px;
}

/* 欢迎横幅 */
.welcome-banner {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border-radius: var(--radius-lg);
  padding: 32px 36px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: white;
  margin-bottom: var(--space-lg);
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.25);
}

.welcome-left h1 {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 6px;
}

.pro-badge {
  font-size: 0.6em;
  opacity: 0.7;
  font-weight: 400;
  vertical-align: super;
}

.welcome-left p {
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.95rem;
}

.deco-icon {
  width: 64px;
  height: 64px;
  opacity: 0.15;
  fill: none;
  stroke: white;
  stroke-width: 2;
}

/* 区域标题 */
.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

/* 功能卡片 */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-md);
  margin-bottom: var(--space-xl);
}

.action-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  position: relative;
}

.action-card:hover {
  border-color: var(--accent-blue);
  box-shadow: var(--shadow-lg);
  transform: translateY(-3px);
}

.card-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  margin-bottom: 14px;
}

.card-body h3 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text-primary);
}

.card-body p {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

.card-arrow {
  position: absolute;
  top: 20px;
  right: 20px;
  font-size: 1.2rem;
  color: var(--text-muted);
  opacity: 0;
  transition: all 0.2s;
}

.action-card:hover .card-arrow {
  opacity: 1;
  color: var(--accent-blue);
}

/* 信息卡片 */
.info-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-md);
}

.info-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  text-align: center;
}

.info-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-value {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
