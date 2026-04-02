/**
 * NodeController - 节点操作管理
 * 
 * 职责：
 * 1. 创建节点 (createNewNode)
 * 2. 删除节点 (removeNode) 及级联删除连线
 * 3. 拖拽行为 (makeDraggable)
 * 4. 碰撞检测 (findNonCollidingPosition)
 * 5. 自动排列 (autoArrangeNodes)
 */
class NodeController {
    /**
     * @param {NodeFactory} nodeFactory
     * @param {LinkSystem} linkSystem
     * @param {UndoManager} undoManager
     * @param {I18nService} i18nService
     * @param {GraphModel} [graphModel] - 可选，Phase 2 引入
     */
    constructor(nodeFactory, linkSystem, undoManager, i18nService, graphModel = null) {
        this.nodeFactory = nodeFactory;
        this.linkSystem = linkSystem;
        this.undoManager = undoManager;
        this.i18nService = i18nService;
        this.graphModel = graphModel;

        // Callbacks (injected by orchestrator)
        this.getScale = null;
        this.onAutoSave = null;
        this.showToast = null;
        this.updateAllConnections = null;
        this.updatePinVisuals = null;
    }

    /**
     * 创建节点，自动避开碰撞位置
     * @param {string} type - 节点类型
     * @param {number} posX - X 坐标
     * @param {number} posY - Y 坐标
     */
    createNewNode(type, posX, posY) {
        const adjustedPos = this.findNonCollidingPosition(posX, posY, 260, 150);
        const nodeEl = this.nodeFactory.createNode(type, adjustedPos.x, adjustedPos.y);

        // 同步到 GraphModel
        if (this.graphModel && nodeEl) {
            this.graphModel.addNode(nodeEl.id, type, adjustedPos.x, adjustedPos.y, {});
        }

        if (this.onAutoSave) this.onAutoSave();
        return nodeEl;
    }

    /**
     * 删除节点及其关联连线
     * @param {string} nodeId - 节点 ID
     */
    removeNode(nodeId) {
        const nodeEl = document.getElementById(nodeId);
        if (!nodeEl) return;

        // 收集元数据用于撤销（优先）和 outerHTML（向后兼容）
        const nodeType = nodeEl.dataset.type || 'unknown';
        const posX = parseFloat(nodeEl.style.left) || 0;
        const posY = parseFloat(nodeEl.style.top) || 0;
        const properties = {};
        nodeEl.querySelectorAll('.property-input').forEach(input => {
            const key = input.dataset.prop;
            if (key) {
                properties[key] = input.type === 'checkbox' ? input.checked : input.value;
            }
        });

        this.undoManager.record({
            type: 'delete',
            id: nodeId,
            data: {
                type: nodeType,
                x: posX,
                y: posY,
                properties
            }
        });

        // 级联删除关联连线
        const relatedConnIds = [];
        this.linkSystem.connections.forEach((conn, connId) => {
            const connData = this.graphModel ? this.graphModel.connections.get(connId) : null;
            if (connData && (connData.source.startsWith(nodeId + '::') || connData.target.startsWith(nodeId + '::'))) {
                relatedConnIds.push(connId);
            }
        });
        relatedConnIds.forEach(connId => {
            this.linkSystem.deleteConnectionInteractive(connId);
            if (this.graphModel) this.graphModel.removeConnection(connId);
        });

        nodeEl.remove();

        // 同步到 GraphModel
        if (this.graphModel) {
            this.graphModel.nodes.delete(nodeId);
        }

        if (this.updatePinVisuals) this.updatePinVisuals();
        if (this.onAutoSave) this.onAutoSave();
    }

    /**
     * 应用属性元数据到节点元素
     * @param {HTMLElement} nodeEl 
     * @param {Object} properties 
     */
    applyProperties(nodeEl, properties) {
        if (!properties) return;
        for (const [key, val] of Object.entries(properties)) {
            const input = nodeEl.querySelector(`.property-input[data-prop="${key}"]`);
            if (input) {
                if (input.type === 'checkbox') {
                    input.checked = (val === true || val === 'true');
                } else {
                    input.value = val;
                }
                // 触发变更事件以应用某些逻辑（如互斥检查）
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }

    /**
     * 使节点可拖拽（支持多选拖拽）
     * @param {HTMLElement} nodeEl - 节点 DOM 元素
     */
    makeDraggable(nodeEl) {
        const self = this;

        nodeEl.addEventListener('mousedown', function (event) {
            // 忽略 Pin/表单控件的点击
            if (event.target.closest('.pin')) return;
            const tagName = event.target.tagName.toLowerCase();
            if (tagName === 'input' || tagName === 'select' || tagName === 'button' || tagName === 'textarea') return;
            if (event.target.classList.contains('close-btn') || event.target.classList.contains('browse-btn')) return;

            event.preventDefault();
            event.stopPropagation();

            // 选中管理
            if (!event.ctrlKey && !event.shiftKey && !nodeEl.classList.contains('selected')) {
                document.querySelectorAll('.node').forEach(otherNode => otherNode.classList.remove('selected'));
                nodeEl.classList.add('selected');
            } else if (event.ctrlKey) {
                nodeEl.classList.toggle('selected');
            } else {
                nodeEl.classList.add('selected');
            }

            // 记录所有选中节点的起始位置
            const dragStarts = new Map();
            document.querySelectorAll('.node.selected').forEach(selectedNode => {
                dragStarts.set(selectedNode.id, {
                    x: parseFloat(selectedNode.style.left) || 0,
                    y: parseFloat(selectedNode.style.top) || 0
                });
                selectedNode.style.zIndex = 100;
            });

            const startMouseX = event.clientX;
            const startMouseY = event.clientY;
            document.body.classList.add('dragging-node');

            const onMouseMove = (moveEvent) => {
                const currentScale = self.getScale ? self.getScale() : 1;
                const deltaX = (moveEvent.clientX - startMouseX) / currentScale;
                const deltaY = (moveEvent.clientY - startMouseY) / currentScale;

                document.querySelectorAll('.node.selected').forEach(selectedNode => {
                    const start = dragStarts.get(selectedNode.id);
                    if (start) {
                        selectedNode.style.left = (start.x + deltaX) + 'px';
                        selectedNode.style.top = (start.y + deltaY) + 'px';
                    }
                });

                if (self.updateAllConnections) {
                    document.querySelectorAll('.node.selected').forEach(node => {
                        self.updateAllConnections(node.id);
                    });
                }
            };

            const onMouseUp = () => {
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                document.body.classList.remove('dragging-node');

                // 碰撞修正 + 同步 GraphModel 位置
                document.querySelectorAll('.node.selected').forEach(selectedNode => {
                    const nodeX = parseFloat(selectedNode.style.left) || 0;
                    const nodeY = parseFloat(selectedNode.style.top) || 0;
                    const nodeW = selectedNode.offsetWidth || 260;
                    const nodeH = selectedNode.offsetHeight || 150;

                    let finalX = nodeX;
                    let finalY = nodeY;

                    if (self._checkCollision(selectedNode.id, nodeX, nodeY, nodeW, nodeH)) {
                        const adjusted = self.findNonCollidingPosition(nodeX, nodeY, nodeW, nodeH, selectedNode.id);
                        selectedNode.style.left = adjusted.x + 'px';
                        selectedNode.style.top = adjusted.y + 'px';
                        finalX = adjusted.x;
                        finalY = adjusted.y;
                        if (self.updateAllConnections) self.updateAllConnections();
                    }

                    // 同步位置到 GraphModel
                    if (self.graphModel) {
                        self.graphModel.updateNodePosition(selectedNode.id, finalX, finalY);
                    }

                    if (self.onAutoSave) self.onAutoSave();
                });
            };

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    }

    /**
     * 自动排列节点：连通节点按拓扑从左到右，孤立节点放右侧
     */
    autoArrangeNodes() {
        const allNodes = Array.from(document.querySelectorAll('.node'));
        if (allNodes.length === 0) return;

        // 构建邻接关系
        const connectedNodeIds = new Set();
        const edges = [];
        this.linkSystem.connections.forEach((conn, connId) => {
            if (connId === 'temp') return;
            const srcNodeId = conn.source.split('-out-')[0];
            const tgtNodeId = conn.target.split('-in-')[0];
            connectedNodeIds.add(srcNodeId);
            connectedNodeIds.add(tgtNodeId);
            edges.push({ from: srcNodeId, to: tgtNodeId });
        });

        const connectedNodes = allNodes.filter(nodeEl => connectedNodeIds.has(nodeEl.id));
        const isolatedNodes = allNodes.filter(nodeEl => !connectedNodeIds.has(nodeEl.id));

        // Kahn 拓扑排序
        const inDegree = {};
        const adjacency = {};
        connectedNodes.forEach(nodeEl => {
            inDegree[nodeEl.id] = 0;
            adjacency[nodeEl.id] = [];
        });

        edges.forEach(edge => {
            if (adjacency[edge.from] && inDegree[edge.to] !== undefined) {
                adjacency[edge.from].push(edge.to);
                inDegree[edge.to]++;
            }
        });

        const queue = [];
        const layers = [];
        for (const nodeId in inDegree) {
            if (inDegree[nodeId] === 0) queue.push(nodeId);
        }

        while (queue.length > 0) {
            const layer = [...queue];
            layers.push(layer);
            queue.length = 0;
            for (const nodeId of layer) {
                for (const neighbor of adjacency[nodeId]) {
                    inDegree[neighbor]--;
                    if (inDegree[neighbor] === 0) queue.push(neighbor);
                }
            }
        }

        // 布局参数
        const ORIGIN_X = 2000;
        const ORIGIN_Y = 2000;
        const H_PADDING = 60;
        const V_PADDING = 50;

        // 计算每层宽度
        const layerWidths = layers.map(layer =>
            Math.max(...layer.map(nodeId => {
                const el = document.getElementById(nodeId);
                return el ? el.offsetWidth : 260;
            }))
        );

        // 计算行高
        const maxRowCount = Math.max(...layers.map(layer => layer.length), 1);
        const rowHeights = [];
        for (let rowIdx = 0; rowIdx < maxRowCount; rowIdx++) {
            let maxHeight = 150;
            layers.forEach(layer => {
                if (layer[rowIdx]) {
                    const el = document.getElementById(layer[rowIdx]);
                    if (el) maxHeight = Math.max(maxHeight, el.offsetHeight);
                }
            });
            rowHeights.push(maxHeight);
        }

        // 定位连通节点
        let currentX = ORIGIN_X;
        layers.forEach((layer, layerIndex) => {
            let currentY = ORIGIN_Y;
            layer.forEach((nodeId, nodeIndex) => {
                const el = document.getElementById(nodeId);
                if (el) {
                    el.style.left = `${currentX}px`;
                    el.style.top = `${currentY}px`;
                }
                currentY += rowHeights[nodeIndex] + V_PADDING;
            });
            currentX += layerWidths[layerIndex] + H_PADDING;
        });

        // 定位孤立节点
        const isolatedStartX = currentX + H_PADDING;
        let isoY = ORIGIN_Y;
        isolatedNodes.forEach(nodeEl => {
            nodeEl.style.left = `${isolatedStartX}px`;
            nodeEl.style.top = `${isoY}px`;
            isoY += (nodeEl.offsetHeight || 150) + V_PADDING;
        });

        if (this.updateAllConnections) this.updateAllConnections();
        const arrangedMsg = this.i18nService ? this.i18nService.t('ui.msg.arranged') : 'Nodes arranged';
        if (this.showToast) this.showToast(arrangedMsg || 'Nodes arranged');
    }

    /**
     * 螺旋搜索找到无碰撞位置
     * @param {number} posX - 目标 X
     * @param {number} posY - 目标 Y
     * @param {number} width - 节点宽度
     * @param {number} height - 节点高度
     * @param {string|null} excludeId - 排除检测的节点 ID
     * @returns {{x: number, y: number}}
     */
    findNonCollidingPosition(posX, posY, width = 260, height = 150, excludeId = null) {
        const PADDING = 25;
        const STEP = 30;
        const MAX_DISTANCE = 500;

        if (!this._checkCollision(excludeId, posX, posY, width, height, PADDING)) {
            return { x: posX, y: posY };
        }

        for (let dist = STEP; dist <= MAX_DISTANCE; dist += STEP) {
            const offsets = [
                [dist, 0], [-dist, 0], [0, dist], [0, -dist],
                [dist, dist], [-dist, dist], [dist, -dist], [-dist, -dist]
            ];
            for (const [deltaX, deltaY] of offsets) {
                const testX = posX + deltaX;
                const testY = posY + deltaY;
                if (!this._checkCollision(excludeId, testX, testY, width, height, PADDING)) {
                    return { x: testX, y: testY };
                }
            }
        }

        return { x: posX + width + PADDING, y: posY };
    }

    // --- Private ---

    /**
     * 检查指定位置是否与其他节点碰撞
     * @returns {boolean} true = 有碰撞
     */
    _checkCollision(excludeId, testX, testY, width = 260, height = 150, padding = 20) {
        const nodes = document.querySelectorAll('.node');
        for (const nodeEl of nodes) {
            if (excludeId && nodeEl.id === excludeId) continue;
            const nodeX = parseFloat(nodeEl.style.left) || 0;
            const nodeY = parseFloat(nodeEl.style.top) || 0;
            const nodeW = nodeEl.offsetWidth || 260;
            const nodeH = nodeEl.offsetHeight || 150;

            if (testX < nodeX + nodeW + padding && testX + width + padding > nodeX &&
                testY < nodeY + nodeH + padding && testY + height + padding > nodeY) {
                return true;
            }
        }
        return false;
    }
}
