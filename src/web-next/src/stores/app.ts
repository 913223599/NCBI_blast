/**
 * 全局应用状态 (Pinia Store)
 * 管理语言、侧边栏、通知、页面标题及后端翻译热覆盖状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getBridge } from '../bridge'
import type { AppLocale } from '../locales'

function readInitialLocale(): AppLocale {
  try {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('app_locale') : null
    if (saved === 'en_US' || saved === 'zh_CN') return saved
  } catch {
    // 忽略受限存储环境
  }
  return 'zh_CN'
}

export interface NotificationItem {
  id: number
  message: string
  type: string
}

export const useAppStore = defineStore('app', () => {
  /* -------- 状态 -------- */
  const locale = ref<AppLocale>(readInitialLocale())
  const sidebarCollapsed = ref(false)
  const notifications = ref<NotificationItem[]>([])
  const pageTitle = ref('Dashboard')
  const translations = ref<Record<string, string>>({})
  const translationsLocale = ref<AppLocale | null>(null)
  const projectRoot = ref('')

  /* -------- 计算属性 -------- */
  const isZhCN = computed(() => locale.value === 'zh_CN')

  /* -------- 操作 -------- */

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    try {
      localStorage.setItem('sidebar_collapsed', String(sidebarCollapsed.value))
    } catch {
      // 忽略受限存储环境
    }
  }

  function initSidebarState(): void {
    try {
      const stored = localStorage.getItem('sidebar_collapsed')
      if (stored === 'true') {
        sidebarCollapsed.value = true
      }
    } catch {
      // 忽略受限存储环境
    }

    if (window.electronAPI?.getProjectRoot) {
      window.electronAPI.getProjectRoot().then((root: string) => {
        projectRoot.value = root
      })
    }
  }

  let notifIdCounter = 0
  function showNotification(message: string, type = 'info'): void {
    const id = ++notifIdCounter
    notifications.value.push({ id, message, type })
    setTimeout(() => {
      notifications.value = notifications.value.filter((n) => n.id !== id)
    }, 4000)
  }

  function setLocale(lang: AppLocale): void {
    locale.value = lang
    translations.value = {}
    translationsLocale.value = null
    try {
      localStorage.setItem('app_locale', lang)
    } catch {
      // 忽略受限存储环境
    }
    void fetchTranslations(lang)
  }

  function setPageTitle(title: string): void {
    pageTitle.value = title
  }

  function fetchTranslations(targetLang?: AppLocale): Promise<void> {
    const requestedLang = targetLang ?? locale.value
    return new Promise((resolve) => {
      try {
        const bridge = getBridge() as {
          get_ui_translations?: (cb: (res: string) => void, lang?: string) => void
        }
        if (typeof bridge.get_ui_translations !== 'function') {
          resolve()
          return
        }
        bridge.get_ui_translations((res: string) => {
          if (res && res !== 'null' && locale.value === requestedLang) {
            try {
              const parsed = JSON.parse(res)
              if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
                translations.value = parsed
                translationsLocale.value = requestedLang
              }
            } catch (e) {
              console.error('Failed to parse loaded translations', e)
            }
          }
          resolve()
        }, requestedLang)
      } catch {
        resolve()
      }
    })
  }

  // 数据同步订阅（防抖保护）
  let syncTimer: ReturnType<typeof setTimeout> | null = null
  try {
    const bridge = getBridge()
    bridge.sync_event.connect((data: { module?: string } | null) => {
      if (!data || !data.module) return
      if (syncTimer) clearTimeout(syncTimer)
      syncTimer = setTimeout(() => {
        if (
          data.module === 'dictionary' ||
          data.module === 'dictionaries' ||
          data.module === 'config' ||
          data.module === 'all'
        ) {
          void fetchTranslations()
        }
        syncTimer = null
      }, 500)
    })
  } catch {
    // 非实时通信环境静默跳过
  }

  return {
    locale,
    sidebarCollapsed,
    notifications,
    pageTitle,
    translations,
    translationsLocale,
    projectRoot,
    isZhCN,
    toggleSidebar,
    initSidebarState,
    showNotification,
    setLocale,
    setPageTitle,
    fetchTranslations,
  }
})
