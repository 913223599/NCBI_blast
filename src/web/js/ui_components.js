/**
 * Bio-Station WebOS UI Components
 * Custom Select System (v1.0)
 */

class CustomSelect {
    constructor(originalSelect) {
        this.originalSelect = originalSelect;
        this.container = null;
        this.trigger = null;
        this.menu = null;
        this.isOpen = false;

        this._init();
    }

    _init() {
        // Hide original
        this.originalSelect.style.display = 'none';

        // Create container
        this.container = document.createElement('div');
        this.container.className = 'custom-select-container';
        if (this.originalSelect.className) {
            this.container.classList.add(...this.originalSelect.classList);
        }

        // Store instance for external syncing
        this.originalSelect.__customSelect = this;

        // Create trigger
        this.trigger = document.createElement('div');
        this.trigger.className = 'select-trigger';
        this.trigger.innerHTML = `<span class="curr-val"></span><i class="arrow"></i>`;

        // Create menu
        this.menu = document.createElement('div');
        this.menu.className = 'select-menu hidden';

        this.container.appendChild(this.trigger);
        this.container.appendChild(this.menu);

        // Insert after original
        this.originalSelect.parentNode.insertBefore(this.container, this.originalSelect.nextSibling);

        this._populate();
        this._bindEvents();
        this._updateDisplay();

        // Listen to external changes on original select
        this.originalSelect.addEventListener('change', () => this._updateDisplay());

        // MutationObserver to watch for dynamic option changes (like AI models)
        this.observer = new MutationObserver(() => {
            this._populate();
            this._updateDisplay();
        });
        this.observer.observe(this.originalSelect, {
            childList: true,
            characterData: true,
            subtree: true
        });
    }

    _populate() {
        this.menu.innerHTML = '';
        Array.from(this.originalSelect.options).forEach(opt => {
            const div = document.createElement('div');
            div.className = 'select-option';
            if (opt.selected) div.classList.add('selected');
            div.dataset.value = opt.value;
            div.innerText = opt.text;

            div.addEventListener('click', (e) => {
                e.stopPropagation();
                this._selectOption(opt.value);
                this.close();
            });

            this.menu.appendChild(div);
        });
    }

    _bindEvents() {
        this.trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });

        document.addEventListener('click', () => this.close());
    }

    _selectOption(value) {
        this.originalSelect.value = value;
        // Trigger original change event for backend/logic sync
        const event = new Event('change', { bubbles: true });
        this.originalSelect.dispatchEvent(event);
        this._updateDisplay();
    }

    _updateDisplay() {
        const selectedIndex = this.originalSelect.selectedIndex;
        const text = selectedIndex >= 0 ? this.originalSelect.options[selectedIndex].text : '请选择...';
        this.trigger.querySelector('.curr-val').innerText = text;

        // Update selection in menu
        Array.from(this.menu.querySelectorAll('.select-option')).forEach(div => {
            div.classList.toggle('selected', div.dataset.value === this.originalSelect.value);
        });
    }

    toggle() {
        this.isOpen ? this.close() : this.open();
    }

    open() {
        // Close all other open custom selects
        document.querySelectorAll('.select-menu').forEach(m => m.classList.add('hidden'));

        this.menu.classList.remove('hidden');
        this.container.classList.add('active');
        this.isOpen = true;
    }

    close() {
        this.menu.classList.add('hidden');
        this.container.classList.remove('active');
        this.isOpen = false;
    }

    /**
     * Static helper to init all selects
     */
    static initAll(selector = 'select.settings-input') {
        document.querySelectorAll(selector).forEach(sel => {
            if (!sel.hasAttribute('data-custom-select-initialized')) {
                new CustomSelect(sel);
                sel.setAttribute('data-custom-select-initialized', 'true');
            }
        });
    }

    /**
     * Force sync UI with original select
     */
    static sync(sel) {
        if (sel && sel.__customSelect) {
            sel.__customSelect._populate();
            sel.__customSelect._updateDisplay();
        }
    }
}

// Global expose
window.CustomSelect = CustomSelect;

/**
 * Global Help Tooltip Manager
 * Handles smart hover tooltips with defensive logic and collision detection.
 */
class HelpTooltipManager {
    constructor() {
        this.tooltip = null;
        this.timer = null;
        this.activeElement = null;
        this.translations = {};
        this.delay = 600;

        this._init();
    }

    _init() {
        this._createTooltipElement();
        this._bindEvents();
    }

    _createTooltipElement() {
        if (document.getElementById('global-help-tooltip')) {
            this.tooltip = document.getElementById('global-help-tooltip');
            return;
        }
        this.tooltip = document.createElement('div');
        this.tooltip.id = 'global-help-tooltip';
        this.tooltip.className = 'help-tooltip';
        this.tooltip.setAttribute('role', 'tooltip');
        document.body.appendChild(this.tooltip);
    }

    _bindEvents() {
        // Use event delegation for performance
        document.addEventListener('mouseover', (e) => this._handleMouseOver(e));
        document.addEventListener('mouseout', (e) => this._handleMouseOut(e));

        // Defensive: Hide on significant user actions
        const hideImmediately = () => this.hide();
        window.addEventListener('scroll', hideImmediately, true);
        window.addEventListener('resize', hideImmediately);
        document.addEventListener('mousedown', hideImmediately);
        document.addEventListener('contextmenu', hideImmediately);
    }

    _handleMouseOver(e) {
        const target = e.target.closest('[data-i18n-help]');
        if (!target) return;

        // If mouse moved between siblings with help, clear old timer
        if (this.activeElement !== target) {
            this.hide();
            this.activeElement = target;
        }

        const helpKey = target.getAttribute('data-i18n-help');
        const content = this.translations[helpKey];

        if (!content) return;

        this.timer = setTimeout(() => {
            this.show(target, content);
        }, this.delay);
    }

    _handleMouseOut(e) {
        const target = e.target.closest('[data-i18n-help]');
        if (!target) return;

        this.hide();
    }

    show(target, text) {
        this.tooltip.innerText = text;
        this.tooltip.classList.add('visible');

        // Accessibility
        const id = `help-${Math.random().toString(36).substr(2, 9)}`;
        this.tooltip.id = id;
        target.setAttribute('aria-describedby', id);

        this._positionTooltip(target);
    }

    hide() {
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        if (this.tooltip) {
            this.tooltip.classList.remove('visible');
        }
        if (this.activeElement) {
            this.activeElement.removeAttribute('aria-describedby');
            this.activeElement = null;
        }
    }

    _positionTooltip(target) {
        const targetRect = target.getBoundingClientRect();
        const tooltipRect = this.tooltip.getBoundingClientRect();
        const offset = 10;

        let top = targetRect.top - tooltipRect.height - offset;
        let left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);

        // Collision Detection: Top boundary
        if (top < 10) {
            // Flip to bottom
            top = targetRect.bottom + offset;
        }

        // Collision Detection: Left/Right boundary
        const viewportWidth = window.innerWidth;
        if (left < 10) left = 10;
        if (left + tooltipRect.width > viewportWidth - 10) {
            left = viewportWidth - tooltipRect.width - 10;
        }

        this.tooltip.style.top = `${top}px`;
        this.tooltip.style.left = `${left}px`;
    }

    /**
     * Update translations used by the manager
     */
    updateTranslations(translations) {
        this.translations = translations || {};
    }

    /**
     * Global Init
     */
    static init(translations) {
        if (!window.__helpTooltipManager) {
            window.__helpTooltipManager = new HelpTooltipManager();
        }
        if (translations) {
            window.__helpTooltipManager.updateTranslations(translations);
        }
        return window.__helpTooltipManager;
    }
}

/**
 * Global Dialog System
 * Simple, beautiful modal for branching choices.
 */
class BioDialog {
    static show(options) {
        const { title, message, choices, onSelect } = options;

        const overlay = document.createElement('div');
        overlay.className = 'dialog-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'dialog-box';

        dialog.innerHTML = `
            <div class="dialog-header">${title}</div>
            <div class="dialog-content">${message}</div>
            <div class="dialog-actions"></div>
        `;

        const actions = dialog.querySelector('.dialog-actions');
        choices.forEach(choice => {
            const btn = document.createElement('button');
            btn.className = `btn ${choice.type || 'btn-secondary'}`;
            btn.innerText = choice.text;
            btn.onclick = () => {
                document.body.removeChild(overlay);
                if (onSelect) onSelect(choice.id);
            };
            actions.appendChild(btn);
        });

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
    }
}

// Global expose
window.CustomSelect = CustomSelect;
window.HelpTooltipManager = HelpTooltipManager;
window.BioDialog = BioDialog;
