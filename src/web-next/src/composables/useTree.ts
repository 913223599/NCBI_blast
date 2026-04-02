import { ref, onMounted, onUnmounted, nextTick, reactive, watch } from 'vue'
import { TreeModel } from '../core/tree/models/TreeModel'
import { LayoutEngine, DEFAULT_SETTINGS, type LayoutSettings } from '../core/tree/layout/LayoutEngine'
import { HybridRenderer } from '../core/tree/renderer/HybridRenderer'

export function useTree() {
    const containerRef = ref<HTMLElement | null>(null)
    const renderer = new HybridRenderer()
    const model = new TreeModel()

    // Reactive Settings
    const settings = reactive<LayoutSettings>({ ...DEFAULT_SETTINGS })

    // State
    const isLoading = ref(false)
    const error = ref<string | null>(null)
    const hasTree = ref(false)
    const nodeCount = ref(0) // Stats

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
        // Create new Layout Engine instance or reuse? 
        // LayoutEngine is stateless logic mostly, but holds refs to model/settings
        const layout = new LayoutEngine(model, settings)
        layout.calculateCoordinates()
        renderer.render(model, settings)
    }

    async function loadNewick(newick: string) {
        isLoading.value = true
        error.value = null
        try {
            // Simulate slight delay for UI responsiveness if needed
            await nextTick()

            const root = model.parse(newick)
            if (root) {
                hasTree.value = true
                nodeCount.value = model.getLeafCount() + Object.keys(model.nodesById).length - model.getLeafCount()

                updateLayout()
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
        exportSVG,
        isLoading,
        error,
        hasTree,
        nodeCount
    }
}
