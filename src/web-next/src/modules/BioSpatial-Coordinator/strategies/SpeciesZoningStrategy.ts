import type { StrainRecord } from '../../../stores/strain/types'
import { TopologyScanner, type BoxCapacityInfo } from '../core/TopologyScanner'

export interface AllocationResult {
  sampleId: string
  sampleName: string
  species: string
  allocatedBoxId: string
  allocatedPath: string
  positionLabel: string
  reason: string 
  record: Partial<StrainRecord> // 记录原始样本引用
}

/**
 * 按种属分区分配策略
 */
export class SpeciesZoningStrategy {
  /**
   * 执行分配算法
   */
  static allocate(
    newBatch: Partial<StrainRecord>[], 
    inventoryIndex: Map<string, BoxCapacityInfo>
  ): AllocationResult[] {
    const results: AllocationResult[] = []
    const virtualIndex = new Map(inventoryIndex)

    newBatch.forEach(sample => {
      const species = sample.species || 'Unknown'
      const sampleType = sample.sampleType || 'Other'
      const genus = TopologyScanner.getGenus(species)
      
      // 1. 优先级：同类同种匹配
      let targetBoxId = this.findAffinityBox(species, sampleType, genus, virtualIndex)
      let reason = '同品类/同物种聚类分配'

      // 2. 兜底：开辟新区 - 寻找完全符合兼容性规则的空盒子
      if (!targetBoxId) {
        targetBoxId = this.findCompatibleEmptyBox(species, sampleType, genus, virtualIndex)
        reason = '新开辟物种分区'
      }

      // 3. 极限兜底：寻找物理及规则上兼容的可用盒子
      if (!targetBoxId) {
        targetBoxId = this.findAnyCompatibleBox(species, sampleType, genus, virtualIndex)
        reason = '跨种属兼容格位分配'
      }

      if (targetBoxId) {
        const box = virtualIndex.get(targetBoxId)!
        const pos = box.emptyPositions.shift()! 
        
        box.usedCount++
        box.availableCount--
        box.occupants.add(species)
        box.sampleTypeOccupants.add(sampleType) // 记录品类占用
        
        if (!box.genusOccupants.has(genus)) {
          box.genusOccupants.set(genus, new Set())
        }
        box.genusOccupants.get(genus)!.add(species)

        results.push({
          sampleId: sample.id || `pending-${Date.now()}-${Math.random()}`,
          sampleName: sample.name || 'Unnamed',
          species: species,
          allocatedBoxId: targetBoxId,
          allocatedPath: `${box.path} / ${box.boxName}`,
          positionLabel: pos.label,
          reason: reason,
          record: sample 
        })
      }
    })

    return results
  }

  /**
   * 找寻已有同类同种的盒子
   */
  private static findAffinityBox(species: string, sampleType: string, genus: string, index: Map<string, BoxCapacityInfo>): string | null {
    for (const [id, info] of index) {
      if (info.availableCount > 0 && info.occupants.has(species)) {
        // 如果物理上已有该种，大类必然也匹配（除非库数据错乱），直接允许
        return id
      }
    }
    return null
  }

  private static findCompatibleEmptyBox(species: string, sampleType: string, genus: string, index: Map<string, BoxCapacityInfo>): string | null {
    for (const [id, info] of index) {
      if (info.usedCount === 0 && info.availableCount > 0) {
        return id
      }
    }
    return null
  }

  private static findAnyCompatibleBox(species: string, sampleType: string, genus: string, index: Map<string, BoxCapacityInfo>): string | null {
    for (const [id, info] of index) {
      if (info.availableCount > 0 && this.isBoxCompatible(species, sampleType, genus, info)) {
        return id
      }
    }
    return null
  }

  /**
   * 核心隔离准入逻辑
   * 1. 品类必须一致 (大类隔离)
   * 2. 如果存在同属，必须是同种 (同属不同种隔离)
   */
  private static isBoxCompatible(species: string, sampleType: string, genus: string, boxInfo: BoxCapacityInfo): boolean {
    // 准则 1: 大类不同，绝不能混放
    if (boxInfo.sampleTypeOccupants.size > 0 && !boxInfo.sampleTypeOccupants.has(sampleType)) {
      return false
    }

    // 准则 2: 同属不同种，绝不能混放
    const speciesInGenus = boxInfo.genusOccupants.get(genus)
    if (speciesInGenus && speciesInGenus.size > 0) {
      // 盒子里已经有这个属了，必须检查当前这个“种”是否已包含在内
      if (!speciesInGenus.has(species)) {
        return false // 同属但种名不同，冲突
      }
    }

    return true
  }
}
