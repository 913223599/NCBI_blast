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
}>()

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
 * 实际执行 phylotree 渲染逻辑
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  if (!svgHost.value || !nwk) return
  svgHost.value.innerHTML = ''

  try {
    treeInstance = new (Phylotree as any)(nwk)

    let layoutType = "left-to-right"
    if (props.mode === 'circular' || props.mode === 'unrooted') {
      layoutType = "radial"
    }

    const display = treeInstance.render({
      container: svgHost.value,
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

    if (display && typeof display.show === 'function') {
      const svgElement = display.show()
      svgHost.value.appendChild(svgElement)
    }
  } catch (error) {
    console.error('[PhylotreeJS] Render Error:', error)
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

:deep(svg) {
  overflow: visible;
}

:deep(path.branch) {
  fill: none;
  stroke: #0f172a;
  stroke-width: 1.5px;
  stroke-linejoin: round;
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
</style>
