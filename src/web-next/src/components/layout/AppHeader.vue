<script setup lang="ts">
/**
 * AppHeader - 全局顶部信息架构栏
 * 提供面包屑定位、活跃任务状态胶囊、后端连通状态、语言快速切换与设置/帮助直达入口
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../../stores/app'
import { useBlastStore } from '../../stores/blast'
import { apiGet } from '../../bridge/electron-bridge'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const blastStore = useBlastStore()

const apiOnline = ref<'checking' | 'online' | 'offline'>('checking')

const runningBlastCount = computed(() =>
  blastStore.tasks.filter((t) => t.status === 'running' || t.status === 'queued').length
)

async function probeBackendHealth(): Promise<void> {
  apiOnline.value = 'checking'
  try {
    const res = await apiGet('/api/health')
    apiOnline.value = res && res.status === 'ok' ? 'online' : 'offline'
  } catch {
    apiOnline.value = 'offline'
  }
}

function toggleLocale(): void {
  const next = appStore.locale === 'zh_CN' ? 'en_US' : 'zh_CN'
  appStore.setLocale(next)
  appStore.showNotification(next === 'zh_CN' ? '界面语言已切换为简体中文' : 'UI language switched to English', 'info')
}

onMounted(() => {
  void probeBackendHealth()
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
