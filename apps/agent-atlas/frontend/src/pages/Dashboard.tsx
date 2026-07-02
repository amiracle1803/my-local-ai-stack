import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type AgentDef } from "../api/client";
import { wsClient } from "../api/ws";
import { useAgentActivity } from "../hooks/useAgentActivity";

function relTime(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  if (d < 60_000)    return `${Math.floor(d / 1000)}s ago`;
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`;
  if (d < 86_400_000)return `${Math.floor(d / 3_600_000)}h ago`;
  return `${Math.floor(d / 86_400_000)}d ago`;
}

function statusBadge(s: string) {
  const m: Record<string, string> = { running:"b-blue", done:"b-green", failed:"b-red", queued:"b-yellow", paused:"b-yellow", stopped:"b-gray" };
  return m[s] ?? "b-gray";
}
function statusDot(s: string) {
  const m: Record<string, string> = { running:"sdot-running", done:"sdot-done", failed:"sdot-failed", queued:"sdot-queued", paused:"sdot-paused", stopped:"sdot-stopped" };
  return m[s] ?? "sdot-stopped";
}

function agentColor(id: string) {
  if (id === "orchestrator")  return "#a855f7";
  if (id === "planner")       return "#6366f1";
  if (id === "evaluator" || id === "guardian_agent") return "#f59e0b";
  if (["knowledge_hub","retrieval_agent","obsidian_brain","memory_agent"].includes(id)) return "#3b82f6";
  if (id === "code_agent")    return "#22c55e";
  if (id === "creative_studio_agent") return "#ec4899";
  return "#6366f1";
}

const LAYER_COLOR: Record<string, string> = {
  control: "#a855f7", knowledge: "#3b82f6", action: "#22c55e", platform: "#64748b",
};
const LAYER_ORDER = ["control","knowledge","action","platform"] as const;

export default function Dashboard() {
  const [jobs,   setJobs]   = useState<Job[] | null>(null);
  const [agents, setAgents] = useState<AgentDef[]>([]);
  const [health, setHealth] = useState<{ agents_loaded: number; models_loaded: number } | null>(null);

  const agentIds = agents.map(a => a.id);
  const activity = useAgentActivity(agentIds);
  const busyCount = Object.values(activity).filter(s => s.busy).length;

  const loadJobs = useCallback(() => {
    api.jobs.list().then(setJobs).catch(() => {});
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.agents.list().then(setAgents).catch(() => {});
    loadJobs();
    return wsClient.subscribe(msg => { if (msg.event === "job_update") loadJobs(); });
  }, [loadJobs]);

  const running = (jobs ?? []).filter(j => j.status === "running").length;
  const queued  = (jobs ?? []).filter(j => j.status === "queued").length;
  const done    = (jobs ?? []).filter(j => j.status === "done").length;
  const failed  = (jobs ?? []).filter(j => j.status === "failed").length;
  const recent  = (jobs ?? []).slice(0, 8);

  const byLayer = LAYER_ORDER.reduce<Record<string, AgentDef[]>>((acc, l) => {
    acc[l] = agents.filter(a => a.layer === l);
    return acc;
  }, {});

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Dashboard</span>
        <div className="topbar-right">
          <Link to="/run" className="btn btn-primary btn-sm">▷ New task</Link>
        </div>
      </div>
      <div className="page">

        {/* ── Agent Status Board ── always first, most prominent ── */}
        <div style={{
          background: "var(--s1)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r2)",
          padding: "16px 18px",
          marginBottom: 20,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Agent Status</span>
              {busyCount > 0 ? (
                <span style={{
                  background: "rgba(245,158,11,.15)", color: "#fbbf24",
                  border: "1px solid rgba(245,158,11,.3)",
                  borderRadius: 20, fontSize: 11, fontWeight: 700,
                  padding: "2px 10px",
                  display: "flex", alignItems: "center", gap: 5,
                }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#f59e0b", display: "inline-block", animation: "pulse-dot 1s infinite" }} />
                  {busyCount} working
                </span>
              ) : (
                <span style={{ fontSize: 11, color: "var(--text3)" }}>all idle</span>
              )}
            </div>
            <Link to="/agents" style={{ fontSize: 11, color: "var(--text3)" }}>View all →</Link>
          </div>

          {agents.length === 0 && (
            <div className="loading-row" style={{ padding: "8px 0" }}><div className="spinner" /> Loading agents…</div>
          )}

          {LAYER_ORDER.map(layer => {
            const group = byLayer[layer];
            if (!group?.length) return null;
            const lColor = LAYER_COLOR[layer];
            return (
              <div key={layer} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: lColor, textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 6 }}>
                  {layer}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {group.map(agent => {
                    const slot  = activity[agent.id];
                    const busy  = slot?.busy ?? false;
                    const color = agentColor(agent.id);
                    return (
                      <div
                        key={agent.id}
                        title={busy && slot?.task ? `Working on: ${slot.task}` : agent.description}
                        style={{
                          display: "flex", alignItems: "center", gap: 6,
                          padding: "5px 10px",
                          borderRadius: 20,
                          background: busy ? `${color}15` : "var(--s2)",
                          border: `1px solid ${busy ? color + "44" : "var(--border)"}`,
                          transition: "all .2s",
                          cursor: "default",
                        }}
                      >
                        <div style={{
                          width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                          background: busy ? color : "var(--border2)",
                          boxShadow: busy ? `0 0 6px ${color}` : "none",
                          animation: busy ? "pulse-dot 1s infinite" : "none",
                        }} />
                        <span style={{ fontSize: 11, fontWeight: busy ? 700 : 500, color: busy ? color : "var(--text3)", whiteSpace: "nowrap" }}>
                          {agent.display_name.replace(" Agent","").replace(" Hub","").replace(" Brain","")}
                        </span>
                        {busy && (
                          <span style={{ fontSize: 9, color: color, opacity: .8 }}>●</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Stats strip ── */}
        <div className="stat-grid" style={{ marginBottom: 20 }}>
          <div className="stat-box">
            <div className="stat-n" style={{ color: "var(--accent2)" }}>{health?.agents_loaded ?? "—"}</div>
            <div className="stat-l">Total agents</div>
          </div>
          <div className="stat-box">
            <div className="stat-n" style={{ color: busyCount > 0 ? "#f59e0b" : "var(--text2)" }}>{busyCount}</div>
            <div className="stat-l">Busy now</div>
          </div>
          <div className="stat-box">
            <div className="stat-n" style={{ color: (running + queued) > 0 ? "var(--blue)" : "var(--text2)" }}>{running + queued}</div>
            <div className="stat-l">Active jobs</div>
          </div>
          <div className="stat-box">
            <div className="stat-n" style={{ color: "var(--green)" }}>{done}</div>
            <div className="stat-l">Completed</div>
          </div>
          <div className="stat-box">
            <div className="stat-n" style={{ color: failed > 0 ? "var(--red)" : "var(--text2)" }}>{failed}</div>
            <div className="stat-l">Failed</div>
          </div>
          <div className="stat-box">
            <div className="stat-n">{health?.models_loaded ?? "—"}</div>
            <div className="stat-l">Models</div>
          </div>
        </div>

        {/* ── Recent jobs ── */}
        <div className="section-hd" style={{ marginBottom: 10 }}>
          <h2>Recent jobs</h2>
          <Link to="/jobs" className="btn btn-ghost btn-sm">All jobs →</Link>
        </div>

        {!jobs && <div className="loading-row"><div className="spinner" /> Loading…</div>}
        {jobs?.length === 0 && (
          <div className="empty-box"><h3>No jobs yet</h3><p>Submit a task to get started.</p></div>
        )}
        {recent.length > 0 && (
          <div className="job-list">
            {recent.map(j => (
              <Link key={j.id} to={`/jobs/${j.id}`} className="job-row">
                <div className={`sdot ${statusDot(j.status)}`} />
                <span className="job-goal">{j.title ?? j.type}</span>
                <span className={`badge ${statusBadge(j.status)}`}>{j.status}</span>
                <span className="job-meta">{relTime(j.updated_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
