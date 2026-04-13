import { getBridge } from '../../bridge'

export function useSyncActions(state: any, recordsActions: any) {
  const { 
    freezers, 
    records, 
    codeLookupEntries, 
    sourceEntries, 
    serialCounters, 
    codeConfig, 
    isInitialized,
    locationMap
  } = state

  let isLoading = false

  /**
   * 纯静态加载逻辑：
   * 仅在启动或手动刷新时执行一次。
   * 完全剥离 WebSocket 监听，杜绝任何“被动触发”的可能性。
   */
  async function initFromDatabase() {
    if (isLoading) return
    isLoading = true
    
    try {
      const bridge = getBridge()
      bridge.db_load_all((result: any) => {
        if (!result) { isLoading = false; return }

        try {
          const data = typeof result === 'string' ? JSON.parse(result) : result
          if (!data) { isLoading = false; return }

          // A. 冰箱管理 (使用极简 Object.freeze 隔离)
          if (data.freezers) {
            const map: Record<string, string> = {}
            data.freezers.forEach((f: any) => {
              map[f.id] = f.name
              f.shelves?.forEach((s: any) => {
                map[s.id] = s.name
                s.cabinets?.forEach((c: any) => {
                  map[c.id] = c.name
                  c.drawers?.forEach((d: any) => {
                    map[d.id] = d.name
                    d.boxes?.forEach((b: any) => {
                      map[b.id] = b.name
                    })
                  })
                })
              })
            })
            freezers.value = Object.freeze(data.freezers)
            locationMap.value = Object.freeze(map)
          }

          // B. 样本记录 (使用 Object.freeze 物理断绝对响应式系统的依赖)
          if (data.records) {
            // 脱水处理：列表页不需要庞大的序列/元数据
            const dehydrated = data.records.map((r: any) => {
               const { sequence, metadata, ...rest } = r
               return Object.freeze(rest)
            })
            records.value = Object.freeze(dehydrated)
          }

          // C. 系统配置
          if (data.codeLookup) {
            codeLookupEntries.value = Object.freeze(data.codeLookup.entries || [])
            sourceEntries.value = Object.freeze(data.codeLookup.sources || [])
            serialCounters.value = Object.freeze(data.codeLookup.counters || [])
            codeConfig.value = data.codeLookup.config || codeConfig.value
          }

          recordsActions.applyFilters()
          isInitialized.value = true
        } catch (e) {
          console.error('[StrainStore] Parse Error', e)
        } finally {
          isLoading = false
        }
      })
    } catch (e) {
      isLoading = false
    }
  }

  return {
    initFromDatabase,
    setupSync: () => {}, // 物理删止同步订阅
    autoSave: () => {},  // 彻底禁用自动保存，防止竞态
    cleanup: () => {}
  }
}
