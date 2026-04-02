/**
 * LinkSystem - 负责连线的渲染、数据管理与交互逻辑
 * 
 * 职责：
 * 1. 渲染 Bezier 曲线
 * 2. 管理连线数据模型 (Type, Color, Metadata)
 * 3. 处理连线交互 (Select, Delete, Hover)
 */

class LinkSystem {
    constructor(svgLayer, undoManager, graphModel = null) {
        this.svg = svgLayer;
        this.undoManager = undoManager;
        this.graphModel = graphModel;
        this.connections = new Map(); // id -> { group, path, hitPath }
        this.selectedConnectionId = null;
        this.onConnectionChanged = null; // Callback for UI refresh

        // Init SVG Interaction
        this.svg.style.pointerEvents = 'none'; // Default passthrough
        this.svg.style.overflow = 'visible';
    }

    /**
     * 创建一条新的连线
     * @param {string} id - 连线唯一ID
     * @param {string} sourceId - 源 Pin ID
     * @param {string} targetId - 目标 Pin ID
     * @param {object} options - { color, type, data }
     */
    createConnection(id, sourceId, targetId, options = {}) {
        if (this.connections.has(id)) return;

        const type = options.type || 'default';
        const color = options.color || this.getConnectionColor(type);

        // --- Create SVG Path ---
        // We create a group to hold the visible path and a wider "hit area" path for easier selection
        const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
        group.setAttribute("class", "connection-group");
        group.id = `grp-${id}`;
        group.style.pointerEvents = "all"; // Enable interaction on the group
        group.style.cursor = "pointer";

        // 1. Invisible wide hit path
        const hitPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        hitPath.setAttribute("stroke", "transparent");
        hitPath.setAttribute("stroke-width", "10"); // Wide hit area
        hitPath.setAttribute("fill", "none");

        // 2. Visible path
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("class", "connection-line");
        path.setAttribute("stroke", color);
        path.style.stroke = color; // Force style to query override CSS
        path.setAttribute("stroke-width", "2");
        path.setAttribute("fill", "none");

        group.appendChild(hitPath);
        group.appendChild(path);
        this.svg.appendChild(group);

        // --- Store Elements ---
        this.connections.set(id, {
            group,
            path,
            hitPath
        });

        // --- Notify ---
        if (this.onConnectionChanged) this.onConnectionChanged();

        // --- Bind Interaction ---
        // Use mousedown instead of click to be more responsive and prevent canvas drag interference
        group.addEventListener('mousedown', (e) => {
            if (e.button === 0) { // Left click only
                // e.stopPropagation(); // DO NOT stop propagation here if you want nodes to lose focus? 
                // Wait, if I click a wire, I want to select IT, not deselect everything else? 
                // The main canvas mousedown clears selection.
                // If I stop propagation, canvas won't see it -> selection PRESERVED?
                // Actually, standard behavior: click object = select object, deselect others.
                e.stopPropagation();

                // Clear node selection manually if we want exclusion
                // But for now just select connection
                this.selectConnection(id);
            }
        });

        // Right click to delete
        group.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.deleteConnectionInteractive(id);
        });

        return group;
    }

    /**
     * 更新连线位置
     * @param {function} getPinCenterFunc
     * @param {string|null} filterNodeId - 如果指定，则仅更新与该节点相关的连线 (局部更新)
     */
    updateConnectionPositions(getPinCenterFunc, filterNodeId = null) {
        let targetIds;
        if (filterNodeId && this.graphModel) {
            targetIds = this.graphModel.getConnectionsForNode(filterNodeId);
        } else {
            targetIds = Array.from(this.connections.keys()).filter(id => id !== 'temp');
        }

        targetIds.forEach(id => {
            const elements = this.connections.get(id);
            const connData = this.graphModel ? this.graphModel.connections.get(id) : null;
            if (!elements || !connData) return;

            const sourcePos = this._getPinPosCached(connData.source, getPinCenterFunc);
            const targetPos = this._getPinPosCached(connData.target, getPinCenterFunc);

            if (sourcePos && targetPos) {
                const d = this._calculateBezierPath(sourcePos.x, sourcePos.y, targetPos.x, targetPos.y);
                elements.path.setAttribute("d", d);
                elements.hitPath.setAttribute("d", d);
            }
        });
    }

    /** 带缓存的销位坐标获取 */
    _getPinPosCached(pinId, fetchFunc) {
        if (this.graphModel) {
            let cached = this.graphModel.getPinCenter(pinId);
            if (cached) return cached;

            cached = fetchFunc(pinId);
            if (cached) this.graphModel.updatePinCenter(pinId, cached.x, cached.y);
            return cached;
        }
        return fetchFunc(pinId);
    }

    /**
     * 绘制临时连线 (用于拖拽过程)
     */
    drawTempConnection(x1, y1, x2, y2, options = {}) {
        let temp = this.connections.get('temp');
        if (!temp) {
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            path.setAttribute("fill", "none");
            path.setAttribute("stroke-dasharray", "5,5");
            path.setAttribute("stroke-opacity", "0.6");
            path.style.pointerEvents = "none"; // Important!
            this.svg.appendChild(path);
            temp = { path };
            this.connections.set('temp', temp);
        }

        const type = options.type || 'default';
        const color = options.color || this.getConnectionColor(type);
        // Only update if changed to avoid DOM thrashing? Attributes are cheap.
        temp.path.setAttribute("stroke", color);

        const d = this._calculateBezierPath(x1, y1, x2, y2);
        temp.path.setAttribute("d", d);
    }

    isPinConnected(pinId) {
        if (this.graphModel) {
            for (let conn of this.graphModel.connections.values()) {
                if (conn.source === pinId || conn.target === pinId) return true;
            }
        }
        return false;
    }

    showConnectionError() {
        const temp = this.connections.get('temp');
        if (temp) {
            temp.path.setAttribute("stroke", "#ef4444");
            temp.path.setAttribute("stroke-width", "3");
            temp.path.setAttribute("stroke-dasharray", "5,5"); // Back to dashed for error
            temp.path.classList.add("connection-error");
        }
    }

    freezeError(x1, y1, x2, y2) {
        this.drawTempConnection(x1, y1, x2, y2);
        this.showConnectionError();
    }

    removeTempConnection() {
        const temp = this.connections.get('temp');
        if (temp) {
            temp.path.remove();
            this.connections.delete('temp');
        }
    }

    /**
     * 计算平滑的 Bezier 曲线路径
     */
    _calculateBezierPath(x1, y1, x2, y2) {
        const dist = Math.abs(x2 - x1);
        const curvature = Math.max(dist * 0.5, 50);
        const cp1x = x1 + curvature;
        const cp1y = y1;
        const cp2x = x2 - curvature;
        const cp2y = y2;
        return `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`;
    }

    /**
     * 选中连线
     */
    selectConnection(id) {
        // Deselect previous
        if (this.selectedConnectionId && this.connections.has(this.selectedConnectionId)) {
            const prev = this.connections.get(this.selectedConnectionId);
            const prevData = this.graphModel ? this.graphModel.connections.get(this.selectedConnectionId) : null;
            const prevType = prevData ? prevData.type : 'default';

            prev.path.classList.remove('selected');
            // Restore default color
            prev.path.setAttribute("stroke", this.getConnectionColor(prevType));
            prev.path.setAttribute("stroke-width", "2");
        }

        // If clicking same wire, it remains selected, logic below updates it
        // Or unselecting if clicking null?
        if (id === null) {
            this.selectedConnectionId = null;
            return;
        }

        this.selectedConnectionId = id;
        const conn = this.connections.get(id);
        if (conn) {
            conn.path.classList.add('selected');
            // We depend on CSS !important, but let's clear inline styles that might conflict
            conn.path.setAttribute("stroke", "");
            conn.path.setAttribute("stroke-width", "");
        }
    }

    clearSelection() {
        if (this.selectedConnectionId) {
            this.selectConnection(null); // Will handle deselect logic
            this.selectedConnectionId = null;
        }
    }

    /**
     * 获取连线默认颜色
     */
    /**
     * 验证连接是否合法
     */
    validateConnection(sourceType, targetType) {
        if (!sourceType || !targetType) return false;
        const s = sourceType.toLowerCase();
        const t = targetType.toLowerCase();

        // Direct match
        if (s === t) return true;

        // Wildcards
        if (s === 'default' || t === 'default') return true;
        if (s === 'any' || t === 'any') return true;

        return false;
    }

    getConnectionColor(type) {
        switch (type) {
            case 'seq': return '#06b6d4'; // Cyan (Raw Data)
            case 'matrix': return '#8b5cf6'; // Violet (Intermediate)
            case 'tree': return '#10b981'; // Green (Result)
            case 'report': return '#f59e0b'; // Amber (Report)
            case 'exec': return '#ef4444'; // Red (Execution flow)
            default: return '#64748b'; // Slate (Default/Generic)
        }
    }

    /**
     * 交互式删除连线 (带 Undo 记录)
     */
    deleteConnectionInteractive(id) {
        const elements = this.connections.get(id);
        const connData = this.graphModel ? this.graphModel.connections.get(id) : null;
        if (!elements || !connData) return;

        // Record Undo
        if (this.undoManager) {
            this.undoManager.record({
                type: 'disconnect',
                id: id,
                data: {
                    id: id,
                    source: connData.source,
                    target: connData.target,
                    type: connData.type,
                    data: connData.data
                }
            });
        }

        this.removeConnection(id);
    }

    /**
     * 移除连线 (物理删除)
     */
    removeConnection(id) {
        const conn = this.connections.get(id);
        if (conn) {
            conn.group.remove();
            this.connections.delete(id);
            if (this.selectedConnectionId === id) this.selectedConnectionId = null;

            if (this.onConnectionChanged) this.onConnectionChanged();
        }
    }
}
