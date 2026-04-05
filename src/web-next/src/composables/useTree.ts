import { ref, onMounted, onUnmounted, nextTick, reactive, watch } from 'vue'
import { TreeModel } from '../core/tree/models/TreeModel'
import { LayoutEngine, DEFAULT_SETTINGS, type LayoutSettings } from '../core/tree/layout/LayoutEngine'
import { HybridRenderer } from '../core/tree/renderer/HybridRenderer'

export function useTree() {
    const containerRef = ref<HTMLElement | null>(null)
    const renderer = new HybridRenderer()
    const model = ref<TreeModel>(new TreeModel())

    // Reactive Settings
    const settings = reactive<LayoutSettings>({ ...DEFAULT_SETTINGS })

    // State
    const isLoading = ref(false)
    const error = ref<string | null>(null)
    const hasTree = ref(false)
    const nodeCount = ref(0) // Stats
    const rawNewick = ref<string | null>(null)

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

    async function loadNewick(newick: string) {
        isLoading.value = true
        error.value = null
        try {
            // Simulate slight delay for UI responsiveness if needed
            await nextTick()

            // Create fresh model instance to force renderer full update
            model.value = new TreeModel()
            const root = model.value.parse(newick)
            if (root) {
                rawNewick.value = newick
                hasTree.value = true
                nodeCount.value = model.value.getLeafCount()

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

    function midpointRooting() {
        if (hasTree.value && model.value) {
            model.value.rerootMidpoint()
            
            // 核心修复：将定根后的新拓扑同步回字符串，触发 UI 插件监听
            const newNwk = model.value.getNewick()
            rawNewick.value = newNwk

            renderer.lastModel = null 
            updateLayout()
            renderer.fitView(model.value)
        }
    }

    function exportSVG() {
        // Helper to export SVG content
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
        loadNewick,
        midpointRooting,
        exportSVG,
        isLoading,
        error,
        hasTree,
        nodeCount,
        renderer,
        rawNewick
    }
}
