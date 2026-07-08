import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type JobStatus } from "../api/client";
import { wsClient } from "../api/ws";

const STATUSES: (JobStatus | "all")[] = ["all", "queued", "running", "done", "failed", "paused", "stopped"];
const STATUS_LABEL: Record<JobStatus | "all", string> = {
  all: "All", queued: "Waiting", running: "In progress", done: "Done",
  failed: "Failed", paused: "Paused", stopped: "Stopped",
};
const TYPE_LABEL: Record<string, string> = { compose_task: "Task" };

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [filter, setFilter] = useState<JobStatus | "all">("all");
  const [search, setSearch] = useState("");

  function refresh() {
    api.jobs.list(filter === "all" ? undefined : filter).then(setJobs).catch(() => {});
  }

  useEffect(() => { refresh(); }, [filter]);

  useEffect(() => {
    return wsClient.subscribe((e) => {
      if (e.event === "job_update") refresh();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const filtered = (jobs ?? []).filter((j) =>
    !search || (j.title ?? j.id).toLowerCase().includes(search.toLowerCase())
  );

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">History</span>
        <span className="topbar-sub">{jobs ? `${jobs.length} tasks` : "loading…"}</span>
        <div className="topbar-right">
          <input type="search" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 180 }} />
          <Link to="/run" className="btn btn-primary btn-sm">+ New task</Link>
        </div>
      </div>
      <div className="page">
        <div className="tabs">
          {STATUSES.map((s) => (
            <button key={s} className={`tab${filter === s ? " on" : ""}`} onClick={() => setFilter(s)}>{STATUS_LABEL[s]}</button>
          ))}
        </div>

        <div className="job-list">
          {!jobs && <div className="loading-row"><div className="spinner" />Loading…</div>}
          {jobs && filtered.length === 0 && (
            <div className="empty-box">
              <h3>No tasks yet</h3>
              <p><Link to="/run" className="agent-link">Start one →</Link></p>
            </div>
          )}
          {filtered.map((j) => (
            <Link key={j.id} to={`/jobs/${j.id}`} className="job-row">
              <span className={`sdot sdot-${j.status}`} />
              <span className="job-goal">{j.title || j.id}</span>
              <span className="badge b-gray">{TYPE_LABEL[j.type] ?? j.type}</span>
              <span className="job-meta">{relativeTime(j.created_at)}</span>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
