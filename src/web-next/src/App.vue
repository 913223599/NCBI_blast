<script setup lang="ts">
/**
 * App.vue - 应用根组件
 * 负责整体布局：侧边栏 + 头部 + 路由视图
 */
import { onMounted } from 'vue'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'
import NotificationStack from './components/common/NotificationStack.vue'
import { useAppStore } from './stores/app'
import { initBridge, registerGlobalHandler } from './bridge/pyqt-bridge'

const appStore = useAppStore()

import { useBlastStore } from './stores/blast'
import { useStrainStore } from './stores/strain'

onMounted(async () => {
  appStore.initSidebarState()
  const blastStore = useBlastStore()
  const strainStore = useStrainStore()

  // 1. 立即定义全局桥接回调，确保 Python 随时可以调用
  const globalApp = {
    handleFileLoaded: (content: string, type: string, path: string) => {
      console.log(`[Bridge->App] File Loaded: ${path} (${type})`)
      appStore.showNotification(`已从本地添加文件: ${path.split(/[/\\]/).pop()}`, 'success')
      
      const currentRoute = window.location.hash // Simple way to check route in SPA
      if (currentRoute.includes('tree')) {
         // 如果在进化树页面，且加载的是 tree 类型或通用 fasta
         if (type === 'tree') {
            (window as any).treeView?.loadNewick(content)
         } else {
            // 提示：Tree 页面目前主要通过 side panel 处理序列，
            // 但如果用户直接拖入 fasta，我们可以尝试后续支持
            appStore.showNotification('检测到序列文件，请在左侧面板点击“载入”', 'info')
         }
      } else {
         // 默认逻辑：放入 BLAST
         if (type === 'fasta' || type === 'sequence' || !type) {
           blastStore.addFile(path)
         }
      }
    },
    handleFilesDropped: (paths: string[]) => {
      console.log('[Bridge->App] Files Dropped:', paths)
      const currentRoute = window.location.hash
      
      if (currentRoute.includes('tree')) {
        // [修复] 如果在进化树页面，不应该进入 BLAST 列表
        appStore.showNotification(`检测到 ${paths.length} 个文件拖入进化树工作区`, 'success')
        // 这里可以调用 treeView 组件的方法来处理这些路径
        if ((window as any).treeView?.handleExternalFiles) {
          (window as any).treeView.handleExternalFiles(paths)
        } else {
          // Fallback: 提示用户在左侧操作
          console.warn('TreeView has no handleExternalFiles handler yet.')
        }
      } else {
        // BLAST 页面逻辑
        appStore.showNotification(`检测到 ${paths.length} 个文件拖入比对列表`, 'info')
        paths.forEach(p => blastStore.addFile(p))
      }
    },
    showNotification: (msg: string, type: string = 'info') => {
      appStore.showNotification(msg, type as any)
    },
    showLoading: (msg: string) => {
      // Proxy to active view if it handles loading
      if ((window as any).treeView?.setLoading) {
        (window as any).treeView.setLoading(true, msg)
      }
    },
    hideLoading: () => {
      if ((window as any).treeView?.setLoading) {
        (window as any).treeView.setLoading(false)
      }
    },
    updateLoading: (percent: number, msg: string) => {
      if ((window as any).treeView?.setLoading) {
        (window as any).treeView.setLoading(true, msg, percent)
      }
    }
  }

  if (typeof window !== 'undefined') {
    (window as any).app = globalApp
    // Also bind directly to window for legacy/simplified calls from Python
    const win = window as any
    win.showLoading = globalApp.showLoading
    win.hideLoading = globalApp.hideLoading
    win.updateLoading = globalApp.updateLoading
  }

  // 2. 初始化 QWebChannel 桥接
  const bridge = await initBridge()

  // 3. 注册通用事件处理
  registerGlobalHandler('handleBridgeEvent', (type: any, data: any) => {
    if (type === 'single_result_update') {
      try {
        const resultObj = typeof data === 'string' ? JSON.parse(data) : data
        blastStore.appendSingleResult(resultObj)
      } catch (e) {
        console.error('Failed to parse single result stream', e)
      }
    } else if (type === 'translation_done') {
      try {
        const dataObj = typeof data === 'string' ? JSON.parse(data) : data
        blastStore.updateTranslation(dataObj.original, dataObj.translated)
      } catch (e) {
        console.error('Failed to parse translation update', e)
      }
    }
  })

  // 4. 通知 Python 页面已就绪
  bridge.on_page_ready()
  
  // 5. 初始化加载由后端注入的当前语言包
  appStore.fetchTranslations()

  // 6. 从 SQLite 数据库初始化样本数据
  strainStore.initFromDatabase()
})
</script>

<template>
  <div id="bio-station" :class="{ 'sidebar-collapsed': appStore.sidebarCollapsed }">
    <AppSidebar />
    <div class="main-wrapper">
      <AppHeader />
      <main class="main-content">
        <RouterView v-slot="{ Component }">
          <KeepAlive>
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>
    <NotificationStack />
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
  /* transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1); */
}

.main-content {
  flex: 1;
  overflow: auto;
  padding: 0;
  position: relative;
}

</style>
