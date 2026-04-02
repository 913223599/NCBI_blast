/**
 * StudioApp - Node Studio 核心编排器
 * 
 * 职责：
 * 1. 实例化并配置所有子系统 (Model, Controllers, Bridge)
 * 2. 集中管理依赖注入 (DI)
 * 3. 封装全局事件监听与生命周期钩子
 * 4. 提供统一的基础服务 (Toast, Confirmation)
 */
class StudioApp {
    constructor() {
        // --- 1. 基础数据模型 ---
        this.graphModel = new GraphModel();

        // --- 2. 核心系统 ---
        this.i18n = window.i18n || new I18nService();
        window.i18n = this.i18n; // 强制同步单例
        this.undoManager = new UndoManager(null, 10); // Canvas will be set later

        // --- 3. DOM 引用与系统 ---
        this.dom = {
            container: document.getElementById('studio-container'),
            canvas: document.getElementById('canvas-root'),
            connectionLayer: document.getElementById('connections-layer')
        };

        this.linkSystem = new LinkSystem(this.dom.connectionLayer, this.undoManager, this.graphModel);

        // --- 4. 控制器 ---
        this.viewportCtrl = new ViewportController(this.dom.container, this.dom.canvas);

        this.wireCtrl = new WireController(this.linkSystem, this.undoManager, this.i18n);

        this.nodeFactory = new NodeFactory(this.dom.canvas, this.undoManager, this.i18n, {
            onRemove: (id) => this.nodeCtrl.removeNode(id),
            onWireDrag: (e, pinId) => this.wireCtrl.startWireDrag(e, pinId),
            makeDraggable: (el) => this.nodeCtrl.makeDraggable(el)
        });

        this.topologyManager = new TopologyManager(this.nodeFactory, this.linkSystem, this.graphModel);

        this.nodeCtrl = new NodeController(this.nodeFactory, this.linkSystem, this.undoManager, this.i18n, this.graphModel);

        this.uiCtrl = new UIController(this.dom, this.i18n);

        this.bridge = new StudioBridge(this.i18n, this.nodeFactory, this.topologyManager, this.linkSystem, this.dom.canvas);

        // --- 5. 生命周期定时器 ---
        this.autoSaveTimer = null;

        this._injectDependencies();
    }

    /** 模块间手动依赖注入 */
    _injectDependencies() {
        // UndoManager 配置
        this.undoManager.canvas = this.dom.canvas;
        this.undoManager.setNodeRestoreCallback((el) => this.nodeCtrl.makeDraggable(el));

        // Phase 2/5: 使用元数据重建回调 (SSOT)
        this.undoManager.setNodeCreateCallback((type, x, y, id, props) => {
            const el = this.nodeFactory.createNode(type, x, y, id);
            if (props) this.nodeCtrl.applyProperties(el, props);
            this.graphModel.addNode(id, type, x, y, props);
            return el;
        });

        this.undoManager.setConnectionCallbacks({
            remove: (id) => {
                this.linkSystem.removeConnection(id);
                this.graphModel.removeConnection(id);
                this._refreshPins();
            },
            restore: (data) => {
                const { id, source, target, type } = data;
                this.linkSystem.createConnection(id, source, target, { type });
                this.graphModel.addConnection(id, source, target, type);
                this._refreshPins();
                this.linkSystem.updateConnectionPositions((pid) => this.getPinCenter(pid));
            }
        });

        // WireController 注入
        this.wireCtrl.getPinCenter = (pid) => this.getPinCenter(pid);
        this.wireCtrl.showToast = (m, t) => this.showToast(m, t);
        this.wireCtrl.onAutoSave = () => this.triggerAutoSave();
        this.wireCtrl.getScale = () => this.viewportCtrl.scale;
        this.wireCtrl.getCanvas = () => this.dom.canvas;
        this.wireCtrl.onConnectionCreated = (id, s, t, ty) => {
            this.graphModel.addConnection(id, s, t, ty);
        };

        // NodeController 注入
        this.nodeCtrl.getScale = () => this.viewportCtrl.scale;
        this.nodeCtrl.onAutoSave = () => this.triggerAutoSave();
        this.nodeCtrl.showToast = (m, t) => this.showToast(m, t);
        this.nodeCtrl.updateAllConnections = (nodeId = null) => this.linkSystem.updateConnectionPositions((pid) => this.getPinCenter(pid), nodeId);
        this.nodeCtrl.updatePinVisuals = () => this._refreshPins();

        // UIController 注入
        this.uiCtrl.onSearchNodes = (q) => this.uiCtrl.filterLibrary(q);
        this.uiCtrl.onAutoArrange = () => this.nodeCtrl.autoArrangeNodes();
        this.uiCtrl.onClearCanvas = () => this.showClearConfirm();

        // Bridge 注入
        this.bridge.showToast = (m, t) => this.showToast(m, t);
        this.bridge.makeDraggable = (el) => this.nodeCtrl.makeDraggable(el);

        // 对外暴露桥接入口
        window.handleBridgeEvent = (type, data) => this.bridge.handleBridgeEvent(type, data);
    }

    /** 初始化应用 */
    init() {
        console.log('[StudioApp] Booting...');

        // 1. 初始化视口
        this.viewportCtrl.updateTransform();

        // 2. 初始化连线监听
        this.linkSystem.onConnectionChanged = () => this._refreshPins();

        // 3. 绑定视口全局事件
        this.dom.container.addEventListener('mousedown', (e) => this.viewportCtrl.handleMouseDown(e, this.wireCtrl.isDragging));
        this.dom.container.addEventListener('mousemove', (e) => this.viewportCtrl.handleMouseMove(e));
        this.dom.container.addEventListener('mouseup', (e) => this.viewportCtrl.handleMouseUp(e));

        // 4. 绑定拖拽库
        this.dom.container.addEventListener('dragover', (e) => e.preventDefault());
        this.dom.container.addEventListener('drop', (e) => this._handleLibraryDrop(e));

        // 5. 初始化 TooltipFix
        if (typeof TooltipFix !== 'undefined' && TooltipFix.init) {
            TooltipFix.init({});
        }

        // 6. 尝试加载父级翻译并启动桥接
        this.bridge.tryLoadFromParent();
        this.bridge.init();

        // 7. 处理窗口调整大小 (解决黑屏与连线对齐问题)
        window.addEventListener('resize', () => {
            this.viewportCtrl.handleResize();
            this.linkSystem.updateConnectionPositions((pid) => this.getPinCenter(pid));
        });

        console.log('[StudioApp] System ready.');
    }

    /** 
     * 工具函数：获取销位中心坐标
     * Phase 5 优化：优先使用相对于节点的偏移量缓存，规避 Layout Thrashing
     */
    getPinCenter(pinId) {
        // 解析节点 ID (pinId 格式通常为 node-xxx::in::0)
        const nodeId = pinId.split('::')[0];
        const nodeData = this.graphModel ? this.graphModel.getNode(nodeId) : null;

        // 如果拥有偏移量缓存且已知节点位置，直接计算（极快，无需 DOM 调用）
        if (nodeData && this.graphModel.pinOffsets.has(pinId)) {
            const offset = this.graphModel.pinOffsets.get(pinId);
            return {
                x: nodeData.x + offset.dx,
                y: nodeData.y + offset.dy
            };
        }

        // 首次获取或缓存失效：调用 DOM 计算并存入偏移量
        const pinEl = document.getElementById(pinId);
        if (!pinEl) return null;

        const circle = pinEl.querySelector('.pin-circle');
        if (!circle) return null;

        const rect = circle.getBoundingClientRect();
        const canvasRect = this.dom.canvas.getBoundingClientRect();
        const scale = this.viewportCtrl.scale;

        const centerX = (rect.left + rect.width / 2 - canvasRect.left) / scale;
        const centerY = (rect.top + rect.height / 2 - canvasRect.top) / scale;

        // 如果存在节点数据，则计算并缓存相对偏移
        if (nodeData) {
            this.graphModel.pinOffsets.set(pinId, {
                dx: centerX - nodeData.x,
                dy: centerY - nodeData.y
            });
        }

        return { x: centerX, y: centerY };
    }

    /** 触发自动计划 */
    triggerAutoSave() {
        if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
        this.autoSaveTimer = setTimeout(() => {
            if (window.py_bridge && window.py_bridge.save_topology) {
                const topology = this.topologyManager.serializeGraph();
                window.py_bridge.save_topology(JSON.stringify(topology));
            }
        }, 2000);
    }

    /** 显示全局消息提示 (代理到 uiCtrl) */
    showToast(message, type = 'info') {
        if (this.uiCtrl) this.uiCtrl.showToast(message, type);
    }

    /** 提供国际化便捷方法 */
    t(key, params = {}) { return this.i18n.t(key, params); }
    applyTranslations() { this.i18n.applyTranslations(); }

    /** 显示清空画布确认弹窗 */
    showClearConfirm() {
        if (typeof UIHelper === 'undefined') {
            if (confirm('确定要清空画布吗？')) {
                this.topologyManager.clearCanvas();
                this.graphModel.clear();
            }
            return;
        }
        UIHelper.showConfirm(
            this.t('ui.confirm.clear_title') || '确认清空',
            this.t('ui.confirm.clear_msg') || '这将移除画布上所有的节点和连线，确定吗？',
            () => {
                this.topologyManager.clearCanvas();
                this.graphModel.clear();
                this.showToast(this.t('ui.msg.canvas_cleared') || '画布已清空', 'success');
            }
        );
    }

    /** 刷新销位激活状态视觉效果 */
    _refreshPins() {
        document.querySelectorAll('.pin').forEach(el => {
            const isConnected = this.linkSystem.isPinConnected(el.id);
            el.classList.toggle('connected', isConnected);
        });
    }

    /** 从库中拖拽节点后的逻辑 */
    _handleLibraryDrop(event) {
        event.preventDefault();
        const type = event.dataTransfer.getData('node-type');
        const rect = this.dom.canvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) / this.viewportCtrl.scale;
        const y = (event.clientY - rect.top) / this.viewportCtrl.scale;
        this.nodeCtrl.createNewNode(type, x, y);
    }
}
