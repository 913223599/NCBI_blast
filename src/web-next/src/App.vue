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
import { setupBridge, registerGlobalHandler, getBridge, getClientId, onEvent } from './bridge'

const appStore = useAppStore()

import { useBlastStore } from './stores/blast'
import { useStrainStore } from './stores/strain'

onMounted(async () => {
  appStore.initSidebarState()
  const blastStore = useBlastStore()
  const strainStore = useStrainStore()

  // 1. 立即定义全局桥接回调，确保 Python 随时可以调用
  const globalApp = {
    handleFileLoaded: async (content: string, type: string, path: string) => {
      const currentRoute = window.location.hash
      if (currentRoute.includes('tree')) {
         if (type === 'tree') {
            (window as any).treeView?.loadNewick(content)
            appStore.showNotification(`已解析树结构: ${path.split(/[/\\]/).pop()}`, 'success')
         } else {
            appStore.showNotification('检测到序列文件，请在左侧面板点击“载入”', 'info')
         }
      } else {
         // BLAST 逻辑：支持解压
         if (type === 'fasta' || type === 'sequence' || !type) {
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
      }
    },
    handleFilesDropped: async (paths: string[]) => {
      const currentRoute = window.location.hash
      
      if (currentRoute.includes('tree')) {
        appStore.showNotification(`正在导入 ${paths.length} 个项目到进化树工作区...`, 'info')
        if ((window as any).treeView?.handleExternalFiles) {
          (window as any).treeView.handleExternalFiles(paths)
        }
      } else {
        // BLAST 页面逻辑：支持解压
        appStore.showNotification(`正在处理 ${paths.length} 个比对项...`, 'info')
        const res = await getBridge().process_blast_files(paths)
        if (res && res.success && res.paths) {
           res.paths.forEach((p: string) => blastStore.addFile(p))
           appStore.showNotification(`成功导入 ${res.paths.length} 个比对文件`, 'success')
        } else {
           // Fallback if unpack failed
           paths.forEach(p => blastStore.addFile(p))
        }
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

    // 2. 初始化桥接 (并强制进行版本/身份检查)
    try {
      const bridge = await setupBridge()
      
      const clientId = getClientId();
      if (!clientId || clientId === 'unknown') {
         appStore.showNotification('检测到系统版本更新，请刷新页面以加载最新组件', 'warning');
         window.location.reload();
         return;
      }

    // 3. 注册通用事件处理 (使用 onEvent 支持多端监听，防止 Overwrite)
    onEvent((type: any, data: any) => {
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
      } else if (type === 'detailed_results_ready') {
        try {
          const hits = typeof data === 'string' ? JSON.parse(data) : data
          if ((window as any)._onDetailedResultsReady) {
            (window as any)._onDetailedResultsReady(hits)
          }
        } catch (e) {
          console.error('Failed to parse detailed results stream', e)
        }
      }
    })

    // 4. 初始化应用数据（首屏翻译与业务数据解耦，避免串行瀑布阻塞交互）
    if (typeof bridge.on_page_ready === 'function') {
      bridge.on_page_ready()
    }

    await appStore.fetchTranslations()

    // 并行后台预热菌株库与 BLAST 历史，不阻塞首屏渲染与路由切换
    void Promise.allSettled([
      strainStore.initFromDatabase(),
      typeof (blastStore as any).loadAllHistory === 'function'
        ? (blastStore as any).loadAllHistory()
        : Promise.resolve(),
    ])
  } catch (err) {
    console.error('[App] 初始化链崩溃:', err)
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
  /* transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1); backface-visibility: hidden; -webkit-backface-visibility: hidden; */
}

.main-content {
  flex: 1;
  overflow: auto;
  padding: 0;
  position: relative;
}

</style>