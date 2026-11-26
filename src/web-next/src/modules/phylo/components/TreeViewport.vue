<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { PhyloTreeCanvas } from '../core/TreeCanvas'
import { TreeExporter } from '../core/TreeExporter'
import type { PhyloTreeNode } from '../core/TreeModel'
import { usePhyloStore } from '../stores/usePhyloStore'
import { useAppStore } from '../../../stores/app'
import PublicationFigurePreview from './PublicationFigurePreview.vue'

const store = usePhyloStore()
const appStore = useAppStore()
const hostRef = ref<HTMLElement | null>(null)
const canvas = new PhyloTreeCanvas()

const contextMenu = ref<{
  visible: boolean
  x: number
  y: number
  node: PhyloTreeNode | null
}>({
  visible: false,
  x: 0,
  y: 0,
  node: null,
})

function renderTree(fit = false, relayout = true) {
  if (!store.hasTree) {
    canvas.clear()
    return
  }
  canvas.render(store.treeModel, store.visual, fit, relayout)
}

watch(() => store.hasTree, (val) => {
  if (!val) canvas.clear()
})

watch(() => store.treeRevision, () => {
  renderTree(true, true)
})

watch(() => store.viewportMode, (mode) => {
  if (mode === 'interactive' && store.hasTree) {
    nextTick(() => {
      renderTree(false, false)
    })
  }
})

watch(
  () => [
    store.visual.layout,
    store.visual.useBranchLengths,
    store.visual.rowSpacing,
    store.visual.fontSize,
    store.visual.showMetadataStrips,
    store.visual.labelFormat,
    store.visual.journalTheme,
    store.visual.alignTipLabels,
    store.visual.showCladeShading,
    store.visual.italicizeTaxa,
    store.visual.smartLabelCull,
  ],
  () => {
    renderTree(true, true)
  }
)

watch(
  () => [
    store.visual.showLabels,
    store.visual.showSupport,
    store.visual.supportThreshold,
    store.visual.highlightStrongUfboot,
  ],
  () => {
    renderTree(false, false)
  }
)

let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => store.visual.searchQuery,
  () => {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
    searchDebounceTimer = setTimeout(() => {
      renderTree(false, false)
    }, 150)
  }
)

onMounted(() => {
  if (hostRef.value) {
    canvas.mount(hostRef.value)
  }
  canvas.onNodeClick = (node, clientX, clientY) => {
    const menuW = 210
    const menuH = 220
    const clampedX = Math.max(8, Math.min(clientX, window.innerWidth - menuW - 8))
    const clampedY = Math.max(8, Math.min(clientY, window.innerHeight - menuH - 8))
    contextMenu.value = { visible: true, x: clampedX, y: clampedY, node }
  }
  if (store.hasTree) {
    renderTree(true, true)
  }
})

onUnmounted(() => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  canvas.dispose()
})

function closeContextMenu() {
  contextMenu.value.visible = false
}

async function handleOutgroup() {
  const n = contextMenu.value.node
  closeContextMenu()
  if (n && n.isLeaf && n.name) {
    await store.rerootOutgroup(n.name)
  }
}

function handleToggleCollapse() {
  const n = contextMenu.value.node
  closeContextMenu()
  if (n && !n.isLeaf) {
    store.toggleNodeCollapse(n.id)
  }
}

function handleColorClade(color: string | null) {
  const n = contextMenu.value.node
  closeContextMenu()
  if (n) {
    store.colorClade(n.id, color)
  }
}

async function handleCopyId() {
  const n = contextMenu.value.node
  closeContextMenu()
  if (n?.name) {
    await navigator.clipboard?.writeText(n.name).catch(() => {})
    appStore.showNotification(`已复制节点名: ${n.name}`, 'info')
  }
}

function handleExportSvg() {
  TreeExporter.exportSVG(canvas.buildExportSvg(), `${store.currentJob?.title || 'phylo_tree'}.svg`)
}

function handleExportPng() {
  TreeExporter.exportPNG(canvas.buildExportSvg(), `${store.currentJob?.title || 'phylo_tree'}.png`)
}

function handleExportNewick() {
  if (store.rawNewick) {
    TreeExporter.downloadText(store.rawNewick, `${store.currentJob?.title || 'phylo_tree'}.nwk`)
  }
}
</script>

<template>
  <div class="viewport-wrap" @click="closeContextMenu">
    <!-- 顶部悬浮画布工具栏 -->
    <div class="viewport-toolbar">
      <div class="toolbar-left">
        <div class="mode-switch">
          <button
            type="button"
            class="mode-tab"
            :class="{ active: store.viewportMode === 'interactive' }"
            @click="store.closeFigurePreview()"
          >
            交互式拓扑树
          </button>
          <button
            type="button"
            class="mode-tab"
            :class="{ active: store.viewportMode === 'publication' }"
            :disabled="!store.hasGeneratedFigures"
            :title="
              store.hasGeneratedFigures
                ? '查看本地渲染或 iTOL 导出的出版级图件'
                : '请先在左侧「出版级导出」面板生成图件'
            "
            @click="store.openFigurePreview()"
          >
            出版级成图预览
            <span
              v-if="store.hasGeneratedFigures"
              class="mode-badge"
            >
              {{ store.availablePublicationFigures.length + store.availableItolExports.length }}
            </span>
          </button>
        </div>

        <div v-if="store.viewportMode === 'interactive'" class="search-box">
          <input
            v-model="store.visual.searchQuery"
            class="search-input"
            placeholder="搜索样本 ID 高亮..."
          />
        </div>
      </div>

      <div v-if="store.viewportMode === 'interactive'" class="toolbar-actions">
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="canvas.zoomBy(1.2)">放大</button>
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="canvas.zoomBy(0.83)">缩小</button>
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="canvas.fitView()">适应窗口</button>
        <span class="tb-sep"></span>
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="handleExportSvg">SVG</button>
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="handleExportPng">高清 PNG</button>
        <button type="button" class="tb-btn" :disabled="!store.hasTree" @click="handleExportNewick">Newick</button>
      </div>
      <div v-else class="toolbar-mode-hint">
        正在预览出版级成图，可切换上方「交互式拓扑树」继续编辑节点
      </div>
    </div>

    <!-- 画布容器（使用 v-show 保留 PhyloTreeCanvas 实例与缩放状态） -->
    <div v-show="store.viewportMode === 'interactive'" ref="hostRef" class="canvas-host"></div>

    <!-- 出版级成图交互预览组件 -->
    <PublicationFigurePreview v-if="store.viewportMode === 'publication'" />

    <!-- 空状态指引 -->
    <div v-if="!store.hasTree && store.viewportMode === 'interactive'" class="empty-canvas">
      <div class="empty-card">
        <div class="empty-title">PhyloCore 系统发育工作台</div>
        <div class="empty-desc">
          请在左侧导入序列（FASTA / ZIP / ABI / NWK）。系统会自动识别短基因或全基因组尺度并推荐最优构树赛道。
        </div>
      </div>
    </div>

    <!-- 节点交互菜单 -->
    <div
      v-if="contextMenu.visible && contextMenu.node"
      class="node-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @click.stop
    >
      <div class="nm-header">
        {{ contextMenu.node.isLeaf ? contextMenu.node.name : `内部节点 (${contextMenu.node.leafCount} 叶子)` }}
      </div>
      <div v-if="contextMenu.node.support !== null" class="nm-info">
        支持率: {{ contextMenu.node.support }}% | 枝长: {{ contextMenu.node.branchLength.toFixed(5) }}
      </div>
      <button type="button" v-if="contextMenu.node.isLeaf" class="nm-item" @click="handleOutgroup">设为外群并重定根</button>
      <button type="button" v-if="!contextMenu.node.isLeaf" class="nm-item" @click="handleToggleCollapse">
        {{ contextMenu.node.collapsed ? '展开此支系' : '折叠此支系' }}
      </button>
      <button type="button" v-if="contextMenu.node.name" class="nm-item" @click="handleCopyId">复制节点名称</button>
      <div class="nm-colors">
        <span>标记颜色:</span>
        <button type="button" class="clr-dot" style="background:#2563eb" @click="handleColorClade('#2563eb')"></button>
        <button type="button" class="clr-dot" style="background:#dc2626" @click="handleColorClade('#dc2626')"></button>
        <button type="button" class="clr-dot" style="background:#16a34a" @click="handleColorClade('#16a34a')"></button>
        <button type="button" class="clr-dot" style="background:#d97706" @click="handleColorClade('#d97706')"></button>
        <button type="button" class="clr-clear" @click="handleColorClade(null)">清除</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.viewport-wrap { position: relative; flex: 1; height: 100%; background: #ffffff; display: flex; flex-direction: column; overflow: hidden; }
.viewport-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; gap: 12px; flex-wrap: wrap; }
.toolbar-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mode-switch { display: inline-flex; padding: 2px; border-radius: 7px; background: #e2e8f0; gap: 2px; }
.mode-tab { display: inline-flex; align-items: center; gap: 5px; border: none; background: transparent; color: #475569; padding: 4px 10px; border-radius: 5px; font-size: 11px; font-weight: 700; cursor: pointer; }
.mode-tab.active { background: #ffffff; color: #0f172a; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08); }
.mode-tab:disabled { opacity: 0.45; cursor: not-allowed; }
.mode-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 999px; background: #0f766e; color: #ffffff; font-size: 10px; font-weight: 700; }
.toolbar-mode-hint { font-size: 11px; color: #64748b; }
.search-input { border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 10px; font-size: 12px; width: 210px; background: #fff; }
.toolbar-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tb-btn { padding: 5px 10px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: #334155; font-size: 11px; font-weight: 600; cursor: pointer; }
.tb-btn:hover:not(:disabled) { border-color: #2563eb; color: #2563eb; background: #eff6ff; }
.tb-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.tb-sep { width: 1px; height: 16px; background: #cbd5e1; margin: 0 2px; }
.canvas-host { flex: 1; width: 100%; height: 100%; }
.empty-canvas { position: absolute; inset: 48px 0 0 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
.empty-card { max-width: 440px; text-align: center; padding: 28px 32px; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 12px; }
.empty-title { font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: #64748b; line-height: 1.6; }
.node-menu { position: fixed; z-index: 2000; min-width: 190px; background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; box-shadow: 0 10px 25px rgba(15, 23, 42, 0.14); padding: 6px; display: flex; flex-direction: column; gap: 4px; }
.nm-header { font-size: 12px; font-weight: 700; color: #0f172a; padding: 4px 8px; border-bottom: 1px solid #f1f5f9; }
.nm-info { font-size: 10px; color: #64748b; padding: 2px 8px; }
.nm-item { text-align: left; border: none; background: none; padding: 6px 8px; border-radius: 5px; font-size: 12px; color: #334155; cursor: pointer; }
.nm-item:hover { background: #eff6ff; color: #1d4ed8; }
.nm-colors { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 11px; color: #475569; border-top: 1px solid #f1f5f9; }
.clr-dot { width: 14px; height: 14px; border-radius: 50%; border: none; cursor: pointer; }
.clr-clear { border: none; background: none; color: #64748b; font-size: 11px; cursor: pointer; margin-left: auto; }
</style>
