import type { Ref } from 'vue'
import { getBridge } from '../../bridge'
import { safeDeepClone } from '../../utils/clone'
import type { Freezer, StrainRecord } from './types'
import { createLogger } from '../../utils/logger'

const _log = createLogger('StrainFreezer')

type FreezerBoxItem = Freezer['shelves'][number]['cabinets'][number]['drawers'][number]['boxes'][number]
type RecordWithLegacyCoords = StrainRecord & { freezer_id?: string; box_id?: string }

interface FreezerActionState {
  freezers: Ref<Freezer[]>
  activeFreezerId: Ref<string | null>
  records: Ref<RecordWithLegacyCoords[]>
  locationMap: Ref<Record<string, string>>
  setIsUpdating: (val: boolean) => void
}

export function useFreezerActions(state: FreezerActionState) {
  const { freezers, activeFreezerId } = state

  function addFreezer(freezer: Omit<Freezer, 'id' | 'createdAt' | 'updatedAt'>): Freezer {
    const now = new Date().toISOString()
    const newFreezer: Freezer = {
      ...freezer,
      id: `freezer_${Date.now()}`,
      createdAt: now,
      updatedAt: now,
    }
    freezers.value = [...freezers.value, newFreezer]
    activeFreezerId.value = newFreezer.id
    try {
      getBridge().db_save_freezer(newFreezer)
    } catch (e) {
      _log.debug('保存新冰箱异常:', e)
    }
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
      } catch (e) {
        _log.debug('更新冰箱异常:', e)
      }
    }
  }

  function removeFreezer(id: string) {
    freezers.value = freezers.value.filter((f: Freezer) => f.id !== id)
    if (activeFreezerId.value === id) activeFreezerId.value = freezers.value[0]?.id || null
    try {
      getBridge().db_delete_freezer(id)
    } catch (e) {
      _log.debug('删除冰箱异常:', e)
    }
  }

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

    for (const shelf of freezer.shelves) {
      if (shelf.id !== shelfId) continue
      for (const cabinet of shelf.cabinets) {
        if (cabinet.id !== cabinetId) continue
        for (const drawer of cabinet.drawers) {
          if (drawer.id !== drawerId) continue
          for (const box of drawer.boxes) {
            if (box.id !== boxId) continue
            const pos = box.positions.find((p) => p.label === positionLabel)
            if (pos) {
              pos.occupied = occupied
              pos.sampleId = sampleId
            }
          }
        }
      }
    }

    freezers.value = [...freezers.value]
    try {
      getBridge().db_save_freezer(freezer)
    } catch (e) {
      _log.debug('更新格位占用持久化异常:', e)
    }
  }

  function refreshFreezerOccupancy(shouldSave: boolean = true) {
    const allRecords = state.records.value
    if (!freezers.value.length) return

    const target = freezers.value
    const boxMap = new Map<string, FreezerBoxItem>()
    _log.debug(`[TopologySync] 开始扫描拓扑... 冰箱总数: ${target.length}`)
    const locMap: Record<string, string> = {}

    target.forEach((f) => {
      const fId = String(f.id || '').trim().toLowerCase()
      const fName = f.name || '未知冰箱'

      f.shelves?.forEach((s) => {
        const sName = s.name || '未知层'
        s.cabinets?.forEach((c) => {
          c.drawers?.forEach((d) => {
            const dName = d.name || '未知抽屉'
            d.boxes?.forEach((b) => {
              const bId = String(b.id || '').trim().toLowerCase()
              const bName = b.name || '未知盒子'
              const compositeKey = `${fId}|${bId}`
              boxMap.set(compositeKey, b)
              const fullPath = `${fName} / ${sName} / ${dName} / ${bName}`
              locMap[bId] = fullPath
              locMap[compositeKey] = fullPath
              b.positions?.forEach((p) => {
                p.occupied = false
                p.sampleId = undefined
              })
            })
          })
        })
      })
    })

    state.locationMap.value = locMap
    _log.debug(`[TopologySync] 盒子索引构建完成，已更新 ${Object.keys(locMap).length} 个位置名称`)

    let sampleMatchCount = 0
    let boxMatchCount = 0
    let errorCount = 0

    allRecords.forEach((record, idx) => {
      const fId = String(record.freezerId || record.freezer_id || '').trim().toLowerCase()
      const bId = String(record.boxId || record.box_id || '').trim().toLowerCase()
      const posLabel = String(record.position || '').trim().toUpperCase()
      if (!fId || !bId || !posLabel) return

      const compositeKey = `${fId}|${bId}`
      const box = boxMap.get(compositeKey)
      if (idx < 3) {
        _log.debug(`[TopologySync] 正在尝试匹配记录: ${record.name} -> Key: ${compositeKey}`)
      }

      if (box) {
        boxMatchCount++
        const pos = box.positions?.find((p) => String(p.label || '').trim().toUpperCase() === posLabel)
        if (pos) {
          pos.occupied = true
          pos.sampleId = record.id
          sampleMatchCount++
        } else if (errorCount < 10) {
          _log.warn(`[TopologySync] 格位缺失: 盒 ${bId} 中找不到位置 [${posLabel}]`)
          errorCount++
        }
      } else if (errorCount < 10) {
        _log.warn(`[TopologySync] 盒子匹配失败: Key [${compositeKey}] 不存在于索引中`)
        if (errorCount === 0) {
          _log.debug('[TopologySync] 索引样例 Key:', Array.from(boxMap.keys()).slice(0, 3))
        }
        errorCount++
      }
    })

    _log.debug(`[TopologySync] 同步流水线结束: 成功标记 ${sampleMatchCount} 个样本, 找到 ${boxMatchCount} 个有效冰箱盒`)
    const deepCloned = safeDeepClone(target)
    freezers.value = deepCloned

    if (shouldSave) {
      state.setIsUpdating(true)
      try {
        const bridge = getBridge()
        Promise.all(
          deepCloned.map((f) => new Promise((resolve) => bridge.db_save_freezer(f, resolve)))
        ).finally(() => {
          state.setIsUpdating(false)
        })
      } catch {
        state.setIsUpdating(false)
      }
    }
  }

  return {
    addFreezer,
    updateFreezer,
    removeFreezer,
    updatePositionOccupancy,
    refreshFreezerOccupancy,
  }
}
