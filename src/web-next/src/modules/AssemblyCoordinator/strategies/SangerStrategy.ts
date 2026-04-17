import { BaseAssemblyStrategy } from './AssemblyStrategy';
import { type AssemblyTask } from '../types';

/**
 * SangerStrategy - 一代测序 (Sanger) 技术路线
 * 专门处理 .ab1 和 .seq 文件，侧重于高质量 Consensus 序列的提取
 */
export class SangerStrategy extends BaseAssemblyStrategy {
  getPreprocessingPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] AB1 Quality Assessment - 峰图质量动态评估 (Phred scores)',
      '[TODO] Mott Trimming - 自动裁剪末端低质量碱基',
      '[TODO] DNA Trace Cleaner - 识别冗余背景噪音'
    ];
  }

  getAssemblyPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] Forward/Reverse Alignment - 双端引物序列比对',
      '[TODO] Consensus Generation - 多重序列比对合并获取一致性序列',
      '[TODO] Vector Removal - 识别并剔除克隆载体序列'
    ];
  }

  getPolishingPipeline(task: AssemblyTask): string[] {
    // Sanger 测序通常通过人工校对峰图来完成“抛光”
    return ['[TODO] Manual Peak Verification (UI Component)'];
  }

  override getAnnotationPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] Targeted BLAST (16S/RefSeq) - 物种身份快速识别',
      '[TODO] Phylogenetic Placement - 在进化树上定位目标克隆'
    ];
  }
}
