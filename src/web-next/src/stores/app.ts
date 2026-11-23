/*  *//**
 * 全局应用状态 (Pinia Store)
 * 管理语言、主题、通知等应用级别状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getBridge } from '../bridge'

export const useAppStore = defineStore('app', () => {
    /* -------- 状态 -------- */
    const locale = ref<'zh_CN' | 'en_US'>('zh_CN')
    const sidebarCollapsed = ref(false)
    const notifications = ref<Array<{ id: number; message: string; type: string }>>([])
    const pageTitle = ref('Dashboard')
    const translations = ref<Record<string, string>>({})
    const projectRoot = ref('')

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

        // 初始化项目根路径
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

    function fetchTranslations(): Promise<void> {
        return new Promise((resolve) => {
            try {
                const bridge = getBridge()
                bridge.get_ui_translations((res: string) => {
                    if (res && res !== 'null') {
                        try {
                            translations.value = JSON.parse(res)
                            console.log('[AppStore] 界面翻译加载完成')
                        } catch (e) {
                            console.error("Failed to parse loaded translations", e)
                        }
                    } else {
                        console.warn('[AppStore] 收到空翻译包')
                    }
                    resolve()
                })
            } catch (error) {
                console.warn("Bridge missing, local translations kept empty.")
                resolve()
            }
        })
    }

    // ─── 数据同步订阅 (带来源排除与防抖保护) ───────────────────────────────────────
    let syncTimer: ReturnType<typeof setTimeout> | null = null;
    try {
        const bridge = getBridge();
        bridge.sync_event.connect((data: any) => {
            if (!data || !data.module) return;

            // 防抖：防止多个信号瞬间堆叠导致的并发加载
            if (syncTimer) clearTimeout(syncTimer);
            syncTimer = setTimeout(() => {
                if (data.module === 'dictionary' || data.module === 'dictionaries' || data.module === 'config' || data.module === 'all') {
                    console.log('[AppStore] 收到远程词库/配置更新，同步中...');
                    fetchTranslations();
                }
                syncTimer = null;
            }, 500);
        });
    } catch (e) {
        console.warn('[AppStore] WebSocket 同步订阅失败');
    }

    return {
        locale,
        sidebarCollapsed,
        notifications,
        pageTitle,
        translations,
        projectRoot,
        isZhCN,
        toggleSidebar,
        initSidebarState,
        showNotification,
        setLocale,
        setPageTitle,
        fetchTranslations
    }
})
