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
    const isRerooted = ref(false)
    const currentSource = ref<string>('Unknown') // 追踪当前树对应的原始归档文件路径
    const currentIdToHash = ref<Record<string, string>>({}) // 记录当前的 ID 映射关系 (Issue #5)

    // Initialize
    onMounted(() => {
        if (containerRef.value) {
            renderer.mount(containerRef.value)
        }
        
        // Issue #5: 尝试从 sessionStorage 恢复树状态
        try {
            const savedSource = sessionStorage.getItem('tree_current_source')
            const savedIdToHash = sessionStorage.getItem('tree_current_id_to_hash')
            if (savedSource) currentSource.value = savedSource
            if (savedIdToHash) currentIdToHash.value = JSON.parse(savedIdToHash)
        } catch (e) {
            console.warn('Failed to restore tree state from session storage', e)
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

    async function loadNewick(newick: string, algorithm = 'Calculated', sourceFile = 'Unknown', filePath?: string, skipHistory = false, idToHash?: Record<string, string>) {
        isLoading.value = true
        error.value = null
        try {
            await nextTick()
            const newModel = new TreeModel()
            const root = newModel.parse(newick)
            
            if (root) {
                if (settings.sortMode !== 'original') {
                    newModel.prepareWeights(settings.sortMode as any)
                    newModel.applySorting(settings.sortMode as any)
                }

                model.value = newModel
                rawNewick.value = newModel.getNewick()
                initialNewick.value = newick 
                isRerooted.value = false 
                hasTree.value = true
                currentSource.value = sourceFile // 存入当前源
                nodeCount.value = newModel.getLeafCount()
                if (idToHash) {
                    currentIdToHash.value = idToHash
                }
                
                // Issue #5: 状态持久化，防止 F5 刷新丢失状态导致 ID 还原失败
                try {
                    sessionStorage.setItem('tree_current_source', currentSource.value)
                    sessionStorage.setItem('tree_current_id_to_hash', JSON.stringify(currentIdToHash.value || {}))
                } catch (e) { }
                
                // 核心维护：仅对明确的新分析进行归档，持久化指纹映射
                if (appStore && !skipHistory && algorithm !== 'Auto-Redraw') {
                    if (algorithm === 'Calculated' && sourceFile === 'Unknown') {
                        // skip
                    } else {
                        appStore.addTreeHistory(newick, algorithm, sourceFile, filePath, idToHash)
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
            // 静默加载：恢复原始拓扑时不产生冗余分析记录
            await loadNewick(initialNewick.value, 'Original', 'Unknown', undefined, true)
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
        rawNewick,
        currentSource,
        currentIdToHash
    }
}
