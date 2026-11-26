<script setup lang="ts">
/**
 * App.vue - 应用根组件
 * 负责整体布局：侧边栏 + 头部 + 路由视图
 */
import { onMounted, onUnmounted } from 'vue'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'
import NotificationStack from './components/common/NotificationStack.vue'
import AppConfirmDialog from './components/common/AppConfirmDialog.vue'
import { useAppStore } from './stores/app'
import type { NotificationItem } from './stores/app'
import { setupBridge, getBridge, getClientId, onEvent } from './bridge'
import { useBlastStore } from './stores/blast'
import { useStrainStore } from './stores/strain'
import { createLogger } from './utils/logger'

const logger = createLogger('App')
const appStore = useAppStore()

interface TreeViewGlobalHook {
  loadNewick?: (content: string) => void
  handleExternalFiles?: (paths: string[]) => void
  setLoading?: (loading: boolean, message?: string, percent?: number) => void
}

interface BioStationWindow extends Window {
  treeView?: TreeViewGlobalHook
  app?: {
    handleFileLoaded: (content: string, type: string, path: string) => Promise<void>
    handleFilesDropped: (paths: string[]) => Promise<void>
    showNotification: (msg: string, type?: NotificationItem['type']) => void
    showLoading: (msg: string) => void
    hideLoading: () => void
    updateLoading: (percent: number, msg: string) => void
  }
  showLoading?: (msg: string) => void
  hideLoading?: () => void
  updateLoading?: (percent: number, msg: string) => void
  _onDetailedResultsReady?: (hits: unknown) => void
}

onMounted(async () => {
  appStore.initSidebarState()
  const blastStore = useBlastStore()
  const strainStore = useStrainStore()
  const win = window as BioStationWindow

  const globalApp = {
    handleFileLoaded: async (content: string, type: string, path: string) => {
      const currentRoute = window.location.hash
      if (currentRoute.includes('tree')) {
        if (type === 'tree') {
          win.treeView?.loadNewick?.(content)
          appStore.showNotification(`已解析树结构: ${path.split(/[/\\]/).pop()}`, 'success')
        } else {
          appStore.showNotification('检测到序列文件，请在左侧面板点击“载入”', 'info')
        }
      } else if (type === 'fasta' || type === 'sequence' || !type) {
        if (path.toLowerCase().endsWith('.zip')) {
          appStore.showNotification(`正在解压并识别序列: ${path.split(/[/\\]/).pop()}`, 'info')
          const res = await getBridge().process_blast_files([path])
          if (res && res.success && res.paths) {
            res.paths.forEach((p: string) => blastStore.addFile(p))
            appStore.showNotification(`成功载入 ${res.paths.length} 条序列`, 'success')
          }
        } else {
          blastStore.addFile(path)
          appStore.showNotification(`已添加序列文件: ${path.split(/[/\\]/).pop()}`, 'success')
        }
      }
    },
    handleFilesDropped: async (paths: string[]) => {
      const currentRoute = window.location.hash
      if (currentRoute.includes('tree')) {
        appStore.showNotification(`正在导入 ${paths.length} 个项目到进化树工作区...`, 'info')
        win.treeView?.handleExternalFiles?.(paths)
      } else {
        appStore.showNotification(`正在处理 ${paths.length} 个比对项...`, 'info')
        const res = await getBridge().process_blast_files(paths)
        if (res && res.success && res.paths) {
          res.paths.forEach((p: string) => blastStore.addFile(p))
          appStore.showNotification(`成功导入 ${res.paths.length} 个比对文件`, 'success')
        } else {
          paths.forEach((p) => blastStore.addFile(p))
        }
      }
    },
    showNotification: (msg: string, type: NotificationItem['type'] = 'info') => {
      appStore.showNotification(msg, type)
    },
    showLoading: (msg: string) => {
      win.treeView?.setLoading?.(true, msg)
    },
    hideLoading: () => {
      win.treeView?.setLoading?.(false)
    },
    updateLoading: (percent: number, msg: string) => {
      win.treeView?.setLoading?.(true, msg, percent)
    },
  }

  if (typeof window !== 'undefined') {
    win.app = globalApp
    win.showLoading = globalApp.showLoading
    win.hideLoading = globalApp.hideLoading
    win.updateLoading = globalApp.updateLoading
  }

  try {
    const bridge = await setupBridge()

    const clientId = getClientId()
    if (!clientId || clientId === 'unknown') {
      appStore.showNotification('检测到系统版本更新，请刷新页面以加载最新组件', 'warning')
      window.location.reload()
      return
    }

    onEvent((type: string, data: unknown) => {
      if (type === 'single_result_update') {
        try {
          const resultObj = typeof data === 'string' ? JSON.parse(data) : data
          blastStore.appendSingleResult(resultObj)
        } catch (e) {
          logger.error('Failed to parse single result stream', e)
        }
      } else if (type === 'translation_done') {
        try {
          const dataObj = (typeof data === 'string' ? JSON.parse(data) : data) as {
            original?: string
            translated?: string
          }
          if (dataObj.original && dataObj.translated) {
            blastStore.updateTranslation(dataObj.original, dataObj.translated)
          }
        } catch (e) {
          logger.error('Failed to parse translation update', e)
        }
      } else if (type === 'detailed_results_ready') {
        try {
          const hits = typeof data === 'string' ? JSON.parse(data) : data
          win._onDetailedResultsReady?.(hits)
        } catch (e) {
          logger.error('Failed to parse detailed results stream', e)
        }
      }
    })

    if (typeof bridge.on_page_ready === 'function') {
      bridge.on_page_ready()
    }

    await appStore.fetchTranslations()

    const blastWithLoader = blastStore as typeof blastStore & { loadAllHistory?: () => Promise<void> }
    void Promise.allSettled([
      strainStore.initFromDatabase(),
      typeof blastWithLoader.loadAllHistory === 'function'
        ? blastWithLoader.loadAllHistory()
        : Promise.resolve(),
    ])
  } catch (err) {
    logger.error('初始化链崩溃:', err)
  }
})

function preventDefaultDrag(e: DragEvent) {
  e.preventDefault()
}

onMounted(() => {
  window.addEventListener('dragover', preventDefaultDrag, false)
  window.addEventListener('drop', preventDefaultDrag, false)
})

onUnmounted(() => {
  window.removeEventListener('dragover', preventDefaultDrag, false)
  window.removeEventListener('drop', preventDefaultDrag, false)
})
</script>

<template>
  <div id="bio-station" :class="{ 'sidebar-collapsed': appStore.sidebarCollapsed }">
    <AppSidebar />
    <div class="main-wrapper">
      <AppHeader />
      <main class="main-content">
        <RouterView v-slot="{ Component }">
          <KeepAlive :max="4" :exclude="['FigureStudioView', 'HelpView']">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>
    <NotificationStack />
    <AppConfirmDialog />
  </div>
</template>

<style>
#bio-station {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-page);
  font-family: 'Inter', 'Segoe UI', -apple-system, sans-serif;
}

.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.main-content {
  flex: 1;
  overflow: auto;
  padding: 0;
  position: relative;
}
</style>
