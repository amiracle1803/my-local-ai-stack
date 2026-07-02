import { useState, useEffect, useRef } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { api } from '../api'

const TYPE_BADGE = {
  concept: 'b-blue', entity: 'b-purple',
  'source-summary': 'b-amber', comparison: 'b-green',
  overview: 'b-stone', log: 'b-stone',
}

export default function Search() {
  const [params]            = useSearchParams()
  const navigate            = useNavigate()
  const inputRef            = useRef(null)
  const [q, setQ]           = useState(params.get('q') || '')
  const [results, setRes]   = useState(null)
  const [loading, setLoad]  = useState(false)
  const [err, setErr]       = useState(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  useEffect(() => {
    const term = params.get('q') || ''
    setQ(term)
    if (!term) { setRes(null); return }
    setLoad(true); setErr(null)
    api.search(term)
      .then(d => setRes(d.results ?? []))
      .catch(e => setErr(e.message))
      .finally(() => setLoad(false))
  }, [params])

  function submit() {
    if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`)
  }

  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Search</h1>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        <input
          ref={inputRef}
          type="text"
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="Search wiki pages…"
          style={{ flex: 1, fontSize: 15 }}
        />
        <button className="btn btn-primary" onClick={submit}>Search</button>
      </div>

      {err     && <div className="alert alert-err">{err}</div>}
      {loading && <div className="loading-row"><div className="spinner" />Searching…</div>}

      {!loading && results !== null && (
        results.length === 0
          ? <div className="empty-state"><strong>No results</strong>Try a different term.</div>
          : (
            <div>
              <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
                {results.length} result{results.length !== 1 ? 's' : ''} for{' '}
                <strong style={{ color: 'var(--ink)' }}>"{params.get('q')}"</strong>
              </p>
              <div className="card" style={{ padding: 0 }}>
                {results.map((r, i) => (
                  <Link key={r.path} to={`/${r.path}`}
                    className="row-link"
                    style={{ padding: '14px 20px', display: 'block', borderBottom: i < results.length - 1 ? '1px solid var(--rule)' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: r.snippet ? 6 : 0 }}>
                      <span className={`badge ${TYPE_BADGE[r.type] || 'b-stone'}`}>{r.type || '—'}</span>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{r.title}</span>
                      <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--faint)', fontFamily: 'var(--mono)', flexShrink: 0 }}>{r.updated}</span>
                    </div>
                    {r.snippet && (
                      <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}
                        dangerouslySetInnerHTML={{ __html: r.snippet }} />
                    )}
                  </Link>
                ))}
              </div>
            </div>
          )
      )}

      {!loading && results === null && !params.get('q') && (
        <p style={{ color: 'var(--muted)', fontSize: 14 }}>Type a term and press Enter.</p>
      )}
    </div>
  )
}
