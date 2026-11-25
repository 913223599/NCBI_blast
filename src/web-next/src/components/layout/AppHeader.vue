<script setup lang="ts">
/**
 * AppHeader - 全局顶部信息架构栏
 * 提供面包屑定位、Ctrl+K 全局命令面板、硬件微监控胶囊、活跃任务状态、后端连通状态、语言快速切换与设置/帮助直达入口
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { useBlastStore } from '../../stores/blast'
import { apiGet } from '../../bridge/electron-bridge'
import { useI18n } from '../../locales'
import CommandPaletteDialog from '../common/CommandPaletteDialog.vue'
import CitationsDialog from '../common/CitationsDialog.vue'

interface SystemMetricsPayload {
  cpu_percent?: number | null
  memory_percent?: number | null
  memory_used_gb?: number | null
  memory_total_gb?: number | null
  cpu_cores?: number
  safe_cpu_budget?: number
  sampled_at?: number
  gpu?: {
    available?: boolean
    name?: string
    utilization_percent?: number | null
    used_vram_mb?: number
    total_vram_mb?: number
    free_vram_mb?: number
    vram_percent?: number | null
    temperature_c?: number | null
    source?: string
  }
}

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const blastStore = useBlastStore()
const { t } = useI18n()

const apiOnline = ref<'checking' | 'online' | 'offline'>('checking')
const sysMetrics = ref<SystemMetricsPayload | null>(null)
const showCommandPalette = ref(false)
const showCitationsDialog = ref(false)
let metricsTimer: ReturnType<typeof setInterval> | null = null
let isFetchingMetrics = false

const runningBlastCount = computed(() =>
  blastStore.tasks.filter((t) => t.status === 'running' || t.status === 'queued').length
)

const hasMetrics = computed(
  () =>
    sysMetrics.value !== null &&
    (typeof sysMetrics.value.cpu_percent === 'number' || typeof sysMetrics.value.memory_percent === 'number')
)

const metricsLoadLevel = computed<'normal' | 'busy' | 'high'>(() => {
  const m = sysMetrics.value
  if (!m) return 'normal'
  const peak = Math.max(
    typeof m.cpu_percent === 'number' ? m.cpu_percent : 0,
    typeof m.memory_percent === 'number' ? m.memory_percent : 0,
    typeof m.gpu?.utilization_percent === 'number' ? m.gpu.utilization_percent : 0
  )
  if (peak >= 85) return 'high'
  if (peak >= 65) return 'busy'
  return 'normal'
})

const metricsSummary = computed(() => {
  if (!sysMetrics.value) return ''
  const parts: string[] = []
  if (typeof sysMetrics.value.cpu_percent === 'number') {
    parts.push(`CPU ${Math.round(sysMetrics.value.cpu_percent)}%`)
  }
  if (typeof sysMetrics.value.memory_percent === 'number') {
    parts.push(`RAM ${Math.round(sysMetrics.value.memory_percent)}%`)
  }
  const gpu = sysMetrics.value.gpu
  if (gpu?.available) {
    if (typeof gpu.utilization_percent === 'number') {
      parts.push(`GPU ${Math.round(gpu.utilization_percent)}%`)
    } else if (typeof gpu.vram_percent === 'number') {
      parts.push(`VRAM ${Math.round(gpu.vram_percent)}%`)
    } else {
      parts.push('GPU')
    }
  }
  return parts.join(' · ')
})

const metricsTooltip = computed(() => {
  const m = sysMetrics.value
  if (!m) return t('header.metrics_tooltip_default')
  const lines: string[] = []
  if (typeof m.cpu_percent === 'number') {
    lines.push(
      t('header.metrics_cpu', {
        percent: Math.round(m.cpu_percent),
        cores: m.cpu_cores ?? '-',
        budget: m.safe_cpu_budget ?? '-',
      })
    )
  } else {
    lines.push(
      t('header.metrics_cores', { cores: m.cpu_cores ?? '-', budget: m.safe_cpu_budget ?? '-' })
    )
  }
  if (typeof m.memory_used_gb === 'number' && typeof m.memory_total_gb === 'number') {
    lines.push(
      t('header.metrics_mem', {
        used: m.memory_used_gb,
        total: m.memory_total_gb,
        percent: m.memory_percent ?? 0,
      })
    )
  }
  if (m.gpu?.available) {
    if (typeof m.gpu.utilization_percent === 'number') {
      lines.push(
        t('header.metrics_gpu_detail', {
          name: m.gpu.name || 'CUDA',
          util: Math.round(m.gpu.utilization_percent),
          used: m.gpu.used_vram_mb ?? 0,
          total: m.gpu.total_vram_mb ?? 0,
          temp: m.gpu.temperature_c ?? '-',
        })
      )
    } else {
      lines.push(
        t('header.metrics_gpu', {
          name: m.gpu.name || 'CUDA',
          free: m.gpu.free_vram_mb ?? 0,
          total: m.gpu.total_vram_mb ?? 0,
        })
      )
    }
  }
  return lines.join('\n')
})

async function probeBackendHealth(): Promise<void> {
  apiOnline.value = 'checking'
  try {
    const res = await apiGet('/api/health')
    apiOnline.value = res && res.status === 'ok' ? 'online' : 'offline'
  } catch {
    apiOnline.value = 'offline'
  }
}

async function fetchSystemMetrics(force = false): Promise<void> {
  if (isFetchingMetrics) return
  isFetchingMetrics = true
  try {
    const endpoint = force ? '/api/core/system_metrics?force=true' : '/api/core/system_metrics'
    const res = await apiGet(endpoint)
    if (res && (typeof res.cpu_percent === 'number' || typeof res.memory_percent === 'number')) {
      sysMetrics.value = res
    }
  } catch {
    // 离线或单测环境静默跳过，不打断界面
  } finally {
    isFetchingMetrics = false
  }
}

function handleVisibilityChange(): void {
  if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
    void fetchSystemMetrics(true)
  }
}

function toggleLocale(): void {
  const next = appStore.locale === 'zh_CN' ? 'en_US' : 'zh_CN'
  appStore.setLocale(next)
  appStore.showNotification(
    next === 'zh_CN' ? t('header.locale_switched_zh') : t('header.locale_switched_en'),
    'info'
  )
}

function handlePaletteNavigate(path: string, title: string): void {
  void router.push(path)
  appStore.setPageTitle(title)
}

function handlePaletteAction(action: 'citations' | 'toggle-locale' | 'probe-health'): void {
  if (action === 'citations') {
    showCitationsDialog.value = true
  } else if (action === 'toggle-locale') {
    toggleLocale()
  } else if (action === 'probe-health') {
    void probeBackendHealth()
    void fetchSystemMetrics(true)
  }
}

function handleGlobalKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    showCommandPalette.value = !showCommandPalette.value
  }
}

onMounted(() => {
  void probeBackendHealth()
  void fetchSystemMetrics(true)
  window.addEventListener('keydown', handleGlobalKeydown)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }
  metricsTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    void fetchSystemMetrics(false)
  }, 3000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  }
  if (metricsTimer !== null) {
    clearInterval(metricsTimer)
    metricsTimer = null
  }
})
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <button
        v-if="route.path !== '/'"
        type="button"
        class="crumb-home"
        :aria-label="t('header.aria_home')"
        @click="router.push('/')"
      >
        {{ t('header.home') }}
      </button>
      <span v-if="route.path !== '/'" class="crumb-sep" aria-hidden="true">/</span>
      <span class="page-title">{{ appStore.pageTitle }}</span>
    </div>

    <div class="header-actions" :aria-label="t('header.aria_actions')">
      <button
        type="button"
        class="header-search-btn"
        :title="t('header.quick_jump_title')"
        :aria-label="t('header.aria_palette')"
        @click="showCommandPalette = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span>{{ t('header.quick_jump') }}</span>
        <kbd class="kbd-chip">Ctrl+K</kbd>
      </button>

      <button
        v-if="hasMetrics"
        type="button"
        class="header-pill metrics-pill"
        :class="`metrics-${metricsLoadLevel}`"
        :title="metricsTooltip"
        :aria-label="t('header.metrics_aria')"
        @click="() => fetchSystemMetrics(true)"
      >
        <span>{{ metricsSummary }}</span>
      </button>

      <button
        v-if="runningBlastCount > 0"
        type="button"
        class="header-pill pill-running"
        :title="t('header.running_tasks_title')"
        @click="router.push('/blast')"
      >
        <span class="dot-pulse" aria-hidden="true"></span>
        <span>{{ t('header.running_tasks_count', { count: runningBlastCount }) }}</span>
      </button>

      <button
        type="button"
        class="header-pill"
        :class="`status-${apiOnline}`"
        :title="t('header.health_title')"
        @click="probeBackendHealth"
      >
        <span class="status-dot" aria-hidden="true"></span>
        <span>{{ apiOnline === 'online' ? t('header.status_online') : apiOnline === 'offline' ? t('header.status_offline') : t('header.status_checking') }}</span>
      </button>

      <button
        type="button"
        class="header-icon-btn"
        :title="t('header.locale_title')"
        :aria-label="t('header.locale_aria')"
        @click="toggleLocale"
      >
        {{ appStore.locale === 'zh_CN' ? '中' : 'EN' }}
      </button>

      <button
        type="button"
        class="header-icon-btn"
        :title="t('header.help_title')"
        :aria-label="t('header.help_aria')"
        @click="router.push('/help')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </button>

      <button
        type="button"
        class="header-icon-btn"
        :title="t('header.settings_title')"
        :aria-label="t('header.settings_aria')"
        @click="router.push('/settings')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </div>

    <CommandPaletteDialog
      v-model:open="showCommandPalette"
      @navigate="handlePaletteNavigate"
      @action="handlePaletteAction"
    />
    <CitationsDialog v-model:open="showCitationsDialog" />
  </header>
</template>

<style scoped>
.app-header {
  height: 52px;
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.crumb-home {
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
}

.crumb-home:hover {
  background: #f1f5f9;
  color: var(--accent-blue);
}

.crumb-sep {
  color: var(--text-muted);
  font-size: 0.85rem;
}

.page-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.header-search-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 0.78rem;
  color: var(--text-secondary);
  background: #f8fafc;
  border: 1px solid var(--border-color);
  transition: background-color 0.15s, border-color 0.15s, color 0.15s;
}

.header-search-btn:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: var(--text-primary);
}

.kbd-chip {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-muted);
  background: #ffffff;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 1px 5px;
}

.header-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background: #f1f5f9;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  transition: background-color 0.15s, border-color 0.15s;
}

.header-pill:hover {
  background: #e2e8f0;
}

.metrics-pill {
  font-variant-numeric: tabular-nums;
  background: #f8fafc;
  color: #334155;
}

.metrics-pill.metrics-busy {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

.metrics-pill.metrics-high {
  background: #fef2f2;
  color: #b91c1c;
  border-color: #fecaca;
}

.pill-running {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.status-dot,
.dot-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot-pulse {
  background: #2563eb;
}

.status-online .status-dot {
  background: #10b981;
}

.status-offline .status-dot {
  background: #ef4444;
}

.status-checking .status-dot {
  background: #f59e0b;
}

.header-icon-btn {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  font-weight: 700;
  transition: background-color 0.15s, color 0.15s, border-color 0.15s;
}

.header-icon-btn:hover {
  background: #f1f5f9;
  color: var(--text-primary);
  border-color: var(--border-color);
}
</style>
