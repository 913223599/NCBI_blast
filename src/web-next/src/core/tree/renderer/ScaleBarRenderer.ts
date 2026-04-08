/**
 * 缩放比例条渲染器 - 负责在 Canvas 上绘制比例尺
 */
export class ScaleBarRenderer {
    private canvas: HTMLCanvasElement | null = null
    private ctx: CanvasRenderingContext2D | null = null

    constructor(canvas: HTMLCanvasElement) {
        this.canvas = canvas
        this.ctx = canvas.getContext('2d')
    }

    render(scale: number) {
        if (!this.ctx || !this.canvas) return
        const dpr = window.devicePixelRatio || 1
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        const units = Math.pow(10, Math.floor(Math.log10(100 / scale)))
        const pw = units * scale
        const x = 60, y = (this.canvas.height / dpr) - 60

        // 背景卡片
        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.7)'
        this.ctx.beginPath()
        this.ctx.roundRect(x - 10, y - 25, pw + 20, 45, 8)
        this.ctx.fill()

        // 比例尺线条
        this.ctx.strokeStyle = '#1e293b'
        this.ctx.lineWidth = 1.5
        this.ctx.beginPath()
        this.ctx.moveTo(x, y)
        this.ctx.lineTo(x + pw, y)
        this.ctx.moveTo(x, y - 4)
        this.ctx.lineTo(x, y + 4)
        this.ctx.moveTo(x + pw, y - 4)
        this.ctx.lineTo(x + pw, y + 4)
        this.ctx.stroke()

        // 文字标签
        this.ctx.fillStyle = '#1e293b'
        this.ctx.font = 'bold 11px Inter, sans-serif'
        this.ctx.textAlign = 'center'
        this.ctx.fillText(`${units.toFixed(units < 0.1 ? 3 : 2)} sub/site`, x + pw / 2, y - 8)
    }

    dispose() {
        this.canvas = null
        this.ctx = null
    }
}
