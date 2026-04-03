/**
 * 全局应用状态 (Pinia Store)
 * 管理语言、主题、通知等应用级别状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getBridge } from '../bridge/pyqt-bridge'

export const useAppStore = defineStore('app', () => {
    /* -------- 状态 -------- */
    const locale = ref<'zh_CN' | 'en_US'>('zh_CN')
    const sidebarCollapsed = ref(false)
    const notifications = ref<Array<{ id: number; message: string; type: string }>>([])
    const pageTitle = ref('Dashboard')
    const translations = ref<Record<string, string>>({})

    /* -------- 计算属性 -------- */
    const isZhCN = computed(() => locale.value === 'zh_CN')

    /* -------- 操作 -------- */
    function toggleSidebar(): void {
        sidebarCollapsed.value = !sidebarCollapsed.value
        localStorage.setItem('sidebar_collapsed', String(sidebarCollapsed.value))
    }

    function initSidebarState(): void {
        const stored = localStorage.getItem('sidebar_collapsed')
        if (stored === 'true') {
            sidebarCollapsed.value = true
        }
    }

    let notifIdCounter = 0
    function showNotification(message: string, type = 'info'): void {
        const id = ++notifIdCounter
        notifications.value.push({ id, message, type })
        setTimeout(() => {
            notifications.value = notifications.value.filter(n => n.id !== id)
        }, 4000)
    }

    function setLocale(lang: 'zh_CN' | 'en_US'): void {
        locale.value = lang
        fetchTranslations() // Reload translations when language changes
    }

    function setPageTitle(title: string): void {
        pageTitle.value = title
    }

    function fetchTranslations(): void {
        try {
            getBridge().get_ui_translations((res: string) => {
                if (res) {
                    try {
                        translations.value = JSON.parse(res)
                    } catch (e) {
                        console.error("Failed to parse loaded translations", e)
                    }
                }
            })
        } catch (error) {
            console.warn("Bridge missing, local translations kept empty.")
        }
    }

    return {
        locale,
        sidebarCollapsed,
        notifications,
        pageTitle,
        translations,
        isZhCN,
        toggleSidebar,
        initSidebarState,
        showNotification,
        setLocale,
        setPageTitle,
        fetchTranslations
    }
})
