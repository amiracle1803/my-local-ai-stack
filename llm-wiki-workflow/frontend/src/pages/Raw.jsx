import { useState, useEffect } from 'react'
import { api } from '../api'

const TEXT_EXTS = new Set(['md', 'txt', 'json', 'csv', 'yaml', 'yml', 'toml', 'py', 'js', 'ts', 'html'])
const EXT_BADGE = { md: 'b-blue', txt: 'b-stone', json: 'b-green', csv: 'b-green', pdf: 'b-amber', png: 'b-purple', jpg: 'b-purple', svg: 'b-purple' }

function FileViewer({ path, onBack }) {
  const [text, setText] = useState(null)
  const [err,  setErr]  = useState(null)

  useEffect(() => {
    api.rawFile(path).then(d => setText(d.content)).catch(e => setErr(e.message))
  }, [path])

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 18 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back</button>
        <code style={{ fontSize: 12, color: 'var(--muted)' }}>{path}</code>
      </div>
      {err  && <div className="alert alert-err">{err}</div>}
      {!text && !err && <div className="loading-row"><div className="spinner" />Loading…</div>}
      {text  && <pre className="terminal" style={{ maxHeight: 600 }}>{text}</pre>}
    </div>
  )
}

export default function Raw() {
  const [data,   setData]   = useState(null)
  const [viewing, setView]  = useState(null)
  const [filter,  setFilter]= useState('')
  const [err,    setErr]    = useState(null)

  useEffect(() => {
    api.rawList().then(setData).catch(e => setErr(e.message))
  }, [])

  if (viewing) return <FileViewer path={viewing} onBack={() => setView(null)} />

  const groups = data?.groups ?? {}

  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Raw Sources</h1>
        <p className="pg-sub">Immutable source documents — never edited, only read</p>
      </div>

      {err && <div className="alert alert-err">{err}</div>}

      <div style={{ marginBottom: 20 }}>
        <input
          type="text"
          placeholder="Filter files…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{ width: 280 }}
        />
      </div>

      {!data && !err && <div className="loading-row"><div className="spinner" />Loading…</div>}

      {Object.keys(groups).map(dir => {
        const files = (groups[dir] || []).filter(f =>
          !filter || f.name.toLowerCase().includes(filter.toLowerCase())
        )
        if (files.length === 0) return null
        return (
          <div key={dir} style={{ marginBottom: 28 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>
              raw/{dir}/
              <span style={{ fontWeight: 400, marginLeft: 6, color: 'var(--faint)' }}>{files.length} files</span>
            </div>
            <div className="card" style={{ padding: '4px 16px' }}>
              {files.map(f => {
                const ext = f.name.split('.').pop().toLowerCase()
                const canView = TEXT_EXTS.has(ext)
                return (
                  <div
                    key={f.path}
                    className="row-link"
                    style={{ cursor: canView ? 'pointer' : 'default' }}
                    onClick={() => canView && setView(f.path)}
                  >
                    <span className={`badge ${EXT_BADGE[ext] || 'b-stone'}`}>{ext}</span>
                    <span className="row-title" style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{f.name}</span>
                    <span className="row-date">{f.size}</span>
                    {canView && <span style={{ fontSize: 11, color: 'var(--link)' }}>view</span>}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
