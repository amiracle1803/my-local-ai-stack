import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Job, type JobStatus } from "../api/client";
import { wsClient } from "../api/ws";
import LiveFeed from "../components/LiveFeed";

type Tab = "progress" | "result" | "payload" | "notes";

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Waiting to start",
  running: "In progress",
  paused: "Paused",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped",
};

export default function JobDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const [notes, setNotes] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  function refresh() {
    api.jobs.get(id).then((j) => {
      setJob(j);
      setNotes(j.notes ?? "");
      // Land on Progress while it's live, Result once it's settled --
      // but don't yank the user off a tab they've already picked.
      setTab((prev) => prev ?? (j.status === "queued" || j.status === "running" ? "progress" : "result"));
    }).catch(() => {});
  }

  useEffect(() => { setTab(null); refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [id]);

  useEffect(() => {
    const t = setInterval(refresh, 3000);
    const unsub = wsClient.subscribe((e) => {
      if (e.event === "job_update" && e.job_id === id) refresh();
    });
    return () => { clearInterval(t); unsub(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function act(action: "pause" | "resume" | "stop" | "retry" | "delete") {
    setBusyAction(action);
    try {
      if (action === "delete") {
        if (!confirm("Delete this job?")) return;
        await api.jobs.delete(id);
        navigate("/jobs");
        return;
      }
      await api.jobs[action](id);
      refresh();
    } finally {
      setBusyAction(null);
    }
  }

  async function saveNotes() {
    await api.jobs.saveNotes(id, notes);
  }

  if (!job || !tab) return <div className="page"><div className="loading-row"><div className="spinner" />Loading…</div></div>;

  const isLive = job.status === "queued" || job.status === "running";

  return (
    <>
      <div className="topbar">
        <button className="btn btn-ghost btn-sm" onClick={() => navigate("/jobs")}>← History</button>
        <span className="topbar-title">{job.title || job.id}</span>
        <span className={`sdot sdot-${job.status}`} />
        <span className="topbar-sub">{STATUS_LABEL[job.status]}</span>
        <div className="topbar-right">
          {(job.status === "queued" || job.status === "running") && (
            <button className="btn btn-ghost btn-sm" disabled={!!busyAction} onClick={() => act("pause")}>Pause</button>
          )}
          {job.status === "paused" && (
            <button className="btn btn-ghost btn-sm" disabled={!!busyAction} onClick={() => act("resume")}>Resume</button>
          )}
          {(job.status === "queued" || job.status === "running" || job.status === "paused") && (
            <button className="btn btn-danger btn-sm" disabled={!!busyAction} onClick={() => act("stop")}>Stop</button>
          )}
          {(job.status === "failed" || job.status === "stopped" || job.status === "done") && (
            <button className="btn btn-ghost btn-sm" disabled={!!busyAction} onClick={() => act("retry")}>Retry</button>
          )}
          <button className="btn btn-danger btn-sm" disabled={!!busyAction} onClick={() => act("delete")}>Delete</button>
        </div>
      </div>
      <div className="page">
        {job.progress > 0 && job.progress < 1 && (
          <div className="progress-bar" style={{ marginBottom: 16 }}>
            <div className="progress-fill" style={{ width: `${job.progress * 100}%` }} />
          </div>
        )}
        {job.error && <div className="alert alert-err">{job.error}</div>}

        <div className="tabs">
          <button className={`tab${tab === "progress" ? " on" : ""}`} onClick={() => setTab("progress")}>
            Progress{isLive && <span className="dot spin" style={{ marginLeft: 6, verticalAlign: "middle" }} />}
          </button>
          <button className={`tab${tab === "result" ? " on" : ""}`} onClick={() => setTab("result")}>Result</button>
          <button className={`tab${tab === "payload" ? " on" : ""}`} onClick={() => setTab("payload")}>Payload</button>
          <button className={`tab${tab === "notes" ? " on" : ""}`} onClick={() => setTab("notes")}>Notes</button>
        </div>

        {tab === "progress" && (
          <div className="card">
            <LiveFeed jobId={id} active={isLive} />
          </div>
        )}
        {tab === "result" && (
          job.status === "done" ? (
            <div className="card" style={{ borderColor: "rgba(34,197,94,.3)" }}>
              <div className="section-hd"><h2 style={{ color: "var(--green)" }}>✓ Result</h2></div>
              <div className="codeblock" style={{ maxHeight: "none" }}>{job.result?.response ?? "(empty result)"}</div>
            </div>
          ) : (
            <div className="empty-box">
              <h3>Not done yet</h3>
              <p>Check the Progress tab to watch it work, or come back once it finishes.</p>
            </div>
          )
        )}
        {tab === "payload" && (
          <div className="codeblock">{JSON.stringify(job.payload, null, 2)}</div>
        )}
        {tab === "notes" && (
          <div>
            <textarea
              className="note-area"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes about this job…"
              style={{ width: "100%", minHeight: 120 }}
            />
            <div style={{ marginTop: 10 }}>
              <button className="btn btn-primary btn-sm" onClick={saveNotes}>Save notes</button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
