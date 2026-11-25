<script setup lang="ts">
/**
 * FigureStudioView - 科研绘图工坊统一工具组工作台
 * 将系统发育树构建与多环出版出图，以及六大噬菌体顶刊核心图型整合为模块化卡片工具组。
 */
import { computed, defineAsyncComponent, ref } from 'vue'
import AsyncModuleLoading from '../components/common/AsyncModuleLoading.vue'
import AsyncModuleError from '../components/common/AsyncModuleError.vue'
import CitationsDialog from '../components/common/CitationsDialog.vue'
import WorkbenchHubLayout from '../components/layout/WorkbenchHubLayout.vue'

const asyncOpts = {
  loadingComponent: AsyncModuleLoading,
  errorComponent: AsyncModuleError,
  delay: 150,
}

const PhyloWorkbench = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/phylo/components/PhyloWorkbench.vue'),
})
const DiversityWindowTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/DiversityWindowTool.vue'),
})
const GeneNetworkTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/GeneNetworkTool.vue'),
})
const GenomeMapTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/GenomeMapTool.vue'),
})
const HostMatrixTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/HostMatrixTool.vue'),
})
const SyntenyRibbonTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/SyntenyRibbonTool.vue'),
})
const ViridicHeatmapTool = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('../modules/figure_studio/components/ViridicHeatmapTool.vue'),
})

type StudioToolId =
  | 'phylo_tree'
  | 'viridic_heatmap'
  | 'genome_map'
  | 'synteny_ribbon'
  | 'diversity_window'
  | 'gene_network'
  | 'host_matrix'

interface StudioToolCard {
  id: StudioToolId
  title: string
  journalRef: string
  description: string
  iconType: 'tree' | 'heatmap' | 'circmap' | 'synteny' | 'diversity' | 'network' | 'matrix'
}

const tools: StudioToolCard[] = [
  {
    id: 'phylo_tree',
    title: '系统发育树构建与多环出版出图',
    journalRef: 'Nature Micro / Nat Commun / iTOL',
    description:
      '全套 TerL / 蛋白质组构树科研流水线，支持环形多环、180 度半圆宽幅树、复合双拼论文图 (a+b)、矩形多轨及实时缩放大图预览。',
    iconType: 'tree',
  },
  {
    id: 'viridic_heatmap',
    title: 'VIRIDIC 双向相似性与 ANI 矩阵',
    journalRef: 'Viruses (VIRIDIC) / Nat Commun',
    description:
      '生成 ICTV 标准双三角全基因组相似性热图（右上相似度 + 左下对齐覆盖度/长度比 + 顶部长度柱图）及树-热图联动下三角 ANI 矩阵。',
    iconType: 'heatmap',
  },
  {
    id: 'genome_map',
    title: '单株全基因组功能圈图与多轨图',
    journalRef: 'CGView / Proksee / LoVis4u',
    description:
      '一键接入已完成的 Pharokka/Prokka 注释任务或 GBK 文件，输出带正负链 CDS、PHROGs 功能色、GC Content 与 GC Skew 的论文 Figure 1 图谱。',
    iconType: 'circmap',
  },
  {
    id: 'synteny_ribbon',
    title: '比较基因组共线性丝带图',
    journalRef: 'NAR LoVis4u (2025) / clinker',
    description:
      '内置多线程蛋白同源对齐，支持 LoVis4u 去噪高亮风格与 clinker 贝塞尔曲线丝带风格，直观揭示尾丝变异、缺失岛及抗防御基因。',
    iconType: 'synteny',
  },
  {
    id: 'diversity_window',
    title: '同种多株系核苷酸多样性 (Pi) 热点图',
    journalRef: 'Nature Communications (2024)',
    description:
      '专门放大高相似度同种与近缘株内部演化信号，用滑窗 Pi 曲线与基因内部蓝→黄→红热图定量定位高变受体/蛋白热点并附对照表。',
    iconType: 'diversity',
  },
  {
    id: 'gene_network',
    title: '蛋白基因共享网络与构成华夫格图',
    journalRef: 'Nat Biotech vConTACT2 / Nat Commun',
    description:
      '基于力导向图揭示水平基因转移与嵌合噬菌体网状亲缘关系，自动网格化底部孤立小簇并在右侧附带 10x10 类别占比华夫格图。',
    iconType: 'network',
  },
  {
    id: 'host_matrix',
    title: '双树联动宿主谱与特异性矩阵',
    journalRef: 'Nature Commun DepoCatalog / EOP',
    description:
      '支持宿主聚类树 + 噬菌体树双边联动连续热图及对角化血清型-解聚酶/裂解活性稀疏矩阵，快速支撑噬菌体疗法与鸡尾酒配伍发表。',
    iconType: 'matrix',
  },
]

const activeTool = ref<StudioToolId | null>(null)
const showCitationsDialog = ref(false)
const currentToolObj = computed(() => tools.find((t) => t.id === activeTool.value) ?? null)

function selectTool(id: StudioToolId): void {
  activeTool.value = id
}
</script>

<template>
  <WorkbenchHubLayout
    :title="currentToolObj ? currentToolObj.title : '科研绘图工坊'"
    :subtitle="
      currentToolObj
        ? `${currentToolObj.journalRef} · 均支持出版级矢量 PDF / SVG 与高清 PNG 输出及界面实时缩放预览`
        : '对标 Nature Microbiology / Nature Communications / NAR 顶刊图型标准的专用出图工具组，直接复用系统内注释与进化分析产物。'
    "
    :active="Boolean(activeTool)"
    stat-label="可用图型"
    :stat-value="tools.length"
    back-label="返回工坊工具组"
    accent="teal"
    grid-min-width="310px"
    @back="activeTool = null"
  >
    <template #header-extra>
      <button type="button" class="citations-btn" @click="showCitationsDialog = true">
        学术引用 (BibTeX)
      </button>
    </template>

    <template #grid>
      <button
        v-for="tool in tools"
        :key="tool.id"
        type="button"
        class="tool-card"
        @click="selectTool(tool.id)"
      >
        <div class="tool-icon-mini">
          <svg v-if="tool.iconType === 'tree'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0f766e" stroke-width="2.1">
            <path d="M5 4v16" />
            <path d="M5 7h7v-2h5" />
            <path d="M5 7h7v3h5" />
            <path d="M5 17h6v-2h6" />
            <path d="M5 17h6v3h6" />
          </svg>
          <svg v-else-if="tool.iconType === 'heatmap'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0284c7" stroke-width="2.0">
            <rect x="3" y="3" width="6" height="6" fill="#bae6fd" />
            <rect x="9" y="3" width="6" height="6" fill="#0284c7" />
            <rect x="15" y="3" width="6" height="6" fill="#065f46" />
            <rect x="3" y="9" width="6" height="6" fill="#fed7aa" />
            <rect x="9" y="9" width="6" height="6" fill="#0284c7" />
            <rect x="15" y="9" width="6" height="6" fill="#38bdf8" />
            <rect x="3" y="15" width="6" height="6" fill="#fb923c" />
            <rect x="9" y="15" width="6" height="6" fill="#fed7aa" />
            <rect x="15" y="15" width="6" height="6" fill="#065f46" />
          </svg>
          <svg v-else-if="tool.iconType === 'circmap'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2.1">
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" stroke-dasharray="4 2" />
            <path d="M12 3a9 9 0 0 1 8.5 6" stroke="#16a34a" stroke-width="2.6" />
          </svg>
          <svg v-else-if="tool.iconType === 'synteny'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.0">
            <path d="M3 6h6l2 2-2 2H3z" />
            <path d="M13 6h6l2 2-2 2h-6z" />
            <path d="M3 16h6l2 2-2 2H3z" />
            <path d="M14 16h5l2 2-2 2h-5z" />
            <path d="M6 10l0 6M16 10l1 6" stroke="#94a3b8" stroke-width="1.5" />
          </svg>
          <svg v-else-if="tool.iconType === 'diversity'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.1">
            <path d="M2 14h3l2-7 3 9 3-11 2 9h7" />
            <rect x="3" y="17" width="18" height="3" rx="1" stroke="#334155" />
          </svg>
          <svg v-else-if="tool.iconType === 'network'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.1">
            <circle cx="12" cy="12" r="2.5" fill="#dc2626" stroke="#dc2626" />
            <circle cx="5" cy="7" r="2" />
            <circle cx="19" cy="7" r="2" />
            <circle cx="6" cy="18" r="2" />
            <circle cx="18" cy="18" r="2" />
            <path d="M7 8l3 2.5M17 8l-3 2.5M7.5 16.5l3-3M16.5 16.5l-3-3" />
          </svg>
          <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" stroke-width="2.0">
            <path d="M3 7h3v10H3" />
            <rect x="9" y="5" width="4" height="4" fill="#6d326d" />
            <rect x="13" y="5" width="4" height="4" fill="#e8c4c4" />
            <rect x="17" y="5" width="4" height="4" fill="#f8f6ed" />
            <rect x="9" y="9" width="4" height="4" fill="#b86b91" />
            <rect x="13" y="9" width="4" height="4" fill="#6d326d" />
            <rect x="17" y="9" width="4" height="4" fill="#e8c4c4" />
            <path d="M11 19v-3h8v3" />
          </svg>
        </div>
        <div class="tool-body">
          <div class="tool-title-row">
            <h3>{{ tool.title }}</h3>
          </div>
          <div class="tool-journal-badge">{{ tool.journalRef }}</div>
          <p class="tool-desc">{{ tool.description }}</p>
        </div>
      </button>
    </template>

    <template #workspace>
      <PhyloWorkbench v-if="activeTool === 'phylo_tree'" />
      <ViridicHeatmapTool v-else-if="activeTool === 'viridic_heatmap'" />
      <GenomeMapTool v-else-if="activeTool === 'genome_map'" />
      <SyntenyRibbonTool v-else-if="activeTool === 'synteny_ribbon'" />
      <DiversityWindowTool v-else-if="activeTool === 'diversity_window'" />
      <GeneNetworkTool v-else-if="activeTool === 'gene_network'" />
      <HostMatrixTool v-else-if="activeTool === 'host_matrix'" />
    </template>
  </WorkbenchHubLayout>
  <CitationsDialog v-model:open="showCitationsDialog" default-module="figure_studio" />
</template>

<style scoped>
.citations-btn { background: #f0fdfa; border: 1px solid #99f6e4; color: #0f766e; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
.citations-btn:hover { background: #ccfbf1; }
.tool-card { width: 100%; text-align: left; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: flex-start; gap: 15px; }
.tool-card:hover { border-color: #0f766e; background: #f0fdfa; box-shadow: 0 4px 14px rgba(15, 118, 110, 0.1); transform: translateY(-2px); }
.tool-icon-mini { width: 44px; height: 44px; background: #f8fafc; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid #e2e8f0; }
.tool-body { flex: 1; min-width: 0; }
.tool-title-row h3 { margin: 0 0 4px; font-size: 15px; color: #1e293b; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tool-journal-badge { display: inline-block; font-size: 10px; font-weight: 600; color: #0f766e; background: #ccfbf1; padding: 1px 7px; border-radius: 999px; margin-bottom: 6px; }
.tool-desc { margin: 0; color: #64748b; font-size: 12px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
