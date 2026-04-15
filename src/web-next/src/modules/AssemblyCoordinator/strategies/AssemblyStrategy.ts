import type { AssemblyTask } from '../types';

/**
 * AssemblyStrategy - 拼接策略接口
 * 定义了不同样本类型必须实现的技术路线步骤
 */
export interface IAssemblyStrategy {
  /** 预处理阶段: 清洗、质控 */
  getPreprocessingPipeline(task: AssemblyTask): string[];
  
  /** 核心组装阶段: 算法选择与参数生成 */
  getAssemblyPipeline(task: AssemblyTask): string[];
  
  /** 抛光/校正阶段 */
  getPolishingPipeline(task: AssemblyTask): string[];
  
  /** 注释与报告阶段 */
  getAnnotationPipeline(task: AssemblyTask): string[];
}

/**
 * BaseAssemblyStrategy - 基础策略抽象类
 * 提供通用的默认实现，方便子类扩展
 */
export abstract class BaseAssemblyStrategy implements IAssemblyStrategy {
  abstract getPreprocessingPipeline(task: AssemblyTask): string[];
  abstract getAssemblyPipeline(task: AssemblyTask): string[];
  
  getPolishingPipeline(task: AssemblyTask): string[] {
    // 默认通用的 Racon 抛光流程
    return ['[TODO] Default Racon Polishing'];
  }
  
  getAnnotationPipeline(task: AssemblyTask): string[] {
    // 默认通用的 Prokka 注释流程
    return ['[TODO] Default Prokka Annotation'];
  }
}
