const B = '/api'

async function _get(path) {
  const r = await fetch(B + path)
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error(e.detail || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

async function _post(path, body = {}) {
  const r = await fetch(B + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error(e.detail || `${r.status} ${r.statusText}`)
  }
  return r.json()
}

export const api = {
  pages:       ()               => _get('/pages'),
  page:        slug             => _get('/page/' + slug),
  overview:    ()               => _get('/overview'),
  log:         ()               => _get('/log'),
  search:      q                => _get('/search?q=' + encodeURIComponent(q)),
  rawList:     ()               => _get('/raw'),
  rawFile:     path             => _get('/raw/file?path=' + encodeURIComponent(path)),
  tool:        (name, body = {}) => _post('/tool/' + name, body),
  atlasStatus: ()               => _get('/atlas/status'),
  atlasJobs:   ()               => _get('/atlas/jobs'),
  atlasAgents: ()               => _get('/atlas/agents'),
  atlasRun:    (goal, risk, mode) => _post('/atlas/run', { goal, risk_level: risk, run_mode: mode }),
}
