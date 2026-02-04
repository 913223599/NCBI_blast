/**
 * 事件处理器
 * 负责管理所有的事件监听和触发逻辑
 */

export class EventHandler {
    /**
     * 构造函数
     * @param {Object} tooltipManager - Tooltip管理器实例
     */
    constructor(tooltipManager) {
        this.tooltipManager = tooltipManager;
        this.activeElement = null;
        this.timer = null;
        this.isTouchDevice = this.detectTouchDevice();
        this.boundHandlers = new Map();
    }

    /**
     * 检测是否为触摸设备
     * @returns {boolean} 是否为触摸设备
     */
    detectTouchDevice() {
        return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    }

    /**
     * 绑定事件监听器
     * @param {HTMLElement} element - 目标元素
     * @param {string} eventType - 事件类型
     * @param {Function} handler - 事件处理函数
     */
    bind(element, eventType, handler) {
        const key = `${eventType}_${this.getUniqueKey(element)}`;
        const boundHandler = handler.bind(this.tooltipManager);
        
        element.addEventListener(eventType, boundHandler);
        this.boundHandlers.set(key, { element, eventType, handler: boundHandler });
    }

    /**
     * 解绑事件监听器
     * @param {HTMLElement} element - 目标元素
     * @param {string} eventType - 事件类型
     */
    unbind(element, eventType) {
        const key = `${eventType}_${this.getUniqueKey(element)}`;
        const binding = this.boundHandlers.get(key);
        
        if (binding) {
            binding.element.removeEventListener(binding.eventType, binding.handler);
            this.boundHandlers.delete(key);
        }
    }

    /**
     * 获取元素的唯一标识
     * @param {HTMLElement} element - DOM元素
     * @returns {string} 唯一标识符
     */
    getUniqueKey(element) {
        return element.dataset.tooltipId || (element.dataset.tooltipId = Math.random().toString(36).substr(2, 9));
    }

    /**
     * 处理鼠标进入事件
     * @param {Event} event - 鼠标事件
     */
    handleMouseEnter(event) {
        const element = event.currentTarget;
        const content = this.getContentFromElement(element);
        
        if (!content) return;
        
        // 清除之前的定时器
        this.clearTimer();
        
        // 设置新的定时器
        this.timer = setTimeout(() => {
            this.tooltipManager.show(element, content);
            this.activeElement = element;
        }, this.tooltipManager.config.get('delay'));
    }

    /**
     * 处理鼠标离开事件
     * @param {Event} event - 鼠标事件
     */
    handleMouseLeave(event) {
        this.clearTimer();
        this.tooltipManager.hide();
        this.activeElement = null;
    }

    /**
     * 处理触摸开始事件
     * @param {Event} event - 触摸事件
     */
    handleTouchStart(event) {
        const element = event.currentTarget;
        const content = this.getContentFromElement(element);
        
        if (!content) return;
        
        // 阻止默认行为
        event.preventDefault();
        
        // 立即显示tooltip
        this.clearTimer();
        this.tooltipManager.show(element, content);
        this.activeElement = element;
        
        // 设置自动隐藏定时器
        this.timer = setTimeout(() => {
            this.tooltipManager.hide();
            this.activeElement = null;
        }, 3000); // 3秒后自动隐藏
    }

    /**
     * 处理触摸结束事件
     * @param {Event} event - 触摸事件
     */
    handleTouchEnd(event) {
        // 可以在这里添加触摸结束的处理逻辑
        event.preventDefault();
    }

    /**
     * 处理焦点进入事件
     * @param {Event} event - 焦点事件
     */
    handleFocus(event) {
        const element = event.currentTarget;
        const content = this.getContentFromElement(element);
        
        if (!content) return;
        
        this.tooltipManager.show(element, content);
        this.activeElement = element;
    }

    /**
     * 处理焦点离开事件
     * @param {Event} event - 焦点事件
     */
    handleBlur(event) {
        this.tooltipManager.hide();
        this.activeElement = null;
    }

    /**
     * 从元素中获取提示内容
     * @param {HTMLElement} element - 目标元素
     * @returns {string|null} 提示内容
     */
    getContentFromElement(element) {
        // 方法1: data-i18n-help 属性
        const helpKey = element.getAttribute('data-i18n-help');
        if (helpKey && this.tooltipManager.config.get('translations')) {
            return this.tooltipManager.config.get('translations')[helpKey];
        }
        
        // 方法2: title 属性
        const title = element.getAttribute('title');
        if (title) {
            return title;
        }
        
        // 方法3: data-tooltip 属性
        const tooltip = element.getAttribute('data-tooltip');
        if (tooltip) {
            return tooltip;
        }
        
        // 方法4: aria-label 属性
        const ariaLabel = element.getAttribute('aria-label');
        if (ariaLabel) {
            return ariaLabel;
        }
        
        return null;
    }

    /**
     * 清除定时器
     */
    clearTimer() {
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    /**
     * 添加全局事件监听器
     */
    addGlobalListeners() {
        // 监听滚动和窗口大小变化，用于隐藏tooltip
        const hideTooltip = () => {
            if (this.activeElement) {
                this.tooltipManager.hide();
                this.activeElement = null;
            }
        };
        
        window.addEventListener('scroll', hideTooltip, true);
        window.addEventListener('resize', hideTooltip);
        document.addEventListener('mousedown', hideTooltip);
        
        // 存储清理函数
        this.cleanup = () => {
            window.removeEventListener('scroll', hideTooltip, true);
            window.removeEventListener('resize', hideTooltip);
            document.removeEventListener('mousedown', hideTooltip);
        };
    }

    /**
     * 移除全局事件监听器
     */
    removeGlobalListeners() {
        if (this.cleanup) {
            this.cleanup();
            this.cleanup = null;
        }
    }

    /**
     * 销毁事件处理器
     */
    destroy() {
        this.clearTimer();
        this.removeGlobalListeners();
        this.boundHandlers.clear();
    }
}