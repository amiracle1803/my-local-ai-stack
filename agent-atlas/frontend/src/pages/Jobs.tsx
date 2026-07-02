import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type TaskStatus } from "../api/client";
import { wsClient } from "../api/ws";

const STATUS_OPTIONS: (TaskStatus | "all")[] = [
  "all", "running", "queued", "done", "failed", "paused", "stopped",
];

function statusBadge(s: string) {
  const m: Record<string, string> = {
    running: "b-blue", done: "b-green", failed: "b-red",
    queued: "b-yellow", paused: "b-yellow", stopped: "b-gray",
  };
  return m[s] ?? "b-gray";
}

function statusDot(s: string) {
  const m: Record<string, string> = {
    running: "sdot-running", done: "sdot-done", failed: "sdot-failed",
    queued: "sdot-queued",  paused: "sdot-paused", stopped: "sdot-stopped",
  };
  return m[s] ?? "sdot-stopped";
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function Jobs() {
  const [jobs,   setJobs]   = useState<Job[] | null>(null);
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [err,    setErr]    = useState<string | null>(null);

  const load = useCallback(() => {
    const status = filter === "all" ? undefined : filter;
    api.jobs.list(status)
      .then((jobs) => { setErr(null); setJobs(jobs); })
      .catch((e) => setErr(e.message));
  }, [filter]);

  useEffect(() => {
    load();
    return wsClient.subscribe((msg) => {
      if (msg.event === "job_update") load();
    });
  }, [load]);

  const visible = (jobs ?? []).filter((j) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      j.id.toLowerCase().includes(q) ||
      (j.title ?? "").toLowerCase().includes(q) ||
      j.type.toLowerCase().includes(q)
    );
  });

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Jobs</span>
        <span className="topbar-sub">{jobs ? `${jobs.length} total` : "Loading…"}</span>
        <div className="topbar-right">
          <button className="btn btn-ghost btn-sm" onClick={load}>↻ Refresh</button>
          <Link to="/run" className="btn btn-primary btn-sm">▷ New task</Link>
        </div>
      </div>
      <div className="page">
        {err && <div className="alert alert-err">{err}</div>}

        {/* Filters */}
        <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
          <input
            type="search"
            placeholder="Search jobs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 220 }}
          />
          <div className="tabs" style={{ margin: 0, border: "none", gap: 4 }}>
            {STATUS_OPTIONS.map((s) => (
              <button
                key={s}
                className={`tab${filter === s ? " on" : ""}`}
                onClick={() => setFilter(s)}
                style={{ padding: "6px 12px" }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Job list */}
        {!jobs && <div className="loading-row"><div className="spinner" /> Loading jobs…</div>}

        {jobs && visible.length === 0 && (
          <div className="empty-box">
            <h3>No jobs found</h3>
            <p>{search ? "Try a different search." : "Submit a task to create jobs."}</p>
          </div>
        )}

        {visible.length > 0 && (
          <div className="job-list">
            {visible.map((j) => (
              <Link key={j.id} to={`/jobs/${j.id}`} className="job-row">
                <div className={`sdot ${statusDot(j.status)}`} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="job-goal">{j.title ?? j.type}</div>
                  <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 2 }}>
                    {j.id}
                  </div>
                  {j.progress > 0 && j.progress < 1 && (
                    <div className="progress-bar" style={{ marginTop: 5, width: 160 }}>
                      <div className="progress-fill" style={{ width: `${Math.round(j.progress * 100)}%` }} />
                    </div>
                  )}
                </div>
                <span className={`badge ${statusBadge(j.status)}`}>{j.status}</span>
                <span className="job-meta">{fmtDate(j.updated_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
