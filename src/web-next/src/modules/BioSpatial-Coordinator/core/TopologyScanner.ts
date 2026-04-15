import type { Freezer, FreezerShelf, FreezerCabinet, FreezerDrawer, FreezerBox, StrainRecord } from '../../../stores/strain/types'

export interface BoxCapacityInfo {
  boxId: string
  boxName: string
  path: string
  totalSlots: number
  usedCount: number
  availableCount: number
  occupants: Set<string> // 已存物种 (Species) 集合
  genusOccupants: Map<string, Set<string>> // 属 (Genus) -> 种 (Species) 的映射
  sampleTypeOccupants: Set<string> // 已存大类 (sampleType) 集合
  emptyPositions: Array<{ row: number, col: number, label: string }>
}

/**
 * 拓扑扫描器
 */
export class TopologyScanner {
  /**
   * 从全名中提取属名
   */
  static getGenus(species: string): string {
    if (!species) return 'Unknown'
    const parts = species.split(' ')
    return parts[0] ? parts[0].trim() : 'Unknown'
  }

  static scan(freezers: Freezer[], records: StrainRecord[] | undefined): Map<string, BoxCapacityInfo> {
    const boxMap = new Map<string, BoxCapacityInfo>()
    if (!freezers) return boxMap

    freezers.forEach((f: Freezer) => {
      f.shelves?.forEach((s: FreezerShelf) => {
        s.cabinets?.forEach((c: FreezerCabinet) => {
          c.drawers?.forEach((d: FreezerDrawer) => {
            d.boxes?.forEach((box: FreezerBox) => {
              boxMap.set(box.id, {
                boxId: box.id,
                boxName: box.name,
                path: `${f.name} / ${s.name} / ${d.name}`,
                totalSlots: box.rows * box.cols,
                usedCount: 0,
                availableCount: 0,
                occupants: new Set<string>(),
                genusOccupants: new Map<string, Set<string>>(),
                sampleTypeOccupants: new Set<string>(),
                emptyPositions: (box.positions || [])
                  .filter(p => !p.occupied)
                  .map(p => ({ row: p.row, col: p.col, label: p.label }))
              })
            })
          })
        })
      })
    })

    const safeRecords = records || []
    safeRecords.forEach((record: StrainRecord) => {
      // 容错处理：即使没填物种也需要记入大类
      if (!record.boxId) return
      const boxInfo = boxMap.get(record.boxId)
      if (boxInfo) {
        boxInfo.usedCount++
        
        // 记录大类
        if (record.sampleType) {
          boxInfo.sampleTypeOccupants.add(record.sampleType)
        }

        // 记录种属
        if (record.species) {
          const genus = this.getGenus(record.species)
          boxInfo.occupants.add(record.species)
          if (!boxInfo.genusOccupants.has(genus)) {
            boxInfo.genusOccupants.set(genus, new Set())
          }
          boxInfo.genusOccupants.get(genus)!.add(record.species)
        }
      }
    })

    boxMap.forEach(info => { info.availableCount = info.emptyPositions.length })
    return boxMap
  }
}
