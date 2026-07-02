import { useEffect, useState } from "react";
import { api, type AgentDef } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const LAYER_ORDER = ["control", "knowledge", "action", "platform"] as const;

export default function Agents() {
  const [agents, setAgents] = useState<AgentDef[] | null>(null);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ping, setPing] = useState<Record<string, "ok" | "err" | "loading">>({});
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const activity = useAgentActivity();

  function refresh() {
    api.agents.list().then(setAgents).catch((e) => setErr(e.message));
  }

  useEffect(() => { refresh(); }, []);

  async function pingAgent(id: string) {
    setPing((p) => ({ ...p, [id]: "loading" }));
    try {
      const result = await api.agents.ping(id);
      setPing((p) => ({ ...p, [id]: result.status === "ok" ? "ok" : "err" }));
    } catch {
      setPing((p) => ({ ...p, [id]: "err" }));
    }
    setTimeout(() => setPing((p) => { const n = { ...p }; delete n[id]; return n; }), 3000);
  }

  async function deleteAgent(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This removes its config file.`)) return;
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

  const filtered = (agents ?? []).filter((a) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return a.id.includes(q) || a.display_name.toLowerCase().includes(q) || a.description.toLowerCase().includes(q);
  });
  const byLayer = LAYER_ORDER.reduce<Record<string, AgentDef[]>>((acc, l) => {
    acc[l] = filtered.filter((a) => a.layer === l);
    return acc;
  }, {});

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Agents</span>
        <span className="topbar-sub">{agents ? `${agents.length} agents` : "loading…"}</span>
        <div className="topbar-right">
          <input type="search" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 180 }} />
        </div>
      </div>
      <div className="page">
        {err && <div className="alert alert-err">{err}</div>}
        {!agents && !err && <div className="loading-row"><div className="spinner" />Loading…</div>}

        {LAYER_ORDER.map((layer) => {
          const group = byLayer[layer];
          if (!group?.length) return null;
          return (
            <div key={layer} style={{ marginBottom: 24 }}>
              <div className="section-hd"><h2 style={{ textTransform: "capitalize" }}>{layer}</h2></div>
              <div className="agent-grid">
                {group.map((a) => {
                  const busy = activity[a.id]?.busy;
                  const p = ping[a.id];
                  return (
                    <div key={a.id} className="agent-card">
                      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                        <span className={`dot ${busy ? "spin" : ""}`} />
                        <span className="agent-name">{a.display_name}</span>
                      </div>
                      <div className="agent-desc">{a.description.slice(0, 90)}</div>
                      {a.tools.length > 0 && (
                        <div className="agent-tools">
                          {a.tools.slice(0, 3).map((t) => <span key={t} className="chip">{t}</span>)}
                        </div>
                      )}
                      <div style={{ marginTop: 10, display: "flex", gap: 6, alignItems: "center" }}>
                        <button className="btn btn-ghost btn-xs" onClick={() => pingAgent(a.id)} disabled={!!p}>
                          {p === "loading" ? "…" : "Ping"}
                        </button>
                        {p === "ok" && <span style={{ fontSize: 11, color: "var(--green)" }}>✓</span>}
                        {p === "err" && <span style={{ fontSize: 11, color: "var(--red)" }}>✕</span>}
                        {a.deletable && (
                          <button
                            className="btn btn-ghost btn-xs"
                            style={{ color: "var(--red)", marginLeft: "auto" }}
                            onClick={() => deleteAgent(a.id, a.display_name)}
                            disabled={busyDelete === a.id}
                          >
                            {busyDelete === a.id ? "…" : "Delete"}
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

        {agents && filtered.length === 0 && <div className="empty-box"><h3>No match</h3></div>}
      </div>
    </>
  );
}
