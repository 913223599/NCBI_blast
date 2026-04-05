<template>
  <div class="phylotree-container" ref="containerRef">
    <div ref="svgHost"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
// @ts-ignore
import { phylotree as Phylotree } from 'phylotree'
import 'phylotree/dist/phylotree.css'

const props = defineProps<{
  newick: string | null
  mode: 'rect' | 'circular' | 'unrooted'
  showLabels?: boolean
}>()

const emit = defineEmits(['node-click', 'render-complete'])

const containerRef = ref<HTMLElement | null>(null)
const svgHost = ref<HTMLElement | null>(null)
let treeInstance: any = null
let resizeObserver: ResizeObserver | null = null

/**
 * 渲染入口：等待布局稳定后执行渲染
 */
async function renderTree(nwk: string) {
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(resolve))

  if (!svgHost.value || !containerRef.value) return

  const measuredWidth = containerRef.value.clientWidth
  const measuredHeight = containerRef.value.clientHeight

  if (measuredWidth === 0 || measuredHeight === 0) {
    deferRenderUntilSized(nwk)
    return
  }

  executeRender(nwk, measuredWidth, measuredHeight)
}

/**
 * 处理 v-if 导致的容器尺寸滞后问题
 */
function deferRenderUntilSized(nwk: string) {
  if (!containerRef.value) return
  if (resizeObserver) resizeObserver.disconnect()

  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) {
        resizeObserver?.disconnect()
        resizeObserver = null
        executeRender(nwk, Math.round(width), Math.round(height))
        break
      }
    }
  })
  resizeObserver.observe(containerRef.value)
}

/**
 * 实际执行 phylotree 渲染逻辑 (维护版本 2.1)
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  if (!svgHost.value || !nwk) return
  
  // 维护 1: 采用渐进式卸载，防止 DOM 僵死
  while (svgHost.value.firstChild) {
      svgHost.value.removeChild(svgHost.value.firstChild);
  }

  try {
    treeInstance = new (Phylotree as any)(nwk)

    let layoutType = "left-to-right"
    if (props.mode === 'circular' || props.mode === 'unrooted') {
      layoutType = "radial"
    }

    // 维护 2: 注入深度交互配置
    const config = {
      container: svgHost.value,
      width: maxWidth,
      height: maxHeight,
      "layout": layoutType,
      "left-right-spacing": "fit-to-size",
      "top-bottom-spacing": "fit-to-size",
      "show-scale": true,
      "collapsible": true,
      "selectable": true,
      "zoom": true,
      "align-tips": true,
      "brush": false, // 关闭刷子工具以防手势冲突
      "hide-internal-nodes": true // 默认隐藏非叶子节点的占位点
    }

    const display = treeInstance.render(config)

    // 维护 3: 捕获全量事件钩子
    if (display && typeof display.show === 'function') {
      const svgElement = display.show()
      
      // 深度交互：节点点击桥接
      if (typeof display.on === 'function') {
          display.on('node-clicked', (node: any) => {
              if (node && node.data) {
                  console.info(`[PhylotreeJS] User clicked: ${node.data.name}`)
                  emit('node-click', {
                      name: node.data.name,
                      length: node.data.branch_length
                  })
              }
          })
      }
      
      svgHost.value.appendChild(svgElement)
      emit('render-complete', { width: maxWidth, height: maxHeight })
    }
  } catch (error) {
    console.error('[PhylotreeJS] Maintenance Error:', error)
  }
}

watch(() => props.newick, (nwk) => {
  if (nwk) renderTree(nwk)
})

watch(() => props.mode, () => {
  if (props.newick) renderTree(props.newick)
})

onMounted(() => {
  if (props.newick) renderTree(props.newick)
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})
</script>

<style scoped>
.phylotree-container {
  width: 100%;
  height: 100%;
  overflow: hidden; /* 核心维护：由 D3 Zoom 处理缩放，容器应隐藏溢出 */
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 维护 4: 极客风交互样式注入 */
:deep(svg) {
  width: 100%;
  height: 100%;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 分枝高亮交互 */
:deep(path.branch) {
  fill: none;
  stroke: #64748b;
  stroke-width: 1.5px;
  stroke-linecap: round;
  transition: stroke 0.2s, stroke-width 0.2s;
}

:deep(path.branch:hover) {
  stroke: #2563eb !important;
  stroke-width: 3px !important;
  opacity: 0.8;
}

/* 选定路径样式 */
:deep(path.branch.selected) {
  stroke: #2563eb !important;
  stroke-width: 3px !important;
}

/* 节点高级视觉 */
:deep(.node text) {
  font-family: 'Inter', 'SF Pro Text', sans-serif;
  font-size: 13px;
  fill: #1e293b;
  cursor: pointer;
  transition: fill 0.2s, font-weight 0.2s;
}

:deep(.node:hover text) {
  fill: #2563eb !important;
  font-weight: 600;
}

:deep(.node circle) {
  fill: #fff;
  stroke: #94a3b8;
  stroke-width: 1.5px;
  r: 4; /* 初始半径 */
  transition: r 0.2s, fill 0.2s;
}

:deep(.node:hover circle) {
  fill: #2563eb;
  stroke: #2563eb;
  r: 6;
}

/* 缩放标尺视觉优化 */
:deep(.tree-scale-bar) {
  font-size: 11px;
  fill: #64748b;
}
</style>
