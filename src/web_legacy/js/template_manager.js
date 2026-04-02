/**
 * WorkflowTemplateManager - Handles saving, loading and UI listing of workflow templates.
 * Enhanced to support hiding presets and overwriting existing templates.
 */
class WorkflowTemplateManager {
    constructor(canvas, topologyManager, linkSystem, i18n) {
        this.canvas = canvas;
        this.topologyManager = topologyManager;
        this.linkSystem = linkSystem;
        this.i18n = i18n;
        this.storageKey = 'bio_node_templates';
        this.modifiedPresetsKey = 'bio_node_modified_presets';
        this.hiddenPresetsKey = 'bio_node_hidden_presets';
        this.container = document.getElementById('sidebar-templates');

        // Built-in templates (Read-only source)
        this.presets = [
            {
                id: 'fast_bio_chain',
                nameKey: 'ui.template.fast_bio_chain_name',
                descKey: 'ui.template.fast_bio_chain_desc',
                data: {
                    nodes: [
                        { id: 'node-fasta', type: 'fasta', x: 2000, y: 2100, properties: { sequence: '', path: '' } },
                        { id: 'node-dissim', type: 'fasta2dissim', x: 2420, y: 2100, properties: { method: 'dna' } },
                        { id: 'node-make-tree', type: 'makeDistTree', x: 2840, y: 2100 },
                        { id: 'node-print-tree', type: 'printDistTree', x: 3260, y: 2100 }
                    ],
                    connections: [
                        { id: 'conn-1', source: 'node-fasta-out-0', target: 'node-dissim-in-0', type: 'seq' },
                        { id: 'conn-2', source: 'node-dissim-out-0', target: 'node-make-tree-in-0', type: 'matrix' },
                        { id: 'conn-3', source: 'node-make-tree-out-0', target: 'node-print-tree-in-0', type: 'tree' }
                    ]
                }
            }
        ];

        this.init();
    }

    init() {
        this.renderTemplates();
    }

    /**
     * Save current layout to a template
     * @param {string} name 
     * @param {string} overwriteId - If provided, overwrites the existing template
     */
    saveCurrent(name, overwriteId = null) {
        const top = this.topologyManager.getTopology();

        if (overwriteId) {
            // Check if it's a preset or custom
            const isPreset = this.presets.some(p => p.id === overwriteId);
            if (isPreset) {
                const modified = this.getModifiedPresets();
                modified[overwriteId] = {
                    id: overwriteId,
                    data: top,
                    timestamp: Date.now()
                };
                localStorage.setItem(this.modifiedPresetsKey, JSON.stringify(modified));
            } else {
                const templates = this.getSavedTemplates();
                const idx = templates.findIndex(t => t.id === overwriteId);
                if (idx !== -1) {
                    templates[idx].data = top;
                    templates[idx].timestamp = Date.now();
                    localStorage.setItem(this.storageKey, JSON.stringify(templates));
                }
            }
        } else {
            // New custom template
            const templates = this.getSavedTemplates();
            const newTemplate = {
                id: 'tpl-' + Date.now(),
                name: name,
                desc: `Custom template saved on ${new Date().toLocaleDateString()}`,
                data: top,
                isCustom: true,
                timestamp: Date.now()
            };
            templates.push(newTemplate);
            localStorage.setItem(this.storageKey, JSON.stringify(templates));
        }

        this.renderTemplates();
    }

    getSavedTemplates() {
        const stored = localStorage.getItem(this.storageKey);
        return stored ? JSON.parse(stored) : [];
    }

    getModifiedPresets() {
        const stored = localStorage.getItem(this.modifiedPresetsKey);
        return stored ? JSON.parse(stored) : {};
    }

    getHiddenPresets() {
        const stored = localStorage.getItem(this.hiddenPresetsKey);
        return stored ? JSON.parse(stored) : [];
    }

    loadTemplate(id) {
        let tpl = null;

        // 1. Check if it's a modified preset
        const modified = this.getModifiedPresets();
        if (modified[id]) {
            const original = this.presets.find(p => p.id === id);
            tpl = { ...original, ...modified[id] };
        }

        // 2. Check if it's a standard preset
        if (!tpl) {
            tpl = this.presets.find(p => p.id === id);
        }

        // 3. Check if it's a custom template
        if (!tpl) {
            const saved = this.getSavedTemplates();
            tpl = saved.find(s => s.id === id);
        }

        if (tpl) {
            this.topologyManager.clearCanvas();
            this.topologyManager.loadTopology(tpl.data);

            if (this.i18n) {
                const name = tpl.nameKey ? this.i18n.t(tpl.nameKey) : tpl.name;
                const msg = this.i18n.t('ui.msg.template_loaded') || 'Template {name} loaded';
                showToast(msg.replace('{name}', name));
            }
        }
    }

    deleteTemplate(id) {
        const isPreset = this.presets.some(p => p.id === id);
        if (isPreset) {
            // Hide preset
            const hidden = this.getHiddenPresets();
            if (!hidden.includes(id)) {
                hidden.push(id);
                localStorage.setItem(this.hiddenPresetsKey, JSON.stringify(hidden));
            }
            // Also remove its modifications if any
            const modified = this.getModifiedPresets();
            if (modified[id]) {
                delete modified[id];
                localStorage.setItem(this.modifiedPresetsKey, JSON.stringify(modified));
            }
        } else {
            // Delete custom template
            let templates = this.getSavedTemplates();
            templates = templates.filter(t => t.id !== id);
            localStorage.setItem(this.storageKey, JSON.stringify(templates));
        }
        this.renderTemplates();
    }

    renderTemplates(query = '') {
        if (!this.container) return;
        this.container.innerHTML = '';

        const q = query.toLowerCase();
        const hidden = this.getHiddenPresets();
        const modified = this.getModifiedPresets();

        // Show Presets (unless hidden)
        this.presets.forEach(p => {
            if (hidden.includes(p.id)) return;

            const name = this.i18n ? this.i18n.t(p.nameKey) : p.id;
            const desc = this.i18n ? this.i18n.t(p.descKey) : '';
            const isModified = !!modified[p.id];

            if (name.toLowerCase().includes(q) || desc.toLowerCase().includes(q)) {
                this.container.appendChild(this.createTemplateItem(p, name, desc, false, isModified));
            }
        });

        // Show Custom
        const saved = this.getSavedTemplates();
        saved.forEach(s => {
            if (s.name.toLowerCase().includes(q) || s.desc.toLowerCase().includes(q)) {
                this.container.appendChild(this.createTemplateItem(s, s.name, s.desc, true));
            }
        });

        if (this.container.innerHTML === '') {
            this.container.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-dim); font-size:0.8rem;" data-i18n="ui.template.no_templates">
                ${this.i18n ? this.i18n.t('ui.template.no_templates') : 'No templates found'}
            </div>`;
        }

        if (this.i18n && this.i18n.applyTranslations) {
            this.i18n.applyTranslations(this.container);
        }
    }

    createTemplateItem(tpl, name, desc, isCustom, isModified = false) {
        const div = document.createElement('div');
        div.className = 'library-item template-item';
        div.style.cursor = 'pointer';
        div.style.flexDirection = 'column';
        div.style.alignItems = 'flex-start';
        div.style.gap = '4px';
        div.style.position = 'relative';

        const tag = isCustom ? '<span class="tpl-tag custom">CUSTOM</span>' :
            (isModified ? '<span class="tpl-tag modified">PRESET*</span>' : '<span class="tpl-tag">PRESET</span>');

        div.innerHTML = `
            <div style="display:flex; width:100%; justify-content:space-between; align-items:flex-start">
                <div style="font-weight:600; color:var(--accent); font-size:0.85rem; padding-right:45px">${name}</div>
                <div class="tpl-actions">
                    <button class="tpl-action-btn overwrite" title="Overwrite with current layout">💾</button>
                    <button class="tpl-action-btn delete" title="Delete/Hide template">×</button>
                </div>
            </div>
            <div style="font-size:0.65rem; color:var(--text-dim); line-height:1.3; margin-top:2px">${desc}</div>
            <div style="margin-top:6px">${tag}</div>
        `;

        div.onclick = (e) => {
            if (e.target.classList.contains('delete')) {
                e.stopPropagation();
                if (confirm(this.i18n ? this.i18n.t('ui.confirm.delete_template') : "Delete this template?")) {
                    this.deleteTemplate(tpl.id);
                }
                return;
            }
            if (e.target.classList.contains('overwrite')) {
                e.stopPropagation();
                if (confirm(this.i18n ? this.i18n.t('ui.confirm.overwrite_template') : "Overwrite this template with current layout?")) {
                    this.saveCurrent(name, tpl.id);
                    showToast(this.i18n ? this.i18n.t('ui.msg.template_updated') : "Template updated");
                }
                return;
            }
            this.loadTemplate(tpl.id);
        };

        return div;
    }
}

