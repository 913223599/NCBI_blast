import type { Freezer, StrainRecord } from '../../../stores/strain/types'
import { TopologyScanner } from './TopologyScanner'
import { SpeciesZoningStrategy, type AllocationResult } from '../strategies/SpeciesZoningStrategy'

/**
 * BioSpatial-Coordinator 总协调核心
 * 对外统一暴露智能配位接口
 */
export class AllocationCoordinator {
  /**
   * 智能配位核心函数
   * @param batch 待导入的新样本列表
   * @param context 包含当前冰箱(freezers)和现有记录(records)的环境上下文
   */
  static processBatchAssignment(
    batch: Partial<StrainRecord>[],
    context: { freezers: Freezer[], records: StrainRecord[] }
  ): AllocationResult[] {
    // 1. 获取库房“数字孪生”索引
    const inventoryIndex = TopologyScanner.scan(context.freezers, context.records)

    // 2. 调度种属分区策略执行分配
    // 未来可根据配置在此动态切换策略（如切换为紧凑策略、风险分散策略等）
    const results = SpeciesZoningStrategy.allocate(batch, inventoryIndex)

    return results
  }
}
