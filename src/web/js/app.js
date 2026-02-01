/**
 * Bio-Station WebOS Main Controller
 */

class WebOS {
    constructor() {
        this.currentView = 'dashboard';
        this.views = {};
        this.bridge = null;
        this.translations = {}; // UI translations
        this.init();
    }

    async init() {
        console.log("Bio-WebOS Initializing...");

        // Initialize QWebChannel
        if (typeof QWebChannel !== "undefined") {
            new QWebChannel(qt.webChannelTransport, (channel) => {
                this.bridge = channel.objects.py_bridge;
                window.py_bridge = this.bridge;
                console.log("Python Bridge Connected!");

                // Initialize Translations
                this.loadTranslations().then(() => {
                    this.onReady();
                });

                // Restore previous view if exists
                const lastView = localStorage.getItem('biostation_last_view');
                if (lastView && lastView !== 'dashboard') {
                    console.log("Restoring previous view:", lastView);
                    this.navigate(lastView);
                }
            });
        } else {
            console.warn("QWebChannel not found (Dev Mode?)");
            this.onReady();

            // Restore for dev mode too
            const lastView = localStorage.getItem('biostation_last_view');
            if (lastView && lastView !== 'dashboard') {
                this.navigate(lastView);
            }
        }

        // Bind Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const target = e.currentTarget.dataset.target;
                this.navigate(target);
            });
        });

        // Bind Dashboard Cards
        document.querySelectorAll('.dashboard-card').forEach(card => {
            card.addEventListener('click', (e) => {
                const target = e.currentTarget.dataset.target;
                this.navigate(target);
            });
        });

        // Initialize Settings Handlers
        this.initSettingsHandlers();

        // Initialize Custom Dropdowns
        if (window.CustomSelect) {
            window.CustomSelect.initAll();
        }

        // Listen for messages from IFrame (PostMessage API)
        window.addEventListener('message', (event) => {
            const data = event.data;
            if (data && data.type === 'request_file_load') {
                console.log("Received file load request via postMessage:", data.fileType);
                this.requestFile(data.fileType);
            }
            // Future expansion: handle other bridge calls via message
            else if (data && data.type === 'run_blast_job') {
                // Forward to bridge? For now just log
                console.log("Received run_blast_job request (Not implemented via msg yet)");
            }
        });
    }

    onReady() {
        // Notify Python host
        if (this.bridge && this.bridge.on_page_ready) {
            this.bridge.on_page_ready();
        }
    }

    navigate(viewId) {
        console.log(`Navigating to: ${viewId}`);

        // Update Sidebar
        document.querySelectorAll('.nav-item').forEach(item => {
            if (item.dataset.target === viewId) item.classList.add('active');
            else item.classList.remove('active');
        });

        // Update View Area
        document.querySelectorAll('.view-container').forEach(view => {
            view.classList.remove('active');
        });

        const targetView = document.getElementById(`${viewId}-view`);
        if (targetView) {
            targetView.classList.add('active');

            // Lazy Load iFrames
            const iframe = targetView.querySelector('iframe');
            if (iframe && !iframe.src && iframe.dataset.src) {
                console.log(`Lazy loading module: ${viewId}`);
                iframe.src = iframe.dataset.src;
            }

            // If settings view, load existing values
            if (viewId === 'settings') {
                this.loadSettings();
            }
        }

        this.currentView = viewId;
        localStorage.setItem('biostation_last_view', viewId);

        // Update header - but use mobile-friendly logic or translated values if available
        const titleEl = document.getElementById('page-title');
        if (titleEl) {
            const keys = {
                'dashboard': 'nav_dashboard',
                'tree': 'nav_phylogeny',
                'structure': 'nav_structure',
                'sra': 'nav_sra',
                'blast': 'nav_blast',
                'settings': 'nav_settings',
                'help': 'nav_help'
            };
            const key = keys[viewId];
            titleEl.innerText = key ? this.t(key) : viewId;
        }
    }

    // --- Settings Management ---

    initSettingsHandlers() {
        const navItems = document.querySelectorAll('.settings-nav-item[data-panel]');
        navItems.forEach(item => {
            item.addEventListener('click', () => {
                const panelId = item.getAttribute('data-panel');
                if (!panelId) return;

                // Toggle Active Nav
                navItems.forEach(ni => ni.classList.remove('active'));
                item.classList.add('active');

                // Toggle Active Panel
                document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
                const targetPanel = document.getElementById(`panel-${panelId}`);
                if (targetPanel) {
                    targetPanel.classList.add('active');
                }

                console.log(`Switched to settings panel: ${panelId}`);
            });
        });
    }

    async loadSettings() {
        if (!this.bridge) return;

        const statusEl = document.getElementById('settings-status');
        if (statusEl) statusEl.style.display = 'none';

        this.bridge.get_api_key('dashscope', (key) => {
            const input = document.getElementById('dashscope-api-key');
            if (input) {
                input.value = key || '';
                console.log("Settings loaded: DashScope API Key retrieved.");
            }
        });

        // Initialize/Refresh AI Model List
        this.refreshAIModelSelector();

        // Sync Language Selection
        if (this.bridge && this.bridge.get_ui_language) {
            this.bridge.get_ui_language((lang) => {
                const langSelect = document.getElementById('ui-language-select');
                if (langSelect) {
                    langSelect.value = lang || 'zh_CN';
                    // Manually trigger change for CustomSelect sync
                    langSelect.dispatchEvent(new Event('change'));
                }
            });
        }
    }

    /**
     * Refresh AI model selector and management list from backend
     */
    refreshAIModelSelector(force = false) {
        if (!this.bridge || !this.bridge.get_supported_ai_models) return;

        const select = document.getElementById('ai-model-select');
        if (!select) return;

        if (select.dataset.loaded && !force) {
            // Just sync current value if already list loaded
            if (this.bridge.get_current_ai_model) {
                this.bridge.get_current_ai_model((current) => {
                    if (current) select.value = current;
                });
            }
            return;
        }

        console.log("Refreshing AI model selector...");
        this.bridge.get_supported_ai_models((response) => {
            try {
                const models = JSON.parse(response);
                console.log("Received AI models from backend:", models);

                select.innerHTML = '';
                const listContainer = document.getElementById('ai-model-list');
                if (listContainer) listContainer.innerHTML = '';

                Object.entries(models).forEach(([key, name]) => {
                    // 1. Populate standard select
                    const opt = document.createElement('option');
                    opt.value = key;
                    opt.innerText = name;
                    select.appendChild(opt);

                    // 2. Populate Management List
                    if (listContainer) {
                        const item = document.createElement('div');
                        item.className = 'model-list-item';
                        item.style.cssText = 'padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); font-size: 0.85rem;';
                        item.innerHTML = `
                            <div>
                                <span style="font-weight: 600; color: var(--text-primary);">${name}</span>
                                <span style="color: var(--text-secondary); margin-left: 8px; font-family: monospace;">(${key})</span>
                            </div>
                            <button class="btn-icon" onclick="window.app.deleteAIModel('${key}')" title="移除此模型" style="width: 24px; height: 24px; padding: 0; border: none; background: transparent;">
                                <svg class="icon-svg" viewBox="0 0 24 24" style="width: 14px; height: 14px; color: var(--danger-color);"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                            </button>
                        `;
                        listContainer.appendChild(item);
                    }
                });

                select.dataset.loaded = "true";

                // Sync current selection
                if (this.bridge.get_current_ai_model) {
                    this.bridge.get_current_ai_model((current) => {
                        if (current) {
                            select.value = current;
                            // Critical: Dispatch change event to sync CustomSelect UI
                            select.dispatchEvent(new Event('change'));
                        }
                        if (window.CustomSelect) window.CustomSelect.initAll();

                        // If forced (manual refresh/add), scroll to bottom of the list
                        if (force && listContainer) {
                            setTimeout(() => {
                                listContainer.scrollTop = listContainer.scrollHeight;
                            }, 100);
                        }
                    });
                }
            } catch (e) {
                console.error("Failed to parse model list:", e);
            }
        });
    }

    async saveSettings() {
        if (!this.bridge) return;
        const key = document.getElementById('dashscope-api-key').value.trim();
        const modelSelect = document.getElementById('ai-model-select');
        const model = modelSelect ? modelSelect.value : '';
        console.log(`Saving settings: API Key (masked), Model: ${model}`);
        const statusEl = document.getElementById('settings-status');

        if (statusEl) {
            statusEl.innerText = "正在保存...";
            statusEl.style.color = "var(--primary-color)";
            statusEl.style.display = "block";
        }

        this.bridge.save_api_key('dashscope', key, (keySuccess) => {
            if (keySuccess) {
                // Key saved, now save model
                if (this.bridge.save_ai_model) {
                    this.bridge.save_ai_model(model, (modelSuccess) => {
                        if (statusEl) {
                            if (modelSuccess) {
                                statusEl.innerText = this.t('msg_config_saved');
                                statusEl.style.color = "var(--accent-color)";
                                // Pulse animation effect
                                const card = statusEl.closest('.glass-card');
                                if (card) {
                                    card.style.borderColor = "var(--accent-color)";
                                    setTimeout(() => card.style.borderColor = "", 2000);
                                }
                                // Critical: Dispatch change event to sync CustomSelect UI
                                if (modelSelect) modelSelect.dispatchEvent(new Event('change'));
                            } else {
                                statusEl.innerText = this.t('msg_save_failed_key_ok');
                                statusEl.style.color = "var(--warning-color)";
                            }
                            setTimeout(() => { statusEl.style.display = 'none'; }, 5000);
                        }
                    });
                } else {
                    if (statusEl) {
                        statusEl.innerText = "API Key 已保存 (模型切换不可用)";
                        statusEl.style.color = "var(--accent-color)";
                        setTimeout(() => { statusEl.style.display = 'none'; }, 5000);
                    }
                }
            } else {
                if (statusEl) {
                    statusEl.innerText = this.t('msg_save_failed');
                    statusEl.style.color = "var(--danger-color)";
                    setTimeout(() => { statusEl.style.display = 'none'; }, 5000);
                }
            }
        });
    }

    async addAIModel() {
        if (!this.bridge) return;
        const key = document.getElementById('new-model-key').value.trim();
        const name = document.getElementById('new-model-name').value.trim();

        if (!key || !name) {
            this.showNotification("请输入模型标识和名称", "warning");
            return;
        }

        const addBtn = document.querySelector('button[onclick="window.app.addAIModel()"]');
        const originalText = addBtn ? addBtn.innerHTML : '';
        if (addBtn) {
            addBtn.disabled = true;
            addBtn.innerHTML = '正在验证...';
        }

        // 1. Test the model first
        this.bridge.test_ai_model(key, (response) => {
            const result = JSON.parse(response);
            if (!result.success) {
                this.showNotification(`模型验证失败: ${result.message}`, "error");
                if (addBtn) {
                    addBtn.disabled = false;
                    addBtn.innerHTML = originalText;
                }
                return;
            }

            // 2. Add if validation passed
            this.bridge.add_ai_model(key, name, (success) => {
                // Keep loading state for a moment to be visible
                setTimeout(() => {
                    if (addBtn) {
                        addBtn.disabled = false;
                        addBtn.innerHTML = originalText;
                    }

                    if (success) {
                        this.showNotification(`模型 ${name} 已添加！\n${result.message}`, "success");
                        // Clear inputs
                        document.getElementById('new-model-key').value = '';
                        document.getElementById('new-model-name').value = '';

                        // Refresh list forcibly
                        this.refreshAIModelSelector(true);
                    } else {
                        this.showNotification("添加模型失败，请检查日志", "error");
                    }
                }, 500);
            });
        });
    }

    async deleteAIModel(key) {
        if (!this.bridge) return;
        if (!confirm(this.t('confirm_delete_model').replace('${key}', key))) return;

        this.bridge.delete_ai_model(key, (success) => {
            if (success) {
                this.showNotification("模型已移除", "info");
                // Refresh list forcibly
                this.refreshAIModelSelector(true);
            } else {
                this.showNotification("移除失败", "error");
            }
        });
    }

    // Public API for Python to call
    handleFileLoaded(content, type, path) {
        console.log(`JS Handle File: ${type} from ${path}`);

        if (type === 'tree') {
            this.navigate('tree');
            this.dispatchToIframe('tree-view', 'loadTree', content);
        } else if (type === 'structure') {
            this.navigate('structure');
            this.dispatchToIframe('structure-view', 'loadPDBData', content);
        } else if (type === 'fasta') {
            this.dispatchToIframe('blast-view', 'onFileSelected', { path: path, content: content });
        }
    }

    handleFilesDropped(paths) {
        console.log("Files dropped via Python interception:", paths);
        // Determine active view
        if (this.currentView === 'blast') {
            // For each file, trigger selection
            paths.forEach(path => {
                this.dispatchToIframe('blast-view', 'onFileSelected', { path: path }); // Content lazy loaded by backend if needed? No, backend needs path.
            });
        }
    }

    handleBridgeEvent(type, data) {
        console.log(`Bridge Event [${type}]:`, data);
        // Map types to viewers
        if (type.startsWith('blast_')) {
            this.dispatchToIframe('blast-view', 'onBlastEvent', { type, data });
        }
    }

    requestFile(type) {
        if (this.bridge) {
            console.log(`Requesting file load: ${type}`);
            this.bridge.request_file_load(type);
        } else {
            console.error("Bridge not connected");
        }
    }

    dispatchToIframe(viewId, funcName, data) {
        const view = document.getElementById(viewId);
        const iframe = view.querySelector('iframe');

        if (!iframe) return;

        const win = iframe.contentWindow;

        // Helper to execute
        const execute = () => {
            if (win && typeof win[funcName] === 'function') {
                console.log(`Dispatching ${funcName} to ${viewId}`);
                win[funcName](data);
            } else {
                console.error(`Function ${funcName} not found in ${viewId} iframe`);
            }
        };

        // Check if loaded
        if (iframe.contentDocument && iframe.contentDocument.readyState === 'complete') {
            execute();
        } else {
            console.log(`Waiting for ${viewId} iframe to load...`);
            iframe.onload = execute;
        }
    }
    // --- Dictionary Management ---

    async searchDictionary() {
        const queryInput = document.getElementById('dict-search-input');
        if (!queryInput) return;
        const query = queryInput.value.trim();
        if (!query) return;

        const resultsContainer = document.getElementById('dict-results');
        resultsContainer.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-secondary);"><svg class="icon-svg" viewBox="0 0 24 24" style="animation:spin 1s linear infinite; width:24px; height:24px;"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"></path></svg></div>';

        if (this.bridge && this.bridge.search_dictionary) {
            this.bridge.search_dictionary(query, (response) => {
                const results = JSON.parse(response);
                this.renderDictResults(results);
            });
        }
    }

    renderDictResults(results) {
        const container = document.getElementById('dict-results');
        container.innerHTML = '';

        if (results.length === 0) {
            container.innerHTML = `<div style="padding:40px; text-align:center; color:var(--text-secondary);">${this.t('msg_no_dict_results')}</div>`;
            return;
        }

        results.forEach(item => {
            const div = document.createElement('div');
            div.style.cssText = 'padding: 12px 14px; border-bottom: 1px solid #f1f5f9; background: rgba(255,255,255,0.8); display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; border-radius: 4px;';

            // Escape quotes for onclick
            const safeEng = item.english.replace(/'/g, "\\'");
            const safeChn = item.chinese.replace(/'/g, "\\'");

            div.innerHTML = `
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: var(--text-primary); font-size: 0.9rem;">${item.english}</div>
                    <div style="font-size: 0.85rem; color: var(--primary-color); margin-top: 2px;">${item.chinese}</div>
                    <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 2px;">
                        ${item.category || 'other'} • ${item.source || 'unknown'}
                    </div>
                </div>
                <button class="btn-icon" onclick="window.app.editTranslation('${safeEng}', '${safeChn}')" 
                        title="修改此条目" style="padding: 6px; border: 1px solid transparent; cursor: pointer;">
                    <svg class="icon-svg" viewBox="0 0 24 24" style="width: 16px; height: 16px; color: var(--primary-color);">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
            `;
            container.appendChild(div);
        });
    }

    editTranslation(english, chinese) {
        const engInput = document.getElementById('edit-english');
        const chnInput = document.getElementById('edit-chinese');
        if (engInput) engInput.value = english;
        if (chnInput) chnInput.value = chinese;

        const modal = document.getElementById('dict-edit-modal');
        if (modal) modal.style.display = 'block';
    }

    saveTranslation() {
        const engInput = document.getElementById('edit-english');
        const chnInput = document.getElementById('edit-chinese');

        if (!engInput || !chnInput) return;

        const english = engInput.value;
        const chinese = chnInput.value.trim();

        if (!chinese) {
            alert(this.t('msg_enter_translation'));
            return;
        }

        // Optimistic UI update
        const modal = document.getElementById('dict-edit-modal');
        const saveBtn = modal.querySelector('.btn-premium');
        const originalText = saveBtn.innerText;
        saveBtn.innerText = "Saving...";
        saveBtn.disabled = true;

        if (this.bridge && this.bridge.update_dictionary_entry) {
            this.bridge.update_dictionary_entry(english, chinese, (success) => {
                saveBtn.innerText = originalText;
                saveBtn.disabled = false;

                if (success) {
                    modal.style.display = 'none';
                    this.searchDictionary(); // Refresh list

                    // Show success status
                    this.showNotification(this.t('msg_translation_saved'), "success");
                } else {
                    this.showNotification(this.t('msg_update_failed'), "error");
                }
            });
        }
    }

    /**
     * Show global toast notification
     */
    showNotification(message, type = 'info', duration = 5000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        let iconHtml = '';
        if (type === 'error') iconHtml = '<svg class="icon-svg" style="color:var(--danger-color)" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
        else if (type === 'success') iconHtml = '<svg class="icon-svg" style="color:var(--accent-color)" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
        else iconHtml = '<svg class="icon-svg" style="color:var(--primary-color)" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';

        toast.innerHTML = `
            <div class="toast-icon">${iconHtml}</div>
            <div class="toast-content">${message}</div>
        `;

        container.appendChild(toast);

        // Auto remove
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    /**
     * Load translations from backend and apply to DOM
     */
    async loadTranslations() {
        if (!this.bridge || !this.bridge.get_ui_translations) {
            console.warn("Translation bridge not available.");
            return;
        }

        return new Promise((resolve) => {
            this.bridge.get_ui_translations((json) => {
                try {
                    this.translations = JSON.parse(json);
                    console.log("UI Translations loaded.");
                    this.applyTranslations();
                } catch (e) {
                    console.error("Failed to parse translations:", e);
                }
                resolve();
            });
        });
    }

    /**
     * Apply translations to all elements with data-i18n attribute
     */
    applyTranslations() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.t(key);
            if (translation !== key) {
                el.innerText = translation;
            }
        });

        // Handle placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translation = this.t(key);
            if (translation !== key) {
                el.placeholder = translation;
            }
        });

        // Handle titles
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translation = this.t(key);
            if (translation !== key) {
                el.title = translation;
            }
        });

        // Update current page title if active
        if (this.currentView) {
            this.navigate(this.currentView);
        }
    }

    /**
     * Translate a key
     */
    t(key) {
        return (this.translations && this.translations[key]) || key;
    }

    /**
     * Save UI Language selection
     */
    saveUILanguage() {
        const select = document.getElementById('ui-language-select');
        if (!select || !this.bridge) return;

        const lang = select.value;
        this.bridge.save_ui_language(lang, (success) => {
            if (success) {
                this.showNotification(lang === 'zh_CN' ? "语言设置已保存，正在重新加载..." : "Language saved, reloading...", "success");
                setTimeout(() => {
                    location.reload();
                }, 1000);
            } else {
                this.showNotification("Failed to save language.", "error");
            }
        });
    }
}

// Global Instance
window.app = new WebOS();

