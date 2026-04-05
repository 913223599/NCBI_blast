import { ref, onMounted, onUnmounted, nextTick, reactive, watch } from 'vue'
import { TreeModel } from '../core/tree/models/TreeModel'
import { LayoutEngine, DEFAULT_SETTINGS, type LayoutSettings } from '../core/tree/layout/LayoutEngine'
import { HybridRenderer } from '../core/tree/renderer/HybridRenderer'
import { useAppStore } from '../stores/app'

export function useTree() {
    const appStore = useAppStore()
    const containerRef = ref<HTMLElement | null>(null)
    const renderer = new HybridRenderer()
    const model = ref<TreeModel>(new TreeModel())
    const settings = reactive<LayoutSettings>({ ...DEFAULT_SETTINGS })

    // State
    const isLoading = ref(false)
    const error = ref<string | null>(null)
    const hasTree = ref(false)
    const nodeCount = ref(0) // Stats
    const rawNewick = ref<string | null>(null)
    const initialNewick = ref<string | null>(null) 
    const isRerooted = ref(false) // 核心维护：追踪当前是否处于定根状态

    // Initialize
    onMounted(() => {
        if (containerRef.value) {
            renderer.mount(containerRef.value)
        }
    })

    onUnmounted(() => {
        renderer.dispose()
    })

    // Watch settings change to re-layout / re-render
    watch(settings, () => {
        if (hasTree.value) {
            updateLayout()
        }
    }, { deep: true }) // deep watch for settings

    function updateLayout() {
        const layout = new LayoutEngine(model.value, settings)
        layout.calculateCoordinates()
        renderer.render(model.value, settings)
    }

    async function loadNewick(newick: string, algorithm = 'Calculated', sourceFile = 'Unknown', filePath?: string) {
        isLoading.value = true
        error.value = null
        try {
            await nextTick()
            const newModel = new TreeModel()
            const root = newModel.parse(newick)
            
            if (root) {
                // 关键修复：确保模型进入响应式之前，物理上不仅解析好，还排好序
                if (settings.sortMode !== 'original') {
                    newModel.prepareWeights(settings.sortMode as any)
                    newModel.applySorting(settings.sortMode as any)
                }

                model.value = newModel
                // 关键修复：必须生成排序后的 Newick 字符串，否则 PhyloTreeJS 会读到原始顺序
                rawNewick.value = newModel.getNewick()
                initialNewick.value = newick 
                isRerooted.value = false // 重置状态
                hasTree.value = true
                nodeCount.value = newModel.getLeafCount()
                
                // 核心维护：按照组进行归档
                if (appStore) {
                  const existingItem = appStore.treeHistory.flatMap(g => g.items).find(i => i.nwk === newick)
                  if (!existingItem) {
                    const treeName = root.name || `Tree_${nodeCount.value}_TIPS`
                    appStore.addTreeHistory(newick, treeName, algorithm, sourceFile, filePath)
                  }
                }

                updateLayout()
                renderer.fitView(model.value)
            } else {
                throw new Error("Failed to parse tree.")
            }
        } catch (e: any) {
            error.value = e.message
            hasTree.value = false
        } finally {
            isLoading.value = false
        }
    }

    async function resetTopology() {
        if (initialNewick.value) {
            // 这里必须使用 await，确保 loadNewick 内的排序逻辑彻底走完
            await loadNewick(initialNewick.value)
        }
    }

    function midpointRooting() {
        if (hasTree.value && model.value) {
            model.value.rerootMidpoint()
            isRerooted.value = true // 记录状态
            
            if (settings.sortMode !== 'original') {
                model.value.applySorting(settings.sortMode)
            }

            rawNewick.value = model.value.getNewick()
            updateLayout()
            renderer.fitView(model.value)
        }
    }

    function applyTreeSorting(mode: typeof settings.sortMode) {
        if (hasTree.value && model.value) {
            settings.sortMode = mode
            model.value.applySorting(mode)
            rawNewick.value = model.value.getNewick()
            updateLayout()
            renderer.fitView(model.value)
        }
    }

    function exportSVG() {
        if (!renderer.svg) return
        const serializer = new XMLSerializer()
        const source = serializer.serializeToString(renderer.svg)
        const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" })
        const url = URL.createObjectURL(blob)
        const link = document.createElement("a")
        link.href = url
        link.download = "tree_export.svg"
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
    }

    return {
        containerRef,
        settings,
        model,
        loadNewick,
        midpointRooting,
        resetTopology,
        isRerooted,
        applyTreeSorting,
        updateLayout,
        exportSVG,
        isLoading,
        error,
        hasTree,
        nodeCount,
        renderer,
        rawNewick
    }
}
