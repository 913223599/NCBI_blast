import { BaseAssemblyStrategy } from './AssemblyStrategy';
import type { AssemblyTask } from '../types';

/**
 * PhageStrategy - 噬菌体技术路线
 * 侧重于环状基因组识别和完整性验证
 */
export class PhageStrategy extends BaseAssemblyStrategy {
  getPreprocessingPipeline(task: AssemblyTask): string[] {
    return ['[TODO] standard phage QC (High coverage depth normalization)'];
  }

  getAssemblyPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] SPAdes -phage mode',
      '[TODO] Phage-specific circularity detection'
    ];
  }

  override getAnnotationPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] Phanotate - 噬菌体基因预测',
      '[TODO] Pharokka - 综合噬菌体注释库'
    ];
  }
}
