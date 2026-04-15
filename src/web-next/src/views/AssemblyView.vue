<script setup lang="ts">
/**
 * AssemblyView - 基因组拼接模块
 * 负责测序数据的清洗与拼接流程，集成 AssemblyCoordinator 核心模块，支持多物种技术路线。
 */
import { ref, reactive } from 'vue'
import { assemblyCoordinator, SequencingTech, AssemblyStage, SampleType } from '../modules/AssemblyCoordinator'

const assemblySteps = [
  { id: AssemblyStage.PREPROCESSING, title: '数据质控', description: '质量评估与背景移除', icon: 'qc' },
  { id: AssemblyStage.ASSEMBLY, title: '基因组组装', description: '物种专项拼接算法', icon: 'assembly' },
  { id: AssemblyStage.POLISHING, title: '一致性校正', description: 'GPU 序列抛光与评价', icon: 'eval' },
  { id: AssemblyStage.ANNOTATION, title: '功能注释', description: '物种库比对与功能预测', icon: 'anno' }
]

const currentStep = ref(0)
const isRunning = ref(false)

const taskState = reactive<{
  name: string;
  tech: SequencingTech;
  sampleType: SampleType;
  useGPU: boolean;
  progress: number;
  stage: AssemblyStage;
}>({
  name: 'New_Assembly_Task',
  tech: SequencingTech.ILLUMINA,
  sampleType: SampleType.BACTERIA,
  useGPU: true,
  progress: 0,
  stage: AssemblyStage.PREPROCESSING
})

/** 启动拼接任务 */
async function startAssemblyTask() {
  if (isRunning.value) return
  
  isRunning.value = true
  const task = {
    id: Date.now().toString(),
    name: taskState.name,
    tech: taskState.tech,
    sampleType: taskState.sampleType,
    stage: AssemblyStage.PREPROCESSING,
    progress: 0,
    startTime: new Date().toISOString(),
    config: {
      useGPU: taskState.useGPU,
      algorithm: 'AUTO',
      params: {}
    }
  }

  // 模拟进度更新逻辑
  const interval = setInterval(() => {
    taskState.progress = Math.min(taskState.progress + 1, 99)
    if (taskState.progress < 25) currentStep.value = 0
    else if (taskState.progress < 60) currentStep.value = 1
    else if (taskState.progress < 85) currentStep.value = 2
    else currentStep.value = 3
  }, 120)

  try {
    await assemblyCoordinator.engine.startAssembly(task as any)
  } finally {
    clearInterval(interval)
    taskState.progress = 100
    isRunning.value = false
    currentStep.value = 4 // Completed
  }
}
</script>

<template>
  <div class="assembly-workspace">
    <!-- 顶部标题区 -->
    <header class="workspace-header">
      <div class="title-area">
        <h1>基因组拼接</h1>
        <p class="subtitle">面向高通量测序数据的一站式处理平台 - 当前路线: {{ taskState.sampleType }}</p>
      </div>
      <div class="header-actions">
        <button 
          class="btn-primary" 
          :disabled="isRunning" 
          @click="startAssemblyTask"
        >
          {{ isRunning ? '正在执行流水线...' : '启动流水线' }}
        </button>
      </div>
    </header>

    <!-- 流程进度指示器 -->
    <div class="workflow-stepper">
      <div 
        v-for="(step, index) in assemblySteps" 
        :key="index"
        class="step-node"
        :class="{ active: currentStep === index, completed: currentStep > index }"
      >
        <div class="node-circle">
          <span v-if="currentStep > index">✓</span>
          <span v-else>{{ index + 1 }}</span>
        </div>
        <div class="node-label">
          <h3>{{ step.title }}</h3>
          <p>{{ step.description }}</p>
        </div>
      </div>
    </div>
    
    <!-- 全局进度条 -->
    <div v-if="isRunning" class="global-progress-bar">
      <div class="progress-fill" :style="{ width: taskState.progress + '%' }"></div>
      <span class="progress-label">{{ taskState.progress }}% - {{ taskState.stage }}</span>
    </div>

    <!-- 主交互区域 -->
    <div class="workspace-layout">
      <!-- 左侧：数据管理 -->
      <section class="panel-card upload-panel">
        <div class="panel-header">
          <h2>测序数据上传</h2>
          <span class="status-badge" :class="{ running: isRunning }">
            {{ isRunning ? '流水线运行中' : '准备就绪' }}
          </span>
        </div>
        <div class="dropzone" :class="{ disabled: isRunning }">
          <div class="dropzone-content">
            <svg class="drop-icon" viewBox="0 0 24 24">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <p class="main-tip">拖拽 FASTQ 文件到此处，或 <span>点击选择</span></p>
            <p class="sub-tip">已自动识别 {{ taskState.tech }} 格式样本</p>
          </div>
        </div>
      </section>

      <!-- 右侧：参数设置 -->
      <section class="panel-card config-panel">
        <div class="panel-header">
          <h2>技术路线配置</h2>
        </div>
        <div class="config-form">
          <div class="field-item">
            <label>任务名称</label>
            <input type="text" v-model="taskState.name" :disabled="isRunning" class="form-input" placeholder="请输入任务唯一标识">
          </div>
          
          <div class="field-item">
            <label>样本类型 (决定技术路线)</label>
            <div class="type-selector">
              <div 
                v-for="type in [SampleType.BACTERIA, SampleType.VIRUS, SampleType.PHAGE]" 
                :key="type"
                class="type-option"
                :class="{ active: taskState.sampleType === type, disabled: isRunning }"
                @click="!isRunning && (taskState.sampleType = type)"
              >
                <span class="type-icon">{{ type === SampleType.BACTERIA ? '🧫' : type === SampleType.VIRUS ? '🦠' : '🧬' }}</span>
                <span class="type-name">{{ type }}</span>
              </div>
            </div>
          </div>

          <div class="field-item">
            <label>测序平台</label>
            <div class="platform-toggle">
              <div 
                v-for="tech in [SequencingTech.ILLUMINA, SequencingTech.NANOPORE, SequencingTech.PACBIO_HIFI]" 
                :key="tech"
                class="toggle-item"
                :class="{ active: taskState.tech === tech, disabled: isRunning }"
                @click="!isRunning && (taskState.tech = tech)"
              >
                {{ tech === SequencingTech.ILLUMINA ? 'Illumina' : tech === SequencingTech.NANOPORE ? 'Nanopore' : 'PacBio' }}
              </div>
            </div>
          </div>

          <div class="field-item">
            <label class="checkbox-label">
              <input type="checkbox" v-model="taskState.useGPU" :disabled="isRunning"> 开启 GPU 计算加速
            </label>
          </div>

          <div class="field-item hint">
            <p>※ 系统将根据样本类型自动匹配最优流程（如：细菌选用 Unicycler，病毒选用 IVA）</p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.assembly-workspace {
  padding: 24px 32px;
  background: #f8fafc;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.workspace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}

h1 {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.subtitle {
  color: #64748b;
  font-size: 14px;
  margin-top: 4px;
}

.btn-primary {
  background: #2563eb;
  color: white;
  padding: 10px 24px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-1px);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 进度条 */
.workflow-stepper {
  display: flex;
  margin-bottom: 32px;
  padding: 0 40px;
}

.step-node {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}

.step-node::after {
  content: '';
  position: absolute;
  top: 18px;
  left: calc(50% + 24px);
  right: calc(-50% + 24px);
  height: 2px;
  background: #e2e8f0;
}

.step-node:last-child::after { display: none; }

.node-circle {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: white;
  border: 2px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #94a3b8;
  z-index: 1;
  margin-bottom: 12px;
  transition: all 0.3s;
}

.step-node.active .node-circle {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}

.step-node.completed .node-circle {
  background: #10b981;
  border-color: #10b981;
  color: white;
}

.node-label h3 {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.node-label p {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 全局进度 */
.global-progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  margin-bottom: 32px;
  position: relative;
  overflow: visible;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #60a5fa);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-label {
  position: absolute;
  right: 0;
  top: -22px;
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
}

/* 布局区域 */
.workspace-layout {
  display: flex;
  gap: 24px;
  flex: 1;
}

.panel-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
}

.upload-panel { flex: 1.4; display: flex; flex-direction: column; }
.config-panel { flex: 1; }

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.panel-header h2 { font-size: 16px; font-weight: 600; color: #1e293b; margin: 0; }

.status-badge {
  background: #f1f5f9;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  text-transform: uppercase;
}

.status-badge.running {
  background: #eff6ff;
  color: #2563eb;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.6; }
  100% { opacity: 1; }
}

.dropzone {
  flex: 1;
  border: 2px dashed #e2e8f0;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  background: #fcfdfe;
}

.dropzone:not(.disabled):hover {
  border-color: #2563eb;
  background: #f8fafc;
}

.dropzone.disabled {
  background: #f1f5f9;
  cursor: not-allowed;
  border-style: solid;
}

.drop-icon { width: 48px; height: 48px; color: #cbd5e1; margin-bottom: 16px; }

.main-tip { font-size: 15px; color: #1e293b; font-weight: 500; }
.main-tip span { color: #2563eb; text-decoration: underline; }
.sub-tip { font-size: 13px; color: #94a3b8; margin-top: 8px; }

/* 配置表单 */
.config-form { display: flex; flex-direction: column; gap: 24px; }

.type-selector {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.type-option {
  padding: 12px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fcfdfe;
}

.type-option:hover:not(.disabled) { border-color: #2563eb; background: #f8fafc; }
.type-option.active { border-color: #2563eb; background: #eff6ff; color: #2563eb; font-weight: 600; }
.type-icon { font-size: 20px; margin-bottom: 6px; }
.type-name { font-size: 11px; }
.type-option.disabled { opacity: 0.5; cursor: not-allowed; }

.field-item label { display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 10px; }

.form-input {
  width: 100%;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  background: #fcfdfe;
}

.platform-toggle { display: flex; background: #f1f5f9; padding: 4px; border-radius: 10px; }
.toggle-item {
  flex: 1;
  text-align: center;
  padding: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  border-radius: 8px;
}
.toggle-item.active { background: white; color: #1e293b; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.toggle-item.disabled { opacity: 0.5; cursor: not-allowed; }

.checkbox-label { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #475569; cursor: pointer; }
.hint p { font-size: 12px; color: #94a3b8; font-style: italic; line-height: 1.5; }
</style>
