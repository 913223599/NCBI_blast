/**
 * 渲染引擎
 * 负责tooltip的渲染、动画和视觉效果管理
 */

export class Renderer {
    /**
     * 构造函数
     * @param {Object} domAdapter - DOM适配器实例
     * @param {Object} positionHandler - 位置处理器实例
     * @param {Object} config - 配置管理器实例
     */
    constructor(domAdapter, positionHandler, config) {
        this.domAdapter = domAdapter;
        this.positionHandler = positionHandler;
        this.config = config;
        this.animationFrame = null;
        this.isVisible = false;
    }

    /**
     * 渲染tooltip
     * @param {HTMLElement} targetElement - 目标元素
     * @param {string} content - tooltip内容
     */
    render(targetElement, content) {
        // 确保DOM元素存在
        this.domAdapter.createTooltipElement();
        
        // 设置内容
        this.domAdapter.setContent(content);
        
        // 添加到容器
        const container = this.config.getContainer();
        this.domAdapter.appendTo(container);
        
        // 计算位置
        const tooltipElement = this.domAdapter.getTooltipElement();
        const position = this.positionHandler.calculatePosition(
            targetElement, 
            tooltipElement, 
            this.config.get('position')
        );
        
        // 设置位置
        this.domAdapter.setPosition(position.top, position.left);
        
        // 设置箭头位置
        const arrowPosition = this.positionHandler.calculateArrowPosition(
            position.placement, 
            targetElement.getBoundingClientRect(), 
            position
        );
        this.domAdapter.setArrowPosition(arrowPosition.top, arrowPosition.left);
        
        // 添加位置类
        this.domAdapter.addClass(`tooltip-placement-${position.placement}`);
        
        // 显示tooltip
        this.show();
    }

    /**
     * 显示tooltip
     */
    show() {
        if (this.isVisible) return;
        
        this.isVisible = true;
        this.domAdapter.show();
        
        // 触发动画
        if (this.config.isAnimationEnabled()) {
            this.animateShow();
        }
    }

    /**
     * 隐藏tooltip
     */
    hide() {
        if (!this.isVisible) return;
        
        this.isVisible = false;
        
        // 触发动画
        if (this.config.isAnimationEnabled()) {
            this.animateHide();
        } else {
            this.domAdapter.hide();
        }
    }

    /**
     * 显示动画
     */
    animateShow() {
        const tooltip = this.domAdapter.getTooltipElement();
        if (!tooltip) return;
        
        // 重置动画状态
        tooltip.style.opacity = '0';
        tooltip.style.transform = 'scale(0.8)';
        
        // 强制重排
        tooltip.offsetHeight;
        
        // 执行动画
        tooltip.style.transition = 'all 0.2s ease-out';
        tooltip.style.opacity = '1';
        tooltip.style.transform = 'scale(1)';
    }

    /**
     * 隐藏动画
     */
    animateHide() {
        const tooltip = this.domAdapter.getTooltipElement();
        if (!tooltip) return;
        
        tooltip.style.transition = 'all 0.15s ease-in';
        tooltip.style.opacity = '0';
        tooltip.style.transform = 'scale(0.8)';
        
        // 动画结束后隐藏元素
        setTimeout(() => {
            if (!this.isVisible) {
                this.domAdapter.hide();
            }
        }, 150);
    }

    /**
     * 更新tooltip位置
     * @param {HTMLElement} targetElement - 目标元素
     */
    updatePosition(targetElement) {
        if (!this.isVisible) return;
        
        const tooltipElement = this.domAdapter.getTooltipElement();
        if (!tooltipElement) return;
        
        const position = this.positionHandler.calculatePosition(
            targetElement, 
            tooltipElement, 
            this.config.get('position')
        );
        
        this.domAdapter.setPosition(position.top, position.left);
        
        // 更新箭头位置
        const arrowPosition = this.positionHandler.calculateArrowPosition(
            position.placement, 
            targetElement.getBoundingClientRect(), 
            position
        );
        this.domAdapter.setArrowPosition(arrowPosition.top, arrowPosition.left);
        
        // 更新位置类
        this.updatePlacementClass(position.placement);
    }

    /**
     * 更新位置CSS类
     * @param {string} newPlacement - 新的位置
     */
    updatePlacementClass(newPlacement) {
        const tooltip = this.domAdapter.getTooltipElement();
        if (!tooltip) return;
        
        // 移除旧的位置类
        const oldClasses = Array.from(tooltip.classList).filter(cls => 
            cls.startsWith('tooltip-placement-')
        );
        oldClasses.forEach(cls => tooltip.classList.remove(cls));
        
        // 添加新的位置类
        tooltip.classList.add(`tooltip-placement-${newPlacement}`);
    }

    /**
     * 更新主题
     */
    updateTheme() {
        const theme = this.config.getTheme();
        this.domAdapter.setTheme(theme);
    }

    /**
     * 更新配置
     * @param {Object} newOptions - 新的配置选项
     */
    updateConfig(newOptions) {
        // 更新主题
        if (newOptions.theme !== undefined) {
            this.updateTheme();
        }
        
        // 更新最大宽度
        if (newOptions.maxWidth !== undefined) {
            const tooltip = this.domAdapter.getTooltipElement();
            if (tooltip) {
                tooltip.style.maxWidth = `${newOptions.maxWidth}px`;
            }
        }
        
        // 更新动画设置
        if (newOptions.animation !== undefined) {
            const tooltip = this.domAdapter.getTooltipElement();
            if (tooltip) {
                if (newOptions.animation) {
                    tooltip.classList.add('tooltip-animate');
                } else {
                    tooltip.classList.remove('tooltip-animate');
                }
            }
        }
    }

    /**
     * 检查是否可见
     * @returns {boolean} 是否可见
     */
    isVisible() {
        return this.isVisible;
    }

    /**
     * 获取当前内容
     * @returns {string} 当前显示的内容
     */
    getCurrentContent() {
        const contentElement = this.domAdapter.getContentElement();
        return contentElement ? contentElement.textContent : '';
    }

    /**
     * 预渲染内容（用于性能优化）
     * @param {string} content - 要预渲染的内容
     */
    preloadContent(content) {
        // 创建临时元素进行预渲染
        const tempElement = document.createElement('div');
        tempElement.style.position = 'absolute';
        tempElement.style.visibility = 'hidden';
        tempElement.style.pointerEvents = 'none';
        tempElement.innerHTML = content;
        
        document.body.appendChild(tempElement);
        
        // 强制渲染
        tempElement.offsetHeight;
        
        // 清理
        document.body.removeChild(tempElement);
    }

    /**
     * 销毁渲染器
     */
    destroy() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        
        this.isVisible = false;
    }
}