import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import Markdown from '../components/Markdown'

const TYPE_BADGE = {
  concept: 'b-blue', entity: 'b-purple',
  'source-summary': 'b-amber', comparison: 'b-green',
  overview: 'b-stone', log: 'b-stone',
}
const CONF_BADGE = { high: 'b-green', medium: 'b-amber', low: 'b-red' }

function FmBox({ fm }) {
  if (!fm) return null
  const simpleFields = ['type', 'confidence', 'created', 'updated']
  return (
    <div className="fm-box">
      {simpleFields.filter(k => fm[k]).map(k => (
        <div key={k}>
          <span className="fm-k">{k}</span>
          <span style={{ color: 'var(--faint)' }}>: </span>
          <span className="fm-v">{fm[k]}</span>
        </div>
      ))}
      {fm.sources?.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <span className="fm-k">sources</span>
          <span style={{ color: 'var(--faint)' }}>:</span>
          {fm.sources.map((s, i) => <span key={i} className="fm-list-item">{s}</span>)}
        </div>
      )}
      {fm.related?.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <span className="fm-k">related</span>
          <span style={{ color: 'var(--faint)' }}>:</span>
          {fm.related.map((r, i) => {
            const slug = r.replace(/^wiki\//, '').replace(/\.md$/, '')
            return (
              <span key={i} className="fm-list-item">
                <Link to={`/wiki/${slug}`}>{slug}</Link>
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function WikiPage() {
  const { '*': wild } = useParams()
  const [data, setData] = useState(null)
  const [err,  setErr]  = useState(null)

  useEffect(() => {
    setData(null); setErr(null)
    api.page(wild || '').then(setData).catch(e => setErr(e.message))
  }, [wild])

  if (err) return (
    <div>
      <div className="alert alert-err">Page not found: {err}</div>
      <Link to="/wiki" className="btn btn-ghost btn-sm">← All pages</Link>
    </div>
  )

  if (!data) return <div className="loading-row"><div className="spinner" />Loading…</div>

  const { frontmatter: fm, content } = data

  return (
    <div>
      <div className="pg-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
          {fm?.type       && <span className={`badge ${TYPE_BADGE[fm.type] || 'b-stone'}`}>{fm.type}</span>}
          {fm?.confidence && <span className={`badge ${CONF_BADGE[fm.confidence] || 'b-stone'}`}>{fm.confidence} confidence</span>}
        </div>
        <h1 className="pg-title">{fm?.title || wild}</h1>
      </div>

      <FmBox fm={fm} />
      <Markdown text={content || ''} />
    </div>
  )
}
