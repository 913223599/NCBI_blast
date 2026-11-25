/**
 * 安全 HTML 净化与轻量化帮助文档 Markdown 渲染工具
 * 遵循 Modern Web Guidance `sanitize-untrusted-html` 与 `replaceChildren` 准则：
 * 1. 优先特性检测原生 Sanitizer API (`Element.prototype.setHTML`)
 * 2. 在不支持的内核中通过浏览器原生 DOMParser 白名单节点净化（零外部依赖，匹配 KEEP_CONTENT: false 语义）
 */

export interface MarkdownHeading {
  id: string
  level: number
  text: string
}

const ALLOWED_TAGS = new Set([
  'h1', 'h2', 'h3', 'h4', 'p', 'br', 'hr',
  'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
  'strong', 'b', 'em', 'i', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span',
])

const ALLOWED_ATTRS: Record<string, Set<string>> = {
  a: new Set(['href', 'title', 'target', 'rel']),
  code: new Set(['class']),
  span: new Set(['class']),
  h1: new Set(['id']),
  h2: new Set(['id']),
  h3: new Set(['id']),
  h4: new Set(['id']),
}

const SAFE_HEADING_ID_RE = /^help-sec-\d+$/

function isSafeHref(url: string): boolean {
  const trimmed = url.trim().toLowerCase()
  return (
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('#') ||
    trimmed.startsWith('/')
  )
}

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function stripInlineMarkdown(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .trim()
}

function renderInlineMarkdown(line: string): string {
  let out = escapeHtml(line)
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label: string, href: string) => {
    if (!isSafeHref(href)) return label
    return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`
  })
  return out
}

/**
 * 提取 Markdown 标题大纲（跳过围栏代码块，与 markdownToHtml 生成的锚点 id 严格一一对应）
 */
export function extractMarkdownHeadings(markdown: string): MarkdownHeading[] {
  if (!markdown) return []
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const headings: MarkdownHeading[] = []
  let inCodeBlock = false
  let headingIdx = 0

  for (const rawLine of lines) {
    const trimmed = rawLine.trim()
    if (trimmed.startsWith('```')) {
      inCodeBlock = !inCodeBlock
      continue
    }
    if (inCodeBlock) continue

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      headingIdx += 1
      headings.push({
        id: `help-sec-${headingIdx}`,
        level: heading[1]!.length,
        text: stripInlineMarkdown(heading[2]!),
      })
    }
  }
  return headings
}

/**
 * 将帮助手册 Markdown 转为受控语义 HTML（对内联原始 HTML 先按文本转义后再过白名单净化）
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) return ''
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const blocks: string[] = []
  let inCodeBlock = false
  let codeLines: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let headingIdx = 0

  const closeList = () => {
    if (listType) {
      blocks.push(`</${listType}>`)
      listType = null
    }
  }

  for (const rawLine of lines) {
    if (rawLine.trim().startsWith('```')) {
      closeList()
      if (!inCodeBlock) {
        inCodeBlock = true
        codeLines = []
      } else {
        blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
        inCodeBlock = false
      }
      continue
    }
    if (inCodeBlock) {
      codeLines.push(rawLine)
      continue
    }

    const trimmed = rawLine.trim()
    if (!trimmed) {
      closeList()
      continue
    }

    if (/^---+$/.test(trimmed)) {
      closeList()
      blocks.push('<hr />')
      continue
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      closeList()
      headingIdx += 1
      const level = heading[1]!.length
      blocks.push(`<h${level} id="help-sec-${headingIdx}">${renderInlineMarkdown(heading[2]!)}</h${level}>`)
      continue
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/)
    if (ulMatch) {
      if (listType !== 'ul') {
        closeList()
        blocks.push('<ul>')
        listType = 'ul'
      }
      blocks.push(`<li>${renderInlineMarkdown(ulMatch[1]!)}</li>`)
      continue
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/)
    if (olMatch) {
      if (listType !== 'ol') {
        closeList()
        blocks.push('<ol>')
        listType = 'ol'
      }
      blocks.push(`<li>${renderInlineMarkdown(olMatch[1]!)}</li>`)
      continue
    }

    const quoteMatch = trimmed.match(/^>\s+(.+)$/)
    if (quoteMatch) {
      closeList()
      blocks.push(`<blockquote><p>${renderInlineMarkdown(quoteMatch[1]!)}</p></blockquote>`)
      continue
    }

    closeList()
    blocks.push(`<p>${renderInlineMarkdown(trimmed)}</p>`)
  }

  if (inCodeBlock) {
    blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
  }
  closeList()
  return blocks.join('\n')
}

function sanitizeNode(node: Node, targetDoc: Document): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return targetDoc.createTextNode(node.textContent || '')
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null
  }
  const el = node as Element
  const tag = el.tagName.toLowerCase()
  if (!ALLOWED_TAGS.has(tag)) {
    // 对齐原生 Sanitizer API 行为：不在白名单内的危险标签连同内容一并移除
    return null
  }

  const cleanEl = targetDoc.createElement(tag)
  const allowedForTag = ALLOWED_ATTRS[tag]
  if (allowedForTag) {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase()
      if (!allowedForTag.has(name)) continue
      if (name === 'href' && !isSafeHref(attr.value)) continue
      if (name === 'id' && !SAFE_HEADING_ID_RE.test(attr.value)) continue
      cleanEl.setAttribute(name, attr.value)
    }
  }

  for (const child of Array.from(el.childNodes)) {
    const cleanChild = sanitizeNode(child, targetDoc)
    if (cleanChild) cleanEl.appendChild(cleanChild)
  }
  return cleanEl
}

/**
 * 将不受信任的 HTML 片段安全渲染到目标容器（原生 setHTML 优先 + DOMParser 白名单回退）
 */
export function safeSetHTML(container: HTMLElement, rawHtml: string): void {
  const anyEl = container as HTMLElement & {
    setHTML?: (html: string, options?: { sanitizer?: { elements?: string[]; attributes?: string[] } }) => void
  }
  if ('setHTML' in Element.prototype && typeof anyEl.setHTML === 'function') {
    anyEl.setHTML(rawHtml, {
      sanitizer: {
        elements: Array.from(ALLOWED_TAGS),
        attributes: ['href', 'title', 'target', 'rel', 'class', 'id'],
      },
    })
    return
  }

  const parser = new DOMParser()
  const parsed = parser.parseFromString(rawHtml, 'text/html')
  const frag = document.createDocumentFragment()
  for (const child of Array.from(parsed.body.childNodes)) {
    const clean = sanitizeNode(child, document)
    if (clean) frag.appendChild(clean)
  }
  container.replaceChildren(frag)
}
