/**
 * useBlastDetailViewer Composable 单元测试
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import * as bridgeModule from '../../bridge/pyqt-bridge'
import { useBlastDetailViewer } from '../useBlastDetailViewer'

// Mock app store
vi.mock('../../stores/app', () => ({
  useAppStore: () => ({
    showNotification: vi.fn()
  })
}))

describe('useBlastDetailViewer', () => {
  let viewer: ReturnType<typeof useBlastDetailViewer>
  let mockGetDetailedResults: any

  beforeEach(() => {
    // 初始化 Pinia
    setActivePinia(createPinia())
    
    // Mock bridge
    mockGetDetailedResults = vi.fn((csvFile, callback) => {
      Promise.resolve().then(() => {
        callback(JSON.stringify([
          { species: 'Test Species', similarity: '99.5', evalue: '1e-50', acc: 'ACC123', title: 'Test Title' }
        ]))
      })
    })
    
    vi.spyOn(bridgeModule, 'getBridge').mockReturnValue({
      get_detailed_blast_results: mockGetDetailedResults
    } as any)
    
    // 创建 viewer 实例
    viewer = useBlastDetailViewer()
  })
  
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('初始状态应该是关闭的', () => {
    expect(viewer.showAllHitsDialog.value).toBe(false)
    expect(viewer._isLocked.value).toBe(true)
    expect(viewer.currentQueryTitle.value).toBeNull()
    expect(viewer.allHitsData.value).toEqual([])
  })

  it('viewAllHits 应该在参数有效时打开弹窗', async () => {
    viewer.viewAllHits('test.csv', 'Test Query')
    
    // 等待异步操作完成
    await new Promise(resolve => setTimeout(resolve, 100))
    await nextTick()
    await nextTick()
    
    expect(viewer.showAllHitsDialog.value).toBe(true)
    expect(viewer.currentQueryTitle.value).toBe('Test Query')
    expect(viewer.allHitsData.value).toHaveLength(1)
    expect(viewer._isLocked.value).toBe(false)
  })

  it('viewAllHits 应该在csvFile为空时拒绝', () => {
    viewer.viewAllHits('', 'Test Query')
    expect(viewer.showAllHitsDialog.value).toBe(false)
    expect(viewer._isLocked.value).toBe(true)
  })

  it('viewAllHits 应该在queryTitle为空时拒绝', () => {
    viewer.viewAllHits('test.csv', '')
    expect(viewer.showAllHitsDialog.value).toBe(false)
    expect(viewer._isLocked.value).toBe(true)
  })

  it('closeDialog 应该关闭弹窗并清理状态', () => {
    viewer._isLocked.value = false
    viewer._hasUserInteracted.value = true
    viewer._isOpenInternal.value = true
    ;(viewer as any).currentQueryTitle.value = 'Test'
    viewer.allHitsData.value = [{ species: 'Test', similarity: '99', evalue: '1e-50' }]
    
    viewer.closeDialog()
    
    expect(viewer.showAllHitsDialog.value).toBe(false)
    expect(viewer._isLocked.value).toBe(true)
    expect(viewer.currentQueryTitle.value).toBeNull()
    expect(viewer.allHitsData.value).toEqual([])
  })

  it('计算属性应该在title为空时返回false', () => {
    viewer._isLocked.value = false
    viewer._hasUserInteracted.value = true
    viewer._isOpenInternal.value = true
    ;(viewer as any).currentQueryTitle.value = ''
    
    expect(viewer.showAllHitsDialog.value).toBe(false)
  })

  it('计算属性应该在title有值时返回true', () => {
    // 解锁并设置状态
    viewer._isLocked.value = false
    viewer._hasUserInteracted.value = true
    viewer._isOpenInternal.value = true
    ;(viewer as any).currentQueryTitle.value = 'Valid Title'
    
    expect(viewer.showAllHitsDialog.value).toBe(true)
  })

  it('多次调用viewAllHits应该重置状态', async () => {
    viewer.viewAllHits('test1.csv', 'Query 1')
    await new Promise(resolve => setTimeout(resolve, 100))
    await nextTick()
    await nextTick()
    expect(viewer.showAllHitsDialog.value).toBe(true)
    expect(viewer.currentQueryTitle.value).toBe('Query 1')
    
    viewer.viewAllHits('test2.csv', 'Query 2')
    await new Promise(resolve => setTimeout(resolve, 100))
    await nextTick()
    await nextTick()
    expect(viewer.showAllHitsDialog.value).toBe(true)
    expect(viewer.currentQueryTitle.value).toBe('Query 2')
    expect(viewer._isLocked.value).toBe(false)
  })

  it('应该能正确处理关闭后再打开', async () => {
    viewer.viewAllHits('test1.csv', 'Query 1')
    await new Promise(resolve => setTimeout(resolve, 100))
    await nextTick()
    await nextTick()
    expect(viewer.showAllHitsDialog.value).toBe(true)
    expect(viewer._isLocked.value).toBe(false)
    
    viewer.closeDialog()
    expect(viewer.showAllHitsDialog.value).toBe(false)
    expect(viewer._isLocked.value).toBe(true)
    expect(viewer._hasUserInteracted.value).toBe(false)
    
    viewer.viewAllHits('test2.csv', 'Query 2')
    await new Promise(resolve => setTimeout(resolve, 100))
    await nextTick()
    await nextTick()
    expect(viewer.showAllHitsDialog.value).toBe(true)
    expect(viewer._isLocked.value).toBe(false)
    expect(viewer.currentQueryTitle.value).toBe('Query 2')
  })
})
