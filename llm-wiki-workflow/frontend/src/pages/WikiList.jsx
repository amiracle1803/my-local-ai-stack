import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

const TYPE_BADGE = {
  concept: 'b-blue', entity: 'b-purple',
  'source-summary': 'b-amber', comparison: 'b-green',
  overview: 'b-stone', log: 'b-stone',
}
const TYPES = ['all', 'concept', 'entity', 'source-summary', 'comparison']

export default function WikiList() {
  const [data,   setData]   = useState(null)
  const [filter, setFilter] = useState('all')
  const [q,      setQ]      = useState('')
  const [err,    setErr]    = useState(null)

  useEffect(() => {
    api.pages().then(setData).catch(e => setErr(e.message))
  }, [])

  const all = data?.pages ?? []
  const visible = all.filter(p => {
    if (filter !== 'all' && p.type !== filter) return false
    if (q && !p.title.toLowerCase().includes(q.toLowerCase())) return false
    return true
  })

  const grouped = TYPES.slice(1).reduce((acc, t) => {
    acc[t] = visible.filter(p => p.type === t)
    return acc
  }, {})
  const ungrouped = visible.filter(p => !TYPES.slice(1).includes(p.type))

  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Wiki Pages</h1>
        <p className="pg-sub">{data?.count ?? '…'} pages total</p>
      </div>

      {err && <div className="alert alert-err">{err}</div>}

      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="Filter by title…"
          value={q}
          onChange={e => setQ(e.target.value)}
          style={{ width: 260 }}
        />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {TYPES.map(t => (
            <button
              key={t}
              onClick={() => setFilter(t)}
              className={`btn btn-sm ${filter === t ? 'btn-primary' : 'btn-ghost'}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {!data
        ? <div className="loading-row"><div className="spinner" />Loading…</div>
        : visible.length === 0
          ? <div className="empty-state"><strong>No pages match</strong>Try a different filter.</div>
          : filter !== 'all'
            ? (
              <div className="card" style={{ padding: '4px 16px' }}>
                {visible.map(p => (
                  <Link key={p.path} to={`/${p.path}`} className="row-link">
                    <span className={`badge ${TYPE_BADGE[p.type] || 'b-stone'}`}>{p.type || '—'}</span>
                    <span className="row-title">{p.title}</span>
                    <span className="row-date">{p.updated}</span>
                  </Link>
                ))}
              </div>
            )
            : (
              <>
                {TYPES.slice(1).filter(t => grouped[t]?.length > 0).map(t => (
                  <div key={t} style={{ marginBottom: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <span className={`badge ${TYPE_BADGE[t]}`}>{t}</span>
                      <span style={{ fontSize: 12, color: 'var(--faint)' }}>{grouped[t].length}</span>
                    </div>
                    <div className="card" style={{ padding: '4px 16px' }}>
                      {grouped[t].map(p => (
                        <Link key={p.path} to={`/${p.path}`} className="row-link">
                          <span className="row-title">{p.title}</span>
                          <span className="row-date">{p.updated}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                ))}
                {ungrouped.length > 0 && (
                  <div className="card" style={{ padding: '4px 16px' }}>
                    {ungrouped.map(p => (
                      <Link key={p.path} to={`/${p.path}`} className="row-link">
                        <span className={`badge ${TYPE_BADGE[p.type] || 'b-stone'}`}>{p.type || '—'}</span>
                        <span className="row-title">{p.title}</span>
                        <span className="row-date">{p.updated}</span>
                      </Link>
                    ))}
                  </div>
                )}
              </>
            )
      }
    </div>
  )
}
