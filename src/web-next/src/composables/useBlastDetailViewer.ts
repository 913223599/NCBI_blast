/**
 * useBlastDetailViewer - BLAST详细结果查看器组合式函数
 */
import { ref, computed, shallowRef } from 'vue'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge'

export interface BlastHitDetail {
  species?: string
  similarity: string
  evalue: string
  acc?: string
  title?: string
}

export function useBlastDetailViewer() {
  const appStore = useAppStore()
  
  // 内部状态 - 使用 null 作为初始值，更容易检测
  const isOpenInternal = ref(false)
  // 使用 shallowRef 存储大量静态比对数据，极大提升渲染性能
  const allHitsData = shallowRef<BlastHitDetail[]>([])
  const currentQueryTitle = ref<string | null>(null)
  // 关键：添加用户交互标志，防止HMR或初始化时的意外弹窗
  const hasUserInteracted = ref(false)
  // 额外的锁定机制：只有在调用viewAllHits后才允许打开
  const isLocked = ref(true)

  // 只读计算属性：严格控制显示条件
  // 移除 setter，防止任何地方错误地设置弹窗状态
  const showAllHitsDialog = computed(() => {
    // 必须同时满足：1) 未锁定 2) 用户已交互 3) 内部标记为打开 4) 标题是字符串且非空
    // 只有用户主动点击按钮才会打开，其他任何情况下都不会显示
    return isLocked.value === false &&
           hasUserInteracted.value === true &&
           isOpenInternal.value === true &&
           typeof currentQueryTitle.value === 'string' &&
           currentQueryTitle.value.trim().length > 0
  })

  /**
   * 查看所有比对结果
   */
  function viewAllHits(csvFile: string, queryTitle: string): void {
    if (!csvFile || !csvFile.trim()) {
      appStore.showNotification('未找到结果文件', 'warning')
      return
    }
    
    if (!queryTitle || !queryTitle.trim()) {
      console.warn('[DetailViewer] Empty queryTitle')
      return
    }
    
    // 解锁并标记用户已交互，允许弹窗显示
    isLocked.value = false
    hasUserInteracted.value = true
    
    // 先关闭，确保状态干净
    isOpenInternal.value = false
    allHitsData.value = []
    currentQueryTitle.value = null
    
    // 使用setTimeout确保Vue完成基本的弹窗背景更新
    setTimeout(() => {
      currentQueryTitle.value = queryTitle.trim()
      isOpenInternal.value = true
      
      try {
        const bridge = getBridge()
        // [优化] 调用异步解析接口，不再等待回调返回大数据量
        bridge.get_detailed_blast_results(csvFile)
      } catch (error) {
        console.error('[DetailViewer] Request error:', error)
        isOpenInternal.value = false
      }
    }, 50)
  }

  // [优化] 注册全局接收器，处理异步返回的大量比对数据
  if (typeof window !== 'undefined') {
    (window as any)._onDetailedResultsReady = (hits: any[]) => {
      if (Array.isArray(hits)) {
        // 延迟注入，确保弹窗动画丝滑
        setTimeout(() => {
          allHitsData.value = hits
        }, 400)
      } else {
        isOpenInternal.value = false
      }
    }
  }

  /**
   * 关闭弹窗
   */
  function closeDialog(): void {
    // 重新锁定，防止任何意外打开
    isLocked.value = true
    hasUserInteracted.value = false
    isOpenInternal.value = false
    allHitsData.value = []
    currentQueryTitle.value = null
  }

  return {
    showAllHitsDialog,
    allHitsData,
    currentQueryTitle,
    viewAllHits,
    closeDialog,
    // 暴露内部状态供测试使用
    _isOpenInternal: isOpenInternal,
    _hasUserInteracted: hasUserInteracted,
    _isLocked: isLocked
  }
}
