import { type AssemblyTask, AssemblyStage } from '../types';
import { StrategyProvider } from './StrategyProvider';

/**
 * AssemblyEngine - 基因组拼接核心引擎
 * 采用策略模式，根据样本类型选择对应的技术路线
 */
export class AssemblyEngine {
  private currentTask: AssemblyTask | null = null;

  async startAssembly(task: AssemblyTask): Promise<void> {
    console.log(`[AssemblyEngine] Starting ${task.sampleType} assembly: ${task.name}`);
    this.currentTask = task;
    
    // 获取对应的技术路线策略
    const strategy = StrategyProvider.getStrategy(task.sampleType);

    try {
      await this.runStage(AssemblyStage.PREPROCESSING, 10, () => strategy.getPreprocessingPipeline(task));
      await this.runStage(AssemblyStage.ASSEMBLY, 40, () => strategy.getAssemblyPipeline(task));
      await this.runStage(AssemblyStage.POLISHING, 70, () => strategy.getPolishingPipeline(task));
      await this.runStage(AssemblyStage.ANNOTATION, 90, () => strategy.getAnnotationPipeline(task));
      
      this.updateStage(AssemblyStage.COMPLETED, 100);
      console.log(`[AssemblyEngine] ${task.sampleType} pipeline finished.`);
    } catch (error) {
      this.updateStage(AssemblyStage.FAILED, 0);
      console.error('[AssemblyEngine] Execution error:', error);
    }
  }

  /** 通用阶段运行器 */
  private async runStage(stage: AssemblyStage, startProgress: number, getPipeline: () => string[]): Promise<void> {
    this.updateStage(stage, startProgress);
    const steps = getPipeline();
    console.log(`[AssemblyEngine] Stage: ${stage}`);
    steps.forEach(step => console.log(`  > ${step}`));
    
    // TODO: 将 pipeline 发送至后端执行
    await this.mockDelay(1500 + Math.random() * 1000);
  }

  private updateStage(stage: AssemblyStage, progress: number): void {
    if (this.currentTask) {
      this.currentTask.stage = stage;
      this.currentTask.progress = progress;
    }
  }

  private mockDelay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
