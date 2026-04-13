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
import { setupBridge, registerGlobalHandler, getBridge, getClientId } from './bridge'

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
      console.log(`[Bridge->App] File Loaded: ${path} (${type})`)
      
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
      console.log('[Bridge->App] Files Dropped:', paths)
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

  // 1. 全局加载状态控制
  console.log('[App] 初始化应用...')
  
    // 2. 初始化桥接 (并强制进行版本/身份检查)
    try {
      const bridge = await setupBridge()
      console.log('[App] 桥接准备就绪')
      
      const clientId = getClientId();
      if (!clientId || clientId === 'unknown') {
         alert('检测到系统版本更新，请刷新页面以加载最新安全组件');
         window.location.reload();
         return;
      }
      console.log(`[App] 身份验证成功: ${clientId}`);

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
      } else if (type === 'detailed_results_ready') {
        try {
          const hits = typeof data === 'string' ? JSON.parse(data) : data
          if ((window as any)._onDetailedResultsReady) {
            (window as any)._onDetailedResultsReady(hits)
          }
        } catch (e) {
          console.error('Failed to parse detailed results stream', e)
        }
      } else if (type === 'tree_progress') {
        globalApp.updateLoading(data.percent || 0, data.msg || '正在分析...')
      } else if (type === 'tree_finished') {
        globalApp.hideLoading()
        if ((window as any).treeView?.loadNewick) {
          (window as any).treeView.loadNewick(
            data.tree_file_content || data.tree_file, 
            data.algorithm, 
            data.source,
            undefined,
            false,
            data.id_to_hash
          )
        }
      } else if (type === 'tree_error') {
        globalApp.hideLoading()
        appStore.showNotification(`分析失败: ${data.error || data}`, 'error')
      }
    })

    // 4. 初始化应用数据
    console.log('[App] 正在同步后端数据...')
    
    // 通知 Python 页面已就绪
    if (typeof bridge.on_page_ready === 'function') {
      bridge.on_page_ready()
    }
    
    // 加载语言 & 翻译
    console.log('[App] 正在加载语言包...')
    await appStore.fetchTranslations()

    // 初始化各个数据库状态
    console.log('[App] 正在初始化数据库...')
    await strainStore.initFromDatabase()
    
    // 初始化树历史
    appStore.initTreeHistory()
    
    // 如果有 loadAllHistory 等方法，也应在此调用
    if (typeof (blastStore as any).loadAllHistory === 'function') {
      await (blastStore as any).loadAllHistory()
    }

    console.log('[App] 初始化完成')
    
    // 全局禁用默认拖放行为（防止 Electron 意外导航）
    window.addEventListener('dragover', (e) => e.preventDefault(), false)
    window.addEventListener('drop', (e) => e.preventDefault(), false)
  } catch (err) {
    console.error('[App] 初始化链崩溃:', err)
  }
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
  /* transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1); backface-visibility: hidden; -webkit-backface-visibility: hidden; */
}

.main-content {
  flex: 1;
  overflow: auto;
  padding: 0;
  position: relative;
}

</style>