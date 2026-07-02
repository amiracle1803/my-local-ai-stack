import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentDef, type HealthInfo, type Job } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const LAYER_ORDER = ["control", "knowledge", "action", "platform"] as const;
const LAYER_COLOR: Record<string, string> = {
  control: "var(--purple)", knowledge: "var(--blue)", action: "var(--green)", platform: "var(--text3)",
};

export default function Dashboard() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [agents, setAgents] = useState<AgentDef[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const activity = useAgentActivity();

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.agents.list().then(setAgents).catch(() => {});
    api.jobs.list().then((j) => setJobs(j.slice(0, 8))).catch(() => {});
  }, []);

  const busyCount = Object.values(activity).filter((s) => s.busy).length;
  const doneCount = (jobs ?? []).filter((j) => j.status === "done").length;
  const failedCount = (jobs ?? []).filter((j) => j.status === "failed").length;

  const byLayer = LAYER_ORDER.reduce<Record<string, AgentDef[]>>((acc, l) => {
    acc[l] = (agents ?? []).filter((a) => a.layer === l);
    return acc;
  }, {});

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Overview</span>
        <span className="topbar-sub">{health ? `${health.agents_loaded} agents registered` : "connecting…"}</span>
        <div className="topbar-right">
          <Link to="/run" className="btn btn-primary btn-sm">+ New task</Link>
        </div>
      </div>
      <div className="page">
        <div className="stat-grid">
          <div className="stat-box"><div className="stat-n">{agents?.length ?? "—"}</div><div className="stat-l">Agents</div></div>
          <div className="stat-box"><div className="stat-n" style={{ color: busyCount > 0 ? "var(--yellow)" : undefined }}>{busyCount}</div><div className="stat-l">Busy now</div></div>
          <div className="stat-box"><div className="stat-n" style={{ color: "var(--green)" }}>{doneCount}</div><div className="stat-l">Done (recent)</div></div>
          <div className="stat-box"><div className="stat-n" style={{ color: failedCount > 0 ? "var(--red)" : undefined }}>{failedCount}</div><div className="stat-l">Failed (recent)</div></div>
        </div>

        <div className="g2">
          <div>
            <div className="section-hd"><h2>Agent status</h2><Link to="/agents" className="btn btn-ghost btn-sm">All agents →</Link></div>
            {LAYER_ORDER.map((layer) => {
              const group = byLayer[layer];
              if (!group?.length) return null;
              return (
                <div key={layer} className="card card-sm" style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: LAYER_COLOR[layer], textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 8 }}>
                    {layer}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {group.map((a) => {
                      const busy = activity[a.id]?.busy;
                      return (
                        <span key={a.id} className="badge" style={{
                          background: busy ? "rgba(245,158,11,.15)" : "var(--s2)",
                          color: busy ? "var(--yellow)" : "var(--text2)",
                          borderColor: busy ? "rgba(245,158,11,.3)" : "var(--border)",
                        }}>
                          <span className={`dot ${busy ? "spin" : ""}`} style={{ width: 6, height: 6 }} />
                          {a.display_name}
                        </span>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          <div>
            <div className="section-hd"><h2>Recent jobs</h2><Link to="/jobs" className="btn btn-ghost btn-sm">All jobs →</Link></div>
            <div className="job-list">
              {!jobs && <div className="loading-row"><div className="spinner" />Loading…</div>}
              {jobs && jobs.length === 0 && <div className="empty-box"><h3>No jobs yet</h3><p>Run a task to see it here.</p></div>}
              {jobs?.map((j) => (
                <Link key={j.id} to={`/jobs/${j.id}`} className="job-row">
                  <span className={`sdot sdot-${j.status}`} />
                  <span className="job-goal">{j.title || j.id}</span>
                  <span className="job-meta">{j.status}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
