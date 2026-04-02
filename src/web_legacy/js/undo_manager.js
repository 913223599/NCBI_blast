/**
 * UndoManager - 可扩展的撤销/重做管理器
 * 
 * 改进 (Phase 5)：
 * - 彻底移除对 outerHTML 的依赖，实现纯数据驱动的 SSOT 架构
 * - 强制通过 nodeCreateCallback 进行节点重建
 * - 简化 action 数据结构，提升序列化效率
 * 
 * 使用方法：
 * 1. 初始化：const undoManager = new UndoManager(canvasElement, maxSteps);
 * 2. 记录操作：undoManager.record(actionObject);
 * 3. 撤销：undoManager.undo();
 * 4. 重做：undoManager.redo();
 */

class UndoManager {
    /**
     * @param {HTMLElement} canvas - 画布 DOM 元素
     * @param {number} maxSteps - 最大撤销步数
     */
    constructor(canvas, maxSteps = 10) {
        if (!canvas) {
            throw new Error('[UndoManager] canvas element is required');
        }
        this.canvas = canvas;
        this.maxSteps = maxSteps;
        /** @type {Array<UndoManager.Action>} */
        this.undoStack = [];
        /** @type {Array<UndoManager.Action>} */
        this.redoStack = [];

        /** @type {Function|null} 恢复节点后的回调（重新绑定拖拽等交互） */
        this.nodeRestoreCallback = null;

        /** @type {Function|null} 从元数据创建节点的回调（Phase 2 新增） */
        this.nodeCreateCallback = null;

        /** @type {Object} 连线操作回调 */
        this.connectionCallbacks = {
            remove: null,
            restore: null
        };

        this._bindKeyboard();
    }

    /**
     * 设置节点恢复后的回调（如重新绑定拖拽）
     * @param {Function} callback - (nodeElement) => void
     */
    setNodeRestoreCallback(callback) {
        this.nodeRestoreCallback = callback;
    }

    /**
     * 设置从元数据创建节点的回调（Phase 2 新增）
     * @param {Function} callback - (type, x, y, id, properties) => HTMLElement
     */
    setNodeCreateCallback(callback) {
        this.nodeCreateCallback = callback;
    }

    /**
     * 设置连线操作的回调
     * @param {Object} callbacks
     * @param {Function} callbacks.remove - (id) => void
     * @param {Function} callbacks.restore - (data) => void
     */
    setConnectionCallbacks(callbacks) {
        this.connectionCallbacks = callbacks;
    }

    /**
     * 记录一个可撤销的操作
     * @param {UndoManager.Action} action
     * @param {string} action.type - 'create'|'delete'|'move'|'connect'|'disconnect'
     * @param {string} action.id - 节点/连线 ID
     * @param {Object} action.data - 操作相关数据
     */
    record(action) {
        this.undoStack.push(action);
        if (this.undoStack.length > this.maxSteps) {
            this.undoStack.shift();
        }
        // 记录新操作后清空 redo 栈
        this.redoStack = [];
    }

    /**
     * 执行撤销
     * @returns {boolean} 是否成功
     */
    undo() {
        if (this.undoStack.length === 0) return false;

        const action = this.undoStack.pop();
        this._applyUndo(action);
        this.redoStack.push(action);

        return true;
    }

    /**
     * 执行重做
     * @returns {boolean} 是否成功
     */
    redo() {
        if (this.redoStack.length === 0) return false;

        const action = this.redoStack.pop();
        this._applyRedo(action);
        this.undoStack.push(action);

        return true;
    }

    /**
     * 应用撤销逻辑
     * @param {UndoManager.Action} action
     * @private
     */
    _applyUndo(action) {
        switch (action.type) {
            case 'delete':
                this._restoreNode(action);
                break;
            case 'create':
                this._removeNode(action.id);
                break;
            case 'move':
                this._moveNode(action.id, action.data.oldX, action.data.oldY);
                break;
            case 'connect':
                this._removeConnection(action.data.connectionId || action.data.id);
                break;
            case 'disconnect':
                this._restoreConnection(action.data);
                break;
            default:
                console.warn('[UndoManager] Unknown action type:', action.type);
        }
    }

    /**
     * 应用重做逻辑
     * @param {UndoManager.Action} action
     * @private
     */
    _applyRedo(action) {
        switch (action.type) {
            case 'delete':
                this._removeNode(action.id);
                break;
            case 'create':
                this._restoreNode(action);
                break;
            case 'move':
                this._moveNode(action.id, action.data.newX, action.data.newY);
                break;
            case 'connect':
                this._restoreConnection(action.data);
                break;
            case 'disconnect':
                this._removeConnection(action.data.connectionId || action.data.id);
                break;
            default:
                console.warn('[UndoManager] Unknown action type:', action.type);
        }
    }

    /**
     * 恢复被删除的节点
     * 优先使用元数据重建（Phase 2），回退到 outerHTML（向后兼容）
     * @param {UndoManager.Action} action
     * @private
     */
    _restoreNode(action) {
        const { data } = action;

        // Phase 5: 强制从元数据重建，确保数据一致性
        if (this.nodeCreateCallback && data.type) {
            const nodeEl = this.nodeCreateCallback(
                data.type,
                data.x,
                data.y,
                action.id,
                data.properties || {}
            );

            if (nodeEl && this.nodeRestoreCallback) {
                this.nodeRestoreCallback(nodeEl);
            }
            return;
        }

        console.error('[UndoManager] _restoreNode: Missing metadata or callback for action', action.id);
    }

    /**
     * 移除节点
     * @param {string} nodeId
     * @private
     */
    _removeNode(nodeId) {
        const nodeEl = document.getElementById(nodeId);
        if (nodeEl) nodeEl.remove();
    }

    /**
     * 移动节点到指定位置
     * @param {string} nodeId
     * @param {number} posX
     * @param {number} posY
     * @private
     */
    _moveNode(nodeId, posX, posY) {
        const nodeEl = document.getElementById(nodeId);
        if (nodeEl) {
            nodeEl.style.left = posX + 'px';
            nodeEl.style.top = posY + 'px';
        }
    }

    /**
     * 移除连线
     * @param {string} connectionId
     * @private
     */
    _removeConnection(connectionId) {
        if (this.connectionCallbacks.remove) {
            this.connectionCallbacks.remove(connectionId);
        }
    }

    /**
     * 恢复连线
     * @param {Object} connectionData
     * @private
     */
    _restoreConnection(connectionData) {
        if (this.connectionCallbacks.restore) {
            this.connectionCallbacks.restore(connectionData);
        }
    }

    /**
     * 绑定键盘快捷键
     * @private
     */
    _bindKeyboard() {
        document.addEventListener('keydown', (event) => {
            const isModified = event.ctrlKey || event.metaKey;

            // Ctrl+Z / Cmd+Z: Undo
            if (isModified && event.key === 'z' && !event.shiftKey) {
                event.preventDefault();
                this.undo();
            }
            // Ctrl+Shift+Z / Cmd+Shift+Z: Redo
            if (isModified && event.key === 'z' && event.shiftKey) {
                event.preventDefault();
                this.redo();
            }
            // Ctrl+Y: Redo (Windows style)
            if (isModified && event.key === 'y') {
                event.preventDefault();
                this.redo();
            }
        });
    }

    /**
     * 获取当前历史状态（调试用）
     * @returns {Object}
     */
    getStatus() {
        return {
            undoCount: this.undoStack.length,
            redoCount: this.redoStack.length,
            maxSteps: this.maxSteps
        };
    }

    /**
     * 清空所有历史
     */
    clear() {
        this.undoStack = [];
        this.redoStack = [];
    }
}

// 导出供模块化使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UndoManager;
}
