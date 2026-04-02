/**
 * ViewportController - 画布视口管理
 * 
 * 职责：
 * 1. 缩放与平移 (scale, translate)
 * 2. 鼠标滚轮缩放 (handleWheel)
 * 3. 中键/Space 拖拽平移
 * 4. 框选逻辑 (Box Selection)
 * 5. 重置/居中视口 (resetViewport)
 */
class ViewportController {
    /** @type {number} */
    static SIDEBAR_WIDTH = 280;

    /**
     * @param {HTMLElement} container - #studio-container
     * @param {HTMLElement} canvas - #canvas-root
     */
    constructor(container, canvas) {
        this.container = container;
        this.canvas = canvas;

        this.scale = 1;
        this.translateX = -2000;
        this.translateY = -2000;

        this.isDraggingCanvas = false;
        this._startX = 0;
        this._startY = 0;

        // Box selection state
        this.isSelecting = false;
        this._selectionStart = { x: 0, y: 0 };
        this._selectionBox = this._createSelectionBox();

        // Callbacks (injected by orchestrator)
        this.onAutoSave = null;

        this._bindWheelListener();
        this._bindPropertyChangeListeners();
        this.updateTransform();

        // v2 补丁：引入 ResizeObserver，比 window.onresize 更精准地监听容器物理尺寸变化
        this.resizeObserver = new ResizeObserver(entries => {
            for (let entry of entries) {
                if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
                    this.handleResize();
                }
            }
        });
        this.resizeObserver.observe(this.container);
    }

    /** 更新画布变换矩阵 */
    updateTransform() {
        this.canvas.style.transform = `translate(${this.translateX}px, ${this.translateY}px) scale(${this.scale})`;
        const statsEl = document.getElementById('viewport-stats');
        if (statsEl) {
            statsEl.innerText =
                `Zoom: ${Math.round(this.scale * 100)}% | Pos: ${Math.round(this.translateX)}, ${Math.round(this.translateY)}`;
        }
    }

    /** 处理滚轮缩放 */
    handleWheel(event) {
        event.preventDefault();
        const rect = this.container.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const mouseY = event.clientY - rect.top;

        const ZOOM_FACTOR = 1.1;
        const delta = event.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;

        const newScale = Math.min(Math.max(this.scale * delta, 0.15), 4);
        const actualDelta = newScale / this.scale;

        this.translateX = mouseX - (mouseX - this.translateX) * actualDelta;
        this.translateY = mouseY - (mouseY - this.translateY) * actualDelta;
        this.scale = newScale;
        this.updateTransform();
    }

    /**
     * 处理鼠标按下（平移或框选）
     * @param {MouseEvent} event
     * @param {boolean} isDraggingWire - 如果正在拖拽连线则跳过
     */
    handleMouseDown(event, isDraggingWire) {
        if (isDraggingWire) return;

        // 中键或 Space+左键：平移
        if (event.button === 1 || (event.button === 0 && event.getModifierState('Space'))) {
            this.isDraggingCanvas = true;
            this._startX = event.clientX - this.translateX;
            this._startY = event.clientY - this.translateY;
            this.container.classList.add('panning');
            return;
        }

        // 左键点击空白区域：开始框选
        const target = event.target;
        const isEmptyArea = target === this.container || target === this.canvas || target.id === 'connections-layer';
        if (event.button === 0 && isEmptyArea) {
            this.isSelecting = true;
            this._selectionStart = { x: event.clientX, y: event.clientY };

            if (!event.ctrlKey && !event.shiftKey) {
                document.querySelectorAll('.node').forEach(nodeEl => nodeEl.classList.remove('selected'));
            }

            this._selectionBox.style.display = 'block';
            this._selectionBox.style.left = event.clientX + 'px';
            this._selectionBox.style.top = event.clientY + 'px';
            this._selectionBox.style.width = '0px';
            this._selectionBox.style.height = '0px';
        }
    }

    /** 处理鼠标移动（平移或框选更新） */
    handleMouseMove(event) {
        if (this.isDraggingCanvas) {
            this.translateX = event.clientX - this._startX;
            this.translateY = event.clientY - this._startY;
            this.updateTransform();
        } else if (this.isSelecting) {
            const currentX = event.clientX;
            const currentY = event.clientY;
            const minX = Math.min(this._selectionStart.x, currentX);
            const minY = Math.min(this._selectionStart.y, currentY);
            const width = Math.abs(currentX - this._selectionStart.x);
            const height = Math.abs(currentY - this._selectionStart.y);

            this._selectionBox.style.left = minX + 'px';
            this._selectionBox.style.top = minY + 'px';
            this._selectionBox.style.width = width + 'px';
            this._selectionBox.style.height = height + 'px';
        }
    }

    /** 处理鼠标释放（完成平移/框选） */
    handleMouseUp(event) {
        if (this.isDraggingCanvas) {
            this.isDraggingCanvas = false;
            this.container.classList.remove('panning');
        } else if (this.isSelecting) {
            this.isSelecting = false;
            const selRect = this._selectionBox.getBoundingClientRect();
            this._selectionBox.style.display = 'none';

            // 极小框选视为点击
            if (selRect.width < 5 && selRect.height < 5) return;

            document.querySelectorAll('.node').forEach(nodeEl => {
                const nodeRect = nodeEl.getBoundingClientRect();
                if (selRect.left < nodeRect.right &&
                    selRect.right > nodeRect.left &&
                    selRect.top < nodeRect.bottom &&
                    selRect.bottom > nodeRect.top) {
                    nodeEl.classList.add('selected');
                }
            });
        }

        // 拖拽结束后触发自动保存
        if (document.body.classList.contains('dragging-node') && this.onAutoSave) {
            this.onAutoSave();
        }
    }

    /** 重置视口到节点居中位置 */
    resetViewport() {
        const nodes = document.querySelectorAll('.node');
        if (nodes.length === 0) {
            this.translateX = -2000;
            this.translateY = -2000;
            this.scale = 1;
        } else {
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            nodes.forEach(nodeEl => {
                const posX = parseFloat(nodeEl.style.left);
                const posY = parseFloat(nodeEl.style.top);
                minX = Math.min(minX, posX);
                minY = Math.min(minY, posY);
                maxX = Math.max(maxX, posX + nodeEl.offsetWidth);
                maxY = Math.max(maxY, posY + nodeEl.offsetHeight);
            });

            const midX = (minX + maxX) / 2;
            const midY = (minY + maxY) / 2;
            this.scale = 0.8;
            const rect = this.container.getBoundingClientRect();
            const workAreaWidth = rect.width - ViewportController.SIDEBAR_WIDTH;
            this.translateX = ViewportController.SIDEBAR_WIDTH + (workAreaWidth / 2) - midX * this.scale;
            this.translateY = (rect.height / 2) - midY * this.scale;
        }
        this.updateTransform();
    }

    /** 处理窗口调整大小以强制刷新渲染层 */
    handleResize() {
        // v3 补丁：建立多帧重绘队列，应对全屏切换时的渲染管线抖动
        const forceCycle = () => {
            // 1. 强制触发浏览器重排 (Reflow)
            const reflowTrigger = this.container.offsetHeight;

            // 2. 更新矩阵并强制重绘
            this.updateTransform();

            // v4 补丁：执行“像素滚动”强制同步。即使页面没有滚动条，这也能强制内核提交新帧到 Compositor
            window.scrollBy(0, 1);
            window.scrollBy(0, -1);

            console.log(`[Viewport] Frame redraw active with scroll trigger (H: ${reflowTrigger})`);
        };

        // 连续追踪 3 帧，确保 GPU 表面完全稳定
        forceCycle();
        requestAnimationFrame(() => {
            forceCycle();
            requestAnimationFrame(() => {
                forceCycle();
            });
        });
    }

    // --- Private ---

    _createSelectionBox() {
        const box = document.createElement('div');
        box.className = 'selection-box';
        box.style.display = 'none';
        this.container.appendChild(box);
        return box;
    }

    _bindWheelListener() {
        this.container.addEventListener('wheel', (event) => this.handleWheel(event), { passive: false });
    }

    _bindPropertyChangeListeners() {
        const triggerSave = () => { if (this.onAutoSave) this.onAutoSave(); };
        this.container.addEventListener('change', (event) => {
            if (event.target.classList.contains('property-input')) triggerSave();
        });
        this.container.addEventListener('input', (event) => {
            if (event.target.classList.contains('property-input')) triggerSave();
        });
    }
}
