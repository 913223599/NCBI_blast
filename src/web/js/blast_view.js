/**
 * blast_view.js - BLAST Analysis Workbench Controller
 * Handles UI interactions, backend communication via QWebChannel, 
 * and data rendering for the BLAST view.
 */

class BlastViewController {
    constructor() {
        this.currentTaskId = null;
        this.selectedFiles = [];
        this.currentDetailXml = null;
        this.localBridge = null;
        this.pollingInterval = null;

        // DOM References
        this.dom = {
            workbench: document.getElementById('workbench'),
            taskList: document.getElementById('task-list'),
            resultBody: document.getElementById('result-body'),
            emptyState: document.getElementById('empty-state'),
            queryInput: document.getElementById('query-input'),
            progSelect: document.getElementById('prog-select'),
            dbSelect: document.getElementById('db-select'),
            evalueInput: document.getElementById('evalue-input'),
            hitsInput: document.getElementById('hits-input'),
            matrixSelect: document.getElementById('matrix-select'),
            gapOpen: document.getElementById('gap-open'),
            gapExtend: document.getElementById('gap-extend'),
            filterCheck: document.getElementById('filter-check'),
            threadsInput: document.getElementById('threads-input'),
            runBtn: document.getElementById('run-btn'),
            dropZone: document.getElementById('file-drop-area'),
            fileSummary: document.getElementById('selected-files-summary'),
            detailOverlay: document.getElementById('detail-overlay'),
            detailTitle: document.getElementById('detail-title'),
            detailSubtitle: document.getElementById('detail-subtitle'),
            detailBody: document.getElementById('detail-body'),
            dictOverlay: document.getElementById('edit-trans-overlay'),
            dictSource: document.getElementById('edit-source-text'),
            dictTarget: document.getElementById('edit-target-text'),
            dictTab: document.getElementById('dict-tab'),
            dictSearchInput: document.getElementById('dict-search-input'),

            dictResults: document.getElementById('dict-results'),


            // New Input Refs
            tabFile: document.getElementById('tab-file'),
            tabText: document.getElementById('tab-text'),
            modeFile: document.getElementById('mode-file'),
            modeText: document.getElementById('mode-text'),
            fileListScroll: document.getElementById('file-list-scroll'),
            fileCountBadge: document.getElementById('file-count-badge')
        };

        this.inputMode = 'file'; // 'file' | 'text'
        this.translations = {};
    }

    /**
     * Translation Helper
     */
    t(key) {
        return this.translations[key] || key;
    }

    async init() {
        console.log("Initializing BlastViewController...");
        await this.initBridge();
        this.initDragDrop();
        this.restoreParams();

        // Initialize Custom Dropdowns
        if (window.CustomSelect) {
            window.CustomSelect.initAll();
        }

        // Initialize Help Tooltips
        if (window.HelpTooltipManager) {
            window.HelpTooltipManager.init();
        }

        // Initial data load
        if (this.localBridge) {
            setTimeout(() => this.refreshTasks(), 500);
        }
    }

    /**
     * Initialize QWebChannel for direct Python backend communication
     */
    initBridge() {
        return new Promise((resolve) => {
            const setupBridge = (transport) => {
                new QWebChannel(transport, (channel) => {
                    this.localBridge = channel.objects.py_bridge;
                    console.log("IFrame Direct Bridge Connected!", this.localBridge);
                    this.onBridgeReady();
                    resolve(this.localBridge);
                });
            };

            // 1. Try immediate local transport
            if (typeof qt !== "undefined" && qt.webChannelTransport) {
                setupBridge(qt.webChannelTransport);
            }
            // 2. Fallback: Search for transport with retries
            // 2. Fallback: Search for transport with retries
            else {
                console.warn("Qt webChannelTransport not found. Retrying...");

                // Immediate check for parent bridge (Fast Path for IFrame)
                if (window.parent && window.parent.py_bridge) {
                    this.localBridge = window.parent.py_bridge;
                    console.log("Found parent py_bridge immediately.");
                    this.localBridge.blast_event.connect((type, data) => {
                        console.log(`Bridge Event: ${type}`, data);
                        if (type === 'status_update') {
                            const status = JSON.parse(data);
                            this.refreshTasks();
                        } else if (type === 'deletion_failed') {
                            const payload = JSON.parse(data);
                            this.showDeletionFailureDialog(payload.task_id, payload.path);
                        } else if (type === 'batch_deletion_failed') {
                            const payload = JSON.parse(data);
                            this.showBatchDeletionFailureDialog(payload.failed_list);
                        } else if (type === 'single_result_update') {
                            const payload = JSON.parse(data);
                            if (payload.task_id === this.currentTaskId) {
                                this.appendResultRow(payload.result);
                            }
                            // Also trigger refresh for task list counts
                            this.refreshTasks();
                        }
                    });
                    this.onBridgeReady();
                    resolve(this.localBridge);
                    return;
                }

                let retries = 0;
                const interval = setInterval(() => {
                    retries++;
                    if (typeof qt !== "undefined" && qt.webChannelTransport) {
                        clearInterval(interval);
                        setupBridge(qt.webChannelTransport);
                    }
                    // Check parent every tick
                    else if (window.parent && window.parent.py_bridge) {
                        clearInterval(interval);
                        this.localBridge = window.parent.py_bridge;
                        console.log("Connected to parent py_bridge.");
                        this.onBridgeReady();
                        resolve(this.localBridge);
                    }
                    else if (retries > 30) { // 3 seconds timeout
                        clearInterval(interval);
                        console.error("Local Bridge initialization timed out.");
                        resolve(this.localBridge);
                    }
                }, 100);
            }
        });
    }

    onBridgeReady() {
        if (this.localBridge) {
            this.refreshTasks();
            this.loadTranslations();
        }
    }

    /**
     * Load translations from backend
     */
    async loadTranslations() {
        if (!this.localBridge || !this.localBridge.get_ui_translations) return;
        this.localBridge.get_ui_translations((json) => {
            try {
                this.translations = JSON.parse(json);
                console.log("IFrame Translations loaded.");
                this.applyTranslations();
            } catch (e) {
                console.error("Failed to parse translations in iframe:", e);
            }
        });
    }

    /**
     * Apply translations to DOM
     */
    applyTranslations() {
        if (!this.translations) return;
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.translations[key] || key;
            if (translation !== key) {
                el.innerText = translation;
            }
        });

        // Handle placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translation = this.translations[key] || key;
            if (translation !== key) {
                el.placeholder = translation;
            }
        });

        // Handle titles
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translation = this.translations[key] || key;
            if (translation !== key) {
                el.title = translation;
            }
        });

        // Sync Help Tooltips
        if (window.HelpTooltipManager && window.__helpTooltipManager) {
            window.__helpTooltipManager.updateTranslations(this.translations);
        }
    }

    /**
     * UI Toggle: History Panel
     */
    toggleHistory() {
        this.dom.workbench.classList.toggle('history-collapsed');
        if (!this.dom.workbench.classList.contains('history-collapsed')) {
            this.refreshTasks();
        }
    }

    /**
     * BLAST Parameters Management
     */
    updateDBOptions() {
        if (!this.translations) return;
        const prog = this.dom.progSelect.value;
        const currentDb = this.dom.dbSelect.value;
        this.dom.dbSelect.innerHTML = '';

        const addOpt = (textKey, value, defaultText) => {
            const text = this.translations[textKey] || defaultText;
            const opt = new Option(text, value);
            opt.setAttribute('data-i18n', textKey);
            this.dom.dbSelect.add(opt);
        };

        // Biological Map:
        // blastp, blastx -> Protein DBs
        // blastn, tblastn, auto -> Nucleotide DBs
        if (prog === 'blastp' || prog === 'blastx') {
            addOpt('db_nr', 'nr', 'nr - Non-redundant protein sequences');
            addOpt('db_refseq_protein', 'refseq_protein', 'refseq_protein - Reference proteins');
            addOpt('db_swissprot', 'swissprot', 'swissprot - Last release');
        } else {
            addOpt('db_nt', 'nt', 'nt - Nucleotide collection');
            addOpt('db_refseq_rna', 'refseq_rna', 'refseq_rna - Reference RNA');
            addOpt('db_refseq_genomic', 'refseq_genomic', 'refseq_genomic - Reference genomic');
        }

        // Restore DB if valid
        for (let i = 0; i < this.dom.dbSelect.options.length; i++) {
            if (this.dom.dbSelect.options[i].value === currentDb) {
                this.dom.dbSelect.selectedIndex = i;
                break;
            }
        }

        // Refresh CustomSelect if available
        if (window.CustomSelect && window.CustomSelect.sync) {
            window.CustomSelect.sync(this.dom.dbSelect);
        }
        this.saveParams();
    }

    saveParams() {
        const params = {
            prog: this.dom.progSelect.value,
            db: this.dom.dbSelect.value,
            evalue: this.dom.evalueInput.value,
            hits: this.dom.hitsInput.value,
            matrix: this.dom.matrixSelect.value,
            gapOpen: this.dom.gapOpen.value,
            gapExtend: this.dom.gapExtend.value,
            filter: this.dom.filterCheck.checked,
            threads: this.dom.threadsInput ? this.dom.threadsInput.value : '4'
        };
        localStorage.setItem('blast_params', JSON.stringify(params));
    }

    restoreParams() {
        const stored = localStorage.getItem('blast_params');
        if (!stored) return;

        try {
            const params = JSON.parse(stored);
            if (params.prog) this.dom.progSelect.value = params.prog;
            this.updateDBOptions();
            if (params.db) this.dom.dbSelect.value = params.db;
            if (params.evalue) this.dom.evalueInput.value = params.evalue;
            if (params.hits) this.dom.hitsInput.value = params.hits;
            if (params.matrix) this.dom.matrixSelect.value = params.matrix;
            if (params.gapOpen) this.dom.gapOpen.value = params.gapOpen;
            if (params.gapExtend) this.dom.gapExtend.value = params.gapExtend;
            if (params.filter !== undefined) this.dom.filterCheck.checked = params.filter;
            if (params.threads && this.dom.threadsInput) this.dom.threadsInput.value = params.threads;
        } catch (e) {
            console.error("Failed to restore params:", e);
        }
    }

    /**
     * Task Management
     */
    refreshTasks() {
        if (!this.localBridge) return;
        this.localBridge.get_all_tasks((response) => {
            try {
                const tasks = JSON.parse(response);
                this.renderTaskList(tasks);
                this.checkPollingStatus(tasks);
            } catch (e) {
                console.error("Error parsing tasks:", e);
            }
        });
    }

    checkPollingStatus(tasks) {
        const hasActive = tasks.some(t => t.status === 'running' || t.status === 'pending');
        if (hasActive) {
            this.startPolling();
        } else {
            this.stopPolling();
        }
    }

    startPolling() {
        if (this.pollingInterval) return;
        console.log("Starting task polling...");
        this.pollingInterval = setInterval(() => {
            if (this.localBridge) {
                this.localBridge.get_all_tasks((response) => {
                    try {
                        const tasks = JSON.parse(response);
                        this.renderTaskList(tasks);
                        this.checkPollingStatus(tasks);
                    } catch (e) { console.error(e); }
                });
            }
        }, 2000);
    }

    stopPolling() {
        if (this.pollingInterval) {
            console.log("Stopping task polling.");
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    clearHistory() {
        if (!confirm("确定要永久清除所有分析历史吗?")) return;
        if (this.localBridge) {
            this.localBridge.clear_all_history();
            this.currentTaskId = null;
            this.dom.resultBody.innerHTML = '';
            this.dom.emptyState.classList.remove('hidden');
            this.refreshTasks();
        }
    }

    deleteTask(event, taskId) {
        if (event) event.stopPropagation();
        if (!confirm(this.t('confirm_delete_task')?.replace('${id}', taskId) || `确定要删除记录 ${taskId} 吗?`)) return;
        if (this.localBridge) {
            this.localBridge.delete_single_task(taskId);
            if (this.currentTaskId === taskId) {
                this.currentTaskId = null;
                this.dom.resultBody.innerHTML = '';
                this.dom.emptyState.classList.remove('hidden');
            }
            this.refreshTasks();
        }
    }

    showDeletionFailureDialog(taskId, path) {
        BioDialog.show({
            title: this.t('title_deletion_failed') || "删除物理目录失败",
            message: this.t('msg_deletion_failed_desc')?.replace('${path}', path) ||
                `由于文件正在被其他程序占用，无法自动删除该任务的结果文件夹。该条记录已保留在列表中。`,
            choices: [
                { id: 'open', text: this.t('btn_open_folder') || "打开所在目录", type: 'btn-primary' },
                { id: 'close', text: this.t('btn_close') || "关闭提示", type: 'btn-secondary' }
            ],
            onSelect: (choiceId) => {
                if (choiceId === 'open' && this.localBridge) {
                    this.localBridge.open_results_dir(path);
                }
            }
        });
    }

    showBatchDeletionFailureDialog(failedList) {
        const count = failedList.length;
        BioDialog.show({
            title: this.t('title_batch_deletion_failed') || "部分目录清理受阻",
            message: (this.t('msg_batch_deletion_failed_desc') ||
                `在尝试清空历史时，有 ${count} 个项目的文件夹因被占用而未能删除。相关记录已在列表中保留。`)
                .replace('${count}', count),
            choices: [
                { id: 'open', text: this.t('btn_open_results') || "打开结果根目录", type: 'btn-primary' },
                { id: 'close', text: this.t('btn_close') || "关闭提示", type: 'btn-secondary' }
            ],
            onSelect: (choiceId) => {
                if (choiceId === 'open' && this.localBridge && failedList.length > 0) {
                    // Open the parent results dir
                    const parentDir = failedList[0].split(/[/\\]/).slice(0, -1).join('/');
                    this.localBridge.open_results_dir(parentDir);
                }
            }
        });
    }

    renderTaskList(tasks) {
        this.taskListData = tasks;
        this.dom.taskList.innerHTML = '';
        tasks.forEach(task => {
            const div = document.createElement('div');
            div.className = `task-item ${task.task_id === this.currentTaskId ? 'active' : ''}`;
            div.onclick = () => this.loadTask(task.task_id);

            const time = new Date(task.start_time).toLocaleString('zh-CN', {
                month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
            });
            const statusDot = `<span class="status-dot status-${task.status}"></span>`;

            let actionBtns = '';
            if (task.status === 'running') {
                actionBtns = `
                    <button class="btn-task-action" title="暂停" onclick="window.blastView.pauseTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
                    </button>
                    <button class="btn-task-action btn-stop" title="停止" onclick="window.blastView.stopTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                    </button>
                `;
            } else if (task.status === 'paused') {
                actionBtns = `
                    <button class="btn-task-action" style="color:var(--accent); border-color:var(--accent);" title="继续" onclick="window.blastView.resumeTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                    </button>
                    <button class="btn-task-action btn-stop" title="停止" onclick="window.blastView.stopTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                    </button>
                `;
            } else if (['cancelled', 'error', 'failed', 'completed'].includes(task.status)) {
                let resumeBtn = '';
                if (['cancelled', 'error', 'failed'].includes(task.status)) {
                    resumeBtn = `
                        <button class="btn-task-action" title="${this.t('btn_resume')}" onclick="window.blastView.resumeTask(event, '${task.task_id}')">
                            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M5 3l14 9-14 9V3z"/></svg>
                        </button>
                    `;
                }
                actionBtns = `
                    ${resumeBtn}
                    <button class="btn-task-action" title="重试" onclick="window.blastView.retryTask(event, '${task.task_id}')">
                         <svg class="icon-svg" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/></svg>
                    </button>
                    <button class="btn-task-action btn-stop" title="删除记录" onclick="window.blastView.deleteTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                `;
            } else {
                // Default or unknown state
                actionBtns = `
                    <button class="btn-task-action btn-stop" title="删除记录" onclick="window.blastView.deleteTask(event, '${task.task_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                 `;
            }

            div.innerHTML = `
                <div class="task-status-bar">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        ${statusDot}
                        <span class="task-id">${task.task_id}</span>
                    </div>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">
                    ${time} • ${task.progress}% ${this.getStatusLabel(task.status)}
                </div>
                <div class="task-actions">
                    ${actionBtns}
                </div>
            `;
            this.dom.taskList.appendChild(div);
        });
    }

    getStatusLabel(status) {
        const labels = {
            'running': '运行中',
            'paused': '已暂停',
            'cancelled': '已取消',
            'completed': '已完成',
            'error': '错误',
            'failed': '失败'
        };
        return labels[status] || status;
    }

    stopTask(event, taskId) {
        if (event) event.stopPropagation();
        if (this.localBridge && confirm("确定要终止该分析任务吗?")) {
            this.localBridge.stop_blast_job(taskId);
            setTimeout(() => this.refreshTasks(), 200);
        }
    }

    pauseTask(event, taskId) {
        if (event) event.stopPropagation();
        if (this.localBridge) {
            this.localBridge.pause_blast_job(taskId);
            setTimeout(() => this.refreshTasks(), 200);
        }
    }

    resumeTask(event, taskId) {
        if (event) event.stopPropagation();
        if (this.localBridge) {
            this.localBridge.resume_blast_job(taskId);
            setTimeout(() => this.refreshTasks(), 200);
        }
    }

    resumeTask(event, taskId) {
        if (event) event.stopPropagation();
        if (this.localBridge) {
            this.localBridge.resume_task(taskId);
        }
    }

    retryTask(event, taskId) {
        if (event) event.stopPropagation();

        const task = this.taskListData.find(t => t.task_id === taskId);
        if (!task || !task.params) {
            alert(this.t('msg_no_params') || "无法读取任务参数");
            return;
        }

        let historicParams = {};
        try {
            historicParams = JSON.parse(task.params);
        } catch (e) {
            console.error("Params parse error", e);
        }

        BioDialog.show({
            title: this.t('title_retry_task'),
            message: this.t('msg_retry_choice'),
            choices: [
                { id: 'history', text: this.t('btn_retry_history'), type: 'btn-primary' },
                { id: 'current', text: this.t('btn_retry_current'), type: 'btn-secondary' },
                { id: 'cancel', text: this.t('btn_cancel'), type: 'btn-ghost' }
            ],
            onSelect: (choiceId) => {
                if (choiceId === 'history') {
                    this.restoreTaskParams(historicParams);
                    setTimeout(() => this.launchBlast(), 100);
                } else if (choiceId === 'current') {
                    // Directly use current page settings
                    this.launchBlast();
                }
            }
        });
    }

    restoreTaskParams(params) {
        // 1. Inputs
        if (params.files && params.files.length > 0) {
            this.selectedFiles = params.files;
            this.renderFileList();
            this.switchInputMode('file');
        } else {
            this.dom.queryInput.value = params.query || "";
            this.switchInputMode('text');
        }

        // 2. Options
        if (params.program) this.dom.progSelect.value = params.program;
        if (params.database) this.dom.dbSelect.value = params.database;
        if (params.evalue) this.dom.evalueInput.value = params.evalue;
        if (params.hitlist_size) this.dom.hitsInput.value = params.hitlist_size;

        // Advanced
        if (params.matrix_name) this.dom.matrixSelect.value = params.matrix_name;
        if (params.gap_open) this.dom.gapOpen.value = params.gap_open;
        if (params.gap_extend) this.dom.gapExtend.value = params.gap_extend;
        this.dom.filterCheck.checked = !!params.filter;
    }

    async loadTask(taskId) {
        this.currentTaskId = taskId;
        document.querySelectorAll('.task-item').forEach(el => el.classList.remove('active'));
        this.refreshTasks();

        this.dom.emptyState.classList.add('hidden');
        this.dom.resultBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px;">正在加载结果...</td></tr>`;

        if (this.localBridge) {
            this.localBridge.get_task_results(taskId, (response) => {
                try {
                    const results = JSON.parse(response);
                    this.renderResults(results);
                } catch (e) { console.error("Error loading task:", e); }
            });
        }
    }

    /**
     * Launch BLAST Job
     */
    async launchBlast() {
        console.log("Launch BLAST requested. Mode:", this.inputMode);

        // Data Collection based on Mode
        let queryData = "";
        let targetFiles = [];

        if (this.inputMode === 'text') {
            queryData = this.dom.queryInput.value.trim();
            if (!queryData) {
                alert(this.translations['msg_enter_fasta'] || "请先输入 FASTA 序列");
                return;
            }
        } else {
            // File Mode
            if (this.selectedFiles.length === 0) {
                alert(this.translations['msg_no_files'] || "请至少添加一个 FASTA 文件");
                return;
            }
            targetFiles = this.selectedFiles;
        }

        const params = {
            query: queryData,
            files: targetFiles,
            program: this.dom.progSelect.value,
            database: this.dom.dbSelect.value,
            evalue: parseFloat(this.dom.evalueInput.value),
            hitlist_size: parseInt(this.dom.hitsInput.value),
            matrix_name: this.dom.matrixSelect.value,
            gap_open: parseInt(this.dom.gapOpen.value),
            gap_extend: parseInt(this.dom.gapExtend.value),
            filter: this.dom.filterCheck.checked,
            max_workers: parseInt(this.dom.threadsInput ? this.dom.threadsInput.value : '4')
        };

        this.dom.runBtn.disabled = true;
        this.dom.runBtn.innerHTML = `<svg class="icon-svg fa-spin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><path d="M12 6v6l4 2"></path></svg> ${this.translations['blast_running'] || '任务启动中...'}`;

        if (!this.localBridge) {
            alert("Bridge not connected. Cannot launch.");
            this.dom.runBtn.disabled = false;
            return;
        }

        this.localBridge.run_blast_job(JSON.stringify(params), (response) => {
            const res = JSON.parse(response);
            if (res.status === 'started') {
                this.currentTaskId = res.task_id;
                this.dom.resultBody.innerHTML = '';
                this.dom.emptyState.classList.add('hidden');
                this.refreshTasks();
            } else {
                alert((this.translations['msg_start_failed'] || "启动失败: ") + res.error);
            }
            this.dom.runBtn.disabled = false;
            this.dom.runBtn.innerHTML = `<svg class="icon-svg" viewBox="0 0 24 24" style="width: 14px; height: 14px; margin-right: 4px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> <span data-i18n="blast_btn_run">${this.translations['blast_btn_run'] || '开始分析'}</span>`;
        });
    }

    /**
     * Incremental Result Rendering
     */
    appendResultRow(res) {
        // If it was empty state, clear it
        if (this.dom.resultBody.querySelector('td[colspan]')) {
            this.dom.resultBody.innerHTML = '';
            this.dom.emptyState.classList.add('hidden');
        }

        // Check if row already exists (prevent duplicates during resumption sync)
        if (this.dom.resultBody.querySelector(`tr[data-seq-id="${res.sequence_id}"]`)) {
            return;
        }

        const row = document.createElement('tr');
        row.setAttribute('data-seq-id', res.sequence_id);
        this._fillRowContent(row, res);
        this.dom.resultBody.appendChild(row);
    }

    /**
     * Result Rendering (Full)
     */
    renderResults(results) {
        this.dom.resultBody.innerHTML = '';
        if (!results || results.length === 0) {
            this.dom.resultBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px;">${this.translations['msg_no_results'] || '暂无比对数据'}</td></tr>`;
            this.dom.emptyState.classList.remove('hidden');
            return;
        }

        results.forEach(res => {
            const row = document.createElement('tr');
            row.setAttribute('data-seq-id', res.sequence_id);
            this._fillRowContent(row, res);
            this.dom.resultBody.appendChild(row);
        });
    }

    _fillRowContent(row, res) {
        const bestHit = res.data?.[0] || {};
        const metaParts = [];
        if (bestHit.genus && bestHit.genus !== 'N/A') metaParts.push(bestHit.genus);
        if (bestHit.strain) metaParts.push(bestHit.strain);
        if (bestHit.gene_type) metaParts.push(`<span style="color:var(--primary); opacity:0.8">${bestHit.gene_type}</span>`);
        const metaLine = metaParts.length > 0 ? `<div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">${metaParts.join(' • ')}</div>` : '';
        const bgInfo = [];
        if (bestHit.host) bgInfo.push(`宿主: ${bestHit.host}`);
        if (bestHit.seq_type) bgInfo.push(bestHit.seq_type);
        const similarityVal = parseFloat(bestHit.similarity) || 0;
        const badgeColor = similarityVal > 99 ? 'background: #ecfdf5; color: #065f46; border: 1px solid #ccfbf1;' : 'background: #f8fafc; color: #475569; border: 1px solid #e2e8f0;';

        row.innerHTML = `
            <td style="font-weight: 500; font-size: 0.8rem; color: var(--text-muted);">${res.sequence_id}</td>
            <td>
                <div class="species-name" style="font-weight: 700; color: var(--text-main); font-size: 0.85rem;" data-english="${bestHit.species}">${bestHit.species || '未知物种'}</div>
                <div class="translated-name" style="font-size: 0.75rem; color: var(--primary); font-weight: 500; margin-top: 2px; display: none;"></div>
                ${metaLine}
            </td>
            <td style="font-size: 0.82rem; color: #64748b;">${bgInfo.join(' | ') || '--'}</td>
            <td><span class="badge" style="${badgeColor}">${bestHit.similarity || '0%'}</span></td>
            <td style="font-family: 'Fira Code', monospace; font-size: 0.85rem; color: var(--text-main);">${bestHit.evalue || '--'}</td>
            <td style="font-family: 'Fira Code', monospace; font-size: 0.8rem; color: var(--primary); font-weight: 500;">${bestHit.acc || '--'}</td>
            <td>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <button class="btn-icon translate-row-btn" title="AI 翻译物种名" onclick="window.blastView.translateRow(this, '${bestHit.species}')" style="opacity: 0.6;">
                        <svg class="icon-svg" viewBox="0 0 24 24" style="width: 15px; height: 15px;"><path d="M5 8l6 6"></path><path d="M4 14l6-6 2-3"></path><path d="M2 5h12"></path><path d="M22 22l-5-10-5 10"></path><path d="M14 18h6"></path></svg>
                    </button>
                    <button class="btn-icon" title="查看比对详情" onclick="window.blastView.viewDetail('${res.csv_file}', '${res.xml_file}', '${res.sequence_id}')">
                        <svg class="icon-svg" viewBox="0 0 24 24" style="width: 18px; height: 18px;"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                    </button>
                </div>
            </td>
        `;
    }

    /**
     * Alignment Detail View
     */
    viewDetail(csvPath, xmlPath, seqId) {
        this.currentDetailXml = xmlPath;
        this.dom.detailTitle.innerText = `${this.translations['detail_title_prefix'] || '序列比对详情'}: ${seqId}`;
        this.dom.detailSubtitle.innerText = "正在拉取完整命中全谱...";
        this.dom.detailBody.innerHTML = `<div style="text-align:center; padding:100px; color:#cbd5e1;"><i class="fas fa-circle-notch fa-spin fa-2x"></i></div>`;
        this.dom.detailOverlay.classList.add('active');

        if (this.localBridge && this.localBridge.get_detailed_blast_results) {
            this.localBridge.get_detailed_blast_results(csvPath, (response) => {
                try {
                    const hits = JSON.parse(response);
                    this.renderDetailHits(hits);
                } catch (e) { console.error("Error detail results:", e); }
            });
        }
    }

    closeDetail() { this.dom.detailOverlay.classList.remove('active'); }

    triggerVisualizer() {
        if (this.currentDetailXml && this.localBridge?.open_alignment_visualizer) {
            this.localBridge.open_alignment_visualizer(this.currentDetailXml);
        }
    }

    renderDetailHits(hits) {
        this.dom.detailBody.innerHTML = '';
        this.dom.detailSubtitle.innerText = `共找到 ${hits.length} 个显著匹配记录`;
        hits.forEach((hit, idx) => {
            const sim = parseFloat(hit.similarity) || 0;
            const card = document.createElement('div');
            card.className = 'hit-card';
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="font-weight: 700; color: var(--primary); font-size: 0.95rem;">命中记录 #${idx + 1}: ${hit.species || '未知'}</div>
                    <span class="badge" style="background: ${sim > 90 ? '#ecfdf5' : '#f8fafc'}; color: ${sim > 90 ? '#065f46' : '#64748b'}; border: 1px solid ${sim > 90 ? '#ccfbf1' : '#e2e8f0'};">精度: ${hit.similarity}</span>
                </div>
                <div style="font-size: 0.82rem; color: #475569; margin-bottom: 15px; border-left: 3px solid #e2e8f0; padding-left: 10px; line-height: 1.4;">${hit.title}</div>
                <div class="stat-grid">
                    <div class="stat-item"><div class="stat-label">E-Value</div><div class="stat-value" style="font-family:monospace; font-size:0.85rem;">${hit.evalue}</div></div>
                    <div class="stat-item"><div class="stat-label">Accession</div><div class="stat-value" style="color:var(--primary); font-family:monospace; font-size:0.85rem;">${hit.acc}</div></div>
                    <div class="stat-item"><div class="stat-label">Identities</div><div class="stat-value" style="font-size:0.9rem;">${hit.ident_count}/${hit.align_len}</div></div>
                    <div class="stat-item"><div class="stat-label">Gaps</div><div class="stat-value" style="font-size:0.9rem;">${hit.gaps}</div></div>
                </div>
                <div style="margin-top: 15px; font-size: 0.75rem; color: var(--text-muted); display:flex; justify-content: space-between; background: #fff; padding: 8px; border-radius: 6px;">
                    <span>查询起始-结束: <b>${hit.query_range}</b></span><span>命中起始-结束: <b>${hit.hit_range}</b></span>
                </div>`;
            this.dom.detailBody.appendChild(card);
        });
    }

    /**
     * File Selection & Drag-and-Drop
     */
    initDragDrop() {
        const dropZone = this.dom.dropZone;
        if (!dropZone) {
            console.error("Drop zone element not found!");
            return;
        }
        console.log("Initializing Drag & Drop on:", dropZone);

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eName => {
            document.addEventListener(eName, e => { e.preventDefault(); e.stopPropagation(); }, false);
            dropZone.addEventListener(eName, e => { e.preventDefault(); e.stopPropagation(); }, false);
        });
        ['dragenter', 'dragover'].forEach(eName => { dropZone.addEventListener(eName, () => dropZone.classList.add('dragover')); });
        ['dragleave', 'drop'].forEach(eName => { dropZone.addEventListener(eName, () => dropZone.classList.remove('dragover')); });
        dropZone.addEventListener('drop', e => {
            console.log("Drop event detected in IFrame logic", e);
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                console.log("Files found in DataTransfer:", files);
                const file = files[0];
                if (file.path) {
                    console.log("File has path property (Electron/Local?):", file.path);
                    this.handleFileSelected({ path: file.path });
                }
                else {
                    console.log("File missing path, attempting FileReader (Browser limitation override needed).");
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        this.dom.queryInput.value = event.target.result;
                        this.selectedFiles = []; this.dom.fileSummary.innerHTML = "";
                    };
                    reader.readAsText(file);
                }
            }
        });
    }

    selectFiles() {
        console.log("selectFiles clicked. Bridge state:", !!this.localBridge);
        if (this.localBridge) {
            this.localBridge.request_file_load('fasta');
        } else {
            console.warn("Direct bridge not ready. Falling back to postMessage to parent.");
            // Send request to parent window (app.js)
            window.parent.postMessage({
                type: 'request_file_load',
                fileType: 'fasta'
            }, '*');
        }
    }

    switchInputMode(mode) {
        this.inputMode = mode;
        if (mode === 'file') {
            this.dom.tabFile.classList.add('active');
            this.dom.tabText.classList.remove('active');
            this.dom.modeFile.classList.add('active');
            this.dom.modeText.classList.remove('active');
        } else {
            this.dom.tabFile.classList.remove('active');
            this.dom.tabText.classList.add('active');
            this.dom.modeFile.classList.remove('active');
            this.dom.modeText.classList.add('active');
        }
    }

    handleFileSelected(data) {
        if (data.path && !this.selectedFiles.includes(data.path)) {
            this.selectedFiles.push(data.path);
            this.renderFileList();
            // Auto switch to file mode if adding files
            if (this.inputMode !== 'file') this.switchInputMode('file');
        }
    }

    renderFileList() {
        if (!this.dom.fileListScroll) return;

        this.dom.fileCountBadge.innerText = this.selectedFiles.length;

        if (this.selectedFiles.length === 0) {
            this.dom.fileListScroll.innerHTML = `
                <div class="file-list-empty">
                    拖拽文件至上方区域<br>或者点击添加
                </div>`;
            return;
        }

        this.dom.fileListScroll.innerHTML = '';
        this.selectedFiles.forEach((file, idx) => {
            const item = document.createElement('div');
            item.className = 'file-item';
            const name = file.split(/[\\/]/).pop();
            item.innerHTML = `
                <div class="file-name" title="${file}">
                    <svg class="icon-svg" viewBox="0 0 24 24" style="width:14px;height:14px;color:var(--primary)">
                         <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    </svg>
                    ${name}
                </div>
                <div class="file-remove-btn" onclick="if(window.blastView) window.blastView.removeFile(${idx})">
                    <svg class="icon-svg" viewBox="0 0 24 24" style="width:14px;height:14px;">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </div>
            `;
            this.dom.fileListScroll.appendChild(item);
        });
    }

    removeFile(idx) {
        this.selectedFiles.splice(idx, 1);
        this.renderFileList();
    }

    clearFiles() {
        this.selectedFiles = [];
        this.renderFileList();
    }

    /**
     * AI Translation
     */
    translateRow(btn, text) {
        if (!this.localBridge) return;
        const row = btn.closest('tr');
        const targetEl = row?.querySelector('.translated-name');
        if (!targetEl) return;
        btn.innerHTML = `<svg class="icon-svg fa-spin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><path d="M12 6v6l4 2"></path></svg>`;
        btn.disabled = true;
        this.localBridge.translate_text(text, "species", (translated) => {
            if (translated && translated !== text) {
                targetEl.innerText = translated; targetEl.style.display = 'block';
                btn.innerHTML = `<svg class="icon-svg" style="color:var(--accent)" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
            } else {
                btn.innerHTML = `<svg class="icon-svg" style="color:#cbd5e1" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
            }
            setTimeout(() => {
                const isTranslated = targetEl.style.display === 'block';
                btn.innerHTML = `<svg class="icon-svg" viewBox="0 0 24 24" style="width: 14px; height: 14px;"><path d="M5 8l6 6"></path><path d="M4 14l6-6 2-3"></path><path d="M2 5h12"></path><path d="M22 22l-5-10-5 10"></path><path d="M14 18h6"></path></svg>`;
                btn.disabled = false; btn.style.opacity = isTranslated ? "1" : "0.6";
                if (isTranslated) btn.style.color = "var(--primary)";
            }, 1000);
        });
    }

    async translateAllResults() {
        const btns = document.querySelectorAll('.translate-row-btn');
        for (let btn of btns) {
            const row = btn.closest('tr');
            if (row.style.display === 'none') continue;
            const speciesName = row.querySelector('.species-name')?.innerText.trim();
            const translatedEl = row.querySelector('.translated-name');
            if (!speciesName || (translatedEl.style.display === 'block')) continue;
            await new Promise(resolve => { this.translateRow(btn, speciesName); setTimeout(resolve, 300); });
        }
    }

    exportResults() {
        alert(this.translations['msg_export_dev'] || "导出功能正在开发中...");
    }

    /**
     * Dictionary Management
     */
    showDictTab() {
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.settings-content').forEach(c => c.classList.add('hidden'));
        this.dom.dictTab.classList.remove('hidden');
    }



    searchDict() {
        const query = this.dom.dictSearchInput.value.trim();
        if (!query) return;
        this.dom.dictResults.innerHTML = `<div style="padding:40px; text-align:center;"><i class="fas fa-circle-notch fa-spin fa-2x"></i></div>`;
        if (this.localBridge?.search_dictionary) {
            this.localBridge.search_dictionary(query, (response) => {
                try { this.renderDictResults(JSON.parse(response)); } catch (e) { console.error("Search dict error:", e); }
            });
        }
    }

    renderDictResults(results) {
        this.dom.dictResults.innerHTML = results.length === 0 ? `<div style="padding:40px; text-align:center;">未找到匹配记录</div>` : '';
        results.forEach(item => {
            const div = document.createElement('div');
            div.style.cssText = 'padding: 12px 14px; border-bottom: 1px solid #f1f5f9; background: #fff; display: flex; justify-content: space-between; align-items: center;';
            div.innerHTML = `
                <div style="flex: 1;">
                    <div style="font-weight: 600; color: var(--text-main); font-size: 0.9rem;">${item.english}</div>
                    <div style="font-size: 0.85rem; color: var(--primary); margin-top: 2px;">${item.chinese}</div>
                    <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">${item.category || 'other'} • ${item.source || 'unknown'}</div>
                </div>
                <button class="btn btn-ghost" onclick="window.blastView.editTranslation('${item.english.replace(/'/g, "\\'")}', '${item.chinese.replace(/'/g, "\\'")}')" style="padding: 4px 10px;">修改</button>`;
            this.dom.dictResults.appendChild(div);
        });
    }

    editTranslation(english, chinese) {
        this.dom.dictSource.value = english; this.dom.dictTarget.value = chinese; this.dom.dictOverlay.classList.add('active');
    }

    closeEditTrans() { this.dom.dictOverlay.classList.remove('active'); }

    saveTranslationEdit() {
        const english = this.dom.dictSource.value;
        const chinese = this.dom.dictTarget.value.trim();
        if (!chinese) return;
        if (this.localBridge?.update_dictionary_entry) {
            this.localBridge.update_dictionary_entry(english, chinese, (success) => {
                if (success) {
                    this.closeEditTrans(); this.searchDict();
                    document.querySelectorAll('.species-name').forEach(el => {
                        if (el.dataset.english === english) el.closest('tr').querySelector('.translated-name').innerText = chinese;
                    });
                }
            });
        }
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.blastView = new BlastViewController();
    window.blastView.init();

    /**
     * Global interface for app.js (Parent) to call
     */
    window.onFileSelected = (data) => {
        console.log("IFrame Global: Received onFileSelected from parent:", data);
        if (window.blastView) {
            window.blastView.handleFileSelected(data);
        } else {
            console.error("window.blastView not initialized yet!");
        }
    };

    window.onBlastEvent = (event) => {
        console.log("IFrame: Received onBlastEvent from parent:", event);
        if (window.blastView) {
            // Handle specific events like progress if needed
            if (event.type === 'blast_update') {
                window.blastView.refreshTasks();
            }
        }
    };
});
