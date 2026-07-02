import { useEffect, useState } from "react";
import { api, type ModelInfo } from "../api/client";
import { wsClient } from "../api/ws";
import LiveFeed from "../components/LiveFeed";

const MODEL_LABELS: Record<string, { label: string; hint: string }> = {
  ollama_local: { label: "Qwen (general)", hint: "Fast, well-rounded default" },
  ornith_local: { label: "Ornith (coding & reasoning)", hint: "Best for code, thinks before answering" },
  lmstudio_local: { label: "LM Studio model", hint: "Whatever's loaded in LM Studio" },
  groq_powerful: { label: "Groq (cloud, powerful)", hint: "Needs GROQ_API_KEY" },
  groq_fast: { label: "Groq (cloud, fast)", hint: "Needs GROQ_API_KEY" },
};

type Phase = "idle" | "running" | "done" | "error";

export default function Run() {
  const [goal, setGoal] = useState("");
  const [model, setModel] = useState<string>("");
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    api.llm.models().then(setModels).catch(() => setModels([]));
  }, []);

  useEffect(() => {
    if (phase !== "running" || !jobId) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - start) / 1000)), 1000);
    const unsub = wsClient.subscribe((e) => {
      if (e.event === "job_update" && e.job_id === jobId) {
        const status = e.status as string;
        if (status === "done" || status === "failed" || status === "stopped") {
          api.jobs.get(jobId).then((job) => {
            if (job.status === "done") {
              setPhase("done");
              setResult(job.result?.response ?? "(empty result)");
            } else {
              setPhase("error");
              setError(job.error || `Job ${job.status}`);
            }
          });
        }
      }
    });
    return () => { clearInterval(t); unsub(); };
  }, [phase, jobId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim() || phase === "running") return;
    setPhase("running");
    setResult(null);
    setError(null);
    setElapsed(0);
    try {
      const res = await api.run(goal, { run_mode: "background", model: model || undefined });
      setJobId(res.job_id ?? null);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function reset() {
    setPhase("idle");
    setGoal("");
    setJobId(null);
    setResult(null);
    setError(null);
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">New task</span>
        <span className="topbar-sub">Ask Loom anything — watch it work, then read the answer</span>
      </div>
      <div className="page">
        <div className="card">
          <form onSubmit={submit}>
            <div className="field">
              <label>What do you need?</label>
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="e.g. Summarise what's in my vault about the collaboration bus, or write a function that…"
                style={{ minHeight: 110 }}
                disabled={phase === "running"}
              />
            </div>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div style={{ minWidth: 220 }}>
                <label>Model</label>
                <select value={model} onChange={(e) => setModel(e.target.value)} disabled={phase === "running"}>
                  <option value="">Auto (recommended)</option>
                  {(models ?? []).map((m) => (
                    <option key={m.name} value={m.name} disabled={!m.available}>
                      {(MODEL_LABELS[m.name]?.label ?? m.name)}{!m.available ? " — unavailable" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <button type="submit" className="btn btn-primary" disabled={phase === "running" || !goal.trim()}>
                {phase === "running" ? "Working…" : "Ask Loom"}
              </button>
              {phase !== "idle" && phase !== "running" && (
                <button type="button" className="btn btn-ghost" onClick={reset}>New task</button>
              )}
              {model && MODEL_LABELS[model] && (
                <span style={{ fontSize: 12, color: "var(--text3)" }}>{MODEL_LABELS[model].hint}</span>
              )}
            </div>
          </form>
        </div>

        {phase !== "idle" && (
          <div className="card" style={{ marginTop: 16 }}>
            <div className="section-hd">
              <h2>Watching Loom work</h2>
              {phase === "running" && <span className="badge b-yellow">{elapsed}s</span>}
            </div>
            <LiveFeed jobId={jobId} active={phase === "running"} />
          </div>
        )}

        {phase === "error" && error && (
          <div className="alert alert-err" style={{ marginTop: 16 }}>{error}</div>
        )}

        {phase === "done" && result && (
          <div className="card" style={{ marginTop: 16, borderColor: "rgba(34,197,94,.3)" }}>
            <div className="section-hd"><h2 style={{ color: "var(--green)" }}>✓ Result</h2></div>
            <div className="codeblock" style={{ maxHeight: "none" }}>{result}</div>
          </div>
        )}
      </div>
    </>
  );
}
