import { useState, useEffect, useCallback } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { api } from '../api'

const NAV = [
  { to: '/',      label: 'Home',         icon: '⌂',  end: true },
  { to: '/wiki',  label: 'Wiki pages',   icon: '◫' },
  { to: '/search',label: 'Search',       icon: '⊙' },
  { to: '/log',   label: 'Activity log', icon: '≡' },
]
const NAV2 = [
  { to: '/raw',   label: 'Raw sources',  icon: '⊞' },
  { to: '/tools', label: 'Wiki tools',   icon: '⚙' },
  { to: '/atlas', label: 'Agent Atlas',  icon: '◈' },
]

function useAtlasStatus() {
  const [online, setOnline] = useState(null)
  useEffect(() => {
    let alive = true
    const check = () => api.atlasStatus()
      .then(d => alive && setOnline(d.online))
      .catch(() => alive && setOnline(false))
    check()
    const iv = setInterval(check, 12000)
    return () => { alive = false; clearInterval(iv) }
  }, [])
  return online
}

export default function Shell({ children }) {
  const [q, setQ]           = useState('')
  const [count, setCount]   = useState('…')
  const navigate             = useNavigate()
  const location             = useLocation()
  const atlasOnline          = useAtlasStatus()

  useEffect(() => {
    api.pages().then(d => setCount(d.count)).catch(() => {})
  }, [])

  const onSearchKey = useCallback(e => {
    if (e.key === 'Enter' && q.trim()) {
      navigate(`/search?q=${encodeURIComponent(q.trim())}`)
      setQ('')
    }
  }, [q, navigate])

  const dotCls = atlasOnline === null ? '' : atlasOnline ? 'on' : 'off'

  // figure out page title for topbar breadcrumb
  const seg = location.pathname.replace(/^\//, '') || 'home'
  const parts = seg.split('/')
  const crumbs = parts.map((p, i) => ({
    label: p.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Home',
    path: '/' + parts.slice(0, i + 1).join('/'),
    last: i === parts.length - 1,
  }))

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="sb-logo">
          <span className="sb-logo-icon">📖</span>
          <div>
            <div className="sb-logo-text">LLM Wiki</div>
            <div className="sb-logo-sub">{count} pages</div>
          </div>
        </div>

        <div className="sb-search-wrap">
          <input
            className="sb-search"
            type="text"
            placeholder="Quick search…"
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={onSearchKey}
          />
        </div>

        <div className="sb-nav">
          <div className="sb-group">
            <div className="sb-group-label">Wiki</div>
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => 'sb-link' + (isActive ? ' active' : '')}>
                <span className="sb-link-icon">{n.icon}</span>
                {n.label}
              </NavLink>
            ))}
          </div>
          <div className="sb-group">
            <div className="sb-group-label">System</div>
            {NAV2.map(n => (
              <NavLink key={n.to} to={n.to}
                className={({ isActive }) => 'sb-link' + (isActive ? ' active' : '')}>
                <span className="sb-link-icon">{n.icon}</span>
                {n.label}
              </NavLink>
            ))}
          </div>
        </div>

        <div className="sb-footer">
          <div className="status-pill">
            <span className={`dot ${dotCls}`} />
            Atlas {atlasOnline === null ? '…' : atlasOnline ? 'online' : 'offline'}
          </div>
          <div>
            <a href="http://localhost:5173" target="_blank">Atlas UI</a>
            {' · '}
            <a href="http://localhost:7337/api/docs" target="_blank">API docs</a>
          </div>
        </div>
      </nav>

      <div className="main">
        <div className="topbar">
          <nav className="topbar-crumb">
            <NavLink to="/">Home</NavLink>
            {crumbs.map((c, i) => (
              i === 0 && c.path === '/' ? null : (
                <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  <span className="sep">›</span>
                  {c.last
                    ? <span className="current">{c.label}</span>
                    : <a href={c.path} onClick={e => { e.preventDefault(); navigate(c.path) }}>{c.label}</a>
                  }
                </span>
              )
            ))}
          </nav>
        </div>

        <div className="content">
          {children}
        </div>
      </div>
    </div>
  )
}
