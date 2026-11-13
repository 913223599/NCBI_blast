<script setup lang="ts">
/**
 * AnalysisView - 组装分析工作台入口
 * 职责：提供组装后的深度分析工具集（全场景共线性分析、序列交互式可视化、全基因组功能注释）
 * 遵循模块化设计，每个工具为一个独立的子组件。
 */
import { ref } from 'vue'
import GenomeViewerModule from './Analysis/modules/viewer/GenomeViewerModule.vue'
import AnnotationModule from './Analysis/modules/annotation/AnnotationModule.vue'
import PhageDiscoveryModule from './Analysis/modules/phage_discovery/PhageDiscoveryModule.vue'
import PanGenomicsModule from './Analysis/modules/pan_genomics/PanGenomicsModule.vue'
import SangerTraceModule from './Analysis/modules/sanger_trace/SangerTraceModule.vue'

interface AnalysisTool {
  id: string;
  title: string;
  description: string;
  iconType: 'chart' | 'dna' | 'book' | 'phage' | 'pangenome' | 'trace';
  status: 'ready' | 'beta' | 'coming_soon';
}

const tools = ref<AnalysisTool[]>([
  { 
    id: 'sanger_trace', 
    title: 'Sanger 测序峰图分析与突变检测', 
    description: '解析 AB1 测序色谱荧光信号，检测单核苷酸变异 (SNV) 与 InDel 移码重叠峰，支持双单倍型位移解卷积分离与主序列提取。', 
    iconType: 'trace',
    status: 'ready'
  },
  { 
    id: 'annotation', 
    title: '全基因组结构与功能注释', 
    description: '基于 Prokka 与 Pharokka 流程进行 CDS、tRNA 及 rRNA 基因预测与功能注释，生成标准注释文件并支持图谱可视化联动。', 
    iconType: 'book',
    status: 'ready'
  },
  { 
    id: 'phage_discovery', 
    title: '前噬菌体与噬菌体智能发现', 
    description: '基于 Student V4.2 与 200bp SubBinRefiner 边界精修模型，从宿主全基因组或拼接 Contigs 中精准分割前噬菌体区域，支持可选蛋白门控验证与联动注释。', 
    iconType: 'phage',
    status: 'ready'
  },
  { 
    id: 'pan_genomics', 
    title: '多样本泛基因组比较分析', 
    description: '基于直系同源基因聚类构建核心基因组与特异基因组，解析同源家族得失、受体结合蛋白多态性及溶源/安全性特征。', 
    iconType: 'pangenome',
    status: 'ready'
  },
  { 
    id: 'viewer', 
    title: '基因组序列图谱可视化', 
    description: '提供交互式序列与基因特征图谱查看器，支持环形 (Circular) 与线性 (Linear) 双模式，兼容 GenBank 及 GFF3 格式。', 
    iconType: 'dna',
    status: 'ready'
  }
])

const activeTool = ref<string | null>(null)

// 传递给 GenomeViewer 与 Annotation 的跨模块数据
const viewerInitialGbk = ref<string>('')
const viewerInitialName = ref<string>('')
const annotationInitialFasta = ref<string>('')
const annotationInitialName = ref<string>('')
const annotationInitialSampleType = ref<'PHAGE' | 'BACTERIA' | 'VIRUS' | 'GENERAL'>('PHAGE')

function selectTool(tool: AnalysisTool) {
  if (tool.status === 'coming_soon') return
  activeTool.value = tool.id
}

function handleOpenViewerFromAnnotation(payload: { gbkText: string; taskName: string }) {
  viewerInitialGbk.value = payload.gbkText
  viewerInitialName.value = payload.taskName
  activeTool.value = 'viewer'
}

function handleOpenAnnotationFromPhage(payload: { fastaText: string; taskName: string; sampleType?: string }) {
  annotationInitialFasta.value = payload.fastaText
  annotationInitialName.value = payload.taskName
  annotationInitialSampleType.value = (payload.sampleType as any) || 'PHAGE'
  activeTool.value = 'annotation'
}
</script>

<template>
  <div class="analysis-container">
    <header class="analysis-header">
      <div class="header-content">
        <h1>组装分析工作台</h1>
        <p>基因组功能注释与比较基因组学分析工作台，支持结构与功能注释、V4.2 前噬菌体边界发现、多样本泛基因组分析、Sanger 测序突变解析及序列图谱可视化。</p>
      </div>
      <div class="header-stats" v-if="!activeTool">
         <div class="stat-badge">
            <span class="label">可用工具</span>
            <span class="value">{{ tools.length }}</span>
         </div>
      </div>
      <button v-else class="back-btn" @click="activeTool = null">
        &larr; 返回工具列表
      </button>
    </header>

    <main class="analysis-content">
      <!-- 紧凑型工具网格 -->
      <div v-if="!activeTool" class="tools-grid">
        <div 
          v-for="tool in tools" 
          :key="tool.id" 
          :class="['tool-card', tool.status]"
          @click="selectTool(tool)"
        >
          <div class="tool-icon-mini">
            <!-- 矢量 SVG 图标：严禁 Emoji -->
            <svg v-if="tool.iconType === 'trace'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.2">
              <path d="M2 20h20" />
              <path d="M4 20l4-12 4 8 4-14 4 18" />
              <circle cx="8" cy="8" r="1.5" fill="#10b981" />
              <circle cx="16" cy="6" r="1.5" fill="#dc2626" />
            </svg>
            <svg v-else-if="tool.iconType === 'book'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              <line x1="9" y1="7" x2="15" y2="7" />
              <line x1="9" y1="11" x2="13" y2="11" />
            </svg>
            <svg v-else-if="tool.iconType === 'phage'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4338ca" stroke-width="2.1">
              <polygon points="12 2 19 6 19 13 12 17 5 13 5 6 12 2" />
              <line x1="12" y1="17" x2="12" y2="22" />
              <path d="M8 22l4-2 4 2" />
              <circle cx="12" cy="9.5" r="2.2" />
            </svg>
            <svg v-else-if="tool.iconType === 'pangenome'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0284c7" stroke-width="2.2">
              <circle cx="12" cy="12" r="3" />
              <circle cx="4" cy="12" r="2" />
              <circle cx="20" cy="12" r="2" />
              <circle cx="12" cy="4" r="2" />
              <circle cx="12" cy="20" r="2" />
              <line x1="6" y1="12" x2="9" y2="12" />
              <line x1="15" y1="12" x2="18" y2="12" />
              <line x1="12" y1="6" x2="12" y2="9" />
              <line x1="12" y1="15" x2="12" y2="18" />
            </svg>
            <svg v-else-if="tool.iconType === 'dna'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2.2">
              <path d="M2 15c6.667-6 13.333 0 20-6" />
              <path d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993" />
              <path d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993" />
              <path d="M17 6l-2.5-2.5" />
              <path d="M14 8l-4-4" />
              <path d="M7 18l2.5 2.5" />
              <path d="M3.5 14.5l.5.5" />
              <path d="M20 9.5l.5.5" />
            </svg>
          </div>
          <div class="tool-body">
            <div class="tool-title-row">
              <h3>{{ tool.title }}</h3>
              <span :class="['status-tag-mini', tool.status]">{{ tool.status === 'ready' ? '' : tool.status.toUpperCase() }}</span>
            </div>
            <p class="tool-desc">{{ tool.description }}</p>
          </div>
        </div>
      </div>

      <!-- 具体工具工作区 -->
      <div v-else class="tool-workspace">
        <SangerTraceModule v-if="activeTool === 'sanger_trace'" />
        <AnnotationModule 
          v-else-if="activeTool === 'annotation'" 
          :initial-fasta="annotationInitialFasta"
          :initial-name="annotationInitialName"
          :initial-sample-type="annotationInitialSampleType"
          @open-viewer="handleOpenViewerFromAnnotation" 
        />
        <PhageDiscoveryModule
          v-else-if="activeTool === 'phage_discovery'"
          @open-viewer="handleOpenViewerFromAnnotation"
          @open-annotation="handleOpenAnnotationFromPhage"
        />
        <PanGenomicsModule v-else-if="activeTool === 'pan_genomics'" />
        <GenomeViewerModule 
          v-else-if="activeTool === 'viewer'" 
          :initial-gbk="viewerInitialGbk"
          :initial-name="viewerInitialName"
        />
        <div v-else class="workspace-placeholder">
           <h2>{{ tools.find(t => t.id === activeTool)?.title }} 模块开发中</h2>
           <p>正在拉取 {{ activeTool }} 算法引擎，请稍候...</p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.analysis-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
}

.analysis-header {
  padding: 12px 24px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h1 {
  margin: 0;
  font-size: 18px;
  color: #1e293b;
  letter-spacing: -0.5px;
}

.header-content p {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 12px;
}

.stat-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.stat-badge .label {
  color: #64748b;
}

.stat-badge .value {
  color: #2563eb;
  font-weight: 700;
}

.back-btn {
  background: #f1f5f9;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.analysis-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  padding: 32px 40px;
  overflow-y: auto;
}

.tool-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  position: relative;
}

.tool-card:hover:not(.coming_soon) {
  border-color: #3b82f6;
  background: #f0f7ff;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
  transform: translateY(-2px);
}

.tool-icon-mini {
  width: 44px;
  height: 44px;
  background: #f8fafc;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid #e2e8f0;
}

.tool-body {
  flex: 1;
  min-width: 0;
}

.tool-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.tool-title-row h3 {
  margin: 0;
  font-size: 15px;
  color: #1e293b;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-tag-mini {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 700;
}

.status-tag-mini.ready { display: none; }
.status-tag-mini.beta { background: #fff7ed; color: #ea580c; }
.status-tag-mini.coming_soon { background: #f1f5f9; color: #94a3b8; }

.tool-desc {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tool-card.coming_soon {
  opacity: 0.6;
  cursor: not-allowed;
  background: #f8fafc;
}

.tool-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow-y: auto;
}

.workspace-placeholder {
  text-align: center;
  max-width: 400px;
  margin: 60px auto;
}

.workspace-placeholder h2 { color: #1e293b; margin: 0 0 12px; }
.workspace-placeholder p { color: #64748b; font-size: 14px; }
</style>
