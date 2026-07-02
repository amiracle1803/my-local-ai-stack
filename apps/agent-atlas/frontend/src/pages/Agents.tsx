import { useEffect, useState } from "react";
import { api, type AgentDef } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const LAYER_ORDER = ["control","knowledge","action","platform"] as const;
const LAYER_COLOR: Record<string, string> = { control:"#a855f7", knowledge:"#3b82f6", action:"#22c55e", platform:"#64748b" };

function agentColor(layer: string) { return LAYER_COLOR[layer] ?? "#6366f1"; }

export default function Agents() {
  const [agents, setAgents] = useState<AgentDef[] | null>(null);
  const [search, setSearch] = useState("");
  const [err,    setErr]    = useState<string | null>(null);
  const [ping,   setPing]   = useState<Record<string, "ok"|"err"|"loading">>({});
  const [busyDelete, setBusyDelete] = useState<string | null>(null);

  function refresh() {
    api.agents.list().then(setAgents).catch(e => setErr(e.message));
  }

  useEffect(() => { refresh(); }, []);

  async function deleteAgent(id: string, displayName: string) {
    if (!confirm(`Delete "${displayName}"? This removes its config file and can't be undone.`)) return;
    setBusyDelete(id);
    try {
      await api.agents.delete(id);
      refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyDelete(null);
    }
  }

  const agentIds = (agents ?? []).map(a => a.id);
  const activity = useAgentActivity(agentIds);

  const busyCount = Object.values(activity).filter(s => s.busy).length;

  const filtered = (agents ?? []).filter(a => {
    if (!search) return true;
    const q = search.toLowerCase();
    return a.id.includes(q) || a.display_name.toLowerCase().includes(q) || a.layer.includes(q) || a.description.toLowerCase().includes(q);
  });

  const byLayer = LAYER_ORDER.reduce<Record<string, AgentDef[]>>((acc, l) => {
    acc[l] = filtered.filter(a => a.layer === l);
    return acc;
  }, {});

  async function pingAgent(id: string) {
    setPing(p => ({ ...p, [id]: "loading" }));
    try {
      const result = await api.agents.ping(id);
      // Backend always returns HTTP 200 — check the body status field.
      const outcome: "ok" | "err" = result.status === "ok" ? "ok" : "err";
      setPing(p => ({ ...p, [id]: outcome }));
      setTimeout(() => setPing(p => { const n={...p}; delete n[id]; return n; }), 3000);
    } catch {
      setPing(p => ({ ...p, [id]: "err" }));
      setTimeout(() => setPing(p => { const n={...p}; delete n[id]; return n; }), 3000);
    }
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Agents</span>
        <span className="topbar-sub">
          {agents ? `${agents.length} agents` : "Loading…"}
          {busyCount > 0 && <span style={{ color:"var(--yellow)", marginLeft: 10 }}>● {busyCount} working</span>}
        </span>
        <div className="topbar-right">
          <input type="search" placeholder="Search…" value={search} onChange={e=>setSearch(e.target.value)} style={{ width: 190 }} />
        </div>
      </div>

      <div className="page">
        {err && <div className="alert alert-err">{err}</div>}
        {!agents && !err && <div className="loading-row"><div className="spinner"/>Loading agents…</div>}

        {LAYER_ORDER.map(layer => {
          const group = byLayer[layer];
          if (!group?.length) return null;
          const lColor = LAYER_COLOR[layer];

          return (
            <div key={layer} style={{ marginBottom: 30 }}>
              <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:10 }}>
                <span className="badge" style={{ background:`${lColor}18`, color:lColor, borderColor:`${lColor}33` }}>{layer}</span>
                <span style={{ fontSize:11, color:"var(--text3)" }}>{group.length} agents</span>
                {group.some(a => activity[a.id]?.busy) && (
                  <span style={{ fontSize:11, color:lColor }}>● active</span>
                )}
              </div>

              <div className="agent-grid">
                {group.map(agent => {
                  const slot  = activity[agent.id];
                  const busy  = slot?.busy ?? false;
                  const color = agentColor(layer);
                  const ps    = ping[agent.id];

                  return (
                    <div key={agent.id} className="agent-card" style={{
                      borderColor: busy ? `${color}55` : "var(--border)",
                      background:  busy ? `${color}08` : "var(--s1)",
                      transition:  "all .2s",
                    }}>
                      {/* Status dot + name */}
                      <div style={{ display:"flex", alignItems:"center", gap:7, marginBottom:5 }}>
                        <div style={{
                          width:8, height:8, borderRadius:"50%", flexShrink:0,
                          background: busy ? color : "var(--border2)",
                          boxShadow: busy ? `0 0 6px ${color}` : "none",
                          animation: busy ? "pulse-dot 1s infinite" : "none",
                        }} />
                        <span className="agent-name" style={{ margin:0, color: busy ? color : "var(--text)" }}>
                          {agent.display_name}
                        </span>
                      </div>

                      {/* Current task (if busy) */}
                      {busy && slot?.task ? (
                        <div style={{ fontSize:11, color:color, marginBottom:6, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", fontStyle:"italic" }}>
                          "{slot.task}"
                        </div>
                      ) : (
                        <div className="agent-desc">{agent.description.slice(0, 80)}</div>
                      )}

                      {/* Status label */}
                      <div style={{ marginBottom:6 }}>
                        {busy
                          ? <span className="badge b-yellow" style={{ fontSize:10 }}>● busy — {slot?.msgType ?? "working"}</span>
                          : <span className="badge b-gray" style={{ fontSize:10 }}>idle</span>
                        }
                      </div>

                      {/* Tools */}
                      {agent.tools.length > 0 && (
                        <div className="agent-tools">
                          {agent.tools.slice(0, 3).map(t => <span key={t} className="chip">{t}</span>)}
                          {agent.tools.length > 3 && <span className="chip">+{agent.tools.length - 3}</span>}
                        </div>
                      )}

                      {/* Ping / Delete */}
                      <div style={{ marginTop:8, display:"flex", gap:6, alignItems:"center" }}>
                        <button className="btn btn-ghost btn-xs" onClick={() => pingAgent(agent.id)} disabled={!!ps}>
                          {ps === "loading" ? "…" : "Ping"}
                        </button>
                        {ps === "ok"  && <span style={{ fontSize:11, color:"var(--green)" }}>✓ ok</span>}
                        {ps === "err" && <span style={{ fontSize:11, color:"var(--red)" }}>✕ error</span>}
                        {agent.deletable && (
                          <button
                            className="btn btn-ghost btn-xs"
                            style={{ color: "var(--red)", marginLeft: "auto" }}
                            onClick={() => deleteAgent(agent.id, agent.display_name)}
                            disabled={busyDelete === agent.id}
                          >
                            {busyDelete === agent.id ? "…" : "Delete"}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {agents && filtered.length === 0 && (
          <div className="empty-box"><h3>No match</h3><p>Try a different search.</p></div>
        )}
      </div>
    </>
  );
}
