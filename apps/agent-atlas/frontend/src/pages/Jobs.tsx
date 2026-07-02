import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type JobStatus } from "../api/client";
import { wsClient } from "../api/ws";

const STATUSES: (JobStatus | "all")[] = ["all", "queued", "running", "done", "failed", "paused", "stopped"];

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
        <span className="topbar-title">Jobs</span>
        <span className="topbar-sub">{jobs ? `${jobs.length} jobs` : "loading…"}</span>
        <div className="topbar-right">
          <input type="search" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 180 }} />
        </div>
      </div>
      <div className="page">
        <div className="tabs">
          {STATUSES.map((s) => (
            <button key={s} className={`tab${filter === s ? " on" : ""}`} onClick={() => setFilter(s)}>{s}</button>
          ))}
        </div>

        <div className="job-list">
          {!jobs && <div className="loading-row"><div className="spinner" />Loading…</div>}
          {jobs && filtered.length === 0 && <div className="empty-box"><h3>No jobs</h3><p>Nothing matches here yet.</p></div>}
          {filtered.map((j) => (
            <Link key={j.id} to={`/jobs/${j.id}`} className="job-row">
              <span className={`sdot sdot-${j.status}`} />
              <span className="job-goal">{j.title || j.id}</span>
              <span className="badge b-gray">{j.type}</span>
              <span className="job-meta">{new Date(j.created_at).toLocaleString()}</span>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
