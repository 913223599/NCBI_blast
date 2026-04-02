/**
 * NodeFactory - 负责节点 DOM 的创建与组装
 * 
 * 职责：
 * 1. 管理节点模板 (NODE_TEMPLATES)
 * 2. 创建节点 DOM 结构
 * 3. 绑定基础事件 (Close, Drag, Wire)
 * 4. 记录创建操作的 Undo 历史
 */
class NodeFactory {
    constructor(container, undoManager, i18nManager, callbacks) {
        this.container = container;
        this.undoManager = undoManager;
        this.i18nManager = i18nManager;
        this.callbacks = callbacks || {};

        this.templates = {
            'fasta': {
                titleKey: 'node.title.fasta',
                category: 'io',
                content: `
                    <div class="node-hint" title="${this.i18nManager ? this.i18nManager.t('help.node.fasta') : 'Input FASTA sequence or load file'}">💡 粘贴序列或加载文件</div>
                    <div class="property-row" style="flex-direction:column; align-items:stretch; gap:5px;">
                        <textarea class="property-input" placeholder=">Sequence_ID\nATGC..." data-prop="sequence" 
                            style="width:100%; height:60px; font-family:monospace; font-size:0.7rem; background:rgba(0,0,0,0.3); border:1px solid var(--node-border); border-radius:4px; color:#fff; resize:none;"></textarea>
                        <div style="display:flex; gap:5px; align-items:center;">
                            <input class="property-input" type="text" placeholder="或从本地文件导入..." data-prop="path" style="flex:1">
                            <button class="browse-btn" onclick="requestNodeFile('{{ID}}', 'fasta')" title="Open FASTA File">📂</button>
                        </div>
                    </div>
                `,
                inputs: [],
                outputs: ['seq']
            },
            'export': {
                titleKey: 'node.title.export',
                category: 'io',
                content: `<div class="property-row"><label data-i18n="param.fmt">Format:</label><select class="property-input" data-prop="fmt"><option>Newick</option><option>PDF</option></select></div>`,
                inputs: ['tree'],
                outputs: []
            },
            'dist': {
                titleKey: 'node.title.dist',
                category: 'process',
                content: `<div class="property-row"><label data-i18n="param.method">Method:</label><select class="property-input" data-prop="method"><option>Jukes-Cantor</option><option>Kimura</option></select></div>
                          <div class="property-row"><label data-i18n="param.k">K-mer:</label><input class="property-input" type="number" value="20" data-prop="k" style="width: 60px;"></div>`,
                inputs: ['seq'],
                outputs: ['matrix']
            },
            'tree': {
                titleKey: 'node.title.makeDistTree',
                category: 'phylogeny',
                content: `<div class="node-description" data-i18n="help.node.makeDistTree">根据距离矩阵构建进化树，支持 Neighbor-Joining 及多种优化策略。</div>`,
                inputs: ['matrix', 'tree'],
                outputs: ['tree']
            },
            'fasta2dissim': {
                titleKey: 'node.title.fasta2dissim',
                category: 'convert',
                content: `<div class="node-description" data-i18n="help.node.fasta2dissim">计算多序列 FASTA 间的蛋白或核酸差异矩阵。</div>`,
                inputs: ['seq'],
                outputs: ['matrix']
            },
            'tree_preview': {
                titleKey: 'node.title.tree_preview',
                category: 'io',
                content: `
                    <div class="node-description" data-i18n="help.node.tree_preview">预览进化树文件内容 (Newick格式)。</div>
                    <div class="tree-workspace-root" style="width:100%; height:300px; position:relative; overflow:hidden; border:1px solid var(--node-border); border-radius:4px; background:#fff;">
                         <div id="{{ID}}_stage" style="width:100%; height:100%;"></div>
                    </div>
                    <div id="{{ID}}_status" style="font-size:0.7rem; color:#888; margin-top:4px; text-align:center;">Waiting for data...</div>`,
                inputs: ['tree'],
                outputs: []
            },
            'default': {
                titleKey: 'node.title.default',
                category: 'process',
                content: `<div class="property-label">Status</div><div style="font-size:0.7rem">Ready</div>`,
                inputs: ['in'],
                outputs: ['out']
            }
        };
    }

    /**
     * Load templates dynamically from metadata
     * @param {Object} metadata - tools_metadata.json content
     */
    setTemplates(metadata) {
        if (!metadata || !metadata.tools) return;

        metadata.tools.forEach(tool => {
            const helpKey = `help.node.${tool.id}`;
            const helpText = this.i18nManager ? this.i18nManager.t(helpKey) : `[${tool.id}]`;

            // Build parameters HTML
            let paramsHtml = '';
            if (tool.params && tool.params.length > 0) {
                const blacklist = ['qc', 'verbose', 'noprogress', 'profile', 'log', 'json', 'sigpipe', 'seed'];

                // Filter and take first 4 important params
                const importantParams = tool.params.filter(p => {
                    const pName = p.name.replace(/^-+/, '').toLowerCase();
                    return !blacklist.includes(pName);
                });

                if (importantParams.length > 0) {
                    paramsHtml = '<div class="node-params-grid">';
                    importantParams.slice(0, 4).forEach(p => {
                        const pNameRaw = p.name.replace(/^-+/, '');

                        // Use case-insensitive t() for name and description
                        const pNameKey = `param.${pNameRaw}`;
                        const pDescKey = `tip.${pNameRaw}`;

                        let pName = this.i18nManager ? this.i18nManager.t(pNameKey) : pNameRaw;
                        if (pName === pNameKey) pName = pNameRaw; // Fallback

                        const isBoolean = p.default === null;
                        const pVal = p.default !== null ? p.default : '';

                        let pDesc = this.i18nManager ? this.i18nManager.t(pDescKey) : p.desc;
                        if (pDesc === pDescKey) pDesc = p.desc; // Fallback

                        if (isBoolean) {
                            paramsHtml += `
                                <div class="param-row">
                                    <label data-i18n-help="${pDescKey}">${pName}:</label>
                                    <div class="checkbox-wrapper">
                                        <input type="checkbox" class="property-input" data-prop="${pNameRaw}">
                                    </div>
                                </div>`;
                        } else {
                            paramsHtml += `
                                <div class="param-row">
                                    <label data-i18n-help="${pDescKey}">${pName}:</label>
                                    <input type="text" class="property-input" data-prop="${pNameRaw}" value="${pVal}">
                                </div>`;
                        }
                    });
                    paramsHtml += '</div>';
                }
            }

            let toolInputs = tool.in || ['any'];
            // Patch: makeDistTree should always support an optional tree input
            if (tool.id === 'makeDistTree') {
                toolInputs = ['matrix', 'tree'];
            }

            this.templates[tool.id] = {
                titleKey: tool.nameKey || `node.title.${tool.id}`,
                name: tool.name,
                category: tool.cat || 'process',
                content: `
                    <div class="node-description" title="${helpText}">${helpText}</div>
                    ${paramsHtml}
                `,
                inputs: toolInputs,
                outputs: tool.out || ['any'],
                params: tool.params || []
            };
        });
    }

    createNode(type, x, y, id = null) {
        if (!id) id = 'node-' + Date.now();

        const div = document.createElement('div');
        div.className = 'node';
        div.style.left = x + 'px';
        div.style.top = y + 'px';
        div.id = id;
        div.dataset.type = type;

        const template = this.templates[type] || this.templates['default'];

        // Helper to generate Port HTML
        // Helper to map port name to data type for coloring
        const getPortDataType = (name) => {
            const n = name.toLowerCase();
            if (n === 'seq' || n.includes('fasta')) return 'seq';
            if (n === 'matrix' || n === 'dist') return 'matrix';
            if (n === 'tree' || n === 'phylo') return 'tree';
            if (n === 'report' || n === 'fmt' || n === 'pdf') return 'report';
            return 'default';
        };

        // Helper for rich tooltips
        const getPortDescription = (dataType) => {
            const map = {
                'seq': 'FASTA Sequence Data (.fasta, .fna)',
                'matrix': 'Distance Matrix (.dm)',
                'tree': 'Phylogenetic Tree (.nwk)',
                'report': 'Analysis Report (.txt, .pdf)',
                'default': 'Generic Data'
            };
            return map[dataType.toLowerCase()] || dataType;
        };

        // Helper to generate Port HTML
        const createPins = (names, portType) => names.map((name, i) => {
            const dataType = getPortDataType(name);
            const desc = getPortDescription(dataType);
            const role = portType === 'input' ? 'Accepts' : 'Provides';

            return `
            <div class="pin ${portType === 'output' ? 'output' : ''}" 
                 id="${id}::${portType === 'input' ? 'in' : 'out'}::${i}" 
                 data-port-type="${portType}"
                 data-data-type="${dataType}"
                 title="${role}: ${desc}">
                <div class="pin-circle"></div><span class="pin-label">${name}</span>
            </div>`;
        }).join('');

        // Use I18nManager if available, otherwise fallback to key
        const titleText = this.i18nManager ? this.i18nManager.t(template.titleKey) : template.titleKey;

        div.innerHTML = `
            <div class="node-header">
                <span data-i18n="${template.titleKey}">${titleText}</span>
                <span class="close-btn">×</span>
            </div>
            <div class="node-body">
                <div class="pins-column">${createPins(template.inputs, 'input')}</div>
                <div class="node-content">${template.content.replace(/{{ID}}/g, id)}</div>
                <div class="pins-column">${createPins(template.outputs, 'output')}</div>
            </div>
        `;

        // --- Bind Events (Decoupled from Global Scope) ---

        // 1. Close Button
        const closeBtn = div.querySelector('.close-btn');
        if (closeBtn && this.callbacks.onRemove) {
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent drag start
                this.callbacks.onRemove(id);
            });
        }

        // 2. Pins Wire Drag
        div.querySelectorAll('.pin').forEach(pin => {
            if (this.callbacks.onWireDrag) {
                pin.addEventListener('mousedown', (e) => {
                    // Prevent node drag inside the pin
                    // Logic must be handled by the callback or here?
                    // The standard logic: e.stopPropagation() is usually needed.
                    // But in our main code we had 'startWireDrag(event, id)'.
                    this.callbacks.onWireDrag(e, pin.id);
                });
            }
        });

        // 3. Make Draggable
        this.container.appendChild(div);
        if (this.callbacks.makeDraggable) {
            this.callbacks.makeDraggable(div);
        }

        // 4. Mutual Exclusivity: aa and unknown_strand are incompatible
        // (unknown_strand is for nucleotide sequences, aa is for amino acid sequences)
        const aaCheckbox = div.querySelector('input[data-prop="aa"]');
        const unknownStrandCheckbox = div.querySelector('input[data-prop="unknown_strand"]');

        if (aaCheckbox && unknownStrandCheckbox) {
            const syncMutualExclusion = (changedEl) => {
                if (aaCheckbox.checked) {
                    unknownStrandCheckbox.checked = false;
                    unknownStrandCheckbox.disabled = true;
                    unknownStrandCheckbox.closest('.param-row')?.classList.add('disabled-param');
                } else if (unknownStrandCheckbox.checked) {
                    aaCheckbox.checked = false;
                    aaCheckbox.disabled = true;
                    aaCheckbox.closest('.param-row')?.classList.add('disabled-param');
                } else {
                    unknownStrandCheckbox.disabled = false;
                    unknownStrandCheckbox.closest('.param-row')?.classList.remove('disabled-param');
                    aaCheckbox.disabled = false;
                    aaCheckbox.closest('.param-row')?.classList.remove('disabled-param');
                }

                // Trigger change event to notify other systems (like auto-save)
                // but only for the one that WASN'T the source of the event to avoid cycles
                if (changedEl === aaCheckbox) {
                    unknownStrandCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
                } else if (changedEl === unknownStrandCheckbox) {
                    aaCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
                }
            };

            aaCheckbox.addEventListener('change', () => syncMutualExclusion(aaCheckbox));
            unknownStrandCheckbox.addEventListener('change', () => syncMutualExclusion(unknownStrandCheckbox));

            // Initialize state based on current values
            syncMutualExclusion(null);
        }

        // 4. Undo Record
        if (this.undoManager) {
            this.undoManager.record({
                type: 'create',
                id: id,
                data: {
                    x: x,
                    y: y,
                    type: type,
                    properties: {} // 新节点初始属性为空
                }
            });
        }

        return div;
    }
}
