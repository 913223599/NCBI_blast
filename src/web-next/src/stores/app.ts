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
    const treeHistory = ref<Array<{ 
        id: string; 
        sourceFile: string; 
        name: string; 
        items: Array<{ id: string; algorithm: string; nwk: string; filePath?: string; time: number }> 
    }>>([])

    /* -------- 计算属性 -------- */
    const isZhCN = computed(() => locale.value === 'zh_CN')

    /* -------- 操作 -------- */
    function initTreeHistory(): void {
        const stored = localStorage.getItem('tree_history_records')
        if (stored) {
            try { 
                const raw = JSON.parse(stored)
                // 自动迁移逻辑：如果发现是旧格式（Flat Array），则进行包装
                if (Array.isArray(raw) && raw.length > 0 && !('items' in raw[0])) {
                    treeHistory.value = [{
                        id: 'legacy_group',
                        sourceFile: 'legacy',
                        name: '历史导入 (Legacy Records)',
                        items: raw.map((old: any) => ({
                            id: old.id,
                            algorithm: 'Imported',
                            nwk: old.nwk,
                            time: old.time || Date.now()
                        }))
                    }]
                } else {
                    treeHistory.value = raw 
                }
            } catch (e) { 
                treeHistory.value = [] 
            }
        }
    }

    function addTreeHistory(nwk: string, name: string, algorithm: string, sourceFile: string, filePath?: string): void {
        let group = treeHistory.value.find(g => g.sourceFile === sourceFile)
        const newItem = { id: Math.random().toString(36).substring(2, 7), algorithm, nwk, filePath, time: Date.now() }

        if (group) {
            group.items = [newItem, ...group.items.filter(i => i.algorithm !== algorithm).slice(0, 9)]
            treeHistory.value = [group, ...treeHistory.value.filter(g => g.sourceFile !== sourceFile)]
        } else {
            treeHistory.value = [{
                id: Math.random().toString(36).substring(2, 9),
                sourceFile, name, items: [newItem]
            }, ...treeHistory.value.slice(0, 14)]
        }
        localStorage.setItem('tree_history_records', JSON.stringify(treeHistory.value))
    }

    function removeTreeHistory(groupId: string, itemId?: string): void {
        if (!itemId) {
            treeHistory.value = treeHistory.value.filter(g => g.id !== groupId)
        } else {
            const group = treeHistory.value.find(g => g.id === groupId)
            if (group) {
                group.items = group.items.filter(i => i.id !== itemId)
                if (group.items.length === 0) treeHistory.value = treeHistory.value.filter(g => g.id !== groupId)
            }
        }
        localStorage.setItem('tree_history_records', JSON.stringify(treeHistory.value))
    }
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
        treeHistory,
        isZhCN,
        toggleSidebar,
        initSidebarState,
        initTreeHistory,
        addTreeHistory,
        removeTreeHistory,
        showNotification,
        setLocale,
        setPageTitle,
        fetchTranslations
    }
})
