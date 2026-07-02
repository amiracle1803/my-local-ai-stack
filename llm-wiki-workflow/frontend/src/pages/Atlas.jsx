import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const LAYER_BADGE = { control: 'b-purple', knowledge: 'b-blue', action: 'b-amber', platform: 'b-stone' }
const STATUS_BADGE = { pending: 'b-stone', running: 'b-blue', completed: 'b-green', failed: 'b-red', queued: 'b-stone' }
const LAYER_ORDER = ['control', 'knowledge', 'action', 'platform']

/* ── Jobs tab ── */
function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [err,  setErr]  = useState(null)

  const load = useCallback(() => {
    api.atlasJobs().then(d => setJobs(d.jobs ?? [])).catch(e => setErr(e.message))
  }, [])

  useEffect(() => { load(); const iv = setInterval(load, 5000); return () => clearInterval(iv) }, [load])

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Recent jobs</span>
        <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
        <span style={{ fontSize: 11, color: 'var(--faint)' }}>auto-refresh 5 s</span>
      </div>
      {err && <div className="alert alert-err">{err}</div>}
      {!jobs && <div className="loading-row"><div className="spinner" />Loading…</div>}
      {jobs?.length === 0 && <div className="empty-state"><strong>No jobs yet</strong>Submit a task to create one.</div>}
      {jobs?.length > 0 && (
        <div className="card" style={{ padding: '4px 16px' }}>
          {jobs.map(j => (
            <div key={j.id} className="job-row">
              <span className={`badge ${STATUS_BADGE[j.status] || 'b-stone'}`}>{j.status}</span>
              <span className={`badge ${LAYER_BADGE[j.type] || 'b-stone'}`}>{j.type || 'job'}</span>
              <span className="job-goal">{j.goal || j.id}</span>
              <span className="job-ts">{(j.created_at || '').slice(0, 16)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Agents tab ── */
function Agents() {
  const [data, setData] = useState(null)
  const [err,  setErr]  = useState(null)

  useEffect(() => { api.atlasAgents().then(setData).catch(e => setErr(e.message)) }, [])

  const layers = data?.layers ?? {}

  return (
    <div>
      {err && <div className="alert alert-err">{err}</div>}
      {!data && <div className="loading-row"><div className="spinner" />Loading…</div>}
      {LAYER_ORDER.filter(l => layers[l]?.length > 0).map(l => (
        <div key={l} style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span className={`badge ${LAYER_BADGE[l]}`}>{l}</span>
            <span style={{ fontSize: 11, color: 'var(--faint)' }}>{layers[l].length} agents</span>
          </div>
          <div className="grid3">
            {layers[l].map(a => (
              <div key={a.name || a.id} className="agent-card">
                <div className="agent-name">{a.display_name || a.name || a.id}</div>
                {a.description && <div className="agent-desc">{a.description.slice(0, 100)}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Submit tab ── */
function Submit({ onDone }) {
  const [goal, setGoal] = useState('')
  const [risk, setRisk] = useState('low')
  const [mode, setMode] = useState('auto')
  const [out,  setOut]  = useState('')
  const [busy, setBusy] = useState(false)
  const [ok,   setOk]   = useState(null)

  async function submit() {
    if (!goal.trim()) return
    setBusy(true); setOut(''); setOk(null)
    try {
      const d = await api.atlasRun(goal.trim(), risk, mode)
      setOut(JSON.stringify(d, null, 2))
      setOk(true)
      setGoal('')
      onDone?.()
    } catch (e) {
      setOut(e.message)
      setOk(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: 'block', fontSize: 12, color: 'var(--muted)', marginBottom: 5 }}>Goal</label>
        <textarea
          rows={3}
          value={goal}
          onChange={e => setGoal(e.target.value)}
          placeholder="Describe what you want Agent Atlas to do…"
          style={{ width: '100%', resize: 'vertical' }}
        />
      </div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
        <div>
          <label style={{ display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Risk</label>
          <select value={risk} onChange={e => setRisk(e.target.value)}>
            <option>low</option><option>medium</option><option>high</option>
          </select>
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Mode</label>
          <select value={mode} onChange={e => setMode(e.target.value)}>
            <option>auto</option><option>confirm</option><option>preview</option>
          </select>
        </div>
        <div style={{ alignSelf: 'flex-end' }}>
          <button className="btn btn-primary" onClick={submit} disabled={busy || !goal.trim()}>
            {busy ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </div>
      {out && ok === false && <div className="alert alert-err">{out}</div>}
      {out && ok === true  && <pre className="terminal">{out}</pre>}
    </div>
  )
}

/* ── CLI tab ── */
function Cli() {
  return (
    <pre className="terminal" style={{ maxHeight: 'none', fontSize: 11 }}>{`# Submit a task
curl -X POST http://localhost:8000/api/run \\
  -H "Content-Type: application/json" \\
  -d '{"goal":"Summarize recent AI research","risk_level":"low","run_mode":"auto"}'

# Check job status
curl http://localhost:8000/api/jobs

# List agents
curl http://localhost:8000/api/agents

# Health
curl http://localhost:8000/api/health

# Atlas UI
start http://localhost:5173

# API docs
start http://localhost:8000/docs`}
    </pre>
  )
}

/* ── Page root ── */
export default function Atlas() {
  const [tab,    setTab]    = useState('submit')
  const [status, setStatus] = useState(null)

  useEffect(() => {
    const check = () => api.atlasStatus().then(setStatus).catch(() => setStatus({ online: false }))
    check()
    const iv = setInterval(check, 10000)
    return () => clearInterval(iv)
  }, [])

  const online = status?.online

  return (
    <div>
      <div className="pg-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <h1 className="pg-title" style={{ margin: 0 }}>Agent Atlas</h1>
          {status && (
            <span className={`badge ${online ? 'b-green' : 'b-red'}`}>
              {online ? 'online' : 'offline'}
            </span>
          )}
        </div>
        <p className="pg-sub">18-agent local-first multi-agent system · port 8000</p>
      </div>

      {online === false && (
        <div className="alert alert-warn" style={{ marginBottom: 20 }}>
          Atlas is offline. Start it from the Agent Atlas folder, then refresh.
        </div>
      )}

      {status && online && status.agent_count && (
        <div className="stats-row" style={{ marginBottom: 24 }}>
          <div className="stat-box"><div className="stat-n">{status.agent_count}</div><div className="stat-l">Agents</div></div>
          {status.job_count != null && <div className="stat-box"><div className="stat-n">{status.job_count}</div><div className="stat-l">Jobs</div></div>}
        </div>
      )}

      <div className="tabs">
        {[['submit','Submit task'],['jobs','Jobs'],['agents','Agents'],['cli','CLI / API']].map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? 'on' : ''}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'submit'  && <Submit onDone={() => setTab('jobs')} />}
      {tab === 'jobs'    && <Jobs />}
      {tab === 'agents'  && <Agents />}
      {tab === 'cli'     && <Cli />}
    </div>
  )
}
