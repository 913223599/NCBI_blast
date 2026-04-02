/**
 * TopologyManager - 负责图数据的序列化与反序列化
 * 
 * 改进（Phase 2）：
 * - 序列化优先从 GraphModel 读取，不再依赖 DOM 遍历
 * - 反序列化同时更新 GraphModel 和 DOM
 * - 保持向后兼容：如果 GraphModel 不可用，回退到 DOM 遍历
 */
class TopologyManager {
    /**
     * @param {NodeFactory} nodeFactory
     * @param {LinkSystem} linkSystem
     * @param {GraphModel} [graphModel] - 可选，Phase 2 引入
     */
    constructor(nodeFactory, linkSystem, graphModel = null) {
        this.nodeFactory = nodeFactory;
        this.linkSystem = linkSystem;
        this.graphModel = graphModel;
    }

    /**
     * 序列化当前画布为 JSON Topology
     * 优先从 GraphModel 读取，否则回退到 DOM 遍历
     * @returns {Object} topology JSON
     */
    serializeGraph() {
        // 优先使用 GraphModel
        if (this.graphModel && this.graphModel.nodes.size > 0) {
            const topology = this.graphModel.serialize();
            console.log('[TopologyManager] Serialized from GraphModel:', topology);
            return topology;
        }

        // 回退：从 DOM 遍历（向后兼容）
        return this._serializeFromDOM();
    }

    /**
     * 从 DOM 遍历序列化（旧逻辑保留作为回退）
     * @returns {Object}
     * @private
     */
    _serializeFromDOM() {
        const nodes = [];
        document.querySelectorAll('.node').forEach(nodeEl => {
            const properties = {};
            nodeEl.querySelectorAll('.property-input').forEach(input => {
                const key = input.dataset.prop;
                if (key) {
                    properties[key] = input.type === 'checkbox' ? input.checked : input.value;
                }
            });
            nodes.push({
                id: nodeEl.id,
                type: nodeEl.dataset.type || 'unknown',
                x: parseFloat(nodeEl.style.left) || 0,
                y: parseFloat(nodeEl.style.top) || 0,
                properties
            });
        });

        const connections = [];
        this.linkSystem.connections.forEach((conn, connId) => {
            if (connId === 'temp') return;
            connections.push({
                id: connId,
                source: conn.source,
                target: conn.target,
                type: conn.type,
                data: conn.data
            });
        });

        const topology = {
            version: '1.0',
            timestamp: Date.now(),
            nodes,
            connections
        };

        console.log('[TopologyManager] Serialized from DOM:', topology);
        return topology;
    }

    /**
     * 别名
     * @returns {Object}
     */
    getTopology() {
        return this.serializeGraph();
    }

    /**
     * 清空画布和数据模型
     */
    clearCanvas() {
        // 清空 DOM
        document.querySelectorAll('.node').forEach(nodeEl => nodeEl.remove());

        // 清空 LinkSystem
        const connIds = Array.from(this.linkSystem.connections.keys());
        connIds.forEach(connId => this.linkSystem.removeConnection(connId));

        // 清空 GraphModel
        if (this.graphModel) {
            this.graphModel.clear();
        }

        if (typeof updatePinVisuals === 'function') {
            updatePinVisuals();
        }
    }

    /**
     * 从 topology JSON 恢复图状态
     * 同时更新 GraphModel 和 DOM
     * @param {Object} topology
     */
    loadTopology(topology) {
        if (!topology || !topology.nodes) return;

        // 0. 清空现有数据
        this.clearCanvas();

        // 1. 反序列化到 GraphModel
        if (this.graphModel) {
            this.graphModel.deserialize(topology);
        }

        // 2. 创建 DOM 节点
        topology.nodes.forEach(nodeData => {
            const nodeEl = this.nodeFactory.createNode(
                nodeData.type,
                nodeData.x,
                nodeData.y,
                nodeData.id
            );

            const canvasRoot = document.getElementById('canvas-root');
            if (canvasRoot && !canvasRoot.contains(nodeEl)) {
                canvasRoot.appendChild(nodeEl);
            }

            // 恢复属性
            if (nodeData.properties) {
                for (const [key, val] of Object.entries(nodeData.properties)) {
                    const input = nodeEl.querySelector(`.property-input[data-prop="${key}"]`);
                    if (input) {
                        if (input.type === 'checkbox') {
                            input.checked = (val === true || val === 'true');
                        } else {
                            input.value = val;
                        }
                    }
                }
            }

            // 重新绑定交互
            if (typeof makeDraggable === 'function') {
                makeDraggable(nodeEl);
            }
        });

        // 3. 创建连线
        if (topology.connections) {
            topology.connections.forEach(conn => {
                this.linkSystem.createConnection(conn.id, conn.source, conn.target, {
                    type: conn.type,
                    data: conn.data
                });
            });

            // 延迟更新连线位置（等待 DOM 渲染完成）
            const self = this;
            setTimeout(() => {
                if (typeof getPinCenter === 'function') {
                    self.linkSystem.updateConnectionPositions(getPinCenter);
                }
                if (typeof updatePinVisuals === 'function') {
                    updatePinVisuals();
                }
                // 二次刷新确保位置精确
                setTimeout(() => {
                    if (typeof getPinCenter === 'function') {
                        self.linkSystem.updateConnectionPositions(getPinCenter);
                    }
                }, 150);
            }, 150);
        }
    }
}

// 导出供模块化使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TopologyManager;
}
