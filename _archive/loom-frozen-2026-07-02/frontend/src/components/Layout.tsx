import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { api, type HealthInfo } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const NAV = [
  { to: "/run", icon: "✎", label: "New task" },
  { to: "/dashboard", icon: "▣", label: "Overview" },
  { to: "/jobs", icon: "≡", label: "History" },
  { to: "/agents", icon: "◉", label: "Agents" },
  { to: "/knowledge", icon: "⌘", label: "Knowledge" },
  { to: "/settings", icon: "⚙", label: "Settings" },
];

export default function Layout() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const activity = useAgentActivity();
  const busyCount = Object.values(activity).filter((s) => s.busy).length;

  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => setHealth(null));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="shell">
      <aside className="sb">
        <div className="sb-logo">
          <div className="sb-logo-icon">✺</div>
          <div>
            <div className="sb-logo-name">Loom</div>
            <div className="sb-logo-sub">your local AI crew</div>
          </div>
        </div>
        <nav className="sb-nav">
          <div className="sb-group">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => `sb-link${isActive ? " active" : ""}`}>
                <span className="sb-link-ico">{n.icon}</span>
                {n.label}
                {n.to === "/dashboard" && busyCount > 0 && <span className="sb-badge">{busyCount}</span>}
              </NavLink>
            ))}
          </div>
        </nav>
        <div className="sb-foot">
          <div className="sb-foot-row">
            <span className={`dot ${health ? "on" : "off"}`} />
            {health ? `${health.agents_loaded} agents ready` : "can't reach Loom"}
          </div>
          {health && (
            <div className="sb-foot-row" style={{ color: "var(--text3)" }}>
              {health.models_loaded} models · {busyCount > 0 ? `${busyCount} working now` : "idle"}
            </div>
          )}
        </div>
      </aside>
      <div className="main">
        <Outlet />
      </div>
    </div>
  );
}
