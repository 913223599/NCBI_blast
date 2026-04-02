/**
 * GraphModel - 独立的图数据模型
 * 
 * 职责：
 * 1. 维护节点和连线的纯数据表示（不依赖 DOM）
 * 2. 提供 CRUD 操作
 * 3. 提供序列化/反序列化
 * 4. 节点属性的集中管理
 * 
 * 数据结构：
 * - nodes: Map<nodeId, NodeData>
 *   NodeData = { id, type, x, y, properties: {} }
 * - connections: Map<connId, ConnectionData>
 *   ConnectionData = { id, source, target, type, data }
 */
class GraphModel {
    constructor() {
        /** @type {Map<string, GraphModel.NodeData>} */
        this.nodes = new Map();
        /** @type {Map<string, GraphModel.ConnectionData>} */
        this.connections = new Map();

        /** @type {Map<string, {x: number, y: number}>} 销位坐标缓存 (Phase 5) */
        this.pinCenters = new Map();
        /** @type {Map<string, {dx: number, dy: number}>} 销位相对于节点的偏移量 (Phase 5 Optimization) */
        this.pinOffsets = new Map();

        /** @type {string} */
        this.version = '1.0';
    }

    // === 节点操作 ===

    /**
     * 添加节点
     * @param {string} nodeId
     * @param {string} type
     * @param {number} posX
     * @param {number} posY
     * @param {Object} properties - 节点属性键值对
     * @returns {GraphModel.NodeData}
     */
    addNode(nodeId, type, posX, posY, properties = {}) {
        if (this.nodes.has(nodeId)) {
            console.warn(`[GraphModel] Node ${nodeId} already exists, updating.`);
        }
        const nodeData = { id: nodeId, type, x: posX, y: posY, properties: { ...properties } };
        this.nodes.set(nodeId, nodeData);
        return nodeData;
    }

    /**
     * 移除节点及其关联连线
     * @param {string} nodeId
     * @returns {GraphModel.NodeData|null} 被移除的节点数据（用于撤销）
     */
    removeNode(nodeId) {
        const nodeData = this.nodes.get(nodeId);
        if (!nodeData) return null;

        // 级联删除关联连线
        const relatedConnIds = this.getConnectionsForNode(nodeId);
        relatedConnIds.forEach(connId => this.connections.delete(connId));

        this.nodes.delete(nodeId);
        return { ...nodeData, removedConnections: relatedConnIds.map(connId => ({ ...this.connections.get(connId) })) };
    }

    /**
     * 更新节点位置
     * @param {string} nodeId
     * @param {number} posX
     * @param {number} posY
     */
    updateNodePosition(nodeId, posX, posY) {
        const nodeData = this.nodes.get(nodeId);
        if (!nodeData) {
            console.warn(`[GraphModel] updateNodePosition: Node ${nodeId} not found.`);
            return;
        }
        nodeData.x = posX;
        nodeData.y = posY;

        // 失效该节点所有销位的缓存
        const prefix = nodeId + '::';
        for (const pinId of this.pinCenters.keys()) {
            if (pinId.startsWith(prefix)) {
                this.pinCenters.delete(pinId);
            }
        }
    }

    /**
     * 更新节点属性
     * @param {string} nodeId
     * @param {string} propKey
     * @param {*} propValue
     */
    updateNodeProperty(nodeId, propKey, propValue) {
        const nodeData = this.nodes.get(nodeId);
        if (!nodeData) {
            console.warn(`[GraphModel] updateNodeProperty: Node ${nodeId} not found.`);
            return;
        }
        nodeData.properties[propKey] = propValue;
    }

    /**
     * 批量更新节点属性
     * @param {string} nodeId
     * @param {Object} properties
     */
    updateNodeProperties(nodeId, properties) {
        const nodeData = this.nodes.get(nodeId);
        if (!nodeData) return;
        Object.assign(nodeData.properties, properties);
    }

    /**
     * 获取节点数据
     * @param {string} nodeId
     * @returns {GraphModel.NodeData|undefined}
     */
    getNode(nodeId) {
        return this.nodes.get(nodeId);
    }

    /**
     * 获取所有节点数据
     * @returns {GraphModel.NodeData[]}
     */
    getAllNodes() {
        return Array.from(this.nodes.values());
    }

    // === 销位缓存操作 ===

    /**
     * 更新销位坐标缓存
     */
    updatePinCenter(pinId, x, y) {
        this.pinCenters.set(pinId, { x, y });
    }

    /**
     * 获取销位中心（如果缓存存在）
     */
    getPinCenter(pinId) {
        return this.pinCenters.get(pinId);
    }

    // === 连线操作 ===

    /**
     * 添加连线
     * @param {string} connId
     * @param {string} sourcePin - 源 Pin ID
     * @param {string} targetPin - 目标 Pin ID
     * @param {string} connType - 连线类型
     * @param {*} connData - 附加数据
     * @returns {GraphModel.ConnectionData}
     */
    addConnection(connId, sourcePin, targetPin, connType = 'default', connData = null) {
        if (this.connections.has(connId)) {
            console.warn(`[GraphModel] Connection ${connId} already exists, updating.`);
        }
        const connectionData = { id: connId, source: sourcePin, target: targetPin, type: connType, data: connData };
        this.connections.set(connId, connectionData);
        return connectionData;
    }

    /**
     * 移除连线
     * @param {string} connId
     * @returns {GraphModel.ConnectionData|null} 被移除的连线数据（用于撤销）
     */
    removeConnection(connId) {
        const connectionData = this.connections.get(connId);
        if (!connectionData) return null;
        this.connections.delete(connId);
        return { ...connectionData };
    }

    /**
     * 获取与某节点关联的所有连线 ID
     * @param {string} nodeId
     * @returns {string[]}
     */
    getConnectionsForNode(nodeId) {
        const result = [];
        const prefix = nodeId + '::';
        this.connections.forEach((conn, connId) => {
            if (conn.source.startsWith(prefix) || conn.target.startsWith(prefix)) {
                result.push(connId);
            }
        });
        return result;
    }

    /**
     * 获取所有连线数据
     * @returns {GraphModel.ConnectionData[]}
     */
    getAllConnections() {
        return Array.from(this.connections.values());
    }

    // === 序列化 ===

    /**
     * 序列化为 JSON 对象
     * @returns {Object} topology JSON
     */
    serialize() {
        return {
            version: this.version,
            timestamp: Date.now(),
            nodes: this.getAllNodes().map(node => ({
                id: node.id,
                type: node.type,
                x: node.x,
                y: node.y,
                properties: { ...node.properties }
            })),
            connections: this.getAllConnections().map(conn => ({
                id: conn.id,
                source: conn.source,
                target: conn.target,
                type: conn.type,
                data: conn.data
            }))
        };
    }

    /**
     * 从 JSON 对象反序列化（清空当前数据后加载）
     * @param {Object} topology
     */
    deserialize(topology) {
        if (!topology) return;

        this.clear();

        if (topology.version) {
            this.version = topology.version;
        }

        if (topology.nodes) {
            topology.nodes.forEach(nodeData => {
                this.addNode(nodeData.id, nodeData.type, nodeData.x, nodeData.y, nodeData.properties || {});
            });
        }

        if (topology.connections) {
            topology.connections.forEach(conn => {
                this.addConnection(conn.id, conn.source, conn.target, conn.type, conn.data);
            });
        }
    }

    /**
     * 清空所有数据
     */
    clear() {
        this.nodes.clear();
        this.connections.clear();
    }

    /**
     * 从 DOM 同步数据（过渡方法，用于兼容旧代码）
     * 从当前 DOM 中的 .node 元素和 LinkSystem 中读取数据到 GraphModel
     * @param {LinkSystem} linkSystem
     */
    syncFromDOM(linkSystem) {
        this.clear();

        // 同步节点
        document.querySelectorAll('.node').forEach(nodeEl => {
            const properties = {};
            nodeEl.querySelectorAll('.property-input').forEach(input => {
                const key = input.dataset.prop;
                if (key) {
                    properties[key] = input.type === 'checkbox' ? input.checked : input.value;
                }
            });

            this.addNode(
                nodeEl.id,
                nodeEl.dataset.type || 'unknown',
                parseFloat(nodeEl.style.left) || 0,
                parseFloat(nodeEl.style.top) || 0,
                properties
            );
        });

        // 同步连线
        if (linkSystem && linkSystem.connections) {
            linkSystem.connections.forEach((conn, connId) => {
                if (connId === 'temp') return;
                this.addConnection(connId, conn.source, conn.target, conn.type, conn.data);
            });
        }
    }
}

// 导出供模块化使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GraphModel;
}
