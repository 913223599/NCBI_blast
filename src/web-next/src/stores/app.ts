/**
 * 全局应用状态 (Pinia Store)
 * 管理语言、主题、通知等应用级别状态
 */
import { defineStore } from 'pinia'
import { ref, computed, shallowRef, markRaw } from 'vue'
import { getBridge } from '../bridge'

export interface TreeHistoryItem {
    id: string;
    algorithm: string;
    nwk: string;
    filePath?: string;
    idToHash?: Record<string, string>;
    time: number;
    archiveFile?: string;
}

export interface TreeHistoryGroup {
    id: string;
    sourceFile: string;
    name: string;
    items: TreeHistoryItem[];
}

export const useAppStore = defineStore('app', () => {
    /* -------- 状态 -------- */
    const locale = ref<'zh_CN' | 'en_US'>('zh_CN')
    const sidebarCollapsed = ref(false)
    const notifications = ref<Array<{ id: number; message: string; type: string }>>([])
    const pageTitle = ref('Dashboard')
    const translations = ref<Record<string, string>>({})
    const treeHistory = shallowRef<TreeHistoryGroup[]>([])
    const projectRoot = ref('')

    /* -------- 计算属性 -------- */
    const isZhCN = computed(() => locale.value === 'zh_CN')

    /* -------- 操作 -------- */
    function initTreeHistory(): void {
        try {
            const bridge = getBridge()
            if (bridge && typeof bridge.db_load_tree_history === 'function') {
                bridge.db_load_tree_history((res: string) => {
                    if (res && res !== 'null') {
                        try {
                            const parsed = JSON.parse(res) || []
                            treeHistory.value = Object.freeze(parsed)
                        } catch (e) {
                            console.error('Failed to parse tree history', e)
                        }
                    }
                })
            }
        } catch (e) {
            console.warn('Bridge not ready for tree history load')
            const stored = localStorage.getItem('tree_history_records')
            if (stored) {
                try { treeHistory.value = JSON.parse(stored) } catch { }
            }
        }
    }

    function addTreeHistory(nwk: string, algorithm: string, sourceFile: string, filePath?: string, idToHash?: Record<string, string>): void {
        const parts = sourceFile.split(/[\\/]/).filter(Boolean)
        // 健壮性改进：从归档路径中智能提取 Project ID
        // 路径格式通常为: tree_results/ProjectID/SessionID/... 或 ProjectID/SessionID/...
        let projectId = "Unknown"
        if (parts.length >= 3) {
            projectId = parts[parts.length - 2] || "Unknown" // 取 SessionID 的上一级
        } else if (parts.length >= 2) {
            projectId = parts[0] || "Unknown"
        }
        
        const newItem = { 
            id: Math.random().toString(36).substring(2, 7), 
            algorithm, 
            nwk, 
            filePath, 
            idToHash,
            archiveFile: sourceFile,
            time: Date.now() 
        }

        const groupIndex = treeHistory.value.findIndex((g: TreeHistoryGroup) => g.id === projectId)

        if (groupIndex !== -1) {
            const group = treeHistory.value[groupIndex]
            if (group) {
                group.items = [newItem, ...group.items].slice(0, 20)
                treeHistory.value = [group, ...treeHistory.value.filter((g: TreeHistoryGroup) => g.id !== projectId)]
            }
        } else {
            const displayName = projectId.replace(/\.[^/.]+$/, "")
            treeHistory.value = [{
                id: projectId,
                sourceFile: projectId, 
                name: displayName,
                items: [newItem]
            }, ...treeHistory.value.slice(0, 20)]
        }
        
        // 保存到后端
        try {
            const bridge = getBridge()
            if (bridge && typeof bridge.db_save_tree_history === 'function') {
                bridge.db_save_tree_history(treeHistory.value, (res: string) => {
                    console.log('[AppStore] Tree history synced to backend:', res)
                })
            }
        } catch (e) {
            console.warn('[AppStore] Bridge fail, saving history to localStorage')
            localStorage.setItem('tree_history_records', JSON.stringify(treeHistory.value))
        }
    }

    function removeTreeHistory(groupId: string, itemId?: string, physical: boolean = false): void {
        const groupIndex = treeHistory.value.findIndex((g: TreeHistoryGroup) => g.id === groupId)
        if (groupIndex === -1) return
        const group = treeHistory.value[groupIndex]
        if (!group) return

        if (!itemId) {
            // 删除整个项目组 - 立即从本地状态移除，防止竞态
            treeHistory.value = treeHistory.value.filter(g => g.id !== groupId)
            try {
                getBridge().db_delete_tree_history(groupId, physical)
            } catch (e) { }
        } else {
            // 删除组内单个项
            group.items = group.items.filter((i: TreeHistoryItem) => i.id !== itemId)
            if (group.items.length === 0) {
                treeHistory.value = treeHistory.value.filter((g: TreeHistoryGroup) => g.id !== groupId)
                try { getBridge().db_delete_tree_history(groupId, physical) } catch (e) { }
            } else {
                // 如果只删项但不删组物理目录，目前后端 db_save_tree_history 仅支持全量覆盖
                try { getBridge().db_save_tree_history(treeHistory.value) } catch (e) { }
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

    // 自动化同步已按需彻底禁用

    return {
        locale,
        sidebarCollapsed,
        notifications,
        pageTitle,
        translations,
        treeHistory,
        projectRoot,
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
