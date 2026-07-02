import { useEffect, useState } from "react";
import { api, type ModelInfo } from "../api/client";

export default function Settings() {
  const [models,    setModels]    = useState<ModelInfo[] | null>(null);
  const [health,    setHealth]    = useState<{ status: string; service: string; agents_loaded: number; models_loaded: number } | null>(null);
  const [backupMsg, setBackupMsg] = useState<string | null>(null);
  const [lastBk,    setLastBk]    = useState<string | null>(null);
  const [busy,      setBusy]      = useState(false);
  const [err,       setErr]       = useState<string | null>(null);

  useEffect(() => {
    api.llm.models().then(setModels).catch(() => setModels([]));
    api.health().then(setHealth).catch(() => null);
    api.system.backupStatus().then((r) => setLastBk(r.last_backup)).catch(() => null);
  }, []);

  async function runBackup() {
    setBusy(true); setBackupMsg(null); setErr(null);
    try {
      const r = await api.system.runBackup();
      if (r.ok) {
        setBackupMsg(`Backup complete → ${r.dir ?? "backup dir"}`);
        setLastBk(r.timestamp ?? new Date().toISOString());
      } else {
        setErr(r.error ?? "Backup failed");
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const available = (models ?? []).filter((m) => m.available);
  const unavailable = (models ?? []).filter((m) => !m.available);

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Settings</span>
        <span className="topbar-sub">System info &amp; maintenance</span>
      </div>
      <div className="page">
        {err && <div className="alert alert-err">{err}</div>}

        {/* System */}
        <div className="section-hd"><h2>System</h2></div>
        <div className="card" style={{ marginBottom: 24 }}>
          {!health && <div className="loading-row"><div className="spinner" /> Loading…</div>}
          {health && (
            <div className="g2" style={{ gap: 20 }}>
              <div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4 }}>SERVICE</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{health.service}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4 }}>STATUS</div>
                <span className={`badge ${health.status === "ok" ? "b-green" : "b-red"}`}>
                  {health.status}
                </span>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4 }}>AGENTS</div>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{health.agents_loaded}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 4 }}>MODELS</div>
                <div style={{ fontSize: 22, fontWeight: 800 }}>{health.models_loaded}</div>
              </div>
            </div>
          )}
        </div>

        {/* Backup */}
        <div className="section-hd"><h2>Backup</h2></div>
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Run backup now</div>
              <div style={{ fontSize: 12, color: "var(--text3)" }}>
                Snapshots SQLite + ChromaDB to disk.
                {lastBk && <> Last backup: {new Date(lastBk).toLocaleString()}</>}
              </div>
            </div>
            <button className="btn btn-primary" onClick={runBackup} disabled={busy}>
              {busy ? <><div className="spinner spinner-sm" /> Backing up…</> : "Run backup"}
            </button>
          </div>
          {backupMsg && <div className="alert alert-ok" style={{ marginTop: 14, marginBottom: 0 }}>{backupMsg}</div>}
        </div>

        {/* Models */}
        <div className="section-hd"><h2>Available models</h2></div>
        {!models && <div className="loading-row"><div className="spinner" /> Loading models…</div>}
        {models && (
          <>
            {available.length > 0 && (
              <div className="card" style={{ marginBottom: 12, padding: 0, overflow: "hidden" }}>
                {available.map((m) => (
                  <div
                    key={m.name}
                    style={{
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "11px 18px", borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span className="sdot sdot-done" />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text3)" }}>{m.provider}</div>
                    </div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      {m.capabilities.map((c) => (
                        <span key={c} className="chip">{c}</span>
                      ))}
                    </div>
                    <span className="badge b-green">available</span>
                  </div>
                ))}
              </div>
            )}
            {unavailable.length > 0 && (
              <>
                <div style={{ fontSize: 11, color: "var(--text3)", margin: "16px 0 8px", fontWeight: 700, letterSpacing: ".06em" }}>
                  UNAVAILABLE
                </div>
                <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                  {unavailable.map((m) => (
                    <div
                      key={m.name}
                      style={{
                        display: "flex", alignItems: "center", gap: 12, opacity: 0.5,
                        padding: "11px 18px", borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <span className="sdot sdot-stopped" />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{m.name}</div>
                        <div style={{ fontSize: 11, color: "var(--text3)" }}>{m.provider}</div>
                      </div>
                      <span className="badge b-gray">unavailable</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {models.length === 0 && (
              <div className="card card-sm" style={{ color: "var(--text3)", fontSize: 13 }}>
                No model info returned by API.
              </div>
            )}
          </>
        )}

        {/* API info */}
        <div className="section-hd" style={{ marginTop: 24 }}><h2>API endpoints</h2></div>
        <div className="card">
          <pre className="codeblock" style={{ maxHeight: "none" }}>{`FastAPI backend  → http://localhost:8000
Interactive docs → http://localhost:8000/docs
WebSocket        → ws://localhost:8000/ws
React UI         → http://localhost:5173`}
          </pre>
        </div>
      </div>
    </>
  );
}
