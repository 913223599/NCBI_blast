<template>
  <div class="phylotree-container" ref="containerRef">
    <div ref="svgHost"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
// @ts-ignore – vendor source kept in vendor_phylotree/ as algorithm reference
import { phylotree as Phylotree } from 'phylotree'
import 'phylotree/dist/phylotree.css'

const props = defineProps<{
  newick: string | null
  mode: 'rect' | 'circular' | 'unrooted'
}>()

const containerRef = ref<HTMLElement | null>(null)
const svgHost = ref<HTMLElement | null>(null)
let treeInstance: any = null
let resizeObserver: ResizeObserver | null = null

/**
 * 渲染入口：等待 DOM 就绪后检查容器尺寸，
 * 若尺寸为 0（v-if 刚挂载、布局未 settle），则通过 ResizeObserver 延迟触发。
 */
async function renderTree(nwk: string) {
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(resolve))

  if (!svgHost.value || !containerRef.value) {
    console.warn("PhylotreeWidget: container not ready")
    return
  }

  const measuredWidth = containerRef.value.clientWidth
  const measuredHeight = containerRef.value.clientHeight

  if (measuredWidth === 0 || measuredHeight === 0) {
    deferRenderUntilSized(nwk)
    return
  }

  executeRender(nwk, measuredWidth, measuredHeight)
}

/**
 * 当容器尺寸为 0 时（v-if 刚创建、布局未完成），
 * 使用 ResizeObserver 监听容器，一旦有尺寸立即渲染。
 */
function deferRenderUntilSized(nwk: string) {
  if (!containerRef.value) return

  if (resizeObserver) {
    resizeObserver.disconnect()
  }

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
 * 实际执行 phylotree 渲染的核心逻辑（保证容器已有有效尺寸）。
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  if (!svgHost.value) return

  // Clear previous render
  svgHost.value.innerHTML = ''

  const hostId = 'phylotree-host-' + Date.now()
  svgHost.value.setAttribute('id', hostId)

  if (!nwk) return

  try {
    treeInstance = new (Phylotree as any)(nwk)

    let layoutType = "left-to-right"
    if (props.mode === 'circular' || props.mode === 'unrooted') {
      layoutType = "radial"
    }

    treeInstance.render({
      container: '#' + hostId,
      width: maxWidth,
      height: maxHeight,
      "layout": layoutType,
      "left-right-spacing": "fit-to-size",
      "top-bottom-spacing": "fit-to-size",
      "show-scale": true,
      "collapsible": true,
      "selectable": true,
      "zoom": true
    })

    console.log("PhylotreeJS rendered successfully, nodes:", treeInstance.nodes?.descendants?.()?.length)
  } catch (error) {
    console.error("Phylotree.js rendering failed:", error)
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
  overflow: auto;
  background: transparent;
}

/* Phylotree SVG Styles overrides - must use :deep for scoped */
:deep(svg) {
  overflow: visible;
}

:deep(path.branch) {
  fill: none;
  stroke: #0f172a;
  stroke-width: 1.5px;
  stroke-linejoin: round;
}

:deep(.node) {
  cursor: pointer;
}

:deep(.node text) {
  font-family: 'Inter', sans-serif;
  font-size: 13px;
  fill: #334155;
}

:deep(.node circle) {
  fill: #fff;
  stroke: #475569;
  stroke-width: 1.5px;
}

:deep(.tree-scale-bar) {
  font-family: 'Inter', sans-serif;
  font-size: 12px;
}
</style>
