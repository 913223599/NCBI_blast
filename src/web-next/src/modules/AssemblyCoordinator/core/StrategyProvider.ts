import { SampleType } from '../types';
import type { IAssemblyStrategy } from '../strategies/AssemblyStrategy';
import { BacteriaStrategy } from '../strategies/BacteriaStrategy';
import { VirusStrategy } from '../strategies/VirusStrategy';
import { PhageStrategy } from '../strategies/PhageStrategy';

/**
 * StrategyProvider - 技术路线工厂
 * 负责根据样本类型动态提供相应的处理策略
 */
export class StrategyProvider {
  private static strategies: Map<SampleType, IAssemblyStrategy> = new Map([
    [SampleType.BACTERIA, new BacteriaStrategy()],
    [SampleType.VIRUS, new VirusStrategy()],
    [SampleType.PHAGE, new PhageStrategy()]
  ]);

  /**
   * 获取对应的技术路线策略
   * @param type 样本类型
   */
  static getStrategy(type: SampleType): IAssemblyStrategy {
    const strategy = this.strategies.get(type);
    if (!strategy) {
      console.warn(`[StrategyProvider] No specific strategy for ${type}, falling back to Bacteria`);
      return this.strategies.get(SampleType.BACTERIA)!;
    }
    return strategy;
  }

  /**
   * 注册新的技术路线 (模块化扩展)
   * @param type 新样本类型
   * @param strategy 对应的策略实现
   */
  static registerStrategy(type: SampleType, strategy: IAssemblyStrategy): void {
    this.strategies.set(type, strategy);
  }
}
