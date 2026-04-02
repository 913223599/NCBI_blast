/**
 * StudioBridge - 后端桥接与事件处理
 * 
 * 职责：
 * 1. QWebChannel 桥接初始化
 * 2. 工具元数据加载与侧边栏渲染
 * 3. 工作流执行与状态反馈 (handleBridgeEvent)
 * 4. 文件加载路由
 * 5. 翻译加载 (tryLoadFromParent)
 * 6. 树预览渲染
 */
class StudioBridge {
    /**
     * @param {I18nService} i18nService
     * @param {NodeFactory} nodeFactory
     * @param {TopologyManager} topologyManager
     * @param {LinkSystem} linkSystem
     * @param {HTMLElement} canvas - #canvas-root
     */
    constructor(i18nService, nodeFactory, topologyManager, linkSystem, canvas) {
        this.i18nService = i18nService;
        this.nodeFactory = nodeFactory;
        this.topologyManager = topologyManager;
        this.linkSystem = linkSystem;
        this.canvas = canvas;

        this.bridge = null;
        this.templateManager = null;
        this.lastBrowseTargetNodeId = null;

        // Callbacks (injected by orchestrator)
        this.showToast = null;
        this.makeDraggable = null;
    }

    /** 初始化桥接（页面加载时调用） */
    init() {
        console.log('[Studio] Initializing Bridge...');

        // 代理 console 日志到后端
        this._setupConsoleProxy();

        const findBridge = () => {
            if (this.bridge) return true;

            // 1. 本地 QWebChannel
            if (typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined' && qt.webChannelTransport) {
                console.log('[Studio] Connecting via local QWebChannel...');
                new QWebChannel(qt.webChannelTransport, (channel) => {
                    this._setupBridge(channel.objects.py_bridge);
                });
                return true;
            }

            // 2. 父窗口直接注入
            if (window.parent && window.parent.py_bridge) {
                console.log('[Studio] Using bridge from parent window.');
                this._setupBridge(window.parent.py_bridge);
                return true;
            }

            // 3. 父窗口 App 实例
            if (window.parent && window.parent.app && window.parent.app.bridge) {
                console.log('[Studio] Using bridge from parent app object.');
                this._setupBridge(window.parent.app.bridge);
                return true;
            }

            return false;
        };

        if (!findBridge()) {
            console.warn('[Studio] No bridge found yet. Starting poll...');
            let pollCount = 0;
            const pollInterval = setInterval(() => {
                if (findBridge()) {
                    clearInterval(pollInterval);
                    console.log('[Studio] Bridge acquired via polling.');
                }
                if (++pollCount > 20) { // 10s timeout
                    clearInterval(pollInterval);
                    console.error('[Studio] Bridge acquisition timed out.');
                }
            }, 500);
        }
    }

    /** 代理 Console 日志至后端 */
    _setupConsoleProxy() {
        const originalLog = console.log;
        const originalWarn = console.warn;
        const originalError = console.error;
        const self = this;

        const forwardToBridge = (level, args) => {
            const msg = `[StudioJS] [${level}] ` + Array.from(args).map(arg =>
                typeof arg === 'object' ? JSON.stringify(arg) : String(arg)
            ).join(' ');
            if (self.bridge && self.bridge.on_js_log) {
                self.bridge.on_js_log(msg);
            }
        };

        console.log = function () {
            originalLog.apply(console, arguments);
            forwardToBridge('INFO', arguments);
        };
        console.warn = function () {
            originalWarn.apply(console, arguments);
            forwardToBridge('WARN', arguments);
        };
        console.error = function () {
            originalError.apply(console, arguments);
            forwardToBridge('ERROR', arguments);
        };
    }

    /** 执行工作流 */
    runWorkflow() {
        const topology = this.topologyManager.serializeGraph();
        console.log('Compiling Workflow:', JSON.stringify(topology, null, 2));

        if (this.bridge && this.bridge.run_workflow) {
            this.bridge.run_workflow(JSON.stringify(topology), (response) => {
                console.log('Workflow Submission:', response);
            });
        } else {
            alert('Workflow serialized (Check Console). Connect to backend to run.');
        }
    }

    /**
     * 处理桥接事件 (统一入口，修复重复定义问题)
     * @param {string} eventType - 事件类型
     * @param {Object} eventData - 事件数据
     */
    handleBridgeEvent(eventType, eventData) {
        console.log('[Bridge Event]', eventType, eventData);

        switch (eventType) {
            case 'init':
                console.log('[Bridge] Re-initializing tool metadata...');
                this._loadToolsMetadata();
                break;

            case 'workflow_start':
                document.querySelectorAll('.node').forEach(nodeEl => {
                    nodeEl.classList.remove('status-running', 'status-completed', 'status-error', 'status-warning');
                    nodeEl.style.boxShadow = '';
                });
                if (this.showToast) this.showToast('工作流开始执行...', 'info');
                break;

            case 'node_status':
                this._handleNodeStatus(eventData);
                break;

            case 'workflow_complete':
                if (this.showToast) this.showToast('工作流执行完成', 'success');
                break;

            case 'workflow_error':
                if (this.showToast) this.showToast('工作流执行失败: ' + (eventData.message || '未知错误'), 'error');
                break;

            case 'log':
                const msg = typeof eventData === 'string' ? eventData : (eventData.message || JSON.stringify(eventData));
                if (this.showToast) this.showToast(msg, 'info');
                break;

            default:
                console.warn('[Bridge] Unknown event type:', eventType);
        }
    }

    /**
     * 请求选择文件
     * @param {string} nodeId - 触发文件选择的节点 ID
     * @param {string} fileType - 文件类型 (e.g. 'fasta')
     */
    requestNodeFile(nodeId, fileType) {
        console.log(`[Studio] Node ${nodeId} requested file: ${fileType}`);
        this.lastBrowseTargetNodeId = nodeId;

        if (window.parent && window.parent.app && window.parent.app.requestFile) {
            window.parent.app.requestFile(fileType);
        } else if (this.bridge && this.bridge.request_file_load) {
            this.bridge.request_file_load(fileType);
        }
    }

    /**
     * 处理文件加载完成
     * @param {Object} fileData - {content, type, path}
     */
    handleFileLoaded(fileData) {
        const { content, type, path } = fileData;
        console.log(`[Studio] handleFileLoaded: ${type} -> ${path}`);

        if (type !== 'fasta') return;

        let targetNode = null;
        if (this.lastBrowseTargetNodeId) {
            targetNode = document.getElementById(this.lastBrowseTargetNodeId);
        }
        if (!targetNode) {
            const fastaNodes = document.querySelectorAll('.node[data-type="fasta"]');
            if (fastaNodes.length > 0) targetNode = fastaNodes[0];
        }

        if (targetNode) {
            console.log(`[Studio] Injecting path into node: ${targetNode.id}`);
            const pathInput = targetNode.querySelector('input[data-prop="path"]');
            if (pathInput) {
                pathInput.value = path;
                pathInput.dispatchEvent(new Event('change'));
                pathInput.dispatchEvent(new Event('input'));
            }

            const seqInput = targetNode.querySelector('textarea[data-prop="sequence"]');
            if (seqInput && !seqInput.value.trim()) {
                seqInput.value = content;
                seqInput.dispatchEvent(new Event('input'));
            }

            const loadedMsg = this.i18nService ? this.i18nService.t('ui.msg.file_loaded') : 'File loaded';
            if (this.showToast) this.showToast(loadedMsg || 'File loaded');
        } else {
            console.warn('[Studio] No FASTA node found to receive data.');
        }
    }

    /** 尝试从父窗口加载翻译 */
    tryLoadFromParent() {
        try {
            if (window.parent && window.parent.app && window.parent.app.i18n && window.parent.app.i18n.translations) {
                console.log('[Studio] Loading translations from parent window...');
                this.i18nService.translations = window.parent.app.i18n.translations;
                this.i18nService.applyTranslations();

                if (typeof TooltipFix !== 'undefined' && TooltipFix.init) {
                    TooltipFix.init(window.parent.app.i18n.translations);
                }
                return true;
            }
        } catch (error) {
            console.warn('[Studio] Failed to load from parent:', error);
        }
        return false;
    }

    // --- Private ---

    _setupBridge(bridgeInstance) {
        this.bridge = bridgeInstance;
        window.py_bridge = bridgeInstance;
        console.log('[Studio] Bridge Instance acquired.');

        this.i18nService.init(this.bridge);
        this.i18nService.loadTranslations().then(() => {
            console.log('[Studio] Translations loaded.');

            // 初始化 TemplateManager
            this.templateManager = new WorkflowTemplateManager(
                this.canvas, this.topologyManager, this.linkSystem, this.i18nService
            );

            this._loadToolsMetadata();
        });
    }

    _loadToolsMetadata() {
        if (!this.bridge.get_tools_metadata) {
            console.error('[Studio] bridge.get_tools_metadata not found!');
            return;
        }

        this.bridge.get_tools_metadata((jsonStr) => {
            try {
                const metadata = JSON.parse(jsonStr);
                console.log(`[Studio] Loaded ${metadata.tools.length} nodes from metadata.`);

                this.nodeFactory.setTemplates(metadata);

                // 确保基础 I/O 工具存在
                if (!metadata.tools.find(tool => tool.id === 'fasta')) {
                    metadata.tools.push({ id: 'fasta', name: 'FASTA Input', cat: 'io' });
                }
                if (!metadata.tools.find(tool => tool.id === 'export')) {
                    metadata.tools.push({ id: 'export', name: 'Export', cat: 'io' });
                }

                this._renderSidebar(metadata);

                if (typeof TooltipFix !== 'undefined' && TooltipFix.init) {
                    TooltipFix.init(this.i18nService.translations);
                }

                this._restoreWorkspace();
            } catch (error) {
                console.error('[Studio] Failed to parse tools metadata:', error);
            }
        });
    }

    _restoreWorkspace() {
        if (!this.bridge.load_topology) return;

        this.bridge.load_topology((jsonStr) => {
            if (!jsonStr) return;
            try {
                const topology = JSON.parse(jsonStr);
                if (topology && topology.nodes && topology.nodes.length > 0) {
                    this.topologyManager.loadTopology(topology);
                    console.log('[Studio] Workspace restored from disk.');
                }
            } catch (error) {
                console.error('Failed to restore workspace:', error);
            }
        });
    }

    _handleNodeStatus(eventData) {
        const { node_id: nodeId, status, message = '' } = eventData;
        const nodeEl = document.getElementById(nodeId);
        if (!nodeEl) return;

        nodeEl.classList.remove('status-running', 'status-completed', 'status-error', 'status-warning');
        nodeEl.classList.add('status-' + status);

        // 状态发光效果
        const GLOW_MAP = {
            running: '0 0 15px rgba(250, 204, 21, 0.8)',
            completed: '0 0 15px rgba(34, 197, 94, 0.8)',
            error: '0 0 15px rgba(239, 68, 68, 0.8)'
        };
        nodeEl.style.boxShadow = GLOW_MAP[status] || '';

        if (status === 'error') {
            console.error(`Node ${nodeId} Error: ${message}`);
        }

        // 树预览触发
        if (status === 'completed' && message.startsWith('Preview Ready::')) {
            const treePath = message.replace('Preview Ready::', '');
            this._renderTreePreview(nodeId, treePath);
        }

        // 更新状态文本
        const statusEl = document.getElementById(nodeId + '_status');
        if (statusEl) statusEl.textContent = message;
    }

    _renderTreePreview(nodeId, treePath) {
        const stageId = nodeId + '_stage';
        const statusId = nodeId + '_status';
        const stageEl = document.getElementById(stageId);
        const statusEl = document.getElementById(statusId);

        if (!stageEl) {
            console.error('[TreePreview] Stage element not found:', stageId);
            return;
        }

        if (statusEl) statusEl.textContent = 'Loading tree...';

        const readMethod = window.py_bridge
            ? (window.py_bridge.read_result_file || window.py_bridge.read_file)
            : null;

        if (readMethod) {
            readMethod(treePath, (newickContent) => {
                if (!newickContent || newickContent.trim() === '') {
                    if (statusEl) statusEl.textContent = 'Error: Empty tree file';
                    return;
                }
                this._renderTreeInStage(stageEl, statusEl, nodeId, newickContent);
            });
        } else {
            if (statusEl) statusEl.textContent = 'Tree at: ' + treePath;
        }
    }

    _renderTreeInStage(containerEl, statusEl, nodeId, newickContent) {
        if (typeof TreeEngine === 'undefined') {
            console.error('[TreePreview] TreeEngine not found');
            if (statusEl) statusEl.textContent = 'Error: TreeEngine not loaded';
            return;
        }

        try {
            containerEl.innerHTML = '';
            const containerId = nodeId + '_stage';
            const renderer = new TreeEngine.HybridRenderer(containerId);
            const model = new TreeEngine.TreeModel();

            if (!model.parse(newickContent)) {
                throw new Error('Parse failed');
            }

            const layout = new TreeEngine.LayoutEngine(model);
            layout.settings = {
                ...layout.settings,
                mode: 'rect',
                scaleX: 20,
                scaleY: 1,
                leafSpacing: 15,
                showLabels: true,
                fontSize: 10,
                centerOffset: 0
            };
            layout.calculateCoordinates();

            if (renderer.render) {
                renderer.render(model, layout);
                if (renderer.resize) renderer.resize();
            }

            const leafCount = model.getLeafCount ? model.getLeafCount() : '?';
            if (statusEl) statusEl.innerHTML = `<span style="color:green">✔ Loaded: ${leafCount} leaves</span>`;
        } catch (error) {
            console.error('[TreePreview] Render error:', error);
            if (statusEl) statusEl.textContent = 'Render error: ' + error.message;
        }
    }

    /**
     * 渲染侧边栏节点库
     * @param {Object} metadata - tools_metadata
     */
    _renderSidebar(metadata) {
        console.log('Rendering sidebar with metadata...', metadata);
        const sidebarContainer = document.getElementById('sidebar-library');
        if (!sidebarContainer || !metadata || !metadata.categories) {
            console.error('Cannot render sidebar: Missing container or categories metadata');
            return;
        }

        sidebarContainer.innerHTML = '';

        const CATEGORY_COLORS = {
            io: 'var(--pin-exec)',
            process: 'var(--accent)',
            convert: '#06b6d4',
            phylogeny: '#10b981',
            data: '#f59e0b',
            hmm: '#a855f7',
            blast_util: '#ef4444'
        };

        metadata.categories.sort((catA, catB) => {
            if (catA.id === 'io') return -1;
            if (catB.id === 'io') return 1;
            return 0;
        }).forEach(category => {
            const catGroup = document.createElement('div');
            catGroup.className = 'category-group' + (category.id === 'io' ? '' : ' collapsed');
            catGroup.id = `cat-${category.id}`;

            const header = document.createElement('div');
            header.className = 'category-header';
            if (category.id === 'io') {
                header.style.borderLeft = '4px solid var(--pin-exec)';
                header.style.background = 'rgba(245, 158, 11, 0.05)';
            }
            header.onclick = () => {
                catGroup.classList.toggle('collapsed');
            };

            const toggleIcon = document.createElement('span');
            toggleIcon.className = 'toggle-icon';
            toggleIcon.innerText = '▼';

            const title = document.createElement('span');
            title.dataset.i18n = category.nameKey;
            title.innerText = this.i18nService.t(category.nameKey);

            header.appendChild(toggleIcon);
            header.appendChild(title);

            const contentDiv = document.createElement('div');
            contentDiv.className = 'category-content';

            const tools = metadata.tools.filter(tool => tool.cat === category.id);
            tools.forEach(tool => {
                const item = document.createElement('div');
                item.className = 'library-item';
                item.draggable = true;
                item.dataset.id = tool.id;
                item.dataset.name = tool.name;
                item.ondragstart = (event) => event.dataTransfer.setData('node-type', tool.id);

                const color = CATEGORY_COLORS[category.id] || '#94a3b8';
                const localizedTitle = this.i18nService.t('node.title.' + tool.id);
                const displayName = (localizedTitle && localizedTitle !== 'node.title.' + tool.id)
                    ? localizedTitle : tool.name;

                item.innerHTML = `
                    <div style="width: 8px; height: 8px; border-radius: 50%; background: ${color};"></div>
                    <span data-i18n="node.title.${tool.id}">${displayName}</span>
                `;
                contentDiv.appendChild(item);
            });

            catGroup.appendChild(header);
            catGroup.appendChild(contentDiv);
            sidebarContainer.appendChild(catGroup);
        });
    }
}
