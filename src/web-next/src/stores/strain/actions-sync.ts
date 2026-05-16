import { getBridge, onEvent } from '../../bridge'

export function useSyncActions(state: any, recordsActions: any, freezerActions: any) {
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

          // 防护：如果后端返回了 throttled 状态，不要用空数据覆盖已有的内存状态
          if (data.status === 'throttled') {
            console.log('[Sync] 后端节流中，保留当前内存数据')
            isLoading = false
            return
          }

          if (data.freezers) {
            console.log('[Sync] 收到后端冰箱结构更新，准备同步数据...')
            freezers.value = data.freezers
          }

          if (data.records) {
            // 脱水巨大的序列字段，但必须保留所有的物理坐标字段以供拓扑刷新
            const processed = data.records.map((r: any) => {
               const { sequence, ...rest } = r
               // 必须确保返回给 Store 的对象具有统一的驼峰命名字段
               return {
                 ...rest,
                 freezerId: r.freezer_id || r.freezerId,
                 shelfId: r.shelf_id || r.shelfId,
                 cabinetId: r.cabinet_id || r.cabinetId,
                 drawerId: r.drawer_id || r.drawerId,
                 boxId: r.box_id || r.boxId,
                 position: r.position
               }
            })
            records.value = processed
          }

          // 适配后端的 total_count 字段，存入 state 供 UI 准确显示
          if (typeof data.total_count === 'number') {
            state.serverTotalCount.value = data.total_count
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
          
          console.log(`[Sync] 数据加载完成: ${records.value.length} 条样本, ${freezers.value.length} 个冰箱`)

          // 关键修复：初始加载完成后，强制根据最新的 records 同步一次物理拓扑
          // 彻底解决"重启后不亮"的问题：不再依赖数据库里的 structure 状态，而是在内存中根据 records 动态重建
          if (freezerActions?.refreshFreezerOccupancy) {
            console.log(`[Sync] 正在从 ${records.value.length} 条样本记录中恢复物理占用拓补...`)
            // 立即执行一次同步 (false 表示不写回数据库)
            freezerActions.refreshFreezerOccupancy(false)
          }

          isInitialized.value = true
          console.log('[Sync] 系统初始化完成')
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
        const isLocalUpdating = state.getIsUpdating()
        console.log(`[Sync] 收到同步信号 | 模块: strains | 本地护盾状态: ${isLocalUpdating}`)
        
        // 如果本地正在执行原子更新，拦截来自后端的全量刷新请求，防止竞态覆盖
        if (!isLocalUpdating) {
          initFromDatabase();
        } else {
          console.log('[Sync] 本地正在写入，跳过本次后端信号拦截')
        }
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
