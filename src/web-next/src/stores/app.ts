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
        items: Array<{ id: string; algorithm: string; nwk: string; filePath?: string; idToHash?: Record<string, string>; time: number }> 
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

    function addTreeHistory(nwk: string, algorithm: string, sourceFile: string, filePath?: string, idToHash?: Record<string, string>): void {
        // 核心解耦：提取逻辑项目 ID (Project ID)
        // sourceFile 格式规范： "ProjectName/SessionDir/FileName.fasta" 或 "Legacy_FileName.fasta"
        const parts = sourceFile.split(/[\\/]/)
        // 关键修复：增加安全 fallback 解决 lint 告警
        const firstPart = parts[0] || "Unknown"
        const logicalId = firstPart.replace(/^Tree_\d+_\d+_/g, "")
        
        // 每个 item 携带自己的物理指纹路径，以及内容哈希字典，用于断开 ID 依赖
        const newItem = { 
            id: Math.random().toString(36).substring(2, 7), 
            algorithm, 
            nwk, 
            filePath, 
            idToHash,
            archiveFile: sourceFile, // 记录后端提供的完整相对档案路径
            time: Date.now() 
        }

        let group = treeHistory.value.find(g => g.sourceFile === logicalId)

        if (group) {
            // 项目内合并：允许无限次多版本并存，支持深度对比分析
            group.items = [newItem, ...group.items].slice(0, 20)
            // 刷新组在列表中的排序（置顶最近操作的项目）
            treeHistory.value = [group, ...treeHistory.value.filter(g => g.sourceFile !== logicalId)]
        } else {
            // 新建逻辑项目组
            const displayName = logicalId.replace(/\.[^/.]+$/, "") // 去除项目 ID 后的扩展名
            treeHistory.value = [{
                id: Math.random().toString(36).substring(2, 9),
                sourceFile: logicalId, 
                name: displayName,
                items: [newItem]
            }, ...treeHistory.value.slice(0, 20)]
        }
        localStorage.setItem('tree_history_records', JSON.stringify(treeHistory.value))
    }

    function removeTreeHistory(groupId: string, itemId?: string): void {
        const group = treeHistory.value.find(g => g.id === groupId)
        if (!group) return

        try {
            const bridge = (window as any).pywebview?.api || (window as any).qtBridge || (window as any).chrome?.webview?.hostObjects?.bridge
            
            if (!itemId) {
                // 物理连坐：一键删除整个项目目录
                if (bridge && typeof bridge.delete_tree_archive === 'function') {
                    bridge.delete_tree_archive(group.sourceFile)
                }
                treeHistory.value = treeHistory.value.filter(g => g.id !== groupId)
            } else {
                const item = group.items.find(i => i.id === itemId)
                // 物理销毁：删除特定版本的实验快照
                if (item && bridge && typeof bridge.delete_tree_archive === 'function') {
                    const archPath = (item as any).archiveFile || (item.filePath ? item.filePath.split(/[\\/]/).pop() : '')
                    if (archPath) bridge.delete_tree_archive(archPath)
                }
                
                group.items = group.items.filter(i => i.id !== itemId)
                if (group.items.length === 0) treeHistory.value = treeHistory.value.filter(g => g.id !== groupId)
            }
        } catch (e) {
            console.warn("Physical cleanup skipped: Bridge not ready", e)
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
