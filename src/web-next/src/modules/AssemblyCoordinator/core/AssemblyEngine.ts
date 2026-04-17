import { type AssemblyTask, AssemblyStage } from '../types';
import { StrategyProvider } from './StrategyProvider';
import { getBridge, onEvent } from '../../../bridge';

/**
 * AssemblyEngine - 基因组拼接核心引擎
 * 采用策略模式，根据样本类型选择对应的技术路线，并与 Python 后端保持同步
 */
export class AssemblyEngine {
  private currentTask: AssemblyTask | null = null;
  private eventCleanup: (() => void) | null = null;

  constructor() {
    this.initEventListeners();
  }

  /** 初始化后端事件监听 */
  private initEventListeners() {
    this.eventCleanup = onEvent((type, data) => {
      if (type === 'assembly_status' && this.currentTask && data.task_id === this.currentTask.id) {
        this.handleStatusUpdate(data);
      }
    });
  }

  /** 启动拼接任务 */
  async startAssembly(task: AssemblyTask): Promise<void> {
    console.log(`[AssemblyEngine] Initializing ${task.sampleType} pipeline: ${task.name}`);
    this.currentTask = task;
    
    // 获取对应的技术路线策略（用于前端展示或预检查）
    const strategy = StrategyProvider.getStrategy(task.sampleType);
    const pipeline = {
      preprocessing: strategy.getPreprocessingPipeline(task),
      assembly: strategy.getAssemblyPipeline(task),
      polishing: strategy.getPolishingPipeline(task),
      annotation: strategy.getAnnotationPipeline(task)
    };

    try {
      // 通过桥接调用后端任务
      const bridge = getBridge();
      await bridge.run_assembly_job({
        task_id: task.id,
        name: task.name,
        tech: task.tech,
        sample_type: task.sampleType,
        pipeline: pipeline, // 告知后端前端期望的策略步骤
        config: task.config
      });
      
      console.log('[AssemblyEngine] Task sent to backend successfully.');
    } catch (error) {
      this.updateState(AssemblyStage.FAILED, 0);
      console.error('[AssemblyEngine] Failed to initiate task:', error);
    }
  }

  /** 处理来自后端的实时进度更新 */
  private handleStatusUpdate(data: any) {
    if (data.progress !== undefined) {
      this.updateState(data.stage || this.currentTask?.stage, data.progress);
    }
    
    if (data.status === 'finished') {
       console.log('[AssemblyEngine] Backend task completed:', data.results);
       this.updateState(AssemblyStage.COMPLETED, 100);
       if (this.currentTask) this.currentTask.results = data.results;
    } else if (data.status === 'error') {
       this.updateState(AssemblyStage.FAILED, 0);
    }
  }

  private updateState(stage: AssemblyStage, progress: number): void {
    if (this.currentTask) {
      this.currentTask.stage = stage;
      this.currentTask.progress = progress;
    }
  }

  /** 暴露底层的通讯桥接实例 */
  public getBridge() {
    return getBridge();
  }

  /** 销毁引擎，清理监听器 */
  destroy() {
    if (this.eventCleanup) this.eventCleanup();
  }
}
