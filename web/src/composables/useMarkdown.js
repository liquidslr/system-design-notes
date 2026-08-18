import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        /* fall through */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

export function useMarkdown() {
  function render(content, basePath) {
    const html = md.render(content)
    const parser = new DOMParser()
    const doc = parser.parseFromString(`<div>${html}</div>`, 'text/html')
    const root = doc.body.firstChild

    root.querySelectorAll('img').forEach((img) => {
      const src = img.getAttribute('src')
      if (src && !src.startsWith('http') && !src.startsWith('/')) {
        const resolved = new URL(src, `${window.location.origin}${basePath}/`).pathname
        img.setAttribute('src', resolved)
      }
    })

    root.querySelectorAll('a').forEach((link) => {
      const href = link.getAttribute('href')
      if (href?.startsWith('http')) {
        link.setAttribute('target', '_blank')
        link.setAttribute('rel', 'noopener noreferrer')
      }
    })

    return root.innerHTML
  }

  return { render }
}
