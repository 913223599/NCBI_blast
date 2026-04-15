/**
 * AssemblyCoordinator 模块
 * 管理基因组拼接全流程，支持 GPU 加速调度
 */

export type * from './types';
export * from './types'; // This exports constants/values (AssemblyStage etc.)
export { AssemblyEngine } from './core/AssemblyEngine';
export { GPUAccelerationStrategy } from './strategies/GPUAccelerationStrategy';

import { AssemblyEngine } from './core/AssemblyEngine';
import { GPUAccelerationStrategy } from './strategies/GPUAccelerationStrategy';

/**
 * 模块单例
 */
export const assemblyCoordinator = {
  engine: new AssemblyEngine(),
  gpu: new GPUAccelerationStrategy()
};
