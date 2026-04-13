import { getBridge, onEvent } from '../../bridge'

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
  // 物理级“冷却时间”记录，哪怕是页面刷新也无法绕过（存入 sessionStorage）
  const getCooldown = () => {
    return parseInt(sessionStorage.getItem('sync_cooldown') || '0');
  }
  const setCooldown = () => {
    sessionStorage.setItem('sync_cooldown', Date.now().toString());
  }

  async function initFromDatabase() {
    const now = Date.now();
    const lastSync = getCooldown();
    
    // 如果 2500ms 内刚加载过，或者正在加载中，坚决拦截
    if (isLoading || (now - lastSync < 2500)) {
      return;
    }

    isLoading = true
    setCooldown();
    
    try {
      const bridge = getBridge()
      bridge.db_load_all((result: any) => {
        if (!result) { isLoading = false; return }

        try {
          const data = typeof result === 'string' ? JSON.parse(result) : result
          if (!data) { isLoading = false; return }

          // 核心治理：Object.freeze 是防止内存溢出的唯一真神
          if (data.freezers) {
            freezers.value = data.freezers
            const map: Record<string, string> = {}
            const indexLoc = (f: any) => {
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
            }
            locationMap.value = map
          }

          if (data.records) {
            // 彻底脱水，仅保留列表展示必须字段
            const dehydrated = data.records.map((r: any) => {
               const { sequence, metadata, ...rest } = r
               // 暂时保留对历史记录的冻结以防内存溢出，但主目录必须保持活跃
               return rest
            })
            records.value = dehydrated
          }

          if (data.codeLookup) {
            codeLookupEntries.value = data.codeLookup.entries || []
            sourceEntries.value = data.codeLookup.sources || []
            serialCounters.value = data.codeLookup.counters || []
            codeConfig.value = {
              ...codeConfig.value,
              ...data.codeLookup.config
            }
          }

          recordsActions.applyFilters()
          isInitialized.value = true
        } catch (e) {
          console.error('[Sync] Parse Error', e)
        } finally {
          isLoading = false
        }
      })
    } catch (e) {
      isLoading = false
    }
  }

  /* ======== 安全同步逻辑 ======== */
  let cleanupHandler: (() => void) | null = null

  function setupSync() {
    if (cleanupHandler) return
    
    cleanupHandler = onEvent((type: string, data: any) => {
      // 1. 同步全量数据 (通常由其他端修改触发)
      if (type === 'data_updated' && data.module === 'strains') {
        initFromDatabase();
      }
      
      // 2. 差异同步：词典更新
      if (type === 'data_updated' && data.module === 'dictionary') {
        const bridge = getBridge()
        bridge.db_load_code_lookup((res: any) => {
          if (res && res.counters) {
            serialCounters.value = res.counters
          }
          if (res && res.entries) {
            codeLookupEntries.value = res.entries
          }
        })
      }
      
      // 3. 处理 AI 翻译推送的结果
      if (type === 'translation_done' && data.original) {
        const entries = [...codeLookupEntries.value]; 
        let changed = false;
        
        for (let i = 0; i < entries.length; i++) {
           const entry = entries[i];
           if (entry.latinName === data.original || entry.name === data.original) {
              if (data.translated && data.translated !== data.original) {
                 entries[i] = { 
                    ...entry, 
                    name: `${data.translated}(${data.original})`,
                    verified: true 
                 };
                 changed = true;
              }
           }
        }
        
        if (changed) {
           codeLookupEntries.value = entries; 
           autoSave(); 
        }
      }
    })
  }

  let autoSaveTimer: any = null
  
  /**
   * 自动持久化保存：具备防抖能力，防止批量更新时产生请求海啸
   */
  async function autoSave() {
    if (!isInitialized.value) return
    
    // 清除上一个定时器
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    
    // 设置 800ms 防抖，确保批量操作完成后只触发一次网络 IO
    autoSaveTimer = setTimeout(async () => {
      try {
        const bridge = getBridge()
        const data = {
          entries: [...codeLookupEntries.value],
          sources: [...sourceEntries.value],
          counters: [...serialCounters.value],
          config: codeConfig.value
        }
        
        bridge.db_save_code_lookup(data, (success: boolean) => {
          if (success) {
            console.log('[Sync] CodeLookup data persisted (debounced)');
          }
        })
      } catch (e) {
        console.error('[Sync] AutoSave failed', e)
      } finally {
        autoSaveTimer = null
      }
    }, 800)
  }

  return {
    initFromDatabase,
    setupSync,
    autoSave, // 暴露真实的保存函数
    cleanup: () => {
      if (cleanupHandler) {
        cleanupHandler();
        cleanupHandler = null;
      }
    }
  }
}
