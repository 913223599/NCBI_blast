/**
 * Node Studio 状态管理 (Pinia Store)
 * 管理节点图的核心数据模型、视口变换、选中状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

/* -------- 类型定义 -------- */

/** 节点端口 */
export interface NodePin {
    pinId: string
    label: string
    direction: 'input' | 'output'
    dataType: string
}

/** 节点参数 */
export interface NodeParam {
    key: string
    label: string
    type: 'text' | 'number' | 'select' | 'checkbox' | 'file'
    value: string | number | boolean
    options?: Array<{ value: string; label: string }>
    placeholder?: string
}

/** 节点数据 */
export interface NodeData {
    nodeId: string
    type: string
    label: string
    posX: number
    posY: number
    width: number
    height: number
    color: string
    pins: NodePin[]
    params: NodeParam[]
    status: 'idle' | 'running' | 'done' | 'error'
    progress: number
}

/** 连线数据 */
export interface ConnectionData {
    connId: string
    sourcePin: string
    targetPin: string
    sourceNode: string
    targetNode: string
}

/** 视口变换 */
export interface ViewportTransform {
    offsetX: number
    offsetY: number
    scale: number
}

/** 撤销/重做操作 */
interface UndoAction {
    type: string
    forward: () => void
    backward: () => void
}

export const useStudioStore = defineStore('studio', () => {
    /* -------- 画布状态 -------- */
    const nodes = ref<Map<string, NodeData>>(new Map())
    const connections = ref<Map<string, ConnectionData>>(new Map())
    const viewport = ref<ViewportTransform>({ offsetX: 0, offsetY: 0, scale: 1 })

    /* -------- 选择状态 -------- */
    const selectedNodeIds = ref<Set<string>>(new Set())
    const selectedConnIds = ref<Set<string>>(new Set())
    const draggingNodeId = ref<string | null>(null)

    /* -------- 连线拖拽状态 -------- */
    const isDrawingConnection = ref(false)
    const drawingFrom = ref<string | null>(null)
    const drawingEndPos = ref({ x: 0, y: 0 })

    /* -------- 节点库 -------- */
    const nodeLibraryOpen = ref(false)

    /* -------- 撤销/重做 -------- */
    const undoStack = ref<UndoAction[]>([])
    const redoStack = ref<UndoAction[]>([])

    /* -------- 计算属性 -------- */
    const nodeList = computed(() => Array.from(nodes.value.values()))
    const connectionList = computed(() => Array.from(connections.value.values()))
    const hasSelection = computed(() => selectedNodeIds.value.size > 0)

    let idCounter = 0
    function generateId(prefix: string): string {
        return `${prefix}_${Date.now()}_${++idCounter}`
    }

    /* -------- 节点操作 -------- */
    function addNode(type: string, label: string, posX: number, posY: number, config?: Partial<NodeData>): NodeData {
        const nodeId = generateId('node')
        const nodeData: NodeData = {
            nodeId,
            type,
            label,
            posX,
            posY,
            width: 220,
            height: 160,
            color: config?.color ?? '#3b82f6',
            pins: config?.pins ?? [],
            params: config?.params ?? [],
            status: 'idle',
            progress: 0,
            ...config
        }
        nodes.value.set(nodeId, nodeData)
        return nodeData
    }

    function removeNode(nodeId: string): void {
        // 移除关联连线
        const relatedConns = Array.from(connections.value.values())
            .filter(conn => conn.sourceNode === nodeId || conn.targetNode === nodeId)
        for (const conn of relatedConns) {
            connections.value.delete(conn.connId)
        }
        nodes.value.delete(nodeId)
        selectedNodeIds.value.delete(nodeId)
    }

    function updateNodePosition(nodeId: string, posX: number, posY: number): void {
        const node = nodes.value.get(nodeId)
        if (node) {
            node.posX = posX
            node.posY = posY
        }
    }

    function updateNodeParam(nodeId: string, paramKey: string, value: string | number | boolean): void {
        const node = nodes.value.get(nodeId)
        if (node) {
            const param = node.params.find(paramItem => paramItem.key === paramKey)
            if (param) param.value = value
        }
    }

    /* -------- 连线操作 -------- */
    function addConnection(sourcePin: string, targetPin: string, sourceNode: string, targetNode: string): ConnectionData {
        const connId = generateId('conn')
        const connData: ConnectionData = { connId, sourcePin, targetPin, sourceNode, targetNode }
        connections.value.set(connId, connData)
        return connData
    }

    function removeConnection(connId: string): void {
        connections.value.delete(connId)
        selectedConnIds.value.delete(connId)
    }

    /* -------- 选择操作 -------- */
    function selectNode(nodeId: string, append = false): void {
        if (!append) {
            selectedNodeIds.value.clear()
            selectedConnIds.value.clear()
        }
        selectedNodeIds.value.add(nodeId)
    }

    function clearSelection(): void {
        selectedNodeIds.value.clear()
        selectedConnIds.value.clear()
    }

    /* -------- 视口操作 -------- */
    function panViewport(deltaX: number, deltaY: number): void {
        viewport.value.offsetX += deltaX
        viewport.value.offsetY += deltaY
    }

    function zoomViewport(delta: number, centerX: number, centerY: number): void {
        const MIN_SCALE = 0.15
        const MAX_SCALE = 3.0
        const prevScale = viewport.value.scale
        const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, prevScale + delta))
        const ratio = newScale / prevScale
        viewport.value.offsetX = centerX - (centerX - viewport.value.offsetX) * ratio
        viewport.value.offsetY = centerY - (centerY - viewport.value.offsetY) * ratio
        viewport.value.scale = newScale
    }

    function resetViewport(): void {
        viewport.value = { offsetX: 0, offsetY: 0, scale: 1 }
    }

    /* -------- 序列化 -------- */
    function serialize(): string {
        const topology = {
            nodes: nodeList.value.map(node => ({
                id: node.nodeId,
                type: node.type,
                label: node.label,
                x: node.posX,
                y: node.posY,
                params: Object.fromEntries(node.params.map(paramItem => [paramItem.key, paramItem.value]))
            })),
            connections: connectionList.value.map(conn => ({
                id: conn.connId,
                source: conn.sourcePin,
                target: conn.targetPin,
                sourceNode: conn.sourceNode,
                targetNode: conn.targetNode
            }))
        }
        return JSON.stringify(topology)
    }

    function clear(): void {
        nodes.value.clear()
        connections.value.clear()
        selectedNodeIds.value.clear()
        selectedConnIds.value.clear()
        resetViewport()
    }

    /* -------- 撤销/重做 -------- */
    function pushUndo(action: UndoAction): void {
        undoStack.value.push(action)
        redoStack.value = []
    }

    function undo(): void {
        const action = undoStack.value.pop()
        if (action) {
            action.backward()
            redoStack.value.push(action)
        }
    }

    function redo(): void {
        const action = redoStack.value.pop()
        if (action) {
            action.forward()
            undoStack.value.push(action)
        }
    }

    return {
        /* 状态 */
        nodes, connections, viewport,
        selectedNodeIds, selectedConnIds, draggingNodeId,
        isDrawingConnection, drawingFrom, drawingEndPos,
        nodeLibraryOpen,
        undoStack, redoStack,
        /* 计算 */
        nodeList, connectionList, hasSelection,
        /* 节点 */
        addNode, removeNode, updateNodePosition, updateNodeParam,
        /* 连线 */
        addConnection, removeConnection,
        /* 选择 */
        selectNode, clearSelection,
        /* 视口 */
        panViewport, zoomViewport, resetViewport,
        /* 序列化 */
        serialize, clear,
        /* 撤销 */
        pushUndo, undo, redo,
        generateId
    }
})
