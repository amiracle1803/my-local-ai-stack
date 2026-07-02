import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function Run() {
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  function poll(jobId: string, startedAt: number) {
    api.jobs.get(jobId).then((job) => {
      if (job.status === "done") {
        setBusy(false);
        setStatus("");
        setResult(job.result?.response ?? "(no response)");
      } else if (job.status === "failed" || job.status === "stopped") {
        setBusy(false);
        setStatus("");
        setError(job.error || `Job ${job.status}`);
      } else {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        setStatus(`${job.status}… ${elapsed}s`);
        pollRef.current = setTimeout(() => poll(jobId, startedAt), 1500);
      }
    }).catch(() => {
      setStatus("Lost connection…");
      pollRef.current = setTimeout(() => poll(jobId, startedAt), 3000);
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim() || busy) return;
    setBusy(true);
    setResult(null);
    setError(null);
    setStatus("Queued…");
    try {
      const res = await api.run(goal, { run_mode: "background" });
      if (res.job_id) poll(res.job_id, Date.now());
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Run</span>
        <span className="topbar-sub">Ask Agent Atlas anything — it routes through the full agent chain</span>
      </div>
      <div className="page">
        <div className="card">
          <form onSubmit={submit}>
            <div className="field">
              <label>Goal</label>
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="e.g. Summarise what's in my vault about the collaboration bus"
                style={{ minHeight: 100 }}
              />
            </div>
            <div className="row" style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <button type="submit" className="btn btn-primary" disabled={busy || !goal.trim()}>
                {busy ? "Working…" : "Run"}
              </button>
              {status && <span style={{ fontSize: 12, color: "var(--text3)", fontFamily: "var(--mono)" }}>{status}</span>}
            </div>
          </form>
        </div>

        {error && <div className="alert alert-err" style={{ marginTop: 16 }}>{error}</div>}

        {result && (
          <div className="card" style={{ marginTop: 16 }}>
            <div className="section-hd"><h2>Result</h2></div>
            <div className="codeblock">{result}</div>
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate("/jobs")}>View all jobs →</button>
        </div>
      </div>
    </>
  );
}
