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

  return {
    addFreezer,
    updateFreezer,
    removeFreezer,
    updatePositionOccupancy
  }
}
