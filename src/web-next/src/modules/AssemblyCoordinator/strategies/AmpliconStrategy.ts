import { BaseAssemblyStrategy } from './AssemblyStrategy';
import { type AssemblyTask } from '../types';

/**
 * AmpliconStrategy - 扩增子技术路线 (16S / 18S / ITS)
 * 侧重于双端序列拼接、去噪及分类学分配
 */
export class AmpliconStrategy extends BaseAssemblyStrategy {
  getPreprocessingPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] FLASH / PANDAseq - 双端序列重叠拼接 (Merging)',
      '[TODO] Cutadapt - 精确移除引物序列 (Primers)',
      '[TODO] fastp - 过滤低质量及过短序列'
    ];
  }

  getAssemblyPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] DADA2 / Deblur - 降噪生成 ASVs (扩增子序列变体)',
      '[TODO] VSEARCH - 聚类生成 OTUs (97% 相似度)',
      '[TODO] UCHIME - 去除嵌合体序列 (Chimera removal)'
    ];
  }

  getPolishingPipeline(task: AssemblyTask): string[] {
    // 扩增子通常不进行 WGS 风格的抛光，而是进行丰度过滤
    return ['[TODO] Rarefaction / Abundance Filtering'];
  }

  override getAnnotationPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] QIIME2 / IDTAXA - 物种分类学指派',
      '[TODO] Database: SILVA (16S/18S) / PR2 (18S) / UNITE (ITS)',
      '[TODO] 生成物种概况表 (Feature Table / Alpha-Beta Diversity)'
    ];
  }
}
