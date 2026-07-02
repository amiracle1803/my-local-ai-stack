import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { marked } from 'marked'

function preprocess(text) {
  // [[slug|label]] or [[slug]]
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, slug, label) => {
    const display = label || slug.split('/').pop().replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    return `[${display}](/wiki/${slug})`
  })
}

const renderer = new marked.Renderer()
renderer.link = ({ href, title, text }) => {
  const isExternal = href && (href.startsWith('http') || href.startsWith('//'))
  const extra = isExternal ? ' target="_blank" rel="noopener"' : ''
  return `<a href="${href || '#'}" title="${title || ''}"${extra}>${text}</a>`
}

marked.use({ renderer, gfm: true, breaks: false })

export default function Markdown({ text = '', className = 'doc' }) {
  const ref = useRef(null)
  const navigate = useNavigate()
  const html = marked.parse(preprocess(text))

  useEffect(() => {
    if (!ref.current) return
    const handlers = []
    ref.current.querySelectorAll('a[href^="/"]').forEach(a => {
      const h = e => { e.preventDefault(); navigate(a.getAttribute('href')) }
      a.addEventListener('click', h)
      handlers.push(() => a.removeEventListener('click', h))
    })
    return () => handlers.forEach(fn => fn())
  }, [html, navigate])

  return <div ref={ref} className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
