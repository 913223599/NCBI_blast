export class TreeExporter {
  static downloadText(content: string, filename: string, mime = 'text/plain;charset=utf-8'): void {
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  static exportSVG(svgEl: SVGSVGElement | null, filename = 'phylo_tree.svg'): void {
    if (!svgEl) return
    const xml = new XMLSerializer().serializeToString(svgEl)
    this.downloadText(xml, filename, 'image/svg+xml;charset=utf-8')
  }

  static async exportPNG(svgEl: SVGSVGElement | null, filename = 'phylo_tree_300dpi.png'): Promise<void> {
    if (!svgEl) return
    const rawW = Number(svgEl.getAttribute('width')) || 800
    const rawH = Number(svgEl.getAttribute('height')) || 600
    // 若图极其庞大，自动控制最大像素尺寸避免浏览器 Canvas 溢出
    const maxDim = 8192
    const targetScale = Math.min(3, maxDim / Math.max(rawW, rawH))
    const scale = Math.max(1, targetScale)

    const xml = new XMLSerializer().serializeToString(svgEl)
    const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(svgBlob)

    try {
      const img = new Image()
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('SVG 光栅化失败'))
        img.src = url
      })
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(rawW * scale)
      canvas.height = Math.round(rawH * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.scale(scale, scale)
      ctx.drawImage(img, 0, 0, rawW, rawH)

      const pngUrl = canvas.toDataURL('image/png')
      const a = document.createElement('a')
      a.href = pngUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } finally {
      URL.revokeObjectURL(url)
    }
  }
}
