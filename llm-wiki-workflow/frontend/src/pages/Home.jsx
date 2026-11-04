import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import Markdown from '../components/Markdown'

const TYPE_BADGE = {
  concept: 'b-blue', entity: 'b-purple',
  'source-summary': 'b-amber', comparison: 'b-green',
  overview: 'b-stone', log: 'b-stone',
}

export default function Home() {
  const [pages,    setPages]    = useState(null)
  const [overview, setOverview] = useState(null)
  const [err,      setErr]      = useState(null)

  useEffect(() => {
    Promise.all([api.pages(), api.overview()])
      .then(([p, o]) => { setPages(p); setOverview(o) })
      .catch(e => setErr(e.message))
  }, [])

  if (err) return <div className="alert alert-err">Error: {err}</div>

  const all  = pages?.pages ?? []
  const byType = type => all.filter(p => p.type === type).length
  const recent = [...all].sort((a, b) => (b.updated || '').localeCompare(a.updated || '')).slice(0, 10)

  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Knowledge Base</h1>
        <p className="pg-sub">LLM-maintained wiki · ingest sources, query pages, stay current</p>
      </div>

      <div className="stats-row">
        {[
          { n: pages?.count ?? '…', l: 'Pages' },
          { n: byType('concept'),   l: 'Concepts' },
          { n: byType('entity'),    l: 'Entities' },
          { n: byType('source-summary'), l: 'Sources' },
          { n: byType('comparison'),l: 'Comparisons' },
        ].map(({ n, l }) => (
          <div className="stat-box" key={l}>
            <div className="stat-n">{n}</div>
            <div className="stat-l">{l}</div>
          </div>
        ))}
      </div>

      <div className="grid2">
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink2)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '.05em' }}>
            Recent pages
          </div>
          <div className="card" style={{ padding: '4px 16px' }}>
            {!pages
              ? <div className="loading-row"><div className="spinner" />Loading…</div>
              : recent.length === 0
                ? <div className="empty-state"><strong>No pages yet</strong>Start by ingesting a source.</div>
                : recent.map(p => (
                    <Link key={p.path} to={`/${p.path}`} className="row-link">
                      <span className={`badge ${TYPE_BADGE[p.type] || 'b-stone'}`}>{p.type || '—'}</span>
                      <span className="row-title">{p.title}</span>
                      <span className="row-date">{p.updated}</span>
                    </Link>
                  ))
            }
            {all.length > 10 && (
              <div style={{ padding: '10px 4px' }}>
                <Link to="/wiki" style={{ fontSize: 12, color: 'var(--accent)' }}>View all {all.length} pages →</Link>
              </div>
            )}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink2)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '.05em' }}>
            Overview
          </div>
          <div className="card">
            {!overview
              ? <div className="loading-row"><div className="spinner" />Loading…</div>
              : overview.error
                ? <p style={{ color: 'var(--muted)', fontSize: 13 }}>No overview yet. Ingest a source to get started.</p>
                : <Markdown text={overview.content} />
            }
          </div>
        </div>
      </div>

      <hr className="divider" style={{ marginTop: 28 }} />
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          <strong style={{ color: 'var(--ink2)' }}>Quick commands</strong>
          <span style={{ marginLeft: 10 }}>wiki-cli lint · wiki-cli index · agent-cli ingest raw/… · agent-cli query "…"</span>
        </div>
      </div>
    </div>
  )
}
