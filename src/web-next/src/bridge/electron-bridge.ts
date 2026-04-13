/**
 * Electron Bridge — 替代 QWebChannel 的通信层
 *
 * 与 pyqt-bridge.ts 实现相同的 PyBridge 接口，
 * 但底层使用 HTTP REST + WebSocket 与 Python Sidecar 通信，
 * 使用 Electron IPC 调用原生对话框和系统功能。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** 扩展 Window 接口以支持 Electron 预加载 API */
declare global {
    interface Window {
        electronAPI?: {
            openFileDialog: (options: any) => Promise<string[] | null>
            saveFileDialog: (options: any) => Promise<string | null>
            openExternal: (url: string) => Promise<void>
            openPath: (dirPath: string) => Promise<void>
            readFile: (filePath: string) => Promise<string | null>
            writeFile: (filePath: string, content: string) => Promise<boolean>
            getApiPort: () => Promise<number>
            getProjectRoot: () => Promise<string>
            getPathForFile: (file: File) => string
        }
        [key: string]: any
    }
}

// 生成当前会话的唯一标识符，用于排除广播回环
const MY_CLIENT_ID = 'client_' + Math.random().toString(36).substring(2, 10);

/** 获取当前客户端 ID */
export function getClientId() {
    return MY_CLIENT_ID;
}

// ─── 配置常量 ─────────────────────────────────────
// 默认地址 (Electron 环境)
let API_BASE = 'http://127.0.0.1:8765';
let WS_URL = `ws://127.0.0.1:8765/ws?client_id=${MY_CLIENT_ID}`;

// 【自适应逻辑强化】
if (typeof window !== 'undefined') {
    const { protocol, hostname, port, origin } = window.location;
    
    // 如果是通过浏览器直接访问 (非 Vite 开发模式的 5173 端口)
    if (port !== '5173' && (protocol === 'http:' || protocol === 'https:')) {
        console.log(`[ElectronBridge] 检测到外部浏览器访问，自动切换 API 基址至: ${origin}`);
        API_BASE = origin;
        const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:';
        WS_URL = `${wsProtocol}//${window.location.host}/ws?client_id=${MY_CLIENT_ID}`;
    }
}

// ─── HTTP 辅助函数 ────────────────────────────────

async function apiGet(endpoint: string): Promise<any> {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`);
        if (!response.ok) return { success: false, error: `HTTP ${response.status}`, status: response.status };
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        }
        return { success: true, text: await response.text() };
    } catch (err) {
        console.error(`[ElectronBridge] GET ${endpoint} 失败:`, err);
        return { success: false, error: String(err) };
    }
}

async function apiPost(endpoint: string, body?: any): Promise<any> {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-Client-ID': MY_CLIENT_ID
            },
            body: body ? JSON.stringify(body) : undefined
        });
        
        const contentType = response.headers.get('content-type');
        if (response.ok && contentType && contentType.includes('application/json')) {
            return await response.json();
        }
        
        if (!response.ok) {
            const errorText = await response.text().catch(() => 'Unknown Error');
            return { success: false, error: `HTTP ${response.status}: ${errorText}`, status: response.status };
        }
        
        return { success: true, text: await response.text() };
    } catch (err) {
        console.error(`[ElectronBridge] POST ${endpoint} 失败:`, err);
        return { success: false, error: String(err) };
    }
}

async function apiDelete(endpoint: string): Promise<any> {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, { 
            method: 'DELETE',
            headers: { 'X-Client-ID': MY_CLIENT_ID }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (err) {
        console.error(`[ElectronBridge] DELETE ${endpoint} 失败:`, err);
        return { success: false, error: String(err) };
    }
}

// ─── WebSocket 管理 ───────────────────────────────

/** 事件监听器类型 */
type EventHandler = (eventType: string, data: any) => void;

/** 全局事件监听器列表 */
const eventHandlers: EventHandler[] = [];

/** WebSocket 单例 */
let wsConnection: WebSocket | null = null;
let wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;

const WS_RECONNECT_INTERVAL_MS = 3000;
const WS_HEARTBEAT_INTERVAL_MS = 15000;

/** 模拟 PyQt 信号订阅机制 */
class BridgeSignal {
    private handlers: Array<(...args: any[]) => void> = [];
    connect(handler: (...args: any[]) => void) {
        this.handlers.push(handler);
    }
    emit(...args: any[]) {
        for (const h of this.handlers) h(...args);
    }
}

/** 全局事件分发器实例 */
const signals = {
    recall_event: new BridgeSignal(),
    blast_event: new BridgeSignal(),
    sync_event: new BridgeSignal()
};

function connectWebSocket(): void {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    if (wsConnection?.readyState === WebSocket.OPEN) return;

    console.log('[ElectronBridge] 正在连接 WebSocket...');
    wsConnection = new WebSocket(WS_URL);

    wsConnection.onopen = () => {
        console.log('[ElectronBridge] WebSocket 已连接');
        // 启动心跳
        setInterval(() => {
            if (wsConnection?.readyState === WebSocket.OPEN) {
                wsConnection.send('ping');
            }
        }, WS_HEARTBEAT_INTERVAL_MS);
    };

    wsConnection.onmessage = (event) => {
        try {
            const raw = event.data;
            if (raw === '{"type": "pong"}') return; // 快速跳过心跳回包

            const msg = JSON.parse(raw);
            if (msg.type === 'pong') return;

            // 1. 分发给所有监听器 (Legacy 模式)
            for (const handler of eventHandlers) {
                handler(msg.type, msg.data);
            }

            // 2. 分发给特定的信号槽 (Modern 模式)
            if (msg.type === 'data_updated') {
                signals.sync_event.emit(msg.data);
            } else if (msg.type === 'single_result_update') {
                signals.blast_event.emit(msg.type, JSON.stringify(msg.data));
            }

            // 2. 映射到特定信号对象 (兼容旧架构)
            if (msg.type === 'recall_result') {
                signals.recall_event.emit(msg.data.success, msg.data.message || msg.data.recalled_name);
            } else if (['single_result_update', 'task_progress', 'batch_translation_result', 'tree_progress', 'tree_finished', 'tree_error'].includes(msg.type)) {
                signals.blast_event.emit(msg.type, JSON.stringify(msg.data));
            }

            // 3. 兼容旧架构：触发 window.handleBridgeEvent
            if (window.handleBridgeEvent) {
                window.handleBridgeEvent(msg.type, msg.data);
            }
        } catch (parseError) {
            console.warn('[ElectronBridge] WebSocket 消息解析失败:', parseError);
        }
    };

    wsConnection.onclose = () => {
        console.log('[ElectronBridge] WebSocket 连接断开，将自动重连...');
        wsConnection = null;
        wsReconnectTimer = setTimeout(connectWebSocket, WS_RECONNECT_INTERVAL_MS);
    };

    wsConnection.onerror = (err) => {
        console.error('[ElectronBridge] WebSocket 错误:', err);
    };
}

/**
 * 注册事件监听器（接收 Python 推送）
 */
function onEvent(handler: EventHandler): () => void {
    eventHandlers.push(handler);
    return () => {
        const index = eventHandlers.indexOf(handler);
        if (index >= 0) eventHandlers.splice(index, 1);
    };
}

// ─── PyBridge 兼容层 ─────────────────────────────

/** 实现与 pyqt-bridge.ts 完全相同的 PyBridge 接口 */
const electronBridge = {
    // 信号对象
    recall_event: signals.recall_event,
    blast_event: signals.blast_event,
    sync_event: signals.sync_event,

    // ═══ 文件操作（通过 Electron IPC）═══
    request_file_load(fileType: string) {
        const electron = window.electronAPI;
        if (!electron) {
            console.warn('[Bridge] 当前处于非 Electron 环境，无法调用原生文件对话框。');
            (window as any).app?.showNotification('局域网模式暂不支持直接读取本地文件，请使用上传逻辑', 'warning');
            return;
        }

        const filterMap: Record<string, any[]> = {
            fasta: [
                { name: 'Sequence Files', extensions: ['fasta', 'fas', 'fa', 'seq', 'ab1', 'abi'] },
                { name: 'Archives', extensions: ['zip'] },
                { name: 'All Files', extensions: ['*'] }
            ],
            tree: [
                { name: 'Tree Files', extensions: ['nwk', 'newick', 'txt'] },
                { name: 'All Files', extensions: ['*'] }
            ]
        };
        electron.openFileDialog({
            title: `Open ${fileType}`,
            filters: filterMap[fileType] || [{ name: 'All Files', extensions: ['*'] }]
        }).then(async (paths: string[] | null) => {
            if (!paths || paths.length === 0) return;
            const filePath = paths[0];
            if (!filePath) return;
            const content = await electron.readFile(filePath);
            if (content && (window as any).app?.handleFileLoaded) {
                (window as any).app.handleFileLoaded(content, fileType, filePath);
            }
        });
    },

    async save_file(content: string, filenameHint: string, callback?: (success: boolean) => void) {
        const path = await window.electronAPI?.saveFileDialog({
            defaultPath: filenameHint
        });
        if (path) {
            const success = await window.electronAPI?.writeFile(path, content);
            callback?.(success ?? false);
        } else {
            callback?.(false);
        }
    },

    open_results_dir(dirPath: string) {
        window.electronAPI?.openPath(dirPath);
    },

    open_external_url(url: string) {
        window.electronAPI?.openExternal(url);
    },

    // ═══ BLAST 任务管理（通过 HTTP）═══
    async process_blast_files(paths: string[]) {
        const result = await apiPost('/api/blast/process_files', { paths });
        return result;
    },

    async run_blast_job(paramsJson: string, callback?: (res: string) => void) {
        const params = JSON.parse(paramsJson);
        const result = await apiPost('/api/blast/run', params);
        callback?.(JSON.stringify(result));
    },

    async stop_blast_job(taskId: string) {
        await apiPost(`/api/blast/stop/${taskId}`);
    },

    async pause_blast_job(taskId: string) {
        await apiPost(`/api/blast/pause/${taskId}`);
    },

    async resume_blast_job(taskId: string) {
        await apiPost(`/api/blast/resume/${taskId}`);
    },

    async get_task_status(taskId: string, callback?: (res: string) => void) {
        const result = await apiGet(`/api/blast/status/${taskId}`);
        callback?.(JSON.stringify(result));
    },

    async get_task_results(taskId: string, callback?: (res: string) => void) {
        const result = await apiGet(`/api/blast/results/${taskId}`);
        callback?.(JSON.stringify(result));
    },

    async get_all_tasks(callback?: (res: string) => void) {
        const result = await apiGet('/api/blast/tasks');
        callback?.(JSON.stringify(result));
    },

    async delete_single_task(taskId: string) {
        await apiDelete(`/api/blast/task/${taskId}`);
    },

    async resume_task(taskId: string) {
        await apiPost(`/api/blast/resume/${taskId}`);
    },

    async clear_all_history() {
        await apiPost('/api/blast/clear');
    },

    async rename_task(taskId: string, newName: string) {
        await apiPost(`/api/blast/rename/${taskId}`, { new_name: newName });
    },

    async get_detailed_blast_results(csvFile: string) {
        const result = await apiGet(`/api/blast/detailed/${encodeURIComponent(csvFile)}`);
        // 推送到旧的全局事件系统
        if (window.handleBridgeEvent) {
            window.handleBridgeEvent('detailed_results_ready', result);
        }
    },

    // ═══ 本地数据库管理（通过 HTTP）═══
    async list_local_databases(callback?: (res: string) => void) {
        const result = await apiGet('/api/blast/databases');
        callback?.(JSON.stringify(result));
    },

    async make_blast_db(inputFile: string, dbType: string, title: string, outName: string | null, callback?: (success: boolean, message: string) => void) {
        const result = await apiPost('/api/blast/database/make', {
            input_file: inputFile,
            db_type: dbType,
            title: title,
            out_name: outName
        });
        callback?.(result.success, result.message);
    },

    async delete_database(name: string, callback?: (success: boolean) => void) {
        const result = await apiDelete(`/api/blast/database/${encodeURIComponent(name)}`);
        callback?.(result.success);
    },

    async get_alignment_visualization_data(xmlPath: string, sortMode: string = 'evalue', callback?: (res: string) => void) {
        const result = await apiPost('/api/blast/visualization/data', {
            xml_path: xmlPath,
            sort_mode: sortMode
        });
        callback?.(JSON.stringify(result));
    },

    // ═══ 翻译（通过 HTTP + WS 推送）═══
    async translate_text(text: string, category: string, callback?: (res: string) => void) {
        const result = await apiPost('/api/translate/single', { text, category });
        callback?.(result.translated || text);
    },

    async translate_batch(textsJson: string, category: string) {
        const texts = JSON.parse(textsJson);
        await apiPost('/api/translate/batch', { texts, category });
        // 结果通过 WebSocket 逐条推送
    },

    // ═══ 词典管理（通过 HTTP）═══
    async search_dictionary(query: string, proofreadModeOrCallback?: boolean | ((res: string) => void), callback?: (res: string) => void) {
        let proofreadMode = false;
        let actualCallback = callback;
        if (typeof proofreadModeOrCallback === 'boolean') {
            proofreadMode = proofreadModeOrCallback;
        } else if (typeof proofreadModeOrCallback === 'function') {
            actualCallback = proofreadModeOrCallback;
        }
        const result = await apiGet(`/api/dictionary/search?query=${encodeURIComponent(query)}&proofread_mode=${proofreadMode}`);
        actualCallback?.(JSON.stringify(result));
    },

    async save_dictionary_term(english: string, chinese: string, category: string, callback?: (res: boolean) => void) {
        const result = await apiPost('/api/dictionary/save', { english, chinese, category });
        callback?.(result.success);
    },

    async delete_dictionary_term(english: string, callback?: (res: boolean) => void) {
        const result = await apiDelete(`/api/dictionary/term/${encodeURIComponent(english)}`);
        callback?.(result.success);
    },

    async verify_dictionary_term(english: string, callback?: (res: boolean) => void) {
        const result = await apiPost(`/api/dictionary/verify/${encodeURIComponent(english)}`);
        callback?.(result.success);
    },

    async get_all_dictionary_terms(proofreadModeOrCallback?: boolean | ((res: string) => void), callback?: (res: string) => void) {
        let proofreadMode = false;
        let actualCallback = callback;
        if (typeof proofreadModeOrCallback === 'boolean') {
            proofreadMode = proofreadModeOrCallback;
        } else if (typeof proofreadModeOrCallback === 'function') {
            actualCallback = proofreadModeOrCallback;
        }
        const result = await apiGet(`/api/dictionary/all?proofread_mode=${proofreadMode}`);
        actualCallback?.(JSON.stringify(result));
    },

    // ═══ 进化树（通过 HTTP + WS 推送）═══
    async request_tree_analysis(paramsJson: string) {
        const params = JSON.parse(paramsJson);
        await apiPost('/api/tree/analyze', params);
    },

    async request_tree_reroot(nodeId: string) {
        // 需要知道当前活动的树路径
        const currentPath = (window as any).treeView?.currentTreePath;
        if (!currentPath) {
             (window as any).app?.showNotification('未找到当前活动的树文件路径', 'error');
             return;
        }

        (window as any).app?.showLoading('正在重定根...');
        const result = await apiPost('/api/tree/reroot', { 
            old_path: currentPath, 
            node_id: nodeId 
        });
        (window as any).app?.hideLoading();

        if (result.success && window.treeView) {
            window.treeView.loadNewick(result.newick, 'Rerooted', result.source);
        } else if (result.error) {
            (window as any).app?.showNotification(`重定根失败: ${result.error}`, 'error');
        }
    },

    async clear_tree_workspace(callback?: (res: boolean) => void) {
        const result = await apiDelete('/api/tree/workspace');
        callback?.(result.success);
    },

    async list_tree_sequences(callback: (res: string) => void) {
        const result = await apiGet('/api/tree/sequences');
        callback(JSON.stringify(result));
    },

    async get_tree_content(filename: string, callback: (res: string) => void) {
        const result = await apiGet(`/api/tree/content/${filename}`);
        callback(result.content || '');
    },

    async save_tree_sequences(content: string) {
        await apiPost('/api/tree/save_sequences', { content });
    },

    async recall_tree_sequences(sourceFilename: string) {
        await apiPost('/api/tree/recall', { source_filename: sourceFilename });
    },

    async delete_tree_archive(relPath: string) {
        await apiDelete(`/api/tree/archive/${encodeURIComponent(relPath)}`);
    },

    async add_tree_workspace_files(pathsJson: string) {
        const paths = JSON.parse(pathsJson);
        await apiPost('/api/tree/workspace/add', { paths });
    },

    async delete_analysis_files(pathsJson: string) {
        const paths = JSON.parse(pathsJson);
        await apiPost('/api/tree/analysis/delete', { paths });
    },

    async request_batch_blast(seqIdsJson: string, sourceRelPath: string) {
        const seq_ids = JSON.parse(seqIdsJson);
        return await apiPost('/api/blast/batch_from_tree', { seq_ids, source_rel_path: sourceRelPath });
    },

    // ═══ 文件系统直接读写 ═══
    async read_result_file(filePath: string) {
        return await window.electronAPI?.readFile(filePath);
    },

    // ═══ 配置（通过 HTTP）═══
    async get_ui_translations(callback?: (res: string) => void) {
        const result = await apiGet('/api/settings/ui_translations');
        callback?.(JSON.stringify(result));
    },

    async get_ui_language(callback?: (res: string) => void) {
        const result = await apiGet('/api/settings/ui_language');
        callback?.(result.language || 'zh_CN');
    },

    async save_ui_language(langCode: string) {
        await apiPost('/api/settings/ui_language', { lang_code: langCode });
    },

    async get_api_key(service: string, callback?: (res: string) => void) {
        const result = await apiGet(`/api/settings/api_key/${service}`);
        callback?.(result.key || '');
    },

    async save_api_key(service: string, key: string) {
        await apiPost(`/api/settings/api_key/${service}`, { key });
    },
    
    async get_lan_share_info() {
        return await apiGet('/api/settings/lan_info');
    },

    async save_lan_share_settings(enabled: boolean) {
        return await apiPost('/api/settings/lan_share', { enabled });
    },

    async save_selected_model(modelKey: string, callback?: (res: boolean) => void) {
        const result = await apiPost('/api/settings/ai_model', { model_key: modelKey });
        callback?.(result.success);
    },

    async get_selected_model(callback?: (res: string) => void) {
        const result = await apiGet('/api/settings/ai_model');
        callback?.(result.model || '');
    },

    async get_ai_models(callback?: (res: string) => void) {
        const result = await apiGet('/api/settings/ai_models');
        callback?.(JSON.stringify(result));
    },

    async add_ai_model(key: string, name: string, callback?: (success: boolean) => void) {
        const result = await apiPost('/api/settings/ai_models', { key, name });
        callback?.(result.success);
    },

    async delete_ai_model(key: string, callback?: (success: boolean) => void) {
        const result = await apiDelete(`/api/settings/ai_models/${encodeURIComponent(key)}`);
        callback?.(result.success);
    },

    // ═══ 菌种库（通过 HTTP）═══
    async db_save_freezer(freezer: any, callback?: (res: boolean) => void) {
        const result = await apiPost('/api/strain/freezer', { data: freezer });
        callback?.(result.success);
    },

    async db_delete_freezer(freezerId: string, callback?: (res: boolean) => void) {
        const result = await apiDelete(`/api/strain/freezer/${freezerId}`);
        callback?.(result.success);
    },

    async db_save_record(record: any, callback?: (res: boolean) => void) {
        const result = await apiPost('/api/strain/record', { data: record });
        callback?.(result.success);
    },
    
    async db_save_records_batch(records: any[], callback?: (res: boolean) => void) {
        const result = await apiPost('/api/strain/records/batch', { data: records });
        callback?.(result.success);
    },

    async db_delete_record(recordId: string, callback?: (res: boolean) => void) {
        const result = await apiDelete(`/api/strain/record/${recordId}`);
        callback?.(result.success);
    },

    async db_load_all(callback?: (res: any) => void) {
        const result = await apiGet('/api/strain/load');
        callback?.(result);
    },

    async db_clear_all(callback?: (res: boolean) => void) {
        const result = await apiPost('/api/strain/clear');
        callback?.(result.success);
    },

    async db_save_code_lookup(data: any, callback?: (res: boolean) => void) {
        const result = await apiPost('/api/strain/sys_config/codeLookup', data);
        callback?.(result.success);
    },

    async db_save_sequence(seqJson: string, callback?: (res: boolean) => void) {
        const data = JSON.parse(seqJson);
        const result = await apiPost('/api/strain/sequence', data);
        callback?.(result.success);
    },

    async db_load_sequences_by_sample(sampleId: string, callback?: (res: string) => void) {
        const result = await apiGet(`/api/strain/sequences/${encodeURIComponent(sampleId)}`);
        callback?.(JSON.stringify(result));
    },

    async db_search_sequences(keyword: string, callback?: (res: string) => void) {
        const result = await apiGet(`/api/strain/sequences/search?keyword=${encodeURIComponent(keyword)}`);
        callback?.(JSON.stringify(result));
    },

    async db_delete_sequence(seqId: string, callback?: (res: boolean) => void) {
        const result = await apiDelete(`/api/strain/sequence/${encodeURIComponent(seqId)}`);
        callback?.(result.success);
    },

    // ═══ 帮助 & 核心（通过 HTTP）═══
    async get_help_structure() {
        const result = await apiGet('/api/help/structure');
        if (window.handleBridgeEvent) {
            window.handleBridgeEvent('help_structure', result);
        }
    },

    async get_help_content(topicId: string) {
        const result = await apiGet(`/api/help/content/${topicId}`);
        if (window.handleBridgeEvent) {
            window.handleBridgeEvent('help_content', result);
        }
    },

    async sync_taxonomy(speciesName: string, callback?: (res: any) => void) {
        const result = await apiPost('/api/taxonomy/sync', { species_name: speciesName });
        callback?.(result);
    },

    /** 查询物种分类数据库状态 */
    async taxonomy_status(callback?: (res: any) => void) {
        const result = await apiGet('/api/taxonomy/status');
        callback?.(result);
        return result;
    },

    /** 触发物种分类数据库在线更新（含 MD5 智能增量检查） */
    async taxonomy_update(callback?: (res: any) => void) {
        const result = await apiPost('/api/taxonomy/update', {});
        callback?.(result);
        return result;
    },

    /** 检查物种分类数据库是否有更新可用（仅比对 MD5，不下载数据） */
    async taxonomy_check(callback?: (res: any) => void) {
        const result = await apiGet('/api/taxonomy/check');
        callback?.(result);
        return result;
    },

    on_page_ready() {
        console.log('[ElectronBridge] Page ready');
    },

    log_message(message: string) {
        console.log(`[Frontend] ${message}`);
    },

    on_js_error(message: string) {
        console.error(`[Frontend Error] ${message}`);
    },

    // 进化树历史记录
    async db_load_tree_history(callback?: (res: string) => void) {
        const result = await apiGet('/api/tree/history');
        callback?.(JSON.stringify(result));
    },

    async db_save_tree_history(history: any[], callback?: (res: string) => void) {
        const result = await apiPost('/api/tree/history', { history });
        callback?.(JSON.stringify(result));
    },

    async db_delete_tree_history(groupId: string, physical: boolean = false, callback?: (res: string) => void) {
        const result = await apiDelete(`/api/tree/history/${groupId}?physical=${physical}`);
        callback?.(JSON.stringify(result));
    },

    async get_annotations_by_hashes(hashesJson: string) {
        const hashes = JSON.parse(hashesJson);
        const result = await apiPost('/api/translate/hashes', { hashes });
        return JSON.stringify(result);
    },

    async import_sequences_to_strains(paths: string[]) {
        return await apiPost('/api/strains/import_paths', { paths });
    },

    // ═══ 分类学与家谱 (NCBI ETE4) ═══
    async get_taxonomy_lineage(query: string) {
        const result = await apiGet(`/api/taxonomy/lineage?query=${encodeURIComponent(query)}`);
        return result;
    },

    async search_strains_by_category(category: string) {
        const result = await apiGet(`/api/strain/search/category?category=${category}`);
        return result;
    },

    /** 获取拖拽文件的绝对路径 (需 preload 支持) */
    get_path_for_file(file: File): string {
        return window.electronAPI?.getPathForFile(file) || '';
    },

    /** 支持网页端上传文件到服务器 */
    async upload_file(file: File): Promise<any> {
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            const response = await fetch(`${API_BASE}/api/blast/upload`, {
                method: 'POST',
                body: formData
            });
            return await response.json();
        } catch (err) {
            console.error('[ElectronBridge] 文件上传失败:', err);
            return { success: false, error: String(err) };
        }
    }
};

// ─── 桥接初始化 ───────────────────────────────────

let bridgeInstance: typeof electronBridge | null = null;
let bridgeReadyPromise: Promise<typeof electronBridge> | null = null;

/**
 * 初始化 Electron 桥接（与 pyqt-bridge.ts 的 initBridge 签名一致）
 */
async function initBridge(): Promise<typeof electronBridge> {
    if (bridgeReadyPromise) return bridgeReadyPromise;

    bridgeReadyPromise = new Promise(async (resolve) => {
        console.log('[ElectronBridge] 正在验证 API Server 连通性...');

        // 等待 API Server 响应 (最多重试 15 次，约 12 秒)
        let apiStarted = false;
        let attempts = 0;
        while (attempts < 15 && !apiStarted) {
            try {
                const res = await fetch(`${API_BASE}/`);
                if (res.ok) {
                    apiStarted = true;
                    console.log('[ElectronBridge] API Server 已就绪');
                }
            } catch (e) {
                attempts++;
                // console.log(`[ElectronBridge] API Server 尚未就绪... (${attempts}/15)`);
                await new Promise(r => setTimeout(r, 800));
            }
        }

        if (!apiStarted) {
            console.warn('[ElectronBridge] API Server 连通性检查超时，尝试盲目初始化...');
        }

        // 建立 WebSocket 连接
        connectWebSocket();

        bridgeInstance = electronBridge;
        console.log('[ElectronBridge] 桥接准备完成');
        resolve(electronBridge);
    });

    return bridgeReadyPromise;
}

/**
 * 获取桥接实例（与 pyqt-bridge.ts 的 getBridge 签名一致）
 */
function getBridge(): typeof electronBridge {
    if (!bridgeInstance) {
        throw new Error('[ElectronBridge] 桥接尚未初始化，请先调用 initBridge()');
    }
    return bridgeInstance;
}

/**
 * 注册全局回调（兼容 pyqt-bridge.ts 的 registerGlobalHandler）
 */
function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
    window[name] = handler;
}

export { initBridge, getBridge, registerGlobalHandler, onEvent };
