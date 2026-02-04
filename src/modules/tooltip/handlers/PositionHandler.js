/**
 * 位置计算器
 * 负责计算tooltip的最佳显示位置和坐标
 */

export class PositionHandler {
    /**
     * 构造函数
     * @param {Object} config - 配置管理器实例
     */
    constructor(config) {
        this.config = config;
        this.offset = 10; // 默认偏移量
        this.viewportMargin = 10; // 视口边距
    }

    /**
     * 计算最佳位置
     * @param {HTMLElement} targetElement - 目标元素
     * @param {HTMLElement} tooltipElement - tooltip元素
     * @param {string} preferredPosition - 首选位置
     * @returns {Object} 位置信息
     */
    calculatePosition(targetElement, tooltipElement, preferredPosition = 'auto') {
        const targetRect = targetElement.getBoundingClientRect();
        const tooltipRect = tooltipElement.getBoundingClientRect();
        const viewport = this.getViewportDimensions();
        
        let position;
        
        if (preferredPosition === 'auto') {
            position = this.getAutoPosition(targetRect, tooltipRect, viewport);
        } else {
            position = this.validatePosition(preferredPosition, targetRect, tooltipRect, viewport);
        }
        
        const coordinates = this.calculateCoordinates(targetRect, tooltipRect, position);
        
        return {
            top: coordinates.top,
            left: coordinates.left,
            placement: position
        };
    }

    /**
     * 获取视口尺寸信息
     * @returns {Object} 视口信息
     */
    getViewportDimensions() {
        return {
            width: window.innerWidth,
            height: window.innerHeight,
            scrollTop: window.scrollY || document.documentElement.scrollTop,
            scrollLeft: window.scrollX || document.documentElement.scrollLeft
        };
    }

    /**
     * 自动计算最佳位置
     * @param {DOMRect} targetRect - 目标元素矩形
     * @param {DOMRect} tooltipRect - tooltip元素矩形
     * @param {Object} viewport - 视口信息
     * @returns {string} 最佳位置
     */
    getAutoPosition(targetRect, tooltipRect, viewport) {
        const positions = ['top', 'bottom', 'left', 'right'];
        const availablePositions = positions.filter(position => 
            this.canFit(position, targetRect, tooltipRect, viewport)
        );
        
        // 如果没有可用位置，默认使用top
        if (availablePositions.length === 0) {
            return 'top';
        }
        
        // 优先选择不会遮挡目标元素的位置
        const preferredOrder = ['top', 'bottom', 'right', 'left'];
        return preferredOrder.find(pos => availablePositions.includes(pos)) || availablePositions[0];
    }

    /**
     * 验证指定位置是否可行
     * @param {string} position - 位置
     * @param {DOMRect} targetRect - 目标元素矩形
     * @param {DOMRect} tooltipRect - tooltip元素矩形
     * @param {Object} viewport - 视口信息
     * @returns {string} 可行的位置
     */
    validatePosition(position, targetRect, tooltipRect, viewport) {
        if (this.canFit(position, targetRect, tooltipRect, viewport)) {
            return position;
        }
        
        // 如果首选位置不可用，尝试其他位置
        const fallbackPositions = ['top', 'bottom', 'right', 'left']
            .filter(pos => pos !== position);
            
        for (const fallback of fallbackPositions) {
            if (this.canFit(fallback, targetRect, tooltipRect, viewport)) {
                return fallback;
            }
        }
        
        // 如果都不可用，返回首选位置（可能会超出边界）
        return position;
    }

    /**
     * 检查指定位置是否能容纳tooltip
     * @param {string} position - 位置
     * @param {DOMRect} targetRect - 目标元素矩形
     * @param {DOMRect} tooltipRect - tooltip元素矩形
     * @param {Object} viewport - 视口信息
     * @returns {boolean} 是否能容纳
     */
    canFit(position, targetRect, tooltipRect, viewport) {
        const offset = this.offset;
        const margin = this.viewportMargin;
        
        switch (position) {
            case 'top':
                return targetRect.top - tooltipRect.height - offset >= margin;
            case 'bottom':
                return targetRect.bottom + tooltipRect.height + offset <= viewport.height - margin;
            case 'left':
                return targetRect.left - tooltipRect.width - offset >= margin;
            case 'right':
                return targetRect.right + tooltipRect.width + offset <= viewport.width - margin;
            default:
                return false;
        }
    }

    /**
     * 计算具体坐标
     * @param {DOMRect} targetRect - 目标元素矩形
     * @param {DOMRect} tooltipRect - tooltip元素矩形
     * @param {string} position - 位置
     * @returns {Object} 坐标信息
     */
    calculateCoordinates(targetRect, tooltipRect, position) {
        const offset = this.offset;
        let top, left;
        
        switch (position) {
            case 'top':
                top = targetRect.top - tooltipRect.height - offset;
                left = targetRect.left + (targetRect.width - tooltipRect.width) / 2;
                break;
            case 'bottom':
                top = targetRect.bottom + offset;
                left = targetRect.left + (targetRect.width - tooltipRect.width) / 2;
                break;
            case 'left':
                top = targetRect.top + (targetRect.height - tooltipRect.height) / 2;
                left = targetRect.left - tooltipRect.width - offset;
                break;
            case 'right':
                top = targetRect.top + (targetRect.height - tooltipRect.height) / 2;
                left = targetRect.right + offset;
                break;
            default:
                // 默认为top位置
                top = targetRect.top - tooltipRect.height - offset;
                left = targetRect.left + (targetRect.width - tooltipRect.width) / 2;
        }
        
        // 确保不超出视口边界
        return this.constrainToViewport(left, top, tooltipRect);
    }

    /**
     * 约束坐标到视口范围内
     * @param {number} left - 左侧坐标
     * @param {number} top - 顶部坐标
     * @param {DOMRect} tooltipRect - tooltip元素矩形
     * @returns {Object} 约束后的坐标
     */
    constrainToViewport(left, top, tooltipRect) {
        const viewport = this.getViewportDimensions();
        const margin = this.viewportMargin;
        
        // 约束左侧边界
        if (left < margin) {
            left = margin;
        } else if (left + tooltipRect.width > viewport.width - margin) {
            left = viewport.width - tooltipRect.width - margin;
        }
        
        // 约束顶部边界
        if (top < margin) {
            top = margin;
        } else if (top + tooltipRect.height > viewport.height - margin) {
            top = viewport.height - tooltipRect.height - margin;
        }
        
        return { left, top };
    }

    /**
     * 计算箭头位置
     * @param {string} placement - tooltip放置位置
     * @param {DOMRect} targetRect - 目标元素矩形
     * @param {Object} tooltipPosition - tooltip坐标
     * @returns {Object} 箭头位置信息
     */
    calculateArrowPosition(placement, targetRect, tooltipPosition) {
        const arrowSize = 8; // 箭头大小
        let arrowTop, arrowLeft;
        
        switch (placement) {
            case 'top':
                arrowTop = tooltipPosition.top + this.config.get('maxWidth') - arrowSize;
                arrowLeft = targetRect.left + targetRect.width / 2;
                break;
            case 'bottom':
                arrowTop = tooltipPosition.top;
                arrowLeft = targetRect.left + targetRect.width / 2;
                break;
            case 'left':
                arrowTop = targetRect.top + targetRect.height / 2;
                arrowLeft = tooltipPosition.left + this.config.get('maxWidth') - arrowSize;
                break;
            case 'right':
                arrowTop = targetRect.top + targetRect.height / 2;
                arrowLeft = tooltipPosition.left;
                break;
            default:
                arrowTop = 0;
                arrowLeft = 0;
        }
        
        return { top: arrowTop, left: arrowLeft };
    }

    /**
     * 更新偏移量
     * @param {number} newOffset - 新的偏移量
     */
    setOffset(newOffset) {
        if (typeof newOffset === 'number' && newOffset >= 0) {
            this.offset = newOffset;
        }
    }

    /**
     * 更新视口边距
     * @param {number} newMargin - 新的边距
     */
    setViewportMargin(newMargin) {
        if (typeof newMargin === 'number' && newMargin >= 0) {
            this.viewportMargin = newMargin;
        }
    }
}