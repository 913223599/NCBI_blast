<script setup lang="ts">
import { computed } from 'vue';
import { AssemblyStage, SampleType } from '../../../modules/AssemblyCoordinator/index';

const props = defineProps<{
  currentStep: number;
  sampleType: string;
  progress: number;
  stage: string;
  taskId?: string;
}>();

const emit = defineEmits(['openResults']);

const assemblySteps = computed(() => {
  const base: Array<{ id: string; title: string; icon: string }> = [
    { id: '数据质控', title: '数据质控', icon: '🧹' }
  ];
  
  if (props.sampleType === SampleType.PHAGE || props.sampleType === 'PHAGE') {
    base.push({ id: '宿主剔除', title: '宿主剔除', icon: '🛡️' });
  }
  
  base.push(
    { id: '读长合并', title: '读长合并', icon: '🔗' },
    { id: '基因组组装', title: '基因组组装', icon: '🧩' }
  );

  if (props.sampleType === SampleType.PHAGE || props.sampleType === 'PHAGE') {
    base.push({ id: '前噬菌体分离', title: '前噬菌体分离', icon: '✂️' });
  }

  base.push(
    { id: '支架构建', title: '支架构建', icon: '🏗️' },
    { id: '一致性校正', title: '一致性校正', icon: '✨' },
    { id: '功能注释', title: '功能注释', icon: '📖' }
  );
  return base;
});

const getStatusClass = (index: number) => {
  if (index < props.currentStep) return 'completed';
  if (index === props.currentStep) return 'active';
  return 'pending';
};
</script>

<template>
  <div class="stepper-card">
    <div class="stepper-header">
      <div class="status-info">
        <span class="live-tag">LIVE</span>
        <span class="current-stage">{{ stage || '准备就绪' }}</span>
        <span class="percentage">{{ progress.toFixed(1) }}%</span>
        <button 
          v-if="progress >= 100 && taskId" 
          class="open-dir-hint" 
          @click="emit('openResults', taskId)"
          title="打开结果文件夹"
        >
          📁 打开目录
        </button>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
    </div>

    <div class="steps-row">
      <div 
        v-for="(step, index) in assemblySteps" 
        :key="step.id"
        class="step-node"
        :class="getStatusClass(index)"
      >
        <div class="node-dot">{{ step.icon }}</div>
        <span class="node-label">{{ step.title }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stepper-card {
  background: white;
  border-radius: 16px;
  padding: 20px 24px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.04);
  border: 1px solid rgba(226, 232, 240, 0.5);
}

.stepper-header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 20px;
}

.status-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

.live-tag {
  background: #fee2e2;
  color: #ef4444;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
  animation: pulse 2s infinite;
}

.current-stage { font-weight: 700; color: #1e293b; font-size: 13px; }
.percentage { font-family: 'Monaco', monospace; font-weight: 600; color: #3b82f6; font-size: 14px; }

.open-dir-hint {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #dbeafe;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}
.open-dir-hint:hover {
  background: #dbeafe;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}

.progress-track {
  flex: 1;
  height: 6px;
  background: #f1f5f9;
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.steps-row {
  display: flex;
  justify-content: space-between;
  position: relative;
}

.steps-row::before {
  content: '';
  position: absolute;
  top: 15px;
  left: 5%;
  right: 5%;
  height: 1px;
  background: #e2e8f0;
  z-index: 0;
}

.step-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 1;
  flex: 1;
}

.node-dot {
  width: 32px;
  height: 32px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: all 0.3s;
}

.step-node.active .node-dot {
  border-color: #3b82f6;
  box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);
  transform: scale(1.1);
}

.step-node.completed .node-dot {
  background: #3b82f6;
  border-color: #3b82f6;
}

.node-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  transition: all 0.3s;
}

.step-node.active .node-label { color: #1e293b; }
.step-node.completed .node-label { color: #3b82f6; }

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
}
</style>
