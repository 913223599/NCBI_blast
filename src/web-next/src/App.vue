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

onMounted(async () => {
  appStore.initSidebarState()
  const blastStore = useBlastStore()

  // 1. 立即定义全局桥接回调，确保 Python 随时可以调用
  const globalApp = {
    handleFileLoaded: (content: string, type: string, path: string) => {
      console.log(`[Bridge->App] File Loaded: ${path} (${type})`)
      // 弹出轻量通知以确认通信
      appStore.showNotification(`已从本地添加文件: ${path.split(/[/\\]/).pop()}`, 'success')
      
      if (type === 'fasta' || type === 'sequence' || !type) {
        blastStore.addFile(path)
      } else if (type === 'tree') {
        (window as any).treeView?.loadNewick(content)
      }
    },
    handleFilesDropped: (paths: string[]) => {
      console.log('[Bridge->App] Files Dropped:', paths)
      appStore.showNotification(`检测到 ${paths.length} 个文件拖入`, 'info')
      paths.forEach(p => blastStore.addFile(p))
    },
    showNotification: (msg: string, type: string = 'info') => {
      appStore.showNotification(msg, type as any)
    }
  }

  if (typeof window !== 'undefined') {
    (window as any).app = globalApp
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
