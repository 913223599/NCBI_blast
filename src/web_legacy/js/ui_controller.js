/**
 * UIController - 负责常规 UI 交互逻辑
 * 
 * 职责：
 * 1. 侧边栏/面板切换
 * 2. 搜索过滤
 * 3. 弹窗与确认 (Toast, Modal)
 * 4. 画布快捷操作
 */
class UIController {
    /**
     * @param {Object} dom - { container, canvas, searchInput, ... }
     * @param {I18nService} i18n
     */
    constructor(dom, i18n) {
        this.dom = dom;
        this.i18n = i18n;

        // 回调
        this.onSearchNodes = null;
        this.onClearCanvas = null;
        this.onAutoArrange = null;

        this._bindUIEvents();
    }

    /** 绑定面板切换与基础按钮 */
    _bindUIEvents() {
        // 侧边栏 Tab 切换
        document.querySelectorAll('.sidebar-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const targetId = e.target.dataset.target;
                this.switchSidebarPanel(targetId);
            });
        });

        // 搜索框
        const searchInput = document.querySelector('.search-box');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                if (this.onSearchNodes) this.onSearchNodes(e.target.value);
            });
        }

        // 按钮组
        const btnArrange = document.getElementById('btn-arrange');
        if (btnArrange) {
            btnArrange.addEventListener('click', () => {
                if (this.onAutoArrange) this.onAutoArrange();
            });
        }

        const btnClear = document.getElementById('btn-clear');
        if (btnClear) {
            btnClear.addEventListener('click', () => {
                if (this.onClearCanvas) this.onClearCanvas();
            });
        }
    }

    /** 切换侧边栏面板 */
    switchSidebarPanel(panelId) {
        document.querySelectorAll('.sidebar-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.target === panelId);
        });
        document.querySelectorAll('.sidebar-panel').forEach(p => {
            p.classList.toggle('active', p.id === `${panelId}-panel`);
        });
    }

    /** 显示 Toast 提示 */
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const ICONS = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
        toast.innerHTML = `<span style="font-weight:bold">${ICONS[type] || 'ℹ'}</span><span>${message}</span>`;

        container.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /** 执行搜索过滤 */
    filterLibrary(query) {
        const q = query.toLowerCase();
        document.querySelectorAll('.library-item').forEach(item => {
            const text = item.textContent.toLowerCase();
            const id = item.dataset.nodeType.toLowerCase();
            item.style.display = (text.includes(q) || id.includes(q)) ? 'flex' : 'none';
        });
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = UIController;
}
