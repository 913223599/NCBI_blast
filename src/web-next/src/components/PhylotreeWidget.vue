<template>
  <div class="phylotree-container" ref="containerRef">
    <div id="phylotree-svg-host" ref="svgHost"></div>
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
  labelMap?: Record<string, string>
  useBranchLengths?: boolean
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

  if (measuredWidth <= 0 || measuredHeight <= 0) return

  executeRender(nwk, measuredWidth, measuredHeight)
}

/**
 * 核心执行：处理 D3 实例化与渲染生命周期
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  if (!svgHost.value || !nwk) return
  
  // 维护 1: 采用渐进式卸载，防止 DOM 僵死
  while (svgHost.value.firstChild) {
      svgHost.value.removeChild(svgHost.value.firstChild);
  }

  try {
    let layoutType = "left-to-right"
    if (props.mode === 'circular' || props.mode === 'unrooted') {
      layoutType = "radial"
    }

    // 核心工具：Newick 语义增强映射 (极致兼容版)
    let processedNewick = nwk;
    if (props.labelMap && Object.keys(props.labelMap).length > 0) {
        const sortedIds = Object.keys(props.labelMap).sort((a, b) => b.length - a.length);
        
        sortedIds.forEach(id => {
            let annotation = props.labelMap![id];
            if (!annotation) return;
            
            // 安全清洗：移出所有可能破坏 Newick 结构的保留字符
            const safeAnn = annotation.replace(/[()':;,]/g, " ").trim();
            const cleanId = id.replace(/^['"]|['"]$/g, '');
            const escapedId = cleanId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            
            // 匹配 ID 并在替换时强制加单引号
            const re = new RegExp(`(['"]?)${escapedId}\\1(?=[(:;,])`, 'g');
            processedNewick = processedNewick.replace(re, `'${safeAnn}'`);
        });
    }

    console.log(`[PhyloTree-Debug] Re-instantiating engine. NWK Len: ${processedNewick.length}`);
    // 注入处理后的 Newick
    treeInstance = new (Phylotree as any)(processedNewick);

    // 维护 5: 语义化增强 (JS 补丁同步 - 移除不稳定的 branch_length 手动调用)
    let nodes: any[] = []
    const rawNodes = (treeInstance as any).nodes;
    if (rawNodes) {
        if (Array.isArray(rawNodes)) nodes = rawNodes;
        else if (typeof (rawNodes as any).descendants === 'function') {
            nodes = (rawNodes as any).descendants();
        } else {
            nodes = [rawNodes];
        }
    }
    
    if (nodes.length > 0) {
        nodes.forEach((n: any) => {
            const d = n.data || n;
            if (!d) return;
            const parsedName = (d.name || n.name || "").toString().replace(/^['"]|['"]$/g, '').trim();
            if (!d._rawName) d._rawName = parsedName;
        });
    }

    // 维护 2: 注入渲染配置 (防御性增强)
    const config = {
      container: "#phylotree-svg-host",
      width: maxWidth, height: maxHeight,
      "layout": layoutType,
      "left-right-spacing": props.useBranchLengths ? "fixed-step" : "fit-to-size", 
      "top-bottom-spacing": "fit-to-size",
      "show-scale": true, "collapsible": true, "selectable": true, "zoom": true,
      "align-tips": !props.useBranchLengths, // 如果使用进化长度，则关闭对齐以展现真实距离
      "brush": false, "hide-internal-nodes": true,
      "node-label": (n: any) => {
          if (!n) return "";
          const d = n.data || n;
          return d.displayName || d.name || n.name || n.node_data?.name || "";
      }
    }

    const display = treeInstance.render(config)

    // 维护 3: 捕获全量事件钩子
    if (display && typeof display.show === 'function') {
      const svgElement = display.show()
      if (typeof display.on === 'function') {
          display.on('node-clicked', (node: any) => {
              const nd = node ? (node.data || node) : null;
              if (nd) {
                  emit('node-click', { name: nd.name, length: nd.branch_length })
              }
          })
      }
      svgHost.value.appendChild(svgElement)
      emit('render-complete', { width: maxWidth, height: maxHeight })
    }
  } catch (err) {
    console.error("[PhylotreeJS] Maintenance Error:", err)
  }
}

// 监听关键属性变化，触发重绘
watch(() => props.newick, (val) => {
  if (val) renderTree(val)
})

watch(() => props.mode, () => {
  if (props.newick) renderTree(props.newick)
})

watch(() => props.labelMap, () => {
  if (props.newick) renderTree(props.newick)
}, { deep: true })

watch(() => props.useBranchLengths, () => {
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
