import { useEffect, useState } from "react";
import { api, type AgentDef, type AgentLayer, type ModelInfo } from "../api/client";
import { useAgentActivity } from "../hooks/useAgentActivity";

const LAYER_ORDER = ["control", "knowledge", "action", "platform"] as const;
const LAYER_LABEL: Record<string, string> = {
  control: "Control — plans, decides, reviews",
  knowledge: "Knowledge — search & retrieval",
  action: "Action — does things (n8n, code, files)",
  platform: "Platform — memory, infra",
};

const EMPTY_FORM = { id: "", display_name: "", layer: "action" as AgentLayer, description: "", system_prompt: "", model: "ollama_local" };

export default function Agents() {
  const [agents, setAgents] = useState<AgentDef[] | null>(null);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ping, setPing] = useState<Record<string, "ok" | "err" | "loading">>({});
  const [busyDelete, setBusyDelete] = useState<string | null>(null);
  const activity = useAgentActivity();

  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  function refresh() {
    api.agents.list().then(setAgents).catch((e) => setErr(e.message));
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => { api.llm.models().then(setModels).catch(() => setModels([])); }, []);

  async function submitNewAgent(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateErr(null);
    try {
      await api.agents.create({
        id: form.id,
        display_name: form.display_name,
        layer: form.layer,
        description: form.description,
        system_prompt: form.system_prompt || undefined,
        tools: [],
        model_preference: [form.model],
        memory_scopes: [],
        policies: [],
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      refresh();
    } catch (e) {
      setCreateErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

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
          <button className="btn btn-primary btn-sm" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ New agent"}
          </button>
        </div>
      </div>
      <div className="page">
        {err && <div className="alert alert-err">{err}</div>}
        {!agents && !err && <div className="loading-row"><div className="spinner" />Loading…</div>}

        {showForm && (
          <form onSubmit={submitNewAgent} className="card" style={{ marginBottom: 20 }}>
            <div className="section-hd"><h2>New agent</h2></div>
            <p style={{ fontSize: 12, color: "var(--text3)", marginTop: -6, marginBottom: 14 }}>
              Creates a plain LLM agent with its own system prompt -- no tools, no memory, just a
              focused persona you can @-address by name. Good for a narrow, repeatable job; not a
              replacement for the built-in agents.
            </p>
            {createErr && <div className="alert alert-err" style={{ marginBottom: 12 }}>{createErr}</div>}
            <div className="g2" style={{ gap: 12 }}>
              <div className="field">
                <label>ID (slug)</label>
                <input required value={form.id} placeholder="e.g. release_notes_writer"
                  onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))} />
              </div>
              <div className="field">
                <label>Display name</label>
                <input required value={form.display_name} placeholder="e.g. Release Notes Writer"
                  onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} />
              </div>
            </div>
            <div className="g2" style={{ gap: 12 }}>
              <div className="field">
                <label>Layer</label>
                <select value={form.layer} onChange={(e) => setForm((f) => ({ ...f, layer: e.target.value as AgentLayer }))}>
                  {LAYER_ORDER.map((l) => <option key={l} value={l}>{LAYER_LABEL[l]}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Preferred model</label>
                <select value={form.model} onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}>
                  {(models ?? []).map((m) => (
                    <option key={m.name} value={m.name} disabled={!m.available}>
                      {m.name}{!m.available ? " — unavailable" : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="field">
              <label>Description</label>
              <input required value={form.description} placeholder="One line: what this agent is for"
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div className="field">
              <label>System prompt (optional)</label>
              <textarea value={form.system_prompt} placeholder="You are the ... agent. You always ..."
                style={{ minHeight: 80 }}
                onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))} />
            </div>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? "Creating…" : "Create agent"}
            </button>
          </form>
        )}

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
