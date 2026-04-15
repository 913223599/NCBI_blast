import { getBridge } from '../../bridge'
import type { Freezer } from './types'

export function useFreezerActions(state: any) {
  const { freezers, activeFreezerId } = state

  function addFreezer(freezer: Omit<Freezer, 'id' | 'createdAt' | 'updatedAt'>): Freezer {
    const now = new Date().toISOString()
    const newFreezer: Freezer = {
      ...freezer,
      id: `freezer_${Date.now()}`,
      createdAt: now,
      updatedAt: now
    }
    freezers.value = [...freezers.value, newFreezer]
    activeFreezerId.value = newFreezer.id
    
    try {
      getBridge().db_save_freezer(newFreezer)
    } catch (e) {}
    
    return newFreezer
  }

  function updateFreezer(id: string, updates: Partial<Freezer>) {
    freezers.value = freezers.value.map((f: Freezer) => 
      f.id === id ? { ...f, ...updates, updatedAt: new Date().toISOString() } : f
    )
    
    const updated = freezers.value.find((f: Freezer) => f.id === id)
    if (updated) {
      try {
        getBridge().db_save_freezer(updated)
      } catch (e) {}
    }
  }

  function removeFreezer(id: string) {
    freezers.value = freezers.value.filter((f: Freezer) => f.id !== id)
    if (activeFreezerId.value === id) activeFreezerId.value = freezers.value[0]?.id || null
    
    try {
      getBridge().db_delete_freezer(id)
    } catch (e) {}
  }
  
  /** 更新位置占用状态 */
  function updatePositionOccupancy(
    freezerId: string,
    shelfId: string,
    cabinetId: string,
    drawerId: string,
    boxId: string,
    positionLabel: string,
    occupied: boolean,
    sampleId?: string
  ) {
    const freezer = freezers.value.find((f: Freezer) => f.id === freezerId)
    if (!freezer) return
    
    // 深度遍历更新
    for (const shelf of freezer.shelves) {
      if (shelf.id === shelfId) {
        for (const cabinet of shelf.cabinets) {
          if (cabinet.id === cabinetId) {
            for (const drawer of cabinet.drawers) {
              if (drawer.id === drawerId) {
                for (const box of drawer.boxes) {
                  if (box.id === boxId) {
                    const pos = box.positions.find((p: any) => p.label === positionLabel)
                    if (pos) {
                      pos.occupied = occupied
                      pos.sampleId = sampleId
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    // 触发 shallowRef 更新
    freezers.value = [...freezers.value]

    try {
      getBridge().db_save_freezer(freezer)
    } catch (e) {}
  }

  /** 刷新全库占用映射 (全量同步 records -> freezers) */
  function refreshFreezerOccupancy(shouldSave: boolean = true) {
    const allRecords = state.records.value
    if (!freezers.value.length) return

    // 获取当前状态，直接进行就地修改（临时）
    const target = freezers.value 

    // 优化后的盒子索引表：Map<"freezerId|boxId", BoxObject>
    const boxMap = new Map<string, any>()

    console.log(`[TopologySync] 开始扫描拓扑... 冰箱总数: ${target.length}`)

    // 核心新增：清理并准备位置名称映射
    const locMap: Record<string, string> = {}

    // 1. 第一步：深度重置所有格位，并建立快速索引 (O(N_boxes))
    target.forEach((f: any) => {
      const fId = String(f.id || '').trim().toLowerCase()
      const fName = f.name || '未知冰箱'

      f.shelves?.forEach((s: any) => {
        const sName = s.name || '未知层'
        s.cabinets?.forEach((c: any) => {
          const cName = c.name || '未知柜'
          c.drawers?.forEach((d: any) => {
            const dName = d.name || '未知抽屉'
            d.boxes?.forEach((b: any) => {
              const bId = String(b.id || '').trim().toLowerCase()
              const bName = b.name || '未知盒子'
              
              // 建立复合 ID 索引 (全部转小写归一化)
              const compositeKey = `${fId}|${bId}`
              boxMap.set(compositeKey, b)

              // 【核心修复】建立 ID 到名称的完整路径映射，供侧边栏 UI 使用
              const fullPath = `${fName} / ${sName} / ${dName} / ${bName}`
              locMap[bId] = fullPath // 传统 ID 映射
              locMap[`${fId}|${bId}`] = fullPath // 复合 ID 映射 (更安全)

              // 重置格位状态
              b.positions?.forEach((p: any) => {
                p.occupied = false
                p.sampleId = undefined
              })
            })
          })
        })
      })
    })

    // 同步到 store
    state.locationMap.value = locMap
    console.log(`[TopologySync] 盒子索引构建完成，已更新 ${Object.keys(locMap).length} 个位置名称`)

    // 2. 第二步：根据样本记录进行精准标记 (O(N_records))
    let sampleMatchCount = 0
    let boxMatchCount = 0
    let errorCount = 0

    allRecords.forEach((record: any, idx: number) => {
      // 归一化提取 ID，兼容后端可能出现的各种字段名
      const fId = String(record.freezerId || record.freezer_id || '').trim().toLowerCase()
      const bId = String(record.boxId || record.box_id || '').trim().toLowerCase()
      const posLabel = String(record.position || '').trim().toUpperCase()
      
      if (!fId || !bId || !posLabel) return

      const compositeKey = `${fId}|${bId}`
      const box = boxMap.get(compositeKey)
      
      // 诊断日志：只打印前几条或查不到的异常
      if (idx < 3) {
        console.log(`[TopologySync] 正在尝试匹配记录: ${record.name} -> Key: ${compositeKey}`)
      }

      if (box) {
        boxMatchCount++
        // 查找格位 (不区分大小写匹配)
        const pos = box.positions?.find((p: any) => 
          String(p.label || '').trim().toUpperCase() === posLabel
        )
        if (pos) {
          pos.occupied = true
          pos.sampleId = record.id
          sampleMatchCount++
        } else if (errorCount < 10) {
          console.warn(`[TopologySync] 格位缺失: 盒 ${bId} 中找不到位置 [${posLabel}]`)
          errorCount++
        }
      } else if (errorCount < 10) {
        console.warn(`[TopologySync] 盒子匹配失败: Key [${compositeKey}] 不存在于索引中`)
        if (errorCount === 0) {
          console.log('[TopologySync] 索引样例 Key:', Array.from(boxMap.keys()).slice(0, 3))
        }
        errorCount++
      }
    })
    
    console.log(`[TopologySync] 同步流水线结束: 成功标记 ${sampleMatchCount} 个样本, 找到 ${boxMatchCount} 个有效冰箱盒`)

    // 3. 核心修复：执行深拷贝强制刷新 UI
    const deepCloned = JSON.parse(JSON.stringify(target))
    freezers.value = deepCloned
    
    // 4. 安全保护：只有在主动操作时才写库，防止同步引起的广播风暴
    if (shouldSave) {
      state.setIsUpdating(true) // 开启护盾，拦截 data_updated 信号
      try {
        const bridge = getBridge()
        // 性能优化：这里可以考虑在后端增加一个批量保存冰箱的接口
        Promise.all(deepCloned.map((f: any) => {
          return new Promise((resolve) => bridge.db_save_freezer(f, resolve))
        })).finally(() => {
          state.setIsUpdating(false) // 关闭护盾
        })
      } catch (e) {
        state.setIsUpdating(false)
      }
    }
  }

  return {
    addFreezer,
    updateFreezer,
    removeFreezer,
    updatePositionOccupancy,
    refreshFreezerOccupancy
  }
}
