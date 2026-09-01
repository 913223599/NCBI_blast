import { BaseAssemblyStrategy } from './AssemblyStrategy';
import { type AssemblyTask, SequencingTech } from '../types';

/**
 * BacteriaStrategy - 细菌技术路线
 */
export class BacteriaStrategy extends BaseAssemblyStrategy {
  getPreprocessingPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] fastp - 细菌基因组深度质控',
      '[TODO] Trimmomatic - 识别并去除接头'
    ];
  }

  getAssemblyPipeline(task: AssemblyTask): string[] {
    return ['NGCS (Native C++20 Eulerian Residual Flow / Spectral Manifold Engine)'];
  }

  override getAnnotationPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] Prokka (Standard Bacteria)',
      '[TODO] CARD - 耐药基因检测',
      '[TODO] VFDB - 毒力基因检测'
    ];
  }
}
