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
import CommandPaletteDialog from '../common/CommandPaletteDialog.vue'
import CitationsDialog from '../common/CitationsDialog.vue'

interface SystemMetricsPayload {
  cpu_percent?: number | null
  memory_percent?: number | null
  memory_used_gb?: number | null
  memory_total_gb?: number | null
  cpu_cores?: number
  safe_cpu_budget?: number
  gpu?: {
    available?: boolean
    name?: string
    total_vram_mb?: number
    free_vram_mb?: number
  }
}

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const blastStore = useBlastStore()

const apiOnline = ref<'checking' | 'online' | 'offline'>('checking')
const sysMetrics = ref<SystemMetricsPayload | null>(null)
const showCommandPalette = ref(false)
const showCitationsDialog = ref(false)
let metricsTimer: ReturnType<typeof setInterval> | null = null

const runningBlastCount = computed(() =>
  blastStore.tasks.filter((t) => t.status === 'running' || t.status === 'queued').length
)

const hasMetrics = computed(
  () =>
    sysMetrics.value !== null &&
    (typeof sysMetrics.value.cpu_percent === 'number' || typeof sysMetrics.value.memory_percent === 'number')
)

const metricsSummary = computed(() => {
  if (!sysMetrics.value) return ''
  const parts: string[] = []
  if (typeof sysMetrics.value.cpu_percent === 'number') {
    parts.push(`CPU ${Math.round(sysMetrics.value.cpu_percent)}%`)
  }
  if (typeof sysMetrics.value.memory_percent === 'number') {
    parts.push(`RAM ${Math.round(sysMetrics.value.memory_percent)}%`)
  }
  if (sysMetrics.value.gpu?.available) {
    parts.push('GPU')
  }
  return parts.join(' · ')
})

const metricsTooltip = computed(() => {
  const m = sysMetrics.value
  if (!m) return '实时硬件资源监控'
  const lines = [
    `逻辑核心: ${m.cpu_cores ?? '-'} 核（安全并发预算 ${m.safe_cpu_budget ?? '-'} 线程）`,
  ]
  if (typeof m.memory_used_gb === 'number' && typeof m.memory_total_gb === 'number') {
    lines.push(`内存: ${m.memory_used_gb} / ${m.memory_total_gb} GB (${m.memory_percent ?? 0}%)`)
  }
  if (m.gpu?.available) {
    lines.push(`GPU: ${m.gpu.name || 'CUDA'}（空闲 ${m.gpu.free_vram_mb ?? 0} / ${m.gpu.total_vram_mb ?? 0} MB）`)
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

async function fetchSystemMetrics(): Promise<void> {
  try {
    const res = await apiGet('/api/core/system_metrics')
    if (res && (typeof res.cpu_percent === 'number' || typeof res.memory_percent === 'number')) {
      sysMetrics.value = res
    }
  } catch {
    // 离线或单测环境静默跳过，不打断界面
  }
}

function toggleLocale(): void {
  const next = appStore.locale === 'zh_CN' ? 'en_US' : 'zh_CN'
  appStore.setLocale(next)
  appStore.showNotification(next === 'zh_CN' ? '界面语言已切换为简体中文' : 'UI language switched to English', 'info')
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
    void fetchSystemMetrics()
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
  void fetchSystemMetrics()
  window.addEventListener('keydown', handleGlobalKeydown)
  metricsTimer = setInterval(() => {
    void fetchSystemMetrics()
  }, 15000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
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
        aria-label="返回仪表盘首页"
        @click="router.push('/')"
      >
        首页
      </button>
      <span v-if="route.path !== '/'" class="crumb-sep" aria-hidden="true">/</span>
      <span class="page-title">{{ appStore.pageTitle }}</span>
    </div>

    <div class="header-actions" aria-label="工作站全局快捷操作">
      <button
        type="button"
        class="header-search-btn"
        title="打开全局命令面板 (Ctrl+K)"
        aria-label="打开全局命令面板"
        @click="showCommandPalette = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span>快捷跳转</span>
        <kbd class="kbd-chip">Ctrl+K</kbd>
      </button>

      <button
        v-if="hasMetrics"
        type="button"
        class="header-pill metrics-pill"
        :title="metricsTooltip"
        aria-label="刷新实时硬件负载"
        @click="fetchSystemMetrics"
      >
        <span>{{ metricsSummary }}</span>
      </button>

      <button
        v-if="runningBlastCount > 0"
        type="button"
        class="header-pill pill-running"
        title="查看正在执行的 BLAST 任务"
        @click="router.push('/blast')"
      >
        <span class="dot-pulse" aria-hidden="true"></span>
        <span>{{ runningBlastCount }} 项运行中</span>
      </button>

      <button
        type="button"
        class="header-pill"
        :class="`status-${apiOnline}`"
        title="点击检测本地 FastAPI 计算服务健康状态"
        @click="probeBackendHealth"
      >
        <span class="status-dot" aria-hidden="true"></span>
        <span>{{ apiOnline === 'online' ? '服务就绪' : apiOnline === 'offline' ? '服务离线' : '检测中' }}</span>
      </button>

      <button
        type="button"
        class="header-icon-btn"
        title="切换界面语言 (中/EN)"
        aria-label="切换界面语言"
        @click="toggleLocale"
      >
        {{ appStore.locale === 'zh_CN' ? '中' : 'EN' }}
      </button>

      <button
        type="button"
        class="header-icon-btn"
        title="帮助中心"
        aria-label="打开帮助中心"
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
        title="系统设置"
        aria-label="打开系统设置"
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
