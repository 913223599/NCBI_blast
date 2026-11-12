<script setup lang="ts">
/**
 * HeadlessBrowserPanel - 系统级无头浏览器健康检查与自修复面板
 * 职责：
 * 1. 查询 /api/settings/browser_env 并展示 Playwright 驱动、Chromium 内核及 Windows 完整性状态；
 * 2. 允许切换无头浏览器启用开关、静默无头/有头调试模式、系统浏览器兜底；
 * 3. 一键触发后端检查与自动下载/清理重装自修复。
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPost } from '../../bridge/electron-bridge'
import { useAppStore } from '../../stores/app'
import type { BrowserEnvStatus } from '../../views/OtherTools/sangonTypes'

const appStore = useAppStore()
const loading = ref(false)
const repairing = ref(false)
const statusData = ref<BrowserEnvStatus | null>(null)
const enabledInput = ref(true)
const headlessInput = ref(true)
const fallbackInput = ref(true)
const lastError = ref('')

const modeLabel = computed(() => {
  const m = statusData.value?.mode || 'unavailable'
  const map: Record<string, string> = {
    playwright_chromium: 'Playwright 内置 Chromium',
    system_browser_fallback: '系统浏览器兜底 (Edge / Chrome)',
    custom_executable: '自定义浏览器路径',
    disabled: '已按配置禁用',
    unavailable: '未就绪'
  }
  return map[m] || m
})

const stateBadge = computed(() => {
  if (!statusData.value) return { text: '未检测', cls: 'muted' }
  if (!statusData.value.enabled) return { text: '已禁用', cls: 'muted' }
  return statusData.value.ready
    ? { text: '已就绪', cls: 'ok' }
    : { text: '需修复', cls: 'warn' }
})

function syncInputsFromReport(rep: BrowserEnvStatus): void {
  const cfg = rep.config || ({} as BrowserEnvStatus['config'])
  enabledInput.value = cfg.enabled ?? rep.enabled ?? true
  headlessInput.value = cfg.headless ?? true
  fallbackInput.value = cfg.use_system_browser_fallback ?? true
}

async function loadBrowserEnv(probe = false): Promise<void> {
  loading.value = true
  lastError.value = ''
  try {
    const res = await apiGet(`/api/settings/browser_env?probe=${probe ? 'true' : 'false'}`)
    if (res && res.success === false && res.error) {
      lastError.value = res.error
      return
    }
    statusData.value = res as BrowserEnvStatus
    syncInputsFromReport(statusData.value)
  } catch (err: any) {
    lastError.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
}

async function handleRepair(probeLaunch = true): Promise<void> {
  repairing.value = true
  lastError.value = ''
  try {
    const res = await apiPost('/api/settings/browser_env/repair', {
      enabled: enabledInput.value,
      headless: headlessInput.value,
      use_system_browser_fallback: fallbackInput.value,
      auto_install: true,
      probe_launch: probeLaunch
    })
    if (res && res.success === false && res.error) {
      lastError.value = res.error
      appStore.showNotification(`无头浏览器自修复失败: ${res.error}`, 'error')
      return
    }
    statusData.value = res as BrowserEnvStatus
    syncInputsFromReport(statusData.value)
    if (statusData.value.ready) {
      appStore.showNotification('无头浏览器检查与自修复通过', 'success')
    } else if (!statusData.value.enabled) {
      appStore.showNotification('已保存配置：当前禁用无头浏览器自动下载', 'info')
    } else {
      appStore.showNotification('已执行自修复，但浏览器仍未完全就绪，请查看详情', 'warning')
    }
  } catch (err: any) {
    lastError.value = err?.message || String(err)
    appStore.showNotification(`无头浏览器检查失败: ${lastError.value}`, 'error')
  } finally {
    repairing.value = false
  }
}

onMounted(() => {
  void loadBrowserEnv(false)
})
</script>

<template>
  <div class="p-card hb-card">
    <div class="hb-header">
      <div>
        <h3>无头浏览器运行环境与自修复</h3>
        <p class="desc-sm">
          供生工 16S 自动网页下载使用；启动程序时自动检查配置、清理残缺内核并通过国内镜像补齐依赖。
        </p>
      </div>
      <span :class="['hb-badge', stateBadge.cls]">{{ stateBadge.text }}</span>
    </div>

    <div v-if="statusData" class="hb-grid">
      <div class="hb-stat">
        <span class="hb-k">当前引擎模式</span>
        <strong class="hb-v">{{ modeLabel }}</strong>
      </div>
      <div class="hb-stat">
        <span class="hb-k">Playwright / Chromium</span>
        <strong class="hb-v">
          {{ statusData.playwright_version || '-' }} / {{ statusData.expected_version || '-' }}
        </strong>
      </div>
      <div class="hb-stat hb-stat-wide">
        <span class="hb-k">内核存储目录 (PLAYWRIGHT_BROWSERS_PATH)</span>
        <code class="hb-code">{{ statusData.effective_browsers_path || '-' }}</code>
      </div>
    </div>

    <div class="hb-controls">
      <label class="hb-check">
        <input v-model="enabledInput" type="checkbox" :disabled="repairing" />
        <span>启用无头浏览器自动下载与启动自检</span>
      </label>
      <label class="hb-check">
        <input v-model="headlessInput" type="checkbox" :disabled="repairing || !enabledInput" />
        <span>静默无头运行（取消勾选可弹出浏览器窗口以便排查问题）</span>
      </label>
      <label class="hb-check">
        <input v-model="fallbackInput" type="checkbox" :disabled="repairing || !enabledInput" />
        <span>内核缺失或离线时允许使用本机 Edge / Chrome 兜底</span>
      </label>
    </div>

    <div v-if="statusData?.issues?.length" class="hb-list warn-box">
      <div class="hb-list-title">检查发现项</div>
      <ul>
        <li v-for="(item, idx) in statusData.issues" :key="idx">{{ item.message }}</li>
      </ul>
    </div>

    <div v-if="statusData?.actions?.length" class="hb-list ok-box">
      <div class="hb-list-title">自修复执行记录</div>
      <ul>
        <li v-for="(act, idx) in statusData.actions" :key="idx">{{ act }}</li>
      </ul>
    </div>

    <div v-if="statusData?.warnings?.length || lastError" class="hb-list err-box">
      <div class="hb-list-title">告警信息</div>
      <ul>
        <li v-if="lastError">{{ lastError }}</li>
        <li v-for="(w, idx) in (statusData?.warnings || [])" :key="idx">{{ w }}</li>
      </ul>
    </div>

    <div class="hb-actions">
      <button
        class="p-btn p-btn-secondary"
        :disabled="loading || repairing"
        @click="loadBrowserEnv(false)"
      >
        {{ loading ? '检测中...' : '刷新状态' }}
      </button>
      <button
        class="p-btn p-btn-primary"
        :disabled="loading || repairing"
        @click="handleRepair(true)"
      >
        {{ repairing ? '自修复并验证中...' : '应用配置并启动探针自修复' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.hb-card {
  margin-top: 20px;
  margin-bottom: 24px;
}

.hb-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.hb-header h3 {
  margin: 0 0 4px;
}

.hb-badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.hb-badge.ok {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #6ee7b7;
}
.hb-badge.warn {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fcd34d;
}
.hb-badge.muted {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #cbd5e1;
}

.hb-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}

.hb-stat {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hb-stat-wide {
  grid-column: 1 / -1;
}

.hb-k {
  font-size: 11px;
  color: #64748b;
}

.hb-v {
  font-size: 13px;
  color: #0f172a;
}

.hb-code {
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #2563eb;
  word-break: break-all;
}

.hb-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 12px;
}

.hb-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
}

.hb-list {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 12px;
}

.hb-list ul {
  margin: 4px 0 0 18px;
  padding: 0;
}

.hb-list-title {
  font-weight: 700;
}

.warn-box {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

.ok-box {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}

.err-box {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.hb-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
