import { useState, useEffect } from 'react'
import { api } from '../api'
import Markdown from '../components/Markdown'

export default function Log() {
  const [data, setData] = useState(null)
  const [err,  setErr]  = useState(null)

  useEffect(() => {
    api.log().then(setData).catch(e => setErr(e.message))
  }, [])

  return (
    <div>
      <div className="pg-header">
        <h1 className="pg-title">Activity Log</h1>
        <p className="pg-sub">Append-only record of wiki operations</p>
      </div>

      {err  && <div className="alert alert-err">{err}</div>}
      {!data && !err && <div className="loading-row"><div className="spinner" />Loading…</div>}
      {data  && (
        <div className="card">
          <Markdown text={data.content || '_No entries yet._'} />
        </div>
      )}
    </div>
  )
}
