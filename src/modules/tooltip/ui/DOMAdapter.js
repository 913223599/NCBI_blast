/**
 * DOM操作适配器
 * 封装所有DOM相关的操作，提供统一的接口
 */

export class DOMAdapter {
    /**
     * 构造函数
     * @param {Object} config - 配置管理器实例
     */
    constructor(config) {
        this.config = config;
        this.tooltipElement = null;
        this.arrowElement = null;
    }

    /**
     * 创建tooltip元素
     * @returns {HTMLElement} tooltip元素
     */
    createTooltipElement() {
        if (this.tooltipElement) {
            return this.tooltipElement;
        }

        this.tooltipElement = document.createElement('div');
        this.tooltipElement.className = 'tooltip-module';
        this.tooltipElement.setAttribute('role', 'tooltip');
        this.tooltipElement.setAttribute('aria-hidden', 'true');
        
        // 添加主题类
        const theme = this.config.getTheme();
        this.tooltipElement.classList.add(`tooltip-${theme}`);
        
        // 设置最大宽度
        this.tooltipElement.style.maxWidth = `${this.config.get('maxWidth')}px`;
        
        // 创建箭头元素
        this.arrowElement = document.createElement('div');
        this.arrowElement.className = 'tooltip-arrow';
        this.tooltipElement.appendChild(this.arrowElement);
        
        // 创建内容容器
        const contentElement = document.createElement('div');
        contentElement.className = 'tooltip-content';
        this.tooltipElement.appendChild(contentElement);
        
        return this.tooltipElement;
    }

    /**
     * 获取tooltip元素
     * @returns {HTMLElement} tooltip元素
     */
    getTooltipElement() {
        if (!this.tooltipElement) {
            this.createTooltipElement();
        }
        return this.tooltipElement;
    }

    /**
     * 获取内容容器元素
     * @returns {HTMLElement} 内容容器
     */
    getContentElement() {
        const tooltip = this.getTooltipElement();
        return tooltip.querySelector('.tooltip-content');
    }

    /**
     * 获取箭头元素
     * @returns {HTMLElement} 箭头元素
     */
    getArrowElement() {
        if (!this.arrowElement) {
            this.createTooltipElement();
        }
        return this.arrowElement;
    }

    /**
     * 设置tooltip内容
     * @param {string} content - 要显示的内容
     */
    setContent(content) {
        const contentElement = this.getContentElement();
        if (contentElement) {
            // 处理HTML内容或纯文本
            if (this.isHTML(content)) {
                contentElement.innerHTML = content;
            } else {
                contentElement.textContent = content;
            }
        }
    }

    /**
     * 检查内容是否为HTML
     * @param {string} content - 内容字符串
     * @returns {boolean} 是否为HTML
     */
    isHTML(content) {
        const htmlPattern = /<[a-z][\s\S]*>/i;
        return htmlPattern.test(content);
    }

    /**
     * 显示tooltip
     */
    show() {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            tooltip.setAttribute('aria-hidden', 'false');
            tooltip.classList.add('tooltip-visible');
            
            // 触发动画
            if (this.config.isAnimationEnabled()) {
                tooltip.classList.add('tooltip-animate');
            }
        }
    }

    /**
     * 隐藏tooltip
     */
    hide() {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            tooltip.setAttribute('aria-hidden', 'true');
            tooltip.classList.remove('tooltip-visible');
            tooltip.classList.remove('tooltip-animate');
        }
    }

    /**
     * 设置tooltip位置
     * @param {number} top - 顶部坐标
     * @param {number} left - 左侧坐标
     */
    setPosition(top, left) {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            tooltip.style.top = `${top}px`;
            tooltip.style.left = `${left}px`;
        }
    }

    /**
     * 设置箭头位置
     * @param {number} top - 顶部坐标
     * @param {number} left - 左侧坐标
     */
    setArrowPosition(top, left) {
        const arrow = this.getArrowElement();
        if (arrow) {
            arrow.style.top = `${top}px`;
            arrow.style.left = `${left}px`;
        }
    }

    /**
     * 设置tooltip主题
     * @param {string} theme - 主题名称
     */
    setTheme(theme) {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            // 移除旧主题类
            tooltip.classList.remove('tooltip-light', 'tooltip-dark');
            // 添加新主题类
            tooltip.classList.add(`tooltip-${theme}`);
        }
    }

    /**
     * 添加到容器
     * @param {HTMLElement} container - 容器元素
     */
    appendTo(container) {
        const tooltip = this.getTooltipElement();
        if (tooltip && container) {
            // 确保只添加一次
            if (!tooltip.parentElement) {
                container.appendChild(tooltip);
            }
        }
    }

    /**
     * 从DOM中移除
     */
    remove() {
        if (this.tooltipElement && this.tooltipElement.parentElement) {
            this.tooltipElement.parentElement.removeChild(this.tooltipElement);
        }
        this.tooltipElement = null;
        this.arrowElement = null;
    }

    /**
     * 检查元素是否在视口中
     * @param {HTMLElement} element - 要检查的元素
     * @returns {boolean} 是否在视口中
     */
    isInViewport(element) {
        const rect = element.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    }

    /**
     * 获取元素相对于文档的位置
     * @param {HTMLElement} element - 目标元素
     * @returns {Object} 位置信息
     */
    getDocumentPosition(element) {
        const rect = element.getBoundingClientRect();
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        
        return {
            top: rect.top + scrollTop,
            left: rect.left + scrollLeft,
            width: rect.width,
            height: rect.height
        };
    }

    /**
     * 添加CSS类
     * @param {string} className - CSS类名
     */
    addClass(className) {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            tooltip.classList.add(className);
        }
    }

    /**
     * 移除CSS类
     * @param {string} className - CSS类名
     */
    removeClass(className) {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            tooltip.classList.remove(className);
        }
    }

    /**
     * 检查是否包含CSS类
     * @param {string} className - CSS类名
     * @returns {boolean} 是否包含该类
     */
    hasClass(className) {
        const tooltip = this.getTooltipElement();
        return tooltip ? tooltip.classList.contains(className) : false;
    }

    /**
     * 获取元素尺寸
     * @returns {Object} 尺寸信息
     */
    getSize() {
        const tooltip = this.getTooltipElement();
        if (tooltip) {
            return {
                width: tooltip.offsetWidth,
                height: tooltip.offsetHeight
            };
        }
        return { width: 0, height: 0 };
    }

    /**
     * 销毁DOM适配器
     */
    destroy() {
        this.remove();
    }
}