import { SampleType } from '../types';
import type { IAssemblyStrategy } from '../strategies/AssemblyStrategy';
import { BacteriaStrategy } from '../strategies/BacteriaStrategy';
import { VirusStrategy } from '../strategies/VirusStrategy';
import { PhageStrategy } from '../strategies/PhageStrategy';
import { AmpliconStrategy } from '../strategies/AmpliconStrategy';
import { SangerStrategy } from '../strategies/SangerStrategy';

/**
 * StrategyProvider - 技术路线工厂
 * 负责根据样本类型动态提供相应的处理策略
 */
export class StrategyProvider {
  private static strategies: Map<string, IAssemblyStrategy> = new Map([
    [SampleType.BACTERIA, new BacteriaStrategy()],
    [SampleType.VIRUS, new VirusStrategy()],
    [SampleType.PHAGE, new PhageStrategy()],
    [SampleType.AMPLICON, new AmpliconStrategy()],
    ['SANGER_16S', new SangerStrategy()] // 针对 16S Sanger 专项优化
  ]);

  /**
   * 获取对应的技术路线策略
   * @param type 样本类型或特殊标识
   */
  static getStrategy(type: string): IAssemblyStrategy {
    const strategy = this.strategies.get(type);
    if (!strategy) {
      console.warn(`[StrategyProvider] No specific strategy for ${type}, falling back to Bacteria`);
      return this.strategies.get(SampleType.BACTERIA)!;
    }
    return strategy;
  }

  /**
   * 注册新的技术路线 (模块化扩展)
   * @param type 新样本类型标识
   * @param strategy 对应的策略实现
   */
  static registerStrategy(type: string, strategy: IAssemblyStrategy): void {
    this.strategies.set(type, strategy);
  }
}
