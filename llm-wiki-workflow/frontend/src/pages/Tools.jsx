import { useState } from 'react'
import { api } from '../api'

function ToolCard({ icon, title, desc, action, fields = [] }) {
  const [vals,   setVals]  = useState({})
  const [out,    setOut]   = useState('')
  const [busy,   setBusy]  = useState(false)
  const [status, setStat]  = useState(null) // 'ok' | 'err'

  async function run() {
    setBusy(true); setStat(null); setOut('')
    try {
      const d = await action(vals)
      setOut(d.output ?? JSON.stringify(d, null, 2))
      setStat('ok')
    } catch (e) {
      setOut(e.message)
      setStat('err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 14 }}>
        <span style={{ fontSize: 22, lineHeight: 1, marginTop: 1 }}>{icon}</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 3 }}>{title}</div>
          <div style={{ color: 'var(--muted)', fontSize: 12, lineHeight: 1.5 }}>{desc}</div>
        </div>
      </div>
      {fields.map(f => (
        <input
          key={f.key}
          type="text"
          placeholder={f.label}
          value={vals[f.key] || ''}
          onChange={e => setVals(v => ({ ...v, [f.key]: e.target.value }))}
          style={{ display: 'block', width: '100%', marginBottom: 8 }}
        />
      ))}
      <button className="btn btn-primary btn-sm" onClick={run} disabled={busy}>
        {busy ? 'Running…' : 'Run'}
      </button>
      {out && (
        <div style={{ marginTop: 12 }}>
          {status === 'err' && <div className="alert alert-err" style={{ marginBottom: 8 }}>{out}</div>}
          {status === 'ok'  && <pre className="terminal">{out}</pre>}
        </div>
      )}
    </div>
  )
}

export default function Tools() {
  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Wiki Tools</h1>
        <p className="pg-sub">Run maintenance commands from the browser</p>
      </div>

      <div className="grid2" style={{ gap: 16, marginBottom: 24 }}>
        <ToolCard
          icon="⊞"
          title="Rebuild Index"
          desc="Regenerate wiki/index.md from all page frontmatter. Run after creating or editing pages."
          action={() => api.tool('index')}
        />
        <ToolCard
          icon="⊙"
          title="Lint Wiki"
          desc="Check frontmatter schema, broken links, orphan pages, and stale entries."
          action={() => api.tool('lint')}
        />
        <ToolCard
          icon="≡"
          title="Append Log Entry"
          desc="Add a custom entry to wiki/log.md."
          fields={[
            { key: 'action', label: 'Action  (e.g. query, note)' },
            { key: 'title',  label: 'Title' },
            { key: 'note',   label: 'Note (optional)' },
          ]}
          action={v => api.tool('log', v)}
        />
        <ToolCard
          icon="⊕"
          title="CLI Search"
          desc="Run wiki.py search and return raw output."
          fields={[{ key: 'term', label: 'Search term' }]}
          action={v => api.tool('search', v)}
        />
      </div>

      <div className="card">
        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 12 }}>CLI reference</div>
        <pre className="terminal" style={{ maxHeight: 'none', fontSize: 11 }}>{`# Mechanical tools (no API key needed)
wiki-cli index
wiki-cli lint
wiki-cli new concept <slug> --title "My Concept"
wiki-cli new entity  <slug> --title "My Entity"
wiki-cli new source  <slug> --title "My Source"
wiki-cli search "term"
wiki-cli log query "What is X?" --note "answered from wiki"

# LLM-powered tools (needs ANTHROPIC_API_KEY)
agent-cli ingest raw/articles/my-article.md
agent-cli query "What is the attention mechanism?"
agent-cli query "Compare A vs B" --save`}
        </pre>
      </div>
    </div>
  )
}
