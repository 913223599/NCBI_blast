
<script setup lang="ts">
import { SequencingTech, SampleType } from '../../../modules/AssemblyCoordinator/index';

const props = defineProps<{
  taskState: any;
  isRunning: boolean;
  onPickCustomHost?: () => void;
}>();

const emit = defineEmits(['update:taskState']);

const setTech = (tech: string) => {
  if (props.isRunning) return;
  props.taskState.tech = tech;
};

const setSampleType = (type: string) => {
  if (props.isRunning) return;
  props.taskState.sampleType = type;
};
</script>

<template>
  <div class="config-section card">
    <div class="card-header">
      <h3>技术路线配置</h3>
    </div>

    <div class="form-body">
      <div class="field-item">
        <label>任务名称</label>
        <input type="text" v-model="taskState.name" placeholder="输入任务识别名称" class="form-input" :disabled="isRunning">
      </div>

      <div class="field-item">
        <label>样本类型 (决定技术路线)</label>
        <div class="type-selector">
          <div 
            v-for="type in [SampleType.BACTERIA, SampleType.VIRUS, SampleType.PHAGE, SampleType.AMPLICON]" 
            :key="type"
            class="type-option"
            :class="{ 'active': taskState.sampleType === type }"
            @click="setSampleType(type)"
          >
            <span class="type-icon">{{ type === 'PHAGE' ? '🧬' : (type === 'VIRUS' ? '🦠' : (type === 'BACTERIA' ? '🧫' : '🧪')) }}</span>
            <span class="type-label">{{ type }}</span>
          </div>
        </div>
      </div>

      <div class="field-item">
        <label>测序平台</label>
        <div class="tech-grid">
          <button 
            v-for="tech in [SequencingTech.ILLUMINA, SequencingTech.NANOPORE, SequencingTech.PACBIO_HIFI, SequencingTech.SANGER]"
            :key="tech"
            class="tech-btn"
            :class="{ 'active': taskState.tech === tech }"
            @click="setTech(tech)"
            :disabled="isRunning"
          >
            {{ tech.charAt(0) + tech.slice(1).toLowerCase() }}
          </button>
        </div>
      </div>

      <div class="field-item checkbox-group">
        <label class="checkbox-label">
          <input type="checkbox" v-model="taskState.useGPU" :disabled="isRunning">
          开启 GPU 计算加速
        </label>
      </div>

      <!-- 动态路由参数 -->
      <div class="field-item" v-if="taskState.sampleType === 'PHAGE'">
        <label>宿主参考基因组 (用于背景剔除)</label>
        <select class="form-input" v-model="taskState.selectedHostDb" :disabled="isRunning">
          <option value="search_ncbi">🔍 联网搜索并下载 (NCBI)...</option>
          <option value="custom">📤 上传自定义宿主基因组 (.fasta)</option>
        </select>
        
        <!-- 云端搜索 -->
        <div v-if="taskState.selectedHostDb === 'search_ncbi'" class="ncbi-search-box">
          <input 
            type="text" 
            v-model="taskState.ncbiSearchTerm" 
            placeholder="请输入属名或种属学名 (例如: Klebsiella)"
            class="form-input search-input"
            :disabled="isRunning"
          >
          <p class="search-hint">※ 支持输入<b>“属”</b>名，系统将自动抓取该属的代表性参考序列</p>
        </div>

        <!-- 自定义上传 (独立通道) -->
        <div v-if="taskState.selectedHostDb === 'custom'" class="custom-host-box">
          <button @click="onPickCustomHost" class="action-link" :disabled="isRunning">
            📂 选择本地宿主 .fasta 文件
          </button>
          <div v-if="taskState.customHostPath" class="path-preview">
            <span class="path-text">已选择: {{ taskState.customHostPath.split(/[\\/]/).pop() }}</span>
            <span class="full-path" :title="taskState.customHostPath">📁</span>
          </div>
          <p v-else class="search-hint">※ 请选择一个参考基因组文件以便精准过滤</p>
        </div>
      </div>

      <div class="field-item" v-if="taskState.sampleType === 'AMPLICON'">
        <label>参考数据库 (16S/18S)</label>
        <select class="form-input" v-model="taskState.selectedDatabase" :disabled="isRunning">
          <option value="silva">SILVA (138.1)</option>
          <option value="greengenes">Greengenes</option>
          <option value="rdp">RDP</option>
        </select>
      </div>

      <div class="hint">
        <p>※ 系统将根据样本类型自动匹配最优流程 (如：细菌选用 Unicycler，Sanger 选用 Consensus 合并)</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.card-header h3 { font-size: 16px; color: #1e293b; margin: 0 0 20px 0; }

.field-item { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.field-item label { display: block; font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 8px; }

.form-input { 
  width: 100%; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px;
  background: #f8fafc; transition: all 0.2s;
}
.form-input:focus { outline: none; border-color: #3b82f6; background: white; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1); }

.type-selector { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.type-option {
  padding: 12px; border: 1px solid #f1f5f9; border-radius: 10px; cursor: pointer;
  display: flex; flex-direction: row; align-items: center; gap: 10px; transition: all 0.2s;
}
.type-option:hover { background: #f8fafc; }
.type-option.active { border-color: #3b82f6; background: #eff6ff; }
.type-icon { font-size: 18px; }
.type-label { font-size: 11px; font-weight: 600; color: #475569; }

.tech-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.tech-btn {
  padding: 8px; border: 1px solid #f1f5f9; border-radius: 6px; background: #f8fafc;
  font-size: 12px; color: #64748b; cursor: pointer; transition: all 0.2s;
}
.tech-btn.active { background: #3b82f6; color: white; border-color: #3b82f6; font-weight: 700; box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2); }

.ncbi-search-box, .custom-host-box { 
  margin-top: 10px; padding: 12px; background: #f0f7ff; border: 1px dashed #3b82f6; border-radius: 8px; 
}
.action-link {
  background: white; border: 1px solid #3b82f6; color: #3b82f6; padding: 6px 12px;
  border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;
  width: 100%; margin-bottom: 8px;
}
.action-link:hover { background: #3b82f6; color: white; }
.path-preview { display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: #1e293b; background: white; padding: 6px 10px; border-radius: 4px; }
.path-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px; }
.full-path { cursor: help; opacity: 0.6; }

.search-input { background: white !important; }

.hint p { font-size: 11px; color: #94a3b8; font-style: italic; line-height: 1.5; margin-top: 15px; }

.checkbox-label { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #475569; cursor: pointer; }
</style>
