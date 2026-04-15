import { BaseAssemblyStrategy } from './AssemblyStrategy';
import { type AssemblyTask, SequencingTech } from '../types';

/**
 * VirusStrategy - 病毒技术路线
 * 针对病毒基因组小、变异率高的特点
 */
export class VirusStrategy extends BaseAssemblyStrategy {
  getPreprocessingPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] BWA - 移除宿主（Host）背景污染',
      '[TODO] k-mer filtering'
    ];
  }

  getAssemblyPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] IVA (Iterative Virus Assembler)',
      '[TODO] VICUNA - 针对高异质性群体拼接'
    ];
  }

  override getAnnotationPipeline(task: AssemblyTask): string[] {
    return [
      '[TODO] VIGOR - 病毒专用功能注释',
      '[TODO] NCBI GenBank Virus Submission Prep'
    ];
  }
}
