/**
 * Bio-Station UI Utilities
 * Common functions for Modals, Notifications and shared Business Logic
 */

const UIHelper = {
    /**
     * Show modern system modal
     * @param {string} title 
     * @param {string} message 
     * @param {string} type - 'success', 'error', 'warning', 'info'
     * @param {Object} host - The controller instance (app or blastView)
     */
    showModal(title, message, type = 'info', host = window.app || window.blastView) {
        const overlay = document.getElementById('modal-system-overlay');
        const iconContainer = document.getElementById('modal-system-icon');
        const titleEl = document.getElementById('modal-system-title');
        const bodyEl = document.getElementById('modal-system-body');
        const footerEl = document.getElementById('modal-system-footer');

        if (!overlay) return;

        iconContainer.className = `modal-icon modal-icon-${type}`;
        const iconSvg = {
            success: '<svg class="icon-svg" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>',
            error: '<svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
            warning: '<svg class="icon-svg" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
            info: '<svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
        }[type];
        iconContainer.innerHTML = iconSvg;

        titleEl.innerText = title;
        bodyEl.innerText = message;

        // In unified SPA, we always use window.app for system modals
        footerEl.innerHTML = `<button class="btn btn-primary" onclick="window.app.closeSystemModal()">确定</button>`;

        overlay.classList.add('active');
    },

    /**
     * Show modern system confirmation modal
     */
    showConfirm(title, message, onConfirm, host = window.app || window.blastView) {
        const log = (msg) => {
            console.log(msg);
            if (window.py_bridge && window.py_bridge.on_js_log) window.py_bridge.on_js_log("[UIHelper] " + msg);
        };

        const overlay = document.getElementById('modal-system-overlay');
        const iconContainer = document.getElementById('modal-system-icon');
        const titleEl = document.getElementById('modal-system-title');
        const bodyEl = document.getElementById('modal-system-body');
        const footerEl = document.getElementById('modal-system-footer');

        if (!overlay) {
            log("Error: modal-system-overlay not found");
            return;
        }

        iconContainer.className = `modal-icon modal-icon-warning`;
        iconContainer.innerHTML = '<svg class="icon-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';

        titleEl.innerText = title;
        bodyEl.innerText = message;

        // Ensure closeSystemModal is available
        const closeFunc = (host && host.closeSystemModal) ? "host.closeSystemModal()" : "(window.app && window.app.closeSystemModal())";

        footerEl.innerHTML = `
            <button class="btn btn-ghost" id="modal-cancel-btn">取消</button>
            <button class="btn btn-primary" id="modal-confirm-btn">确定</button>
        `;

        // Bind events manually to avoid inline JS scope issues
        document.getElementById('modal-cancel-btn').onclick = () => {
            log("Cancel clicked");
            if (host && host.closeSystemModal) host.closeSystemModal();
            else if (window.app) window.app.closeSystemModal();
            else overlay.classList.remove('active'); // Fallback
        };

        const confirmBtn = document.getElementById('modal-confirm-btn');
        confirmBtn.onclick = () => {
            log("Confirm button clicked");
            try {
                if (onConfirm) {
                    log("Executing onConfirm callback...");
                    onConfirm();
                } else {
                    log("Warning: No onConfirm callback provided");
                }
            } catch (e) {
                log("Error in onConfirm: " + e.message);
            }

            if (host && host.closeSystemModal) host.closeSystemModal();
            else if (window.app) window.app.closeSystemModal();
            else overlay.classList.remove('active'); // Fallback
        };

        overlay.classList.add('active');
        log("Confirm modal shown: " + title);
    },

    /**
     * Show global toast notification
     */
    showNotification(message, type = 'info') {
        const container = document.getElementById('notification-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `notification-toast ${type}`;

        const iconSvg = {
            success: '<svg class="icon-svg" style="color:var(--accent-color)" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>',
            error: '<svg class="icon-svg" style="color:var(--danger-color)" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
            warning: '<svg class="icon-svg" style="color:var(--warning-color)" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>',
            info: '<svg class="icon-svg" style="color:var(--primary-color)" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
        }[type];

        toast.innerHTML = `${iconSvg}<span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => toast.classList.add('active'), 10);
        setTimeout(() => {
            toast.classList.remove('active');
            setTimeout(() => toast.remove(), 400);
        }, 3000);
    },

    /**
     * Shared logic for Intelligent Repair
     * @param {Object} bridge - The bridge instance
     * @param {Object} host - The controller instance (app or blastView)
     * @param {string} btnId - ID of the trigger button
     */
    runIntelligentRepair(bridge, host, btnId = 'btn-repair-dict') {
        if (!bridge || !bridge.repair_dictionary_categories) {
            this.showNotification("修复接口未就绪", "warning");
            return;
        }

        const btn = document.getElementById(btnId);
        if (btn) btn.disabled = true;

        bridge.repair_dictionary_categories((response) => {
            if (btn) btn.disabled = false;
            try {
                const results = JSON.parse(response);
                if (results.error) {
                    this.showModal("修复失败", results.error, "error", host);
                } else {
                    this.showModal("修复完成", `总检测条目: ${results.total}\n智能归位: ${results.fixed}\n剩余 ${results.remained} 条记录建议手动检查。`, "success", host);
                    if (host && host.searchDictionary) host.searchDictionary();
                    else if (host && host.searchDict) host.searchDict();
                }
            } catch (e) {
                console.error("Parse repair results error:", e);
                this.showNotification("修复结果解析失败", "error");
            }
        });
    },

    /**
     * Show global loading overlay
     * @param {string} msg - Loading message
     * @param {string} targetId - Optional ID of element to cover (default: full screen)
     */
    showLoading(msg, targetId = null) {
        // Debug logging
        console.log('[UIHelper] showLoading called:', msg, targetId);
        if (window.py_bridge && window.py_bridge.on_js_log) {
            window.py_bridge.on_js_log('[UIHelper] showLoading called: ' + msg + ', target: ' + targetId);
        }

        // Detect target
        let parent = document.body;
        let isScoped = false;
        if (targetId) {
            const el = document.getElementById(targetId);
            if (el) {
                parent = el;
                isScoped = true;
                // Ensure parent has positioning context
                if (getComputedStyle(parent).position === 'static') {
                    parent.style.position = 'relative';
                }
            }
        }

        let overlay = document.getElementById('loadingOverlay');
        // Dynamic creation if missing
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'loadingOverlay';
            overlay.innerHTML = `
                <div style="text-align: center; width: 300px;">
                    <svg class="icon-svg spinner-icon" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="10" opacity="0.25" stroke="currentColor" fill="none" stroke-width="4"></circle>
                        <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83" opacity="0.75" fill="currentColor"></path>
                    </svg>
                    <h3 id="loadingText" style="margin: 0; color: var(--text-primary); font-weight: 500; font-size: 1.2rem;">正在处理...</h3>
                    <div class="loading-bar-container">
                        <div id="loadingBar" class="loading-bar"></div>
                    </div>
                    <p id="loadingValid" style="margin-top: 4px; color: var(--text-secondary); font-size: 0.85rem; height: 20px;">初始化环境...</p>
                </div>
            `;
        }

        // Move overlay to correct parent if needed
        if (overlay.parentNode !== parent) {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            parent.appendChild(overlay);
        }

        // Apply Scoped Styles if needed
        if (isScoped) {
            overlay.style.position = 'absolute';
            overlay.style.borderRadius = getComputedStyle(parent).borderRadius;
            overlay.style.zIndex = '2000'; // Must be higher than tree-overlay (1500)
        } else {
            overlay.style.position = 'fixed';
            overlay.style.borderRadius = '0';
            overlay.style.zIndex = '9999';
        }

        const txt = document.getElementById('loadingText');
        const bar = document.getElementById('loadingBar');
        const valid = document.getElementById('loadingValid');

        if (txt) txt.innerText = msg || "Processing...";
        if (bar) bar.style.width = '30%'; // Fake progress start
        if (valid) valid.innerText = "正在请求系统资源...";

        overlay.classList.add('active');
    },

    /**
     * Update loading progress
     * @param {number} percent 0-100
     * @param {string} msg Optional status text
     */
    updateLoading(percent, msg) {
        const bar = document.getElementById('loadingBar');
        const txt = document.getElementById('loadingValid');
        if (bar) bar.style.width = percent + '%';
        if (txt && msg) txt.innerText = msg;
    },

    /**
     * Hide global loading overlay
     */
    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            const bar = document.getElementById('loadingBar');
            if (bar) bar.style.width = '100%';

            setTimeout(() => {
                overlay.classList.remove('active');
                if (bar) bar.style.width = '0%';
            }, 300);
        }
    }
};

// Export to window
window.UIHelper = UIHelper;
