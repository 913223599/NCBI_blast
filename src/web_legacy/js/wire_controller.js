/**
 * WireController - 连线拖拽交互管理
 * 
 * 职责：
 * 1. 管理连线拖拽状态 (isDraggingWire, dragSourcePinId)
 * 2. 处理拖拽开始/移动/结束
 * 3. 连线验证与创建
 * 4. 视觉反馈 (类型高亮/错误提示)
 */
class WireController {
    /**
     * @param {LinkSystem} linkSystem
     * @param {UndoManager} undoManager
     * @param {I18nService} i18nService
     */
    constructor(linkSystem, undoManager, i18nService) {
        this.linkSystem = linkSystem;
        this.undoManager = undoManager;
        this.i18nService = i18nService;

        this.isDraggingWire = false;
        this.dragSourcePinId = null;

        // Callbacks (injected by orchestrator)
        this.getPinCenter = null;
        this.showToast = null;
        this.onAutoSave = null;
        this.getScale = null;
        this.getCanvas = null;
        /** @type {Function|null} 连线创建后的回调 (connId, sourceId, targetId, type) => void */
        this.onConnectionCreated = null;

        this._bindGlobalListeners();
    }

    /** 是否正在拖拽连线 */
    get isDragging() {
        return this.isDraggingWire;
    }

    /**
     * 开始连线拖拽
     * @param {MouseEvent} event
     * @param {string} pinId
     */
    startWireDrag(event, pinId) {
        event.preventDefault();
        event.stopPropagation();

        this.isDraggingWire = true;
        this.dragSourcePinId = pinId;

        const pinEl = document.getElementById(pinId);
        if (pinEl) {
            const dataType = pinEl.getAttribute('data-data-type') || 'default';
            document.body.classList.add('dragging-wire');
            document.body.classList.add('dragging-type-' + dataType);
            pinEl.classList.add('dragging-source');
        }
    }

    /** 清理拖拽状态与视觉效果 */
    cleanupDrag() {
        this.linkSystem.removeTempConnection();
        this.isDraggingWire = false;
        this.dragSourcePinId = null;
        document.body.classList.remove('dragging-wire');
        document.body.className = document.body.className
            .split(' ')
            .filter(cls => !cls.startsWith('dragging-type-'))
            .join(' ');
        document.querySelectorAll('.pin.dragging-source').forEach(el => el.classList.remove('dragging-source'));

        if (this.getPinCenter) {
            this._updatePinVisuals();
        }
    }

    // --- Private ---

    _bindGlobalListeners() {
        document.addEventListener('mousemove', (event) => this._onMouseMove(event));
        document.addEventListener('mouseup', (event) => this._onMouseUp(event));
    }

    _onMouseMove(event) {
        if (!this.isDraggingWire || !this.dragSourcePinId || !this.getPinCenter || !this.getScale || !this.getCanvas) return;

        const sourcePos = this.getPinCenter(this.dragSourcePinId);
        if (!sourcePos) return;

        const canvasRect = this.getCanvas().getBoundingClientRect();
        const currentScale = this.getScale();
        const mouseX = (event.clientX - canvasRect.left) / currentScale;
        const mouseY = (event.clientY - canvasRect.top) / currentScale;

        const sourcePinEl = document.getElementById(this.dragSourcePinId);
        const dataType = sourcePinEl ? (sourcePinEl.getAttribute('data-data-type') || 'default') : 'default';
        this.linkSystem.drawTempConnection(sourcePos.x, sourcePos.y, mouseX, mouseY, { type: dataType });
    }

    _onMouseUp(event) {
        if (!this.isDraggingWire) return;

        event.stopPropagation();
        const targetPinEl = event.target.closest('.pin');

        if (targetPinEl && targetPinEl.id !== this.dragSourcePinId) {
            const sourceId = this.dragSourcePinId;
            const targetId = targetPinEl.id;

            const sourcePinEl = document.getElementById(sourceId);
            const targetDataPinEl = document.getElementById(targetId);

            const sourceType = sourcePinEl ? (sourcePinEl.getAttribute('data-data-type') || 'default') : 'default';
            const targetType = targetDataPinEl ? (targetDataPinEl.getAttribute('data-data-type') || 'default') : 'default';

            if (!this.linkSystem.validateConnection(sourceType, targetType)) {
                this._handleInvalidConnection(sourceId, targetId, sourceType, targetType);
                return;
            }

            this._createConnection(sourceId, targetId, sourceType);
        }

        this.cleanupDrag();
    }

    _handleInvalidConnection(sourceId, targetId, sourceType, targetType) {
        const errorMessage = this.i18nService
            ? this.i18nService.t('error.connection.incompatible', {
                source: sourceType.toUpperCase(),
                target: targetType.toUpperCase()
            })
            : `Cannot connect ${sourceType} to ${targetType}`;

        if (this.showToast) this.showToast(errorMessage, 'error');

        this.isDraggingWire = false;

        if (this.getPinCenter) {
            const targetCenter = this.getPinCenter(targetId);
            const sourceCenter = this.getPinCenter(sourceId);
            if (targetCenter && sourceCenter) {
                this.linkSystem.freezeError(sourceCenter.x, sourceCenter.y, targetCenter.x, targetCenter.y);
            }
        }

        setTimeout(() => this.cleanupDrag(), 1200);
    }

    _createConnection(sourceId, targetId, connectionType) {
        const connId = 'conn-' + Date.now();
        this.linkSystem.createConnection(connId, sourceId, targetId, { type: connectionType });

        if (this.getPinCenter) {
            this.linkSystem.updateConnectionPositions(this.getPinCenter);
        }
        this._updatePinVisuals();

        this.undoManager.record({
            type: 'connect',
            id: connId,
            data: { id: connId, source: sourceId, target: targetId, type: connectionType }
        });

        // 通知 GraphModel 同步
        if (this.onConnectionCreated) {
            this.onConnectionCreated(connId, sourceId, targetId, connectionType);
        }

        this.isDraggingWire = false;
        if (this.onAutoSave) this.onAutoSave();
    }

    _updatePinVisuals() {
        document.querySelectorAll('.pin').forEach(pinEl => {
            const isConnected = this.linkSystem.isPinConnected(pinEl.id);
            pinEl.classList.toggle('connected', isConnected);
        });
    }
}
