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
  console.log('%c[PhylotreeWidget] renderTree() 调用', 'color: #10b981; font-weight: bold;')
  console.log('[PhylotreeWidget] newick 长度:', nwk?.length, '| 前 60 字符:', nwk?.substring(0, 60))

  await nextTick()
  await new Promise(resolve => requestAnimationFrame(resolve))

  if (!svgHost.value || !containerRef.value) {
    console.error('[PhylotreeWidget] ❌ DOM ref 不可用: svgHost=', !!svgHost.value, ', containerRef=', !!containerRef.value)
    return
  }

  const measuredWidth = containerRef.value.clientWidth
  const measuredHeight = containerRef.value.clientHeight
  console.log('[PhylotreeWidget] 容器尺寸:', measuredWidth, 'x', measuredHeight)

  if (measuredWidth === 0 || measuredHeight === 0) {
    console.warn('[PhylotreeWidget] ⚠️ 容器尺寸为 0，启动 ResizeObserver 等待布局...')
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
      console.log('[PhylotreeWidget] ResizeObserver 回调:', Math.round(width), 'x', Math.round(height))
      if (width > 0 && height > 0) {
        console.log('[PhylotreeWidget] ✅ ResizeObserver 检测到有效尺寸，开始渲染')
        resizeObserver?.disconnect()
        resizeObserver = null
        executeRender(nwk, Math.round(width), Math.round(height))
        break
      }
    }
  })

  resizeObserver.observe(containerRef.value)
  console.log('[PhylotreeWidget] ResizeObserver 已挂载到容器')
}

/**
 * 实际执行 phylotree 渲染的核心逻辑（保证容器已有有效尺寸）。
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  console.log('%c[PhylotreeWidget] executeRender() 启动', 'color: #3b82f6; font-weight: bold;')
  console.log('[PhylotreeWidget] 渲染尺寸:', maxWidth, 'x', maxHeight)

  if (!svgHost.value) {
    console.error('[PhylotreeWidget] ❌ executeRender 时 svgHost 为 null')
    return
  }

  // Clear previous render
  svgHost.value.innerHTML = ''

  if (!nwk) {
    console.error('[PhylotreeWidget] ❌ newick 为空')
    return
  }

  try {
    console.log('[PhylotreeWidget] 正在创建 Phylotree 实例...')
    treeInstance = new (Phylotree as any)(nwk)
    console.log('[PhylotreeWidget] Phylotree 实例创建成功, nodes:', treeInstance.nodes?.descendants?.()?.length)

    let layoutType = "left-to-right"
    if (props.mode === 'circular' || props.mode === 'unrooted') {
      layoutType = "radial"
    }
    console.log('[PhylotreeWidget] layout:', layoutType, '| container: 直传 DOM 元素')

    // 关键修复：直接传递 DOM 元素引用，而非 CSS 选择器字符串
    // d3.select() 同时支持选择器和 DOM 元素，但 QWebEngineView 中选择器解析可能失败
    // 关键修复：在某些版本的 phylotree 中，render() 不会自动挂载，
    // 需要显式调用 display.show() 获取 SVG 元素并手动 append
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

    console.log('%c[PhylotreeWidget] render() 配置完成', 'color: #10b981; font-weight: bold;')
    
    if (display && typeof display.show === 'function') {
      const svgElement = display.show()
      svgHost.value.appendChild(svgElement)
      console.log('[PhylotreeWidget] ✅ 已手动执行 display.show() 并挂载 SVG')
    } else {
      console.warn('[PhylotreeWidget] ⚠️ display 对象没有 .show() 方法，尝试检查容器内容...')
    }

    console.log('[PhylotreeWidget] SVG 元素探测:', svgHost.value?.querySelector('svg'))
    console.log('[PhylotreeWidget] 最终容器 innerHTML 长度:', svgHost.value?.innerHTML?.length)
  } catch (error) {
    console.error('[PhylotreeWidget] ❌ Phylotree.js 渲染链路崩溃:', error)
  }
}

watch(() => props.newick, (nwk, oldNwk) => {
  console.log('[PhylotreeWidget] watch(newick) 触发: old长度=', oldNwk?.length, '→ new长度=', nwk?.length)
  if (nwk) renderTree(nwk)
})

watch(() => props.mode, (newMode, oldMode) => {
  console.log('[PhylotreeWidget] watch(mode) 触发:', oldMode, '→', newMode)
  if (props.newick) renderTree(props.newick)
})

onMounted(() => {
  console.log('%c[PhylotreeWidget] onMounted 触发', 'color: #8b5cf6; font-weight: bold;')
  console.log('[PhylotreeWidget] props.newick =', props.newick ? `长度 ${props.newick.length}` : null)
  console.log('[PhylotreeWidget] props.mode =', props.mode)
  console.log('[PhylotreeWidget] containerRef =', containerRef.value)
  console.log('[PhylotreeWidget] svgHost =', svgHost.value)
  if (props.newick) renderTree(props.newick)
  else console.warn('[PhylotreeWidget] ⚠️ onMounted 时 newick 为空，跳过渲染')
})

onUnmounted(() => {
  console.log('[PhylotreeWidget] onUnmounted 清理')
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
