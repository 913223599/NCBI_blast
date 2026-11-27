<script setup lang="ts">
/**
 * AnalysisView - 组装分析工作台入口
 * 职责：提供组装后的深度分析工具集（全场景共线性分析、序列交互式可视化、全基因组功能注释）
 * 遵循模块化设计，每个工具为一个独立的子组件。
 */
import { computed, defineAsyncComponent, ref } from 'vue'
import { useI18n } from '../locales'
import AsyncModuleLoading from '../components/common/AsyncModuleLoading.vue'
import AsyncModuleError from '../components/common/AsyncModuleError.vue'
import WorkbenchHubLayout from '../components/layout/WorkbenchHubLayout.vue'
import type { StructureInitialPayload } from './Analysis/modules/phage_structure/types'

const asyncOpts = {
  loadingComponent: AsyncModuleLoading,
  errorComponent: AsyncModuleError,
  delay: 150,
}

const GenomeViewerModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/viewer/GenomeViewerModule.vue'),
})
const AnnotationModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/annotation/AnnotationModule.vue'),
})
const PhageDiscoveryModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/phage_discovery/PhageDiscoveryModule.vue'),
})
const PhageStructureModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/phage_structure/PhageStructureModule.vue'),
})
const PanGenomicsModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/pan_genomics/PanGenomicsModule.vue'),
})
const SangerTraceModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./Analysis/modules/sanger_trace/SangerTraceModule.vue'),
})

interface AnalysisTool {
  id: string;
  title: string;
  description: string;
  iconType: 'chart' | 'dna' | 'book' | 'phage' | 'structure' | 'pangenome' | 'trace';
  status: 'ready' | 'beta' | 'coming_soon';
}

const { t } = useI18n()

const tools = computed<AnalysisTool[]>(() => [
  { 
    id: 'sanger_trace', 
    title: t('analysis.tool.sanger_trace.title'), 
    description: t('analysis.tool.sanger_trace.desc'), 
    iconType: 'trace',
    status: 'ready'
  },
  { 
    id: 'annotation', 
    title: t('analysis.tool.annotation.title'), 
    description: t('analysis.tool.annotation.desc'), 
    iconType: 'book',
    status: 'ready'
  },
  { 
    id: 'phage_discovery', 
    title: t('analysis.tool.phage_discovery.title'), 
    description: t('analysis.tool.phage_discovery.desc'), 
    iconType: 'phage',
    status: 'ready'
  },
  {
    id: 'phage_structure',
    title: t('analysis.tool.phage_structure.title'),
    description: t('analysis.tool.phage_structure.desc'),
    iconType: 'structure',
    status: 'ready'
  },
  { 
    id: 'pan_genomics', 
    title: t('analysis.tool.pan_genomics.title'), 
    description: t('analysis.tool.pan_genomics.desc'), 
    iconType: 'pangenome',
    status: 'ready'
  },
  { 
    id: 'viewer', 
    title: t('analysis.tool.viewer.title'), 
    description: t('analysis.tool.viewer.desc'), 
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
const structureInitialPayload = ref<StructureInitialPayload | null>(null)

function selectTool(tool: AnalysisTool) {
  if (tool.status === 'coming_soon') return
  if (tool.id !== 'phage_structure') {
    structureInitialPayload.value = null
  }
  activeTool.value = tool.id
}

function handleOpenViewerFromAnnotation(payload: { gbkText: string; taskName: string }) {
  viewerInitialGbk.value = payload.gbkText
  viewerInitialName.value = payload.taskName
  activeTool.value = 'viewer'
}

const VALID_ANNOTATION_SAMPLE_TYPES = ['PHAGE', 'BACTERIA', 'VIRUS', 'GENERAL'] as const
type AnnotationSampleType = (typeof VALID_ANNOTATION_SAMPLE_TYPES)[number]

function toAnnotationSampleType(raw?: string): AnnotationSampleType {
  if (raw && (VALID_ANNOTATION_SAMPLE_TYPES as readonly string[]).includes(raw)) {
    return raw as AnnotationSampleType
  }
  return 'PHAGE'
}

function handleOpenAnnotationFromPhage(payload: { fastaText: string; taskName: string; sampleType?: string }) {
  annotationInitialFasta.value = payload.fastaText
  annotationInitialName.value = payload.taskName
  annotationInitialSampleType.value = toAnnotationSampleType(payload.sampleType)
  activeTool.value = 'annotation'
}

function handleOpenStructureFromAnnotation(payload: { taskId: string; taskName: string }) {
  structureInitialPayload.value = {
    sourceMode: 'annotation',
    taskId: payload.taskId,
    taskName: payload.taskName,
  }
  activeTool.value = 'phage_structure'
}

function handleOpenStructureFromPhage(payload: { taskId: string; taskName: string; regionIndex?: number }) {
  structureInitialPayload.value = {
    sourceMode: 'phage_discovery',
    taskId: payload.taskId,
    taskName: payload.taskName,
    regionIndex: payload.regionIndex,
  }
  activeTool.value = 'phage_structure'
}
</script>

<template>
  <WorkbenchHubLayout
    :title="t('analysis.hub.title')"
    :subtitle="t('analysis.hub.subtitle')"
    :active="Boolean(activeTool)"
    :stat-label="t('analysis.hub.stat_label')"
    :stat-value="tools.length"
    :back-label="t('analysis.hub.back_label')"
    accent="blue"
    grid-min-width="300px"
    @back="activeTool = null"
  >
    <template #grid>
      <button
        v-for="tool in tools"
        :key="tool.id"
        type="button"
        :class="['tool-card', tool.status]"
        :disabled="tool.status === 'coming_soon'"
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
          <svg v-else-if="tool.iconType === 'structure'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" stroke-width="2.1">
            <polygon points="12 2 17 5 17 10 12 13 7 10 7 5 12 2" />
            <rect x="10" y="13" width="4" height="7" rx="1" />
            <line x1="8" y1="16" x2="16" y2="16" />
            <line x1="12" y1="20" x2="7" y2="23" />
            <line x1="12" y1="20" x2="17" y2="23" />
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
      </button>
    </template>

    <template #workspace>
      <SangerTraceModule v-if="activeTool === 'sanger_trace'" />
      <AnnotationModule
        v-else-if="activeTool === 'annotation'"
        :initial-fasta="annotationInitialFasta"
        :initial-name="annotationInitialName"
        :initial-sample-type="annotationInitialSampleType"
        @open-viewer="handleOpenViewerFromAnnotation"
        @open-structure="handleOpenStructureFromAnnotation"
      />
      <PhageDiscoveryModule
        v-else-if="activeTool === 'phage_discovery'"
        @open-viewer="handleOpenViewerFromAnnotation"
        @open-annotation="handleOpenAnnotationFromPhage"
        @open-structure="handleOpenStructureFromPhage"
      />
      <PhageStructureModule
        v-else-if="activeTool === 'phage_structure'"
        :initial-payload="structureInitialPayload"
        @open-viewer="handleOpenViewerFromAnnotation"
      />
      <PanGenomicsModule v-else-if="activeTool === 'pan_genomics'" />
      <GenomeViewerModule
        v-else-if="activeTool === 'viewer'"
        :initial-gbk="viewerInitialGbk"
        :initial-name="viewerInitialName"
      />
      <div v-else class="workspace-placeholder">
        <h2>{{ tools.find((t) => t.id === activeTool)?.title }} 模块开发中</h2>
        <p>正在拉取 {{ activeTool }} 算法引擎，请稍候...</p>
      </div>
    </template>
  </WorkbenchHubLayout>
</template>

<style scoped>
.tool-card {
  width: 100%;
  text-align: left;
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

.workspace-placeholder {
  text-align: center;
  max-width: 400px;
  margin: 60px auto;
}

.workspace-placeholder h2 { color: #1e293b; margin: 0 0 12px; }
.workspace-placeholder p { color: #64748b; font-size: 14px; }
</style>
