import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Job } from "../api/client";
import { wsClient } from "../api/ws";

type Tab = "result" | "payload" | "notes";

export default function JobDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<Tab>("result");
  const [notes, setNotes] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  function refresh() {
    api.jobs.get(id).then((j) => { setJob(j); setNotes(j.notes ?? ""); }).catch(() => {});
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [id]);

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

  if (!job) return <div className="page"><div className="loading-row"><div className="spinner" />Loading…</div></div>;

  return (
    <>
      <div className="topbar">
        <button className="btn btn-ghost btn-sm" onClick={() => navigate("/jobs")}>← Jobs</button>
        <span className="topbar-title">{job.title || job.id}</span>
        <span className={`sdot sdot-${job.status}`} />
        <span className="topbar-sub">{job.status}</span>
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
          <button className={`tab${tab === "result" ? " on" : ""}`} onClick={() => setTab("result")}>Result</button>
          <button className={`tab${tab === "payload" ? " on" : ""}`} onClick={() => setTab("payload")}>Payload</button>
          <button className={`tab${tab === "notes" ? " on" : ""}`} onClick={() => setTab("notes")}>Notes</button>
        </div>

        {tab === "result" && (
          <div className="codeblock">
            {job.result?.response ?? (job.status === "done" ? "(empty result)" : "Waiting for the job to complete…")}
          </div>
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
