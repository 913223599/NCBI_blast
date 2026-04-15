/**
 * AssemblyCoordinator 模块类型定义
 * 适配 erasableSyntaxOnly: true
 */

export const AssemblyStage = {
  PREPROCESSING: 'PREPROCESSING', // 预处理 (质控/清洗)
  ASSEMBLY: 'ASSEMBLY',           // 基因组组装
  POLISHING: 'POLISHING',         // 一致性校正/打磨
  ANNOTATION: 'ANNOTATION',       // 功能注释
  COMPLETED: 'COMPLETED',         // 任务完成
  FAILED: 'FAILED'                // 任务失败
} as const;

export type AssemblyStage = typeof AssemblyStage[keyof typeof AssemblyStage];

export const SequencingTech = {
  ILLUMINA: 'ILLUMINA',
  NANOPORE: 'NANOPORE',
  PACBIO_HIFI: 'PACBIO_HIFI'
} as const;

export type SequencingTech = typeof SequencingTech[keyof typeof SequencingTech];

export const SampleType = {
  BACTERIA: 'BACTERIA',
  VIRUS: 'VIRUS',
  PHAGE: 'PHAGE',
  OTHER: 'OTHER'
} as const;

export type SampleType = typeof SampleType[keyof typeof SampleType];

export interface AssemblyTask {
  id: string;
  name: string;
  tech: SequencingTech;
  sampleType: SampleType;
  stage: AssemblyStage;
  progress: number;
  startTime: string;
  endTime?: string;
  config: AssemblyConfig;
  results?: AssemblyResults;
}

export interface AssemblyConfig {
  useGPU: boolean;
  algorithm: string;
  params: Record<string, any>;
  gpuConfig?: {
    cudaDevices: string[];
    enableParabricks: boolean;
  };
}

export interface AssemblyResults {
  n50: number;
  totalLength: number;
  contigCount: number;
  reportPath: string;
  fastaPath: string;
}
