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
  labelDisplayMode?: 'replace' | 'append' | 'original'
  visualGain?: number
}>()

const emit = defineEmits(['node-click', 'render-complete'])

// 缓存 DOM 元素到原始 ID 的映射
const nodeTextMap = new Map<Element, string>()

// 公开方法：手动更新标签显示模式
function updateLabelDisplayMode(mode: 'replace' | 'append' | 'original') {
  console.log('[PhylotreeWidget.updateLabelDisplayMode] Called with mode:', mode)
  
  setTimeout(() => {
    if (!svgHost.value) {
      console.warn('[PhylotreeWidget] svgHost is null')
      return
    }
    
    const textElements = svgHost.value.querySelectorAll('.node text')
    console.log(`[PhylotreeWidget] Found ${textElements.length} text elements`)
    
    if (textElements.length === 0) return
    
    // 如果缓存为空，初始化映射
    if (nodeTextMap.size === 0) {
      textElements.forEach((textEl: Element) => {
        const currentText = textEl.textContent || ''
        nodeTextMap.set(textEl, currentText.trim())
      })
      console.log(`[PhylotreeWidget] Initialized nodeTextMap with ${nodeTextMap.size} entries`)
    }
    
    let updatedCount = 0
    textElements.forEach((textEl: Element) => {
      const originalId = nodeTextMap.get(textEl) || ''
      const annotation = props.labelMap ? props.labelMap[originalId] : null
      
      let newText = originalId
      if (annotation) {
        if (mode === 'replace') {
          newText = annotation
        } else if (mode === 'append') {
          newText = `[${annotation}] ${originalId}`
        }
        // 'original' mode: use originalId
      }
      
      if (textEl.textContent !== newText) {
        textEl.textContent = newText
        updatedCount++
      }
    })
    
    console.log(`[PhylotreeWidget] Updated ${updatedCount}/${textElements.length} labels`)
  }, 150)
}

// 暴露给父组件
defineExpose({
  updateLabelDisplayMode
})

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

  // 再次检查，防止在异步等待期间组件被卸载
  if (!svgHost.value) return

  executeRender(nwk, measuredWidth, measuredHeight)
}

/**
 * 核心执行：处理 D3 实例化与渲染生命周期
 */
function executeRender(nwk: string, maxWidth: number, maxHeight: number) {
  if (!svgHost.value || !nwk) return
  
  // Reset debug flag on each render
  ;(window as any)._phylotreeLogged = false
  
  // 维护 1: 采用渐进式卸载，防止 DOM 僵死
  while (svgHost.value.firstChild) {
      svgHost.value.removeChild(svgHost.value.firstChild);
  }

  try {
    const isRadial = props.mode === 'circular' || props.mode === 'unrooted'
    console.log(`[PhyloTree-Debug] Render Call. Mode: ${props.mode}, Layout: ${isRadial ? 'radial' : 'linear'}, Labels: ${props.labelDisplayMode}`);
    console.log('[PhyloTree-Debug] labelMap keys:', props.labelMap ? Object.keys(props.labelMap).slice(0, 3) : 'null');
    
    // 核心工具：分枝长度视觉增益补偿 (不再替换标签内容，保持 ID 原始性以实现动态切换)
    let processedNewick = nwk;
    if (props.useBranchLengths && props.visualGain && props.visualGain > 0) {
        const lengths = processedNewick.match(/:([0-9eE.+-]+)/g);
        if (lengths) {
            let maxLen = 0.0000001;
            const numericLens = lengths.map(l => parseFloat(l.substring(1))).filter(v => !isNaN(v));
            if (numericLens.length > 0) maxLen = Math.max(...numericLens);
            const offset = maxLen * (props.visualGain || 0) * 0.4;
            processedNewick = processedNewick.replace(/:([0-9eE.+-]+)/g, (match, p1) => {
                const val = parseFloat(p1);
                if (isNaN(val)) return match;
                return `:${(val + offset).toFixed(10)}`;
            });
        }
    }

    // 注入处理后的 Newick (仅调整了长度)
    treeInstance = new (Phylotree as any)(processedNewick);

    // 维护 2: 显式注入拓扑形态 (解决切换失效问题)
    if (typeof treeInstance.radial === 'function') {
        treeInstance.radial(isRadial);
    }

    // 维护 3: 注入渲染配置 (针对 v2.x 优化)
    // 核心修复：直接传入 svgHost.value 作为 container，避免 show() 内部的 DOM 操作异常
    const config = {
      container: svgHost.value,  // 直接指定容器，不再手动 appendChild
      width: maxWidth, 
      height: maxHeight,
      "layout": isRadial ? "radial" : "left-to-right",
      "left-right-spacing": props.useBranchLengths ? "fit-to-size" : "fixed-step", 
      "top-bottom-spacing": "fixed-step",
      "show-scale": props.useBranchLengths,
      "align-tips": !props.useBranchLengths,
      "brush": false, 
      "hide-internal-nodes": true,
      "zoom": true,
      "svg": { // 关键修复：允许 SVG 内容溢出
        overflow: 'visible'
      },
      "node-label": (n: any) => {
          if (!n) return "";
          const d = n.data || n;
          // 彻底去除引号并清理空格，确保与 labelMap 键值精确匹配
          const fullId = (d.name || n.name || "").toString();
          const cleanId = fullId.replace(/^['"]|['"]$/g, '').trim();
          
          const annotation = props.labelMap ? props.labelMap[cleanId] : null;

          // Debug: Log ALL nodes on first render
          if (!window._phylotreeLogged) {
              console.log(`[PhylotreeWidget] Rendering node: ${cleanId}, Annotation: ${annotation}, Mode: ${props.labelDisplayMode}`);
          }

          // 核心修复：根据 labelDisplayMode 动态渲染
          let result;
          if (!annotation || props.labelDisplayMode === 'original') {
              result = cleanId;
          } else if (props.labelDisplayMode === 'append') {
              result = `[${annotation}] ${cleanId}`;
          } else {
              result = annotation; // 'replace' 模式
          }
          
          // Log first few nodes to verify
          if (!window._phylotreeLogged && cleanId.includes('SEQ')) {
              console.log(`[PhylotreeWidget] Node ${cleanId} -> ${result}`);
          }
          
          return result;
      }
    }

    const display = treeInstance.render(config)

    // 维护 4: 捕获全量事件钩子 (兼容性处理)
    if (display) {
      if (typeof display.on === 'function') {
          display.on('node-clicked', (node: any) => {
              const nd = node ? (node.data || node) : null;
              if (nd) {
                  emit('node-click', { name: nd.name, length: nd.branch_length })
              }
          })
      }
      
      // 如果 render 没有自动挂载，才尝试手动调用 show()
      if (svgHost.value.children.length === 0 && typeof display.show === 'function') {
          try {
              const svgElement = display.show()
              if (svgElement && svgHost.value && !svgElement.parentNode) {
                  svgHost.value.appendChild(svgElement)
              }
          } catch (e) {
              console.warn("[PhylotreeJS] Fallback show() failed, but render may have succeeded.", e)
          }
      }

      emit('render-complete', { width: maxWidth, height: maxHeight })
    }
  } catch (err) {
    console.error("[PhylotreeJS] Critical Maintenance Error:", err)
  }
}

// 监听关键属性变化，触发重绘
watch(() => props.newick, (val) => {
  if (val) renderTree(val)
})

watch(() => props.mode, () => {
  if (props.newick) renderTree(props.newick)
})

// 核心优化：当标签映射更新时，不再重绘整棵树（昂贵的 D3 操作），而是仅通过 DOM 补丁更新文本内容
watch(() => props.labelMap, (newMap) => {
  if (props.newick && newMap) {
      console.log('[PhylotreeWidget] labelMap changed, performing DOM-only label sync.');
      updateLabelDisplayMode(props.labelDisplayMode || 'replace');
  }
}, { deep: true })

watch(() => props.labelDisplayMode, (newMode, oldMode) => {
  console.log('[PhylotreeWidget] labelDisplayMode changed from', oldMode, 'to', newMode)
  updateLabelDisplayMode(newMode || 'replace');
})


watch(() => props.visualGain, () => {
  if (props.newick) renderTree(props.newick)
})

watch(() => props.useBranchLengths, () => {
  if (props.newick) renderTree(props.newick)
})

onMounted(() => {
  if (props.newick) renderTree(props.newick)
  
  // 维护 5: 启动自动尺寸监听
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (props.newick) renderTree(props.newick)
    })
    resizeObserver.observe(containerRef.value)
  }
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
  overflow: auto; /* 修复：允许滚动查看超出边界的树内容 */
  background: #f8fafc;
  position: relative;
}

/* 维护 4: 极客风交互样式注入 */
:deep(svg) {
  display: block;
  overflow: visible !important; /* 关键修复：允许 SVG 内容溢出容器 */
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 确保 SVG 内部的 g 元素可以超出边界 */
:deep(svg > g) {
  transform-origin: 0 0;
}

/* 分枝高亮交互 */
:deep(path.branch) {
  fill: none;
  stroke: #64748b;
  stroke-width: 1.5px;
  stroke-linecap: round;
  transition: stroke 0.2s, stroke-width 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
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
  transition: fill 0.2s, font-weight 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
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
  transition: r 0.2s, fill 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
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
/* 维护 7: 修复交互菜单重叠 (解决截图中的文本堆叠问题) */
:deep(.phylotree-container .dropdown-menu) {
    background: white !important; 
    border: 1px solid #e2e8f0 !important; 
    border-radius: 8px !important;
    padding: 8px !important;
    list-style: none !important; 
    display: flex !important; 
    flex-direction: column !important; 
    gap: 4px !important;
    min-width: 140px !important;
    z-index: 1000 !important;
}
:deep(.phylotree-container .dropdown-item), :deep(.phylotree-container a) {
    font-size: 11px !important; 
    padding: 6px 12px !important; 
    border-radius: 6px !important;
    color: #475569 !important; 
    cursor: pointer !important;
    text-decoration: none !important;
    display: block !important;
    transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}
:deep(.phylotree-container .dropdown-item:hover), :deep(.phylotree-container a:hover) {
    background: #eff6ff !important; 
    color: #2563eb !important;
}
</style>