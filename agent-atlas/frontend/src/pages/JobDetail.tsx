import { useEffect, useState, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api, type Job } from "../api/client";
import { wsClient } from "../api/ws";
import LiveFeed from "../components/LiveFeed";
import ResultView from "../components/ResultView";

function statusBadge(s: string) {
  const m: Record<string, string> = { running: "b-blue", done: "b-green", failed: "b-red", queued: "b-yellow", paused: "b-yellow", stopped: "b-gray" };
  return m[s] ?? "b-gray";
}
function statusDot(s: string) {
  const m: Record<string, string> = { running: "sdot-running", done: "sdot-done", failed: "sdot-failed", queued: "sdot-queued", paused: "sdot-paused", stopped: "sdot-stopped" };
  return m[s] ?? "sdot-stopped";
}
function fmtDate(iso: string) { return new Date(iso).toLocaleString(); }

type Tab = "live" | "result" | "payload" | "notes";

export default function JobDetail() {
  const { id }     = useParams<{ id: string }>();
  const navigate   = useNavigate();
  const [job,  setJob]  = useState<Job | null>(null);
  const [err,  setErr]  = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab,  setTab]  = useState<Tab>("live");
  const [notes, setNotes] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!id) return;
    api.jobs.get(id)
      .then((j) => { setJob(j); setNotes(j.notes ?? ""); })
      .catch((e) => setErr(e.message));
  }, [id]);

  useEffect(() => {
    load();
    // poll while running
    const iv = setInterval(() => {
      if (!id) return;
      api.jobs.get(id).then((j) => {
        setJob(j);
        if (j.status !== "running" && j.status !== "queued") clearInterval(iv);
      }).catch(() => {});
    }, 3000);
    // also update on WS events
    const unsub = wsClient.subscribe((msg) => {
      if (msg.event === "job_update" && msg.job_id === id) load();
    });
    return () => { clearInterval(iv); unsub(); };
  }, [id, load]);

  async function act(fn: () => Promise<unknown>, label: string) {
    setBusy(true);
    try { await fn(); load(); }
    catch (e: unknown) { setErr(`${label}: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  }

  async function saveNotes() {
    if (!id) return;
    setBusy(true);
    try {
      await api.jobs.saveNotes(id, notes);
      setSaveMsg("Saved!"); setTimeout(() => setSaveMsg(null), 2000);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function deleteJob() {
    if (!id || !confirm("Delete this job?")) return;
    try {
      const res = await api.jobs.delete(id);
      if (!res.ok) {
        setErr(`Delete failed: HTTP ${res.status}`);
        return;
      }
      navigate("/jobs");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  if (!job && !err) {
    return (
      <>
        <div className="topbar"><Link to="/jobs" className="btn btn-ghost btn-sm">← Jobs</Link></div>
        <div className="page"><div className="loading-row"><div className="spinner" /> Loading job…</div></div>
      </>
    );
  }

  if (err && !job) {
    return (
      <>
        <div className="topbar"><Link to="/jobs" className="btn btn-ghost btn-sm">← Jobs</Link></div>
        <div className="page"><div className="alert alert-err">{err}</div></div>
      </>
    );
  }

  const j = job!;
  const isActive   = j.status === "running" || j.status === "queued";
  const isFinished = j.status === "done" || j.status === "failed" || j.status === "stopped";

  return (
    <>
      <div className="topbar">
        <Link to="/jobs" className="btn btn-ghost btn-sm">← Jobs</Link>
        <div className={`sdot ${statusDot(j.status)}`} style={{ flexShrink: 0 }} />
        <span className="topbar-title" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {j.title ?? j.type}
        </span>
        <span className={`badge ${statusBadge(j.status)}`}>{j.status}</span>
        <div className="topbar-right">
          {isActive && j.status === "running" && (
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => act(() => api.jobs.pause(j.id), "pause")}>
              ⏸ Pause
            </button>
          )}
          {j.status === "paused" && (
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => act(() => api.jobs.resume(j.id), "resume")}>
              ▷ Resume
            </button>
          )}
          {isActive && (
            <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => act(() => api.jobs.stop(j.id), "stop")}>
              ⏹ Stop
            </button>
          )}
          {(j.status === "failed" || j.status === "stopped") && (
            <button className="btn btn-success btn-sm" disabled={busy} onClick={() => act(() => api.jobs.retry(j.id), "retry")}>
              ↺ Retry
            </button>
          )}
          <button className="btn btn-danger btn-sm" onClick={deleteJob} disabled={busy}>✕</button>
        </div>
      </div>

      <div className="page">
        {err && <div className="alert alert-err" style={{ marginBottom: 16 }}>{err}</div>}

        {/* Progress */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text3)", marginBottom: 6 }}>
            <span style={{ fontFamily: "var(--mono)" }}>{j.id}</span>
            <span>{isFinished ? "100%" : j.progress > 0 ? `${Math.round(j.progress * 100)}%` : "—"}</span>
          </div>
          <div className="progress-bar" style={{ height: 5 }}>
            <div
              className="progress-fill"
              style={{
                width: isFinished ? "100%" : j.progress > 0 ? `${Math.round(j.progress * 100)}%` : "0%",
                background: j.status === "done" ? "var(--green)" : j.status === "failed" ? "var(--red)" : "var(--accent)",
              }}
            />
          </div>
        </div>

        {/* Meta strip */}
        <div className="card card-sm" style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: ".06em" }}>Type</div>
              <div style={{ fontSize: 12, fontFamily: "var(--mono)" }}>{j.type}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: ".06em" }}>Created</div>
              <div style={{ fontSize: 12 }}>{fmtDate(j.created_at)}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginBottom: 2, textTransform: "uppercase", letterSpacing: ".06em" }}>Updated</div>
              <div style={{ fontSize: 12 }}>{fmtDate(j.updated_at)}</div>
            </div>
          </div>
        </div>

        {j.status === "failed" && j.error && (
          <div className="alert alert-err" style={{ marginBottom: 16 }}><strong>Error:</strong> {j.error}</div>
        )}

        {/* Tabs */}
        <div className="tabs">
          {([
            ["live",    "Live feed"],
            ["result",  "Result"],
            ["payload", "Payload"],
            ["notes",   "Notes"],
          ] as [Tab, string][]).map(([t, label]) => (
            <button key={t} className={`tab${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>
              {label}
              {t === "live" && isActive && (
                <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--blue)", boxShadow: "0 0 4px var(--blue)", marginLeft: 6, verticalAlign: "middle", animation: "pulse-dot 1.2s infinite" }} />
              )}
            </button>
          ))}
        </div>

        {tab === "live" && (
          <LiveFeed jobId={j.id} status={j.status} />
        )}

        {tab === "result" && (
          j.result
            ? <div className="card"><ResultView result={j.result} /></div>
            : <div className="empty-box"><h3>No result yet</h3><p>{isActive ? "Check Live feed for progress." : "Job didn't produce a result."}</p></div>
        )}

        {tab === "payload" && (
          j.payload
            ? <pre className="codeblock">{JSON.stringify(j.payload, null, 2)}</pre>
            : <div className="empty-box"><h3>No payload</h3><p>This job has no input payload.</p></div>
        )}

        {tab === "notes" && (
          <div>
            <textarea rows={10} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Your notes about this job…" />
            <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
              <button className="btn btn-primary btn-sm" onClick={saveNotes} disabled={busy}>Save notes</button>
              {saveMsg && <span style={{ fontSize: 12, color: "var(--green)" }}>{saveMsg}</span>}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
