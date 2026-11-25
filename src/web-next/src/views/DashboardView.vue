<script setup lang="ts">
/**
 * DashboardView - 科研工作站仪表盘入口
 * 提供全站 6 大核心科研工作流快捷入口与真实系统状态概览
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app'
import { useStrainStore } from '../stores/strain'
import { APP_NAME, APP_VERSION } from '../utils/appMeta'
import { useI18n } from '../locales'

const router = useRouter()
const appStore = useAppStore()
const strainStore = useStrainStore()
const { t } = useI18n()

interface ActionCard {
  id: string
  title: string
  desc: string
  route: string
  iconType: 'blast' | 'assembly' | 'analysis' | 'tree' | 'strain' | 'other_tools'
  gradient: string
}

const actionCards = computed<ActionCard[]>(() => [
  {
    id: 'blast',
    title: t('dash.card.blast.title'),
    desc: t('dash.card.blast.desc'),
    route: '/blast',
    iconType: 'blast',
    gradient: 'linear-gradient(135deg, #2563eb 0%, #4f46e5 100%)',
  },
  {
    id: 'assembly',
    title: t('dash.card.assembly.title'),
    desc: t('dash.card.assembly.desc'),
    route: '/assembly',
    iconType: 'assembly',
    gradient: 'linear-gradient(135deg, #0284c7 0%, #0ea5e9 100%)',
  },
  {
    id: 'analysis',
    title: t('dash.card.analysis.title'),
    desc: t('dash.card.analysis.desc'),
    route: '/analysis',
    iconType: 'analysis',
    gradient: 'linear-gradient(135deg, #7c3aed 0%, #6366f1 100%)',
  },
  {
    id: 'tree',
    title: t('dash.card.tree.title'),
    desc: t('dash.card.tree.desc'),
    route: '/tree',
    iconType: 'tree',
    gradient: 'linear-gradient(135deg, #0f766e 0%, #10b981 100%)',
  },
  {
    id: 'strain',
    title: t('dash.card.strain.title'),
    desc: t('dash.card.strain.desc'),
    route: '/strain',
    iconType: 'strain',
    gradient: 'linear-gradient(135deg, #ea580c 0%, #f59e0b 100%)',
  },
  {
    id: 'other_tools',
    title: t('dash.card.other.title'),
    desc: t('dash.card.other.desc'),
    route: '/other-tools',
    iconType: 'other_tools',
    gradient: 'linear-gradient(135deg, #475569 0%, #334155 100%)',
  },
])

const systemMetrics = computed(() => [
  { label: t('dash.metric.platform_version'), value: `${APP_NAME} v${APP_VERSION}` },
  { label: t('dash.metric.strain_records'), value: t('dash.unit.records', { count: strainStore.records.length }) },
  { label: t('dash.metric.freezers'), value: t('dash.unit.units', { count: strainStore.freezers.length }) },
])

function navigateTo(card: ActionCard): void {
  router.push(card.route)
  appStore.setPageTitle(card.title)
}
</script>

<template>
  <div class="dashboard-view">
    <section class="welcome-banner" :aria-label="t('dash.aria_overview')">
      <div class="welcome-left">
        <h1>{{ APP_NAME }} <span class="pro-badge">{{ t('dash.badge') }}</span></h1>
        <p>{{ t('dash.welcome_desc') }}</p>
      </div>
      <div class="welcome-decoration" aria-hidden="true">
        <svg viewBox="0 0 24 24" class="deco-icon">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="dash-quick-heading">
      <h2 id="dash-quick-heading" class="section-title">{{ t('dash.quick') }}</h2>
      <div class="cards-grid">
        <button
          v-for="card in actionCards"
          :key="card.id"
          type="button"
          class="action-card"
          @click="navigateTo(card)"
        >
          <div class="card-icon" :style="{ background: card.gradient }" aria-hidden="true">
            <svg v-if="card.iconType === 'blast'" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <svg v-else-if="card.iconType === 'assembly'" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
              <line x1="12" y1="22.08" x2="12" y2="12" />
            </svg>
            <svg v-else-if="card.iconType === 'analysis'" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <path d="M21 12A9 9 0 1 1 12 3v9z" />
              <path d="M12 3a9 9 0 0 1 9 9h-9z" />
            </svg>
            <svg v-else-if="card.iconType === 'tree'" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <path d="M5 4v16" />
              <path d="M5 7h7v-2h6" />
              <path d="M5 7h7v3h6" />
              <path d="M5 17h6v-2h7" />
              <path d="M5 17h6v3h7" />
            </svg>
            <svg v-else-if="card.iconType === 'strain'" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <circle cx="12" cy="12" r="6" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.1">
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
            </svg>
          </div>
          <div class="card-body">
            <h3>{{ card.title }}</h3>
            <p>{{ card.desc }}</p>
          </div>
          <span class="card-arrow" aria-hidden="true">&rarr;</span>
        </button>
      </div>
    </section>

    <section class="dashboard-section" aria-labelledby="dash-sys-heading">
      <h2 id="dash-sys-heading" class="section-title">{{ t('dash.sys') }}</h2>
      <div class="info-grid">
        <div v-for="metric in systemMetrics" :key="metric.label" class="info-card">
          <div class="info-label">{{ metric.label }}</div>
          <div class="info-value">{{ metric.value }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-view {
  padding: var(--space-lg) var(--space-xl);
  max-width: 1180px;
  margin: 0 auto;
}

.welcome-banner {
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 60%, #0284c7 100%);
  border-radius: var(--radius-lg);
  padding: 28px 34px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #ffffff;
  margin-bottom: var(--space-lg);
}

.welcome-left h1 {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 6px;
}

.pro-badge {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  font-weight: 600;
  vertical-align: middle;
  margin-left: 6px;
}

.welcome-left p {
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.92rem;
}

.deco-icon {
  width: 60px;
  height: 60px;
  opacity: 0.18;
  fill: none;
  stroke: #ffffff;
  stroke-width: 2;
  flex-shrink: 0;
}

.dashboard-section {
  margin-bottom: var(--space-xl);
}

.section-title {
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 14px;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-md);
}

.action-card {
  width: 100%;
  text-align: left;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  cursor: pointer;
  transition: border-color 0.18s, transform 0.18s, background-color 0.18s;
  display: flex;
  flex-direction: column;
  position: relative;
}

.action-card:hover {
  border-color: var(--accent-blue);
  background: #f8fbff;
  transform: translateY(-2px);
}

.action-card:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
}

.card-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}

.card-body h3 {
  font-size: 0.98rem;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text-primary);
}

.card-body p {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
}

.card-arrow {
  position: absolute;
  top: 20px;
  right: 20px;
  font-size: 1.15rem;
  color: var(--text-muted);
  opacity: 0.5;
  transition: opacity 0.18s, transform 0.18s, color 0.18s;
}

.action-card:hover .card-arrow {
  opacity: 1;
  color: var(--accent-blue);
  transform: translateX(2px);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
  font-size: 0.78rem;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.info-value {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
