import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { api, type HealthInfo } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const NAV = [
  { to: "/dashboard", icon: "▣", label: "Dashboard" },
  { to: "/run", icon: "▶", label: "Run" },
  { to: "/jobs", icon: "≡", label: "Jobs" },
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
          <div className="sb-logo-icon">⚛</div>
          <div>
            <div className="sb-logo-name">Agent Atlas</div>
            <div className="sb-logo-sub">local multi-agent</div>
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
            {health ? `${health.agents_loaded} agents · ${health.models_loaded} models` : "offline"}
          </div>
        </div>
      </aside>
      <div className="main">
        <Outlet />
      </div>
    </div>
  );
}
