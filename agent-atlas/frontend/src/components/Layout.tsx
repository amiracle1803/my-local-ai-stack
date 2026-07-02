import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { wsClient, WSState } from "../api/ws";
import { api } from "../api/client";

const NAV = [
  { to: "/dashboard", icon: "⊞", label: "Dashboard" },
  { to: "/run",       icon: "▷", label: "Run Task"  },
  { to: "/jobs",      icon: "≡", label: "Jobs"      },
  { to: "/agents",    icon: "◈", label: "Agents"    },
  { to: "/knowledge", icon: "⊙", label: "Knowledge" },
  { to: "/settings",  icon: "⚙", label: "Settings"  },
];

const BUSY_TTL = 8_000;

export default function Layout() {
  const [wsState,    setWsState]    = useState<WSState>(wsClient.state);
  const [online,     setOnline]     = useState<boolean | null>(null);
  const [agentCount, setAgentCount] = useState<number>(0);  // total registered
  const [busySet,    setBusySet]    = useState<Set<string>>(new Set());
  const [activeJobs, setActiveJobs] = useState(0);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // WebSocket state
  useEffect(() => {
    wsClient.connect();
    return wsClient.onStateChange(setWsState);
  }, []);

  // Health poll
  useEffect(() => {
    const check = () =>
      api.health()
        .then(h => { setOnline(true); setAgentCount(h.agents_loaded); })
        .catch(() => setOnline(false));
    check();
    const iv = setInterval(check, 15_000);
    return () => clearInterval(iv);
  }, []);

  // Active jobs poll
  useEffect(() => {
    const load = () =>
      api.jobs.list().then(jobs => {
        setActiveJobs(jobs.filter(j => j.status === "running" || j.status === "queued").length);
      }).catch(() => {});
    load();
    const iv = setInterval(load, 8_000);
    return () => clearInterval(iv);
  }, []);

  // Track busy agents from WS
  useEffect(() => {
    return wsClient.subscribe(raw => {
      const ev = raw.event as string | undefined;
      if (ev === "agent_message") {
        const agents = [raw.from as string, raw.to as string].filter(a => a && a !== "user" && a !== "system");
        for (const a of agents) {
          setBusySet(s => new Set([...s, a]));
          clearTimeout(timers.current[a]);
          timers.current[a] = setTimeout(() => {
            setBusySet(s => { const n = new Set(s); n.delete(a); return n; });
          }, BUSY_TTL);
        }
      }
      if (ev === "job_update") {
        const status = raw.status as string;
        if (status === "done" || status === "failed" || status === "stopped") {
          // Refresh job count immediately
          api.jobs.list().then(jobs => {
            setActiveJobs(jobs.filter(j => j.status === "running" || j.status === "queued").length);
          }).catch(() => {});
        }
      }
    });
  }, []);

  const busyCount = busySet.size;

  return (
    <div className="shell">
      <aside className="sb">
        {/* Logo */}
        <div className="sb-logo">
          <div className="sb-logo-icon">⬡</div>
          <div>
            <div className="sb-logo-name">Agent Atlas</div>
            <div className="sb-logo-sub">{agentCount || 19} agents · port 8000</div>
          </div>
        </div>

        {/* Live counter strip */}
        <div style={{
          display: "flex", gap: 0,
          borderBottom: "1px solid var(--border)",
        }}>
          <div style={{ flex: 1, padding: "10px 0", textAlign: "center", borderRight: "1px solid var(--border)" }}>
            <div style={{
              fontSize: 20, fontWeight: 800, lineHeight: 1,
              color: busyCount > 0 ? "#f59e0b" : "var(--text3)",
              transition: "color .3s",
            }}>
              {busyCount}
            </div>
            <div style={{ fontSize: 9, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".06em", marginTop: 3 }}>
              {busyCount === 1 ? "agent busy" : "agents busy"}
            </div>
          </div>
          <div style={{ flex: 1, padding: "10px 0", textAlign: "center" }}>
            <div style={{
              fontSize: 20, fontWeight: 800, lineHeight: 1,
              color: activeJobs > 0 ? "var(--blue)" : "var(--text3)",
              transition: "color .3s",
            }}>
              {activeJobs}
            </div>
            <div style={{ fontSize: 9, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".06em", marginTop: 3 }}>
              {activeJobs === 1 ? "job running" : "jobs running"}
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="sb-nav">
          <div className="sb-group">
            <div className="sb-label">Navigation</div>
            {NAV.map(({ to, icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => `sb-link${isActive ? " active" : ""}`}
              >
                <span className="sb-link-ico">{icon}</span>
                {label}
              </NavLink>
            ))}
          </div>
        </nav>

        {/* Footer */}
        <div className="sb-foot">
          <div className="sb-foot-row">
            <span className={`dot ${online === true ? "on" : online === false ? "off" : "spin"}`} />
            <span>{online === true ? "API online" : online === false ? "API offline" : "Checking…"}</span>
          </div>
          <div className="sb-foot-row">
            <span className={`dot ${wsState === "open" ? "on" : wsState === "connecting" ? "spin" : "off"}`} />
            <span>{wsState === "open" ? "Live" : wsState === "connecting" ? "Connecting…" : "Disconnected"}</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <Outlet />
      </div>
    </div>
  );
}
